#!/usr/bin/env python3
"""lp_drift_guard.py — 2つの公開LPサイトの本文ドリフトと表示素材の404を検知する番犬
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

この番犬が見る3軸:
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

  3. 表示素材（CSS/JS/画像）の404 — 2026-10-08 追加。両サイトの `/` と各ページについて、
     リダイレクトを追従した**最終URL基準で** <link rel=stylesheet> / <script src> /
     <img src|srcset> を解決し、同一オリジンのものが全部 200 で返るかを見る。
     外部（fonts.googleapis.com 等）は見ない。
     背景: lp/netlify.toml の `/` → `/beginner/index.html` が status=200 の書き換えだったため、
     トップでは beginner の相対 `style.css` が `/style.css` を見て404になり、
     2026-07-20〜10-08 の約2か月半、トップがCSSなしの素のHTMLで表示されていた
     （11ca994 で 301 に修正）。HTML自体は200なので link_guard（URLの生死）は緑、
     この番犬の1・2も /beginner/ 等の本文しか見ていないので緑、content_facts_guard は
     ローカルファイルだけ——「ページは返るが見た目が壊れている」を見る番犬が無かった。
     `/` を必ず含めるのは、書き換え・リダイレクトのような**URLとHTMLの対応が変わる設定**で
     壊れるのはその入口だからで、/beginner/ を直接見ても再現しない。

無視してよい差分:
  Netlify の post-processing が各サイトの site_id を埋めて挿し込む netlify.new の
  URL だけ。2026-09-11 に両サイト4ページを実測したとき、site_id を伏せた状態で
  差分は**完全に0バイト**だった（HTMLコメント1行と <meta name="netlify-deploy"> の
  1行、どちらも netlify.new/?…utm_id=<site_id> を含む）。site_id だけを伏せて
  それ以外の差はすべてドリフト扱いにする——「無視リスト」を広げると、
  この番犬は静かに何も見なくなる。

判定ポリシー:
  - NG = 本文ドリフト／-targets の確定ファクト違反／**どちらかのページを取得できなかった**
         ／同一オリジンの表示素材が200以外（接続エラーも含む＝確認できていないので赤）
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
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

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
    """(html, 最終URL, error) を返す。取得できなかったことは**必ず呼び出し側に届ける**。
    page="" はサイトのトップ（/）。最終URLはリダイレクト追従後のもので、
    表示素材の相対パスはこれを基準に解決する（ブラウザと同じ）。"""
    url = f"{site}/{page}/" if page else f"{site}/"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20,
                         allow_redirects=True)
    except requests.RequestException as e:
        return None, url, f"{url} の取得に失敗: {type(e).__name__}: {e}"[:200]
    if r.status_code != 200:
        return None, r.url, f"{url} が HTTP {r.status_code}"
    r.encoding = r.encoding or "utf-8"
    return r.text, r.url, None


# ── 3. 表示素材（CSS/JS/画像）──
# Content-Type も見る。200 でも中身が HTML（例: リダイレクト規則が素材パスまで
# 巻き込んでページに飛ばす）だと、ブラウザは nosniff でCSSとして読まないので
# 見た目は404と同じく壊れる。ステータスだけ見ると、それはまた素通りになる。
ASSET_TYPES = {
    "css": ("text/css",),
    "js": ("javascript", "ecmascript"),
    "img": ("image/",),
}


class _AssetCollector(HTMLParser):
    """<link rel=stylesheet> / <script src> / <img src|srcset> と <base href> を拾う"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.base = None
        self.assets = []  # [(kind, 生のURL)]

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "").strip() for k, v in attrs}
        if tag == "base" and a.get("href") and self.base is None:
            self.base = a["href"]
        elif tag == "link" and "stylesheet" in a.get("rel", "").lower().split():
            if a.get("href"):
                self.assets.append(("css", a["href"]))
        elif tag == "script" and a.get("src"):
            self.assets.append(("js", a["src"]))
        elif tag == "img":
            if a.get("src"):
                self.assets.append(("img", a["src"]))
            for cand in a.get("srcset", "").split(","):
                if cand.strip():
                    self.assets.append(("img", cand.split()[0]))


def collect_assets(html, final_url):
    """最終URL基準で解決した同一オリジンの素材 [(kind, 絶対URL)]（重複なし）。
    外部ドメイン（fonts.googleapis.com 等）は見ない＝こちらで直せないため。"""
    p = _AssetCollector()
    p.feed(html)
    p.close()
    base = urljoin(final_url, p.base) if p.base else final_url
    origin = urlsplit(final_url)[:2]
    out = {}
    for kind, raw in p.assets:
        if raw.startswith(("data:", "javascript:", "#")):
            continue
        url = urljoin(base, raw).split("#", 1)[0]
        if urlsplit(url)[:2] != origin:
            continue
        out.setdefault(url, kind)
    return [(kind, url) for url, kind in out.items()]


def check_asset(url, kind):
    """(ok, 詳細)。接続エラーと5xxだけ1回取り直す（Netlify側の瞬断で赤にしないため）。
    取り直しても確認できなければ赤——「確認できなかった」を緑にしない。"""
    last = ""
    for _ in range(2):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=20,
                             allow_redirects=True, stream=True)
            code = r.status_code
            ctype = r.headers.get("Content-Type", "").lower()
            r.close()
        except requests.RequestException as e:
            last = f"接続エラー: {type(e).__name__}"
            time.sleep(2)
            continue
        if code >= 500:
            last = f"HTTP {code}"
            time.sleep(2)
            continue
        if code != 200:
            return False, f"HTTP {code}"
        if not any(t in ctype for t in ASSET_TYPES[kind]):
            return False, (f"HTTP 200 だが Content-Type が {ctype or '(なし)'}"
                           f"（{kind} として読まれない）")
        return True, "HTTP 200"
    return False, f"{last}（取り直しても確認できず）"


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
    # 表示素材チェック用に、取得したページを (サイト名, パス) → (html, 最終URL, err) で取っておく
    fetched = {}

    for page in PAGES:
        main_html, main_final, err_a = fetch(SITE_MAIN, page)
        time.sleep(0.4)
        targets_html, targets_final, err_b = fetch(SITE_TARGETS, page)
        time.sleep(0.4)
        fetched[("main", f"/{page}/")] = (main_html, main_final, err_a)
        fetched[("targets", f"/{page}/")] = (targets_html, targets_final, err_b)

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

    # ── 3. 表示素材 ──
    # トップ（/）は本文突合の対象外（リダイレクトで /beginner/ に着くだけ）だが、
    # 2026-07〜10 に壊れていたのはまさにここなので、素材チェックでは必ず入口に含める。
    sites = {"main": SITE_MAIN, "targets": SITE_TARGETS}
    for label, site in sites.items():
        fetched[(label, "/")] = fetch(site, "")
        time.sleep(0.4)

    print("\n[表示素材] 同一オリジンの CSS/JS/画像 を最終URL基準で確認")
    asset_entries, asset_verified, assets_broken = [], [], []
    asset_cache = {}  # 絶対URL → (ok, 詳細)。共通素材をページごとに叩き直さない
    entry_order = ["/"] + [f"/{p}/" for p in PAGES]
    for label in sites:
        for path in entry_order:
            key = f"{label}:{path}"
            asset_entries.append(key)
            html, final_url, err = fetched[(label, path)]
            page_url = f"{sites[label]}{path}"
            if err:
                # 素材を見られなかった入口は「壊れていなかった」ではない
                assets_broken.append({"entry": key, "page_url": page_url,
                                      "final_url": final_url, "asset": "",
                                      "kind": "page", "reason": f"ページ取得失敗: {err}"})
                print(f" ❌ {key} ページ取得失敗")
                continue
            assets = collect_assets(html, final_url)
            bad = []
            for kind, url in assets:
                if url not in asset_cache:
                    asset_cache[url] = check_asset(url, kind)
                    time.sleep(0.2)
                ok, detail = asset_cache[url]
                if not ok:
                    bad.append({"entry": key, "page_url": page_url,
                                "final_url": final_url, "asset": url,
                                "kind": kind, "reason": detail})
            assets_broken += bad
            asset_verified.append(key)
            hop = f" → {final_url}" if final_url != page_url else ""
            if bad:
                print(f" ❌ {key}{hop} 素材 {len(bad)}/{len(assets)}件が取得できず")
                for b in bad:
                    print(f"     {b['kind']:3s} {b['reason']}: {b['asset']}")
            else:
                print(f"    {key}{hop} 素材 {len(assets)}件 すべて200")

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
            # 表示素材（キーは "main:/beginner/" の形）。asset_verified は
            # 「ページを取得して素材を全部叩き終えた入口」。自動クローズはこれしか信用しない。
            "asset_entries": asset_entries,
            "asset_verified": asset_verified,
            "assets_checked": len(asset_cache),
            "assets_broken": assets_broken,
        }, f, ensure_ascii=False, indent=1)

    print(f"\n[走査] {len(verified)}/{len(PAGES)}ページを2サイトで突合、"
          f"表示素材は {len(asset_verified)}/{len(asset_entries)}入口・{len(asset_cache)}URL")
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

    if assets_broken:
        print(f"\n  ❌ 表示素材が取得できない入口: "
              f"{', '.join(sorted({b['entry'] for b in assets_broken}))}"
              f"（{len(assets_broken)}件）")

    if drift or ng:
        print("\n復旧: -targets は手動デプロイなので、直すには ./scripts/lp_targets_deploy.sh")
    if drift or ng or assets_broken:
        return 1
    print("\n2サイトのLP本文は一致・確定ファクト違反なし・表示素材すべて200 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
