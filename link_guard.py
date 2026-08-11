#!/usr/bin/env python3
"""link_guard.py — 死にリンクを構造的に検知する番犬
====================================================
背景（2026-07-12）: 公開Note記事5本が404の旧LINEリンク lin.ee/816qtxyj を
使い続けており、読者を長期間404に誘導していた。リンクは「書いた時点で正しい」
だけでは足りず、切れた瞬間に気づける仕組みが必要。

3層のチェック:
  1. LINEリンク許可リスト — lin.ee のURLは LINE_ALLOWED 以外が
     リポジトリ内・公開記事内のどこかに現れたら即エラー（typo・旧リンク混入防止）
  2. リポジトリ内コンテンツのURL実チェック — 読者の目に触れるファイル群から
     URLを抽出してGETし、404/410 を検知
  3. 公開Note全記事のURL実チェック — 公開APIで全記事本文を取得して同様に検知
     （公開版とリポジトリの乖離も拾える）
  4. フラグメント(#anchor)の実在チェック — 自サイトのLPに限り、着地先HTMLに
     その id/name があるかまで見る（2026-08-10 追加。経緯は check_url 内のコメント）
  5. 稼働中のGoogle広告サイトリンクの着地先チェック — リポジトリに書かれていない
     （管理画面にしか無い）URLを AD_SITELINK_URLS で明示して 2〜4 に乗せる（2026-08-11 追加）

判定ポリシー:
  - DEAD  = 404/410、許可リスト外の lin.ee URL、自サイトの存在しない #anchor
            → exit 1（Actionsが赤くなる）
  - WARN  = 403/405/429/5xx/タイムアウト等（bot拒否の可能性が高い）→ 報告のみ
  - SKIP  = botを全面ブロックするSNSドメイン（誤検知源なので見ない）

使い方:
  python3 link_guard.py              # 全チェック（リポジトリ＋公開Note）
  python3 link_guard.py --repo-only  # ネット越しのNote取得なし（ローカル用・高速）

レポートは data/link_guard_report.json に保存される。
"""
import glob
import json
import os
import re
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_FILE = os.path.join(BASE_DIR, "data", "link_guard_report.json")

NOTE_CREATOR = "taitan_118"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# ── 1. LINEリンク許可リスト ──
# 正しい公式LINEはこれだけ。新アカウントを作ったらここに追加する。
LINE_ALLOWED = {"https://lin.ee/xchCfdn"}
# 過去に事故を起こした既知の死にリンク（検出したら必ずエラー）
KNOWN_DEAD = ["lin.ee/816qtxyj"]

# ── 読者の目に触れるコンテンツファイル ──
CONTENT_GLOBS = [
    "blog/articles_note/*.md",
    "posts/*.json",
    "posts/*.txt",
    "threads/threads_posts.json",
    "instagram/ig_posts.json",
    "lp/**/*.html",
    "line_bot/messages.py",
    "line_bot/config.py",
    "config.py",
    "note_article_generator.py",
    "threads/threads_content.py",
    "cloud_post.py",
    "instagram/ig_viral_generator.py",
    # DMテンプレ（見込み客に直接送られる＝最も目に触れるコンテンツ）
    # 2026-08-01: templates/dm_model_scout.txt が404の告知先を長期間載せていたが
    # 走査対象外だったため一度も検知できなかった。その再発防止。
    "templates/*.txt",          # dm_sender.py がファイル直読みする本番テンプレ
    "liver_app/db.py",          # _DEFAULT_*_TEMPLATE にLPのURLが埋まっている
    "x_app/db.py",              # 同上（X版）
    # 求人原稿（応募者が踏むリンク。生成済み原稿とテンプレの両方を見る）
    "job_posts/templates/*.txt",
    "job_posts/*/*.md",
    # ブログ記事（生成側テンプレと生成済み記事の両方）
    # 2026-08-12: blog/generate_articles.py が実在しないアンカー
    # https://taitan-pro-lp.netlify.app/#apply を長期間埋め込んでおり（cecb291で解消済み）、
    # そこから生成された blog/articles/*.md 6本にも波及していたが、どちらも走査対象外
    # だったため一度も検知できなかった。生成側（正本）と生成物の両方を見る。
    "blog/generate_articles.py",
    "blog/articles/*.md",
]

# 走査から外すパス（相対パスに含まれていたらスキップ）
# templates/retired/ は退役テンプレ置き場。死んだURLが「記録として」残っているので
# 検知対象にすると恒久的に赤くなる（経緯は templates/retired/README.md）。
EXCLUDE_PATH_PARTS = ("templates/retired/",)

# botを全面ブロックしていて実チェックが誤検知になるドメイン
SKIP_DOMAINS = (
    "x.com", "twitter.com", "instagram.com", "facebook.com", "tiktok.com",
    "threads.net", "localhost", "127.0.0.1", "example.com",
    "api.line.me", "notify-api.line.me",  # API系はGETで判定できない
)

# フラグメント（#anchor）の実在まで検証するドメイン。
# 自分で中身を管理しているサイトだけに限る。他所のSPAはHTMLにidが出ないため誤検知源。
FRAGMENT_CHECK_DOMAINS = (
    "taitan-pro-lp.netlify.app",
    "taitan-pro-lp-targets.netlify.app",
)

# ── 稼働中のGoogle広告サイトリンクの着地先（2026-08-11 追加）──
# これらのURLは「管理画面の中だけ」に存在し、リポジトリのどのコンテンツにも書かれていない。
# CONTENT_GLOBS には ads/*.md が入っていないため、2026-08-10 に入れたフラグメント実在
# チェックがあっても**広告のアンカーは1本も見ていなかった**。ここに明示して監視下に置く。
# 正本は ads/google_ads_設計書.md §5-5「サイトリンク詳細」。
# サイトリンクを足す・URLを変えるときは、設計書と**この配列の両方**を更新すること。
# 2026-08-11: 全10本を管理画面で実物照合し、この配列を実値に更新した（推定は残っていない）。
# 2026-08-11（同日追記）: キャンペーンA にキャンペーン単位4本を新規登録し、稼働本数は 10→14 本
#   になった。ただしAの4本はCの4本と**同じURL**（#cases #reward #reasons #faq）なので、
#   この配列に足す行はない。URLの重複を避けるため、本数ではなく「着地先の集合」を管理している。
# 2026-08-12: アカウント単位の運用をやめた（経緯は下の「⚠️ アカウント単位は使わない」）。
#   アカウント単位2本を A・C にキャンペーン単位で移設したので稼働本数は 14→16 本。
#   これもURLの集合は変わらないため、この配列の中身は据え置き。
AD_SITELINK_URLS = [
    # 現在は全17本がキャンペーン単位（A 7本 / C 6本 / D 4本）。URLの実体は下の11種。
    # 2026-08-12: A に #gift を追加して 16→17 本（設計書 §0-15）。
    # ── ライバー向け（/beginner/）: A と C の両方が使う ──
    # #flow は 2026-08-11 に #campaign から変更した。#campaign は期間限定セクションで
    # 枠ごと消される運用だったため、常設の FLOW セクションへ移した（設計書 §5-5）。
    "https://taitan-pro-lp.netlify.app/beginner/#flow",
    "https://taitan-pro-lp.netlify.app/beginner/#network",
    # 下の4本は C単位4本（2026-07-23 照合済み）と A単位4本（2026-08-11 登録）の共通の着地先。
    # A と C で説明文は違うが、URLは同一。
    "https://taitan-pro-lp.netlify.app/beginner/#cases",
    "https://taitan-pro-lp.netlify.app/beginner/#reward",
    "https://taitan-pro-lp.netlify.app/beginner/#reasons",
    "https://taitan-pro-lp.netlify.app/beginner/#faq",
    # A の7本目（2026-08-12 登録＝設計書 §0-15）。LP側に恒久セクション #gift を
    # 新設したうえで着地先にした。既存6本は消していない＝純増。
    "https://taitan-pro-lp.netlify.app/beginner/#gift",
    # ── 代理店向け（/agency/）: D 単位4本のみ ──
    # 2026-08-04 登録・稼働中。2026-08-11 に確定案へ揃える上書き修正。
    "https://taitan-pro-lp.netlify.app/agency/#gift",
    "https://taitan-pro-lp.netlify.app/agency/#reward",
    "https://taitan-pro-lp.netlify.app/agency/#reasons",
    "https://taitan-pro-lp.netlify.app/agency/#faq",
    # ⚠️ #campaign はサイトリンクの着地先ではなくなったが、LP側のセクションは残してある。
    #    再びサイトリンクを向けるときはここに戻すこと。
]

# ⚠️ アカウント単位のサイトリンクは今後**使わない**（2026-08-12 決定・実施済み）
#
# Google広告では、アカウント単位アセットを「特定のキャンペーンにだけ出さない」ことが
# できない。管理画面で確認した実態は次のとおり:
#   ・アセット行の操作は 削除／一時停止／有効／追加先 の4つだけ。「追加先」の中身は
#     アカウント／キャンペーン／広告グループ＝**足す方向のみ**で、除外に当たる項目がない。
#   ・キャンペーン設定にもアカウント単位アセットのオプトアウトは存在しない。
#   ・「キャンペーン単位があれば上書きされる」も誤り。D はキャンペーン単位4本を持ちながら、
#     アカウント単位2本が各198表示していた（＝併走配信される）。
# その結果、ライバー文言の2本が代理店キャンペーンD にも出て、踏めばライバーLPに着地する
# 状態だった（実クリックは0件・￥0 で事故には至らず）。
#
# 対処: 同じアセットを A と C に**キャンペーン単位で紐付け直し**、アカウント単位の関連付けは
# 一時停止した。レベルごとの関連付けは独立していて、アカウント単位を一時停止しても
# キャンペーン単位は「有効」のまま残ることを実データで確認済み。
# ※「削除」は使わないこと。確認ダイアログが「関連付けられているキャンペーンまたは広告
#   グループからも削除されます」と警告するとおり、アセット本体ごと消えてキャンペーン単位の
#   紐付けまで巻き添えになる。止めたいだけなら必ず「一時停止」を使う。

# 読者が踏むリンクではないURL（preconnectヒント・JSON-LDの@context等）
SKIP_EXACT = {
    "https://fonts.googleapis.com",
    "https://fonts.gstatic.com",
    "https://schema.org",
}

URL_RE = re.compile(r"https?://[^\s\"'<>\\){}\]｝】、。」「『』（）【　]+")


def _clean(url):
    return url.rstrip(".,;:!?*_~`)»›」')")


def extract_repo_urls():
    """コンテンツファイルから URL → 出現ファイル一覧 を集める"""
    found = {}
    for pattern in CONTENT_GLOBS:
        for fp in glob.glob(os.path.join(BASE_DIR, pattern), recursive=True):
            try:
                with open(fp, encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, IsADirectoryError):
                continue
            rel = os.path.relpath(fp, BASE_DIR)
            if any(part in rel for part in EXCLUDE_PATH_PARTS):
                continue
            for m in URL_RE.findall(text):
                url = _clean(m)
                # f-string分割等で途切れた断片は除外（実URLはランタイム構築側で取得）
                if url.endswith("@") or url in SKIP_EXACT:
                    continue
                found.setdefault(url, set()).add(rel)

    # 稼働中のGoogle広告サイトリンク（管理画面にしか存在しないURL）
    for url in AD_SITELINK_URLS:
        found.setdefault(url, set()).add("ads/google_ads_設計書.md §5-5（広告サイトリンク）")

    # ランタイム構築される重要URL（特典PDFのjsDelivr URL＝SHA固定）
    try:
        sys.path.insert(0, os.path.join(BASE_DIR, "line_bot"))
        from messages import GUIDE_URL
        found.setdefault(GUIDE_URL, set()).add("line_bot/messages.py(GUIDE_URL)")
    except Exception as e:
        print(f"[WARN] GUIDE_URLのimport失敗: {e}")
    return found


def fetch_note_urls():
    """公開Note全記事の本文からURLを集める（公開API・cookie不要）"""
    found = {}
    keys = []
    page = 1
    while True:
        r = requests.get(
            f"https://note.com/api/v2/creators/{NOTE_CREATOR}/contents?kind=note&page={page}",
            headers={"User-Agent": UA}, timeout=20)
        d = r.json()["data"]
        keys += [c["key"] for c in d["contents"]]
        if d.get("isLastPage"):
            break
        page += 1
        time.sleep(0.5)
    print(f"公開Note記事: {len(keys)}本")
    for k in keys:
        try:
            r = requests.get(f"https://note.com/api/v3/notes/{k}",
                             headers={"User-Agent": UA}, timeout=20)
            body = r.json()["data"].get("body", "")
        except Exception as e:
            print(f"  [WARN] {k} 本文取得失敗: {e}")
            continue
        for m in re.findall(r'href="([^"]+)"', body) + URL_RE.findall(body):
            url = _clean(m)
            if url.startswith("http"):
                found.setdefault(url, set()).add(f"note:{k}")
        time.sleep(0.6)
    return found


def _fragment_exists(html, frag):
    """HTML中に id="frag" / name="frag" が存在するか"""
    q = re.escape(frag)
    return bool(re.search(rf'\b(?:id|name)\s*=\s*["\']{q}["\']', html)
                or re.search(rf"\b(?:id|name)\s*=\s*{q}(?=[\s/>])", html))


def check_url(url):
    """URLの生死判定。('dead'|'warn'|'ok', 詳細) を返す"""
    frag = ""
    if "#" in url:
        base, frag = url.split("#", 1)
    else:
        base = url
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15,
                         allow_redirects=True, stream=True)
        code = r.status_code
        # フラグメント検証のため本文が要る場合だけ読む（それ以外は stream のまま捨てる）
        html = ""
        if frag and code < 400 and any(d in base for d in FRAGMENT_CHECK_DOMAINS):
            r.encoding = r.encoding or "utf-8"
            html = r.text
        r.close()
    except requests.RequestException as e:
        return "warn", f"接続エラー: {type(e).__name__}"
    if code in (404, 410):
        return "dead", f"HTTP {code}"
    if code >= 400:
        return "warn", f"HTTP {code}（bot拒否の可能性）"
    # フラグメント切れ（自サイトのみ判定する）
    # 2026-08-10: `…netlify.app/#apply` の id が LP に一度も存在せず、読者は
    # アンカージャンプせずトップに着地していた。HTTP 200 なので従来のGET判定は
    # 素通りしていた。リンク先の「セクション」まで含めて生死を見る。
    if html and not _fragment_exists(html, frag):
        return "dead", f"HTTP {code} だが #{frag} が着地先に存在しない"
    return "ok", f"HTTP {code}"


def main():
    repo_only = "--repo-only" in sys.argv

    urls = extract_repo_urls()
    if not repo_only:
        for url, srcs in fetch_note_urls().items():
            urls.setdefault(url, set()).update(srcs)

    dead, warns = [], []

    # 1. 許可リスト外の lin.ee / 既知の死にリンク
    for url, srcs in sorted(urls.items()):
        if "lin.ee" in url and url not in LINE_ALLOWED:
            dead.append({"url": url, "reason": "許可リスト外のLINEリンク",
                         "sources": sorted(srcs)})
        elif any(bad in url for bad in KNOWN_DEAD):
            dead.append({"url": url, "reason": "既知の死にリンク",
                         "sources": sorted(srcs)})

    # 2. 実チェック
    flagged = {d["url"] for d in dead}
    targets = [(u, s) for u, s in sorted(urls.items())
               if u not in flagged and not any(d in u for d in SKIP_DOMAINS)]
    print(f"チェック対象URL: {len(targets)}件（全抽出 {len(urls)}件）")
    for url, srcs in targets:
        status, detail = check_url(url)
        mark = {"ok": "  ", "warn": "⚠️", "dead": "❌"}[status]
        print(f" {mark} {detail:28s} {url[:90]}")
        entry = {"url": url, "reason": detail, "sources": sorted(srcs)}
        if status == "dead":
            dead.append(entry)
        elif status == "warn":
            warns.append(entry)
        time.sleep(0.4)

    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump({"checked": len(targets), "dead": dead, "warn": warns},
                  f, ensure_ascii=False, indent=1)

    print(f"\n[結果] dead={len(dead)} warn={len(warns)} → {REPORT_FILE}")
    for d in dead:
        print(f"  ❌ {d['url']}")
        print(f"     理由: {d['reason']}")
        print(f"     出現: {', '.join(d['sources'][:6])}"
              + (f" ほか{len(d['sources'])-6}件" if len(d["sources"]) > 6 else ""))
    if dead:
        sys.exit(1)
    print("死にリンクなし ✅")


if __name__ == "__main__":
    main()
