#!/usr/bin/env python3
"""lp_drift_guard.py — 2つの公開LPサイトの本文ドリフトを検知する番犬
====================================================================
背景（2026-09-11 に実測した取りこぼし）:
  LPは**同じ lp/ から2つのサイトに配られている**。

    - https://taitan-pro-lp.netlify.app          … main への push で自動デプロイ
    - https://taitan-pro-lp-targets.netlify.app  … **手動 zip デプロイ**（求人媒体・広告の遷移先）

  「面談」→「お話しするとき」の置換（[[feedback_no_online_meeting_wording]]）は
  4392b4f（2026-08-24）でリポジトリに入っていたが、-targets 側は手動デプロイなので
  2026-09-11 まで反映されていなかった。実測の差分は /beginner/ の「面談」7箇所、
  /agency/ の6箇所（main側は0）。**応募者が見る面だけが3週間古かった**。

  真因はまたも走査対象の設計:
    - content_facts_guard.py の CONTENT_GLOBS は "lp/**/*.html" ＝**ローカルのファイル**だけ。
      作業ツリーが直っていれば、公開されている実物が古くても緑になる。
    - link_guard.py は -targets も見るが、見るのは**リンクの生死**だけで文面は見ない。
    ⇒ 公開中の -targets の本文を見ている番犬が1本も無かった。手動デプロイを
      忘れても誰も気づけない構造だった。

この番犬が見る2軸:
  1. 2サイト間の本文ドリフト — 4ページ（beginner/agency/liver/sidejob）を
     両サイトから取得して突合する。**ローカルのファイルとは比べない**。
     sidejob/liver は「今後さわらない」方針（[[feedback_lp_scope_beginner_agency]]）だが、
     配られている以上ドリフトは検知する。一方で sidejob に意図的に残している
     「面談」2箇所（キーワード/ボタン名は残してよい）は**片方だけの違反ではない**ので
     ここでは何も言わない。見るのはあくまで「2サイトの差」。
  2. -targets 側の確定ファクト違反 — 物差しは facts_patterns.py（媒体共通の正本）。
     content_facts_guard が lp/**/*.html に当てているのと同じ集合・同じWARN扱い。
     ローカルが直っていても**公開中の -targets に古い違反が残っている**という、
     今回とまったく同じ穴を塞ぐ。

無視してよい差分:
  Netlify の post-processing が各サイトの site_id を埋めて挿し込む netlify.new の
  URL だけ。2026-09-11 に両サイト4ページを実測したとき、site_id を伏せた状態で
  差分は**完全に0バイト**だった（HTMLコメント1行と <meta name="netlify-deploy"> の
  1行、どちらも netlify.new/?…utm_id=<site_id> を含む）。site_id だけを伏せて
  それ以外の差はすべてドリフト扱いにする——「無視リスト」を広げると、
  この番犬は静かに何も見なくなる。

判定ポリシー:
  - NG = 本文ドリフト／-targets の確定ファクト違反／**どちらかのページを取得できなかった**
         → exit 1（Actionsが赤くなる）
    取得失敗を素通りさせない理由: 差分型の番犬は「見なかった」と「差が無かった」が
    どちらも緑になりうる。緑を「4ページ×2サイトを実際に取得して突合できた」の意味に
    固定しないと、Issueの自動クローズが嘘をつく（[[feedback_watchdog_autoclose]]）。
  - WARN = facts_patterns.AUDIT_WARN_LABELS（少額表記・実績誇張・他社比較）。
           主語や文脈で可否が変わるので赤にしない。

使い方:
  python3 lp_drift_guard.py            # 2サイトを取得して突合
  python3 lp_drift_guard.py --verbose  # 差分の本文を全部出す（既定は先頭40行）

ドリフトを見つけたときの復旧（-targets は手動デプロイなので、直すのは人の仕事）:
  ./scripts/lp_targets_deploy.sh

レポートは data/lp_drift_guard_report.json に保存される。
"""

import difflib
import json
import os
import re
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 禁止パターンの正本は facts_patterns.py だけ、HTML→本文の物差しは
# content_facts_guard.py だけ。ここには一切コピーを置かない
# （コピーを置くと「必ずどれか1本が古くなる」に戻る）。
from content_facts_guard import html_source_to_text, scan_text  # noqa: E402

REPORT_FILE = os.path.join(BASE_DIR, "data", "lp_drift_guard_report.json")

# git push で自動デプロイされる側（＝リポジトリの lp/ と一致しているはずの正）
SITE_MAIN = "https://taitan-pro-lp.netlify.app"
# 手動 zip デプロイの側（求人媒体 job_posts/*・広告 ads/* の遷移先）
SITE_TARGETS = "https://taitan-pro-lp-targets.netlify.app"

# 両サイトに配られている全ページ。
# 2026-09-11 時点の4ページを下限として持ちつつ、**lp/ の実体から自動で足す**。
# 手で並べるだけだと、LPを増やしたときに「番犬のPAGESへの追加忘れ」で
# 新しいページだけ誰も見ていない状態が生まれる（この番犬が塞いだ穴と同じ形）。
# 逆に lp/ から消えたページは下限側に残るので、配信だけ残っていても見続ける。
MIN_PAGES = ["beginner", "agency", "liver", "sidejob"]


def discover_pages():
    found = set(MIN_PAGES)
    for name in os.listdir(os.path.join(BASE_DIR, "lp")):
        if os.path.isfile(os.path.join(BASE_DIR, "lp", name, "index.html")):
            found.add(name)
    return sorted(found)


PAGES = discover_pages()

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# Netlify の post-processing が埋める site_id。これ**だけ**を伏せて比較する。
# 挿し込まれるのは2箇所（HTMLコメント／<meta name="netlify-deploy">）で、
# どちらも netlify.new/?…utm_id=<uuid> の形。行ごと落とすのではなく uuid だけを
# 伏せるので、同じ行に本物の変更が入ったらちゃんとドリフトとして出る。
NETLIFY_SITE_ID_RE = re.compile(
    r"(netlify\.new/\?[^\s\"'<>]*utm_id=)[0-9a-fA-F-]{36}")

DIFF_HEAD_LINES = 40


def normalize(html):
    """サイト固有の post-processing を伏せる。ここを増やすほど番犬は目を閉じる。"""
    html = NETLIFY_SITE_ID_RE.sub(r"\1<SITE_ID>", html)
    return html.replace("\r\n", "\n")


def fetch(site, page):
    """(html, error) を返す。取得できなかったことは**必ず呼び出し側に届ける**。"""
    url = f"{site}/{page}/"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20,
                         allow_redirects=True)
    except requests.RequestException as e:
        return None, f"{url} の取得に失敗: {type(e).__name__}: {e}"[:200]
    if r.status_code != 200:
        return None, f"{url} が HTTP {r.status_code}"
    r.encoding = r.encoding or "utf-8"
    return r.text, None


def diff_lines(main_html, targets_html, page):
    """正規化後の unified diff（本文の差分行のリスト）"""
    a = normalize(main_html).split("\n")
    b = normalize(targets_html).split("\n")
    return list(difflib.unified_diff(
        a, b, fromfile=f"main:/{page}/", tofile=f"targets:/{page}/",
        lineterm="", n=1))


def main():
    verbose = "--verbose" in sys.argv

    ng, warns, drift, verified = [], [], [], []

    for page in PAGES:
        main_html, err_a = fetch(SITE_MAIN, page)
        time.sleep(0.4)
        targets_html, err_b = fetch(SITE_TARGETS, page)
        time.sleep(0.4)

        # 取得できなかったページは「差が無かった」ではない。赤にして、
        # verified にも入れない（＝自動クローズの根拠にしない）。
        if err_a or err_b:
            for e in (err_a, err_b):
                if e:
                    ng.append({"page": page, "reason": "取得できず突合不能", "hit": e})
            print(f" ❌ /{page}/ 取得失敗")
            continue

        d = diff_lines(main_html, targets_html, page)
        # -targets の実物に確定ファクト違反が載っていないか（物差しは共通の正本）
        t_ng, t_warn = scan_text(html_source_to_text(targets_html),
                                 f"{SITE_TARGETS}/{page}/")
        for item in t_ng:
            ng.append({"page": page, "reason": item["reason"], "hit": item["hit"],
                       "where": item["where"]})
        warns += [{"page": page, **w} for w in t_warn]

        if d:
            # 差分行数は先頭3行（--- / +++ / @@）を除いた実体の数
            body = [ln for ln in d if ln[:1] in "+-" and not ln.startswith(("---", "+++"))]
            drift.append({"page": page, "lines": len(body), "diff": d})
            print(f" ❌ /{page}/ ドリフト {len(body)}行")
        else:
            print(f"    /{page}/ 一致"
                  + (f"（違反 {len(t_ng)}件）" if t_ng else ""))
        verified.append(page)

    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "sites": {"main": SITE_MAIN, "targets": SITE_TARGETS},
            "pages": PAGES,
            # 「2サイトとも実際に取得して突合できた」ページだけが入る。
            # 自動クローズはこの配列しか信用しない。
            "verified": verified,
            "drift": drift,
            "violations": ng,
            "warn": warns,
        }, f, ensure_ascii=False, indent=1)

    print(f"\n[走査] {len(verified)}/{len(PAGES)}ページを2サイトで突合")
    print(f"[結果] ドリフト={len(drift)}ページ 違反={len(ng)}件 "
          f"警告(判断保留)={len(warns)}件 → {os.path.relpath(REPORT_FILE, BASE_DIR)}")

    for d in drift:
        print(f"\n  ❌ /{d['page']}/ の本文が2サイトで食い違っています（{d['lines']}行）")
        shown = d["diff"] if verbose else d["diff"][:DIFF_HEAD_LINES]
        for ln in shown:
            print(f"     {ln}")
        if not verbose and len(d["diff"]) > DIFF_HEAD_LINES:
            print(f"     …ほか {len(d['diff']) - DIFF_HEAD_LINES} 行（--verbose で全件）")

    for v in ng:
        print(f"  ❌ {v.get('where', v['page'])}: {v['reason']}"
              + (f"\n     → {v['hit']}" if v.get("hit") else ""))
    for w in warns:
        print(f"  ⚠️ {w['where']}: {w['reason']} — {w['hit']}")

    if drift or ng:
        print("\n復旧: -targets は手動デプロイなので、直すには ./scripts/lp_targets_deploy.sh")
        return 1
    print("\n2サイトのLP本文は一致・確定ファクト違反なし ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
