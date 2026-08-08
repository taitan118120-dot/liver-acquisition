#!/usr/bin/env python3
"""social_profile_guard.py — プロフィール／固定ポストの確定ファクト番犬
=====================================================================
背景（2026-08-08）:
  X @taitan_LIVER の固定ポスト（2026-03-28 の初投稿）に
  「累計150名」「傘下11代理店を統括」「DMでご相談を」「私は現役プレイヤー」が
  4ヶ月以上そのまま公開され続けていた。プロフィール本体は 2026-07-31〜08-01 に
  是正済みだったのに、固定ポストだけ取り残されていた。

  真因は走査対象の設計:
    - 一括ファクト更新は **記事本文** を対象にしていて、プロフィール文は対象外だった
      （2026-07-31 に is正済み）
    - さらに **固定ポストは、そのプロフィール是正のときも対象外** だった
    - link_guard.py は「リンクが生きているか」しか見ず、文面の中身は見ない
  → 「一度書いたら二度と読み返さない場所」＝プロフィール・固定ポストを
     毎日読み直す番犬がどこにも居なかった。

このスクリプトが見る2軸:
  1. 禁止パターン走査 — 確定ファクト（[[project_taitan_pro_note_facts]]）の
     常設grepパターンを、実物のプロフィール文・固定ポスト・IG投稿キャプションに当てる
  2. 正本との突合 — marketing/social_profiles.md（表示名・bio・リンクの正本）を
     パースして、実物と1文字単位で一致するか見る。乖離＝どちらかが古い

判定ポリシー:
  - NG   = プロフィール／固定ポストの禁止パターン検出、正本との乖離、
           トークンが別アカウントを指している → exit 1（Actionsが赤くなる）
  - WARN = 過去投稿のキャプションの違反 → 報告のみ。**Graph API でキャプションは編集できない**ので
           赤にすると番犬が永久に鳴きやまなくなる（[[feedback_watchdog_autoclose]]）
  - SKIP = 取得に必要なトークンが無い媒体（ローカル実行時など）→ 報告のみ
  - 手動 = IG @taitanblog は個人アカウントで Graph API が使えない。
           自動取得できないので毎回チェック項目として出力するだけ（赤にはしない）

使い方:
  python3 social_profile_guard.py          # 全媒体
  python3 social_profile_guard.py --local  # 正本パースの自己テストのみ（ネット不要）

必要な環境変数（GitHub Secrets から注入）:
  TWITTER_BEARER_TOKEN                        X
  THREADS_ACCESS_TOKEN                        Threads
  INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ID   Instagram @taitan_pro

レポートは data/social_profile_guard_report.json に保存される。
"""

import json
import os
import re
import sys

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_FILE = os.path.join(BASE_DIR, "data", "social_profile_guard_report.json")
CANON_FILE = os.path.join(BASE_DIR, "marketing", "social_profiles.md")

X_USERNAME = "taitan_LIVER"
IG_GRAPH = "https://graph.facebook.com/v21.0"
THREADS_GRAPH = "https://graph.threads.net/v1.0"

LINE_ALLOWED = "https://lin.ee/xchCfdn"

# ── 禁止パターン ──────────────────────────────────────────────
# 確定ファクトの「常設grepパターン」を、旧値ではなく **フィールド** で組む
# （2026-07-29 の教訓: `150名` を狙うと `50名` を取りこぼす）
NG_PATTERNS = [
    (r"所属(?:ライバー)?\s*(?!200\s*[名人])[0-9]{1,4}\s*[名人]", "所属数が200名以外"),
    (r"(?:累計|総勢|延べ)\s*[0-9]{1,4}\s*[名人]", "所属数の旧表記（累計/総勢）"),
    (r"[0-9]{1,4}\s*[名人][^。\n]{0,6}(?:集客|育成|抱え)", "所属数を集客/育成実績として表記"),
    (r"統括|傘下", "代理店の関係が「提携」でない（統括/傘下）"),
    (r"現役(?:プレイヤー|ライバー)", "代表は「元」Pococha S帯（現役表記はbioと矛盾）"),
    (r"手数料(?:なし|無し|0円|ゼロ|不要)", "「手数料なし」表記"),
    (r"マージン\s*[0０]\s*[%％]|マージン(?:ゼロ|なし|無し|0円)|ノーマージン",
     "「マージンゼロ」＝手数料なしの同義語"),
    (r"違約金(?:なし|無し|[0０])|いつでも(?:解約|退所|辞め|契約解除)", "「いつでも退所」系"),
    (r"還元率\s*100\s*[%％](?!\s*\+\s*α)", "還元率が「100%+α」になっていない"),
    (r"還元率\s*(?!100)[0-9]{2,3}\s*[%％]", "還元率が確定値でない"),
    (r"IRIAM|イリアム|SHOWROOM|ショールーム|ふわっち|REALITY", "取扱外プラットフォーム"),
    (r"Pococha新人期スタートダッシュ", "旧・特典PDF名"),
    (r"DM(?:で|を)?(?:ご相談|ください|下さい|お待ち)|お気軽にDM|DMお願い",
     "CTAがDM誘導（導線は特典PDF→LINE登録に統一）"),
    (r"lit\.link", "リンクが lit.link（公式LINEでない）"),
    (r"オンライン無料相談", "「オンライン無料相談」は使わない"),
    (r"京都コレクション", "実在しないイベント"),
    (r"カーブアウト|ccarveout", "使用禁止ブランド"),
    (r"リスナー(?!さん)", "リスナーの呼び捨て"),
    (r"他アプリ(?:も)?多数", "取扱は Pococha・TikTok LIVE・17LIVE の3つで統一"),
]

# 出典なしの割合統計。2系統で当てる（片方だけだと必ず取りこぼす）
#   ① 割合語 × 離脱/成功語の近接 …「9割が消える」「10人に1人も成功しない」型
#   ② 割合が主語を直接修飾する形 …「9割の副業ライバーはフリーで十分」型。
#      ②は離脱語を含まないので①では絶対に出ない（2026-08-08 実測で取りこぼした）
DROPOUT_RATIO = re.compile(r"[7-9]\s*割|[6-9]0\s*[%％]|10人に[1-3]人")
DROPOUT_WORD = re.compile(r"辞め|消え|脱落|挫折|離脱|成功|続か")
RATIO_SUBJECT = re.compile(
    r"(?:[1-9]\s*割|[0-9]{1,3}\s*[%％])の(?:ライバー|人|副業|女性|男性|初心者|配信者)")

MONEY_LOW = re.compile(r"月\s*([0-9]{1,2})\s*万")
# 確定レンジ（3ヶ月15〜20万 / 6ヶ月30〜40万 / B帯20〜30万）より下は書かない
MONEY_FLOOR = 15


def scan(text, where):
    """1本のテキストに全パターンを当てて violation のリストを返す。"""
    if not text:
        return []
    flat = re.sub(r"\s+", "", text)
    out = []
    for pat, label in NG_PATTERNS:
        m = re.search(pat, text) or re.search(pat, flat)
        if m:
            out.append({"where": where, "reason": label, "hit": m.group(0)[:40]})

    # 割合 × 離脱語の近接（330字窓）
    for m in DROPOUT_RATIO.finditer(text):
        window = text[max(0, m.start() - 40): m.end() + 40]
        if DROPOUT_WORD.search(window):
            out.append({"where": where, "reason": "出典なしの割合統計（離脱/成功率）",
                        "hit": window.strip()[:60]})
            break

    m = RATIO_SUBJECT.search(text)
    if m:
        out.append({"where": where, "reason": "出典なしの割合統計（割合が主語を修飾）",
                    "hit": text[max(0, m.start() - 10): m.end() + 20].strip()[:60]})

    for m in MONEY_LOW.finditer(text):
        if int(m.group(1)) < MONEY_FLOOR:
            out.append({"where": where, "reason": f"確定レンジ未満の少額表記",
                        "hit": m.group(0)})
            break

    for m in re.finditer(r"https?://lin\.ee/\S+", text):
        if m.group(0).rstrip("/。、）)") != LINE_ALLOWED:
            out.append({"where": where, "reason": "許可リスト外のLINEリンク",
                        "hit": m.group(0)})
    return out


# ── 正本（marketing/social_profiles.md）のパース ───────────────────
# 媒体見出し（##/###）→ 項目見出し（###/####）→ 直後のフェンス済みブロック、
# および「リンク欄：`URL`」「URL欄：`URL`」を拾う。
MEDIA_HEADS = [
    (re.compile(r"^##\s*Threads（@taitanblog）"), "threads"),
    (re.compile(r"^##\s*X（Twitter）"), "x"),
    (re.compile(r"^###\s*①\s*@taitan_pro"), "ig_taitan_pro"),
    (re.compile(r"^###\s*②\s*@taitanblog"), "ig_taitanblog"),
]
FIELD_HEADS = [
    (re.compile(r"^#{3,4}\s*(表示名|名前欄)"), "name"),
    (re.compile(r"^#{3,4}\s*(bio|自己紹介)"), "bio"),
    (re.compile(r"^#{3,4}\s*固定(ツイート|投稿)"), "pinned"),
]
LINK_LINE = re.compile(r"^(?:リンク欄|URL欄)[：:]\s*`([^`]+)`")


def parse_canonical(path=CANON_FILE):
    lines = open(path, encoding="utf-8").read().split("\n")
    canon, media, field, buf, in_fence = {}, None, None, None, False

    for line in lines:
        if in_fence:
            if line.startswith("```"):
                canon.setdefault(media, {})[field] = "\n".join(buf).strip()
                in_fence, field, buf = False, None, None
            else:
                buf.append(line)
            continue

        hit = next((k for pat, k in MEDIA_HEADS if pat.match(line)), None)
        if hit:
            media, field = hit, None
            continue
        if media is None:
            continue

        m = LINK_LINE.match(line)
        if m:
            canon.setdefault(media, {})["link"] = m.group(1)
            continue

        hit = next((k for pat, k in FIELD_HEADS if pat.match(line)), None)
        if hit:
            field = hit
            continue
        # 項目見出しの直後に来る最初のフェンスだけを本文として採る
        if field and line.startswith("```"):
            in_fence, buf = True, []
    return canon


def norm(s):
    return re.sub(r"\s+", "", s or "")


# ── 実物の取得 ────────────────────────────────────────────────
def fetch_x():
    token = os.environ.get("TWITTER_BEARER_TOKEN", "").strip()
    if not token:
        return None, "TWITTER_BEARER_TOKEN 未設定"
    r = requests.get(
        f"https://api.x.com/2/users/by/username/{X_USERNAME}",
        params={
            "user.fields": "username,name,description,url,entities,pinned_tweet_id",
            "expansions": "pinned_tweet_id",
            "tweet.fields": "text,created_at",
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if r.status_code != 200:
        return None, f"X API {r.status_code}: {r.text[:200]}"
    d = r.json()
    u = d.get("data") or {}
    pinned = (d.get("includes", {}).get("tweets") or [{}])[0]
    # url は t.co なので entities から実URLを取る
    link = u.get("url", "")
    for e in (u.get("entities", {}).get("url", {}).get("urls") or []):
        if e.get("expanded_url"):
            link = e["expanded_url"]
    return {
        "username": u.get("username", ""),
        "name": u.get("name", ""),
        "bio": u.get("description", ""),
        "link": link,
        "pinned": pinned.get("text", ""),
        "pinned_id": u.get("pinned_tweet_id", ""),
    }, None


def fetch_threads():
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        return None, "THREADS_ACCESS_TOKEN 未設定"
    r = requests.get(
        f"{THREADS_GRAPH}/me",
        params={"fields": "id,username,name,threads_biography", "access_token": token},
        timeout=30,
    )
    if r.status_code != 200:
        return None, f"Threads API {r.status_code}: {r.text[:200]}"
    d = r.json()
    # Threads API はプロフィールリンク・固定投稿を返さない（読み取り不可）
    return {"username": d.get("username", ""), "name": d.get("name", ""),
            "bio": d.get("threads_biography", "")}, None


def fetch_ig():
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    biz = os.environ.get("INSTAGRAM_BUSINESS_ID", "").strip()
    if not (token and biz):
        return None, "INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ID 未設定"
    r = requests.get(f"{IG_GRAPH}/{biz}",
                     params={"fields": "username,name,biography,website",
                             "access_token": token}, timeout=30)
    if r.status_code != 200:
        return None, f"IG API {r.status_code}: {r.text[:200]}"
    d = r.json()
    out = {"username": d.get("username", ""), "name": d.get("name", ""),
           "bio": d.get("biography", ""), "link": d.get("website", ""), "captions": []}
    m = requests.get(f"{IG_GRAPH}/{biz}/media",
                     params={"fields": "caption,permalink,timestamp", "limit": 25,
                             "access_token": token}, timeout=30)
    if m.status_code == 200:
        out["captions"] = [
            {"caption": x.get("caption", ""), "permalink": x.get("permalink", "")}
            for x in m.json().get("data", [])
        ]
    return out, None


# ── 突合 ─────────────────────────────────────────────────────
def compare(media_label, live, canon, fields):
    diffs = []
    for f in fields:
        want, got = canon.get(f), live.get(f)
        if want is None or got is None:
            continue
        if norm(want) != norm(got):
            diffs.append({"where": f"{media_label} / {f}", "canonical": want, "live": got})
    return diffs


def main():
    if "--local" in sys.argv:
        canon = parse_canonical()
        print(json.dumps(canon, ensure_ascii=False, indent=1))
        return 0

    canon = parse_canonical()
    violations, warns, diffs, skipped = [], [], [], []

    # (表示名, 正本キー, 取得関数, 期待username, 突合フィールド, 走査フィールド)
    sources = [
        ("X @taitan_LIVER", "x", fetch_x, "taitan_LIVER",
         ["name", "bio", "link"], ["bio", "pinned"]),
        ("Threads @taitanblog", "threads", fetch_threads, "taitanblog",
         ["name", "bio"], ["bio"]),
        ("IG @taitan_pro", "ig_taitan_pro", fetch_ig, "taitan_pro",
         ["name", "bio", "link"], ["bio"]),
    ]

    for label, key, fetch, want_user, cmp_fields, scan_fields in sources:
        live, err = fetch()
        if err:
            skipped.append({"media": label, "reason": err})
            print(f"  ⏭  {label}: {err}")
            continue

        # トークンが別アカウントを指していたら、以降の検査は全部無意味になる
        got_user = (live.get("username") or "").lstrip("@")
        if got_user and got_user.lower() != want_user.lower():
            violations.append({
                "where": f"{label} / username",
                "reason": f"トークンが別アカウント（@{got_user}）を指している",
                "hit": f"期待 @{want_user} / 実際 @{got_user}"})

        for f in scan_fields:
            violations += scan(live.get(f, ""), f"{label} / {f}")
        # 過去投稿のキャプションはAPIで編集できない（＝直せない）。
        # 赤にすると番犬が永久に鳴きやまなくなるので warn 扱いにする。
        for c in live.get("captions", []):
            warns += scan(c["caption"], f"{label} / 投稿 {c['permalink']}")
        diffs += compare(label, live, canon.get(key, {}), cmp_fields)

        print(f"  ✅ {label}: 取得OK（@{got_user or '?'}）"
              + (f" 固定ポスト {len(live.get('pinned', ''))}字" if live.get("pinned") else ""))
        for f in dict.fromkeys(cmp_fields + scan_fields):
            if live.get(f):
                print(f"     [{f}] {live[f][:70].replace(chr(10), ' / ')}")

    # 自動取得できない媒体は毎回チェックリストとして出すだけ（赤にはしない）
    manual = [
        "IG @taitanblog（個人アカウント／Graph API 対象外）: 表示名・bio・リンク・ハイライト名",
        "X / Threads の「固定」状態そのもの（固定APIが存在しないため自動判定不可）",
    ]

    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump({"violations": violations, "warn": warns, "diffs": diffs,
                   "skipped": skipped, "manual": manual}, f, ensure_ascii=False, indent=1)

    print(f"\n[結果] 禁止パターン={len(violations)} 正本との乖離={len(diffs)} "
          f"警告(過去投稿)={len(warns)} 取得スキップ={len(skipped)} → {REPORT_FILE}")
    for v in violations:
        print(f"  ❌ {v['where']}: {v['reason']}\n     → {v['hit']}")
    for w in warns:
        print(f"  ⚠️ (過去投稿・API編集不可) {w['where']}: {w['reason']}\n     → {w['hit']}")
    for d in diffs:
        print(f"  ⚠️ {d['where']} が正本と不一致")
        print(f"     正本: {d['canonical'][:80]!r}")
        print(f"     実物: {d['live'][:80]!r}")
    print("\n[手動確認]")
    for m in manual:
        print(f"  - {m}")

    if violations or diffs:
        sys.exit(1)
    print("\nプロフィール・固定ポストに違反なし ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
