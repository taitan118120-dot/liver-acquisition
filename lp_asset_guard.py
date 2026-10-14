#!/usr/bin/env python3
"""lp_asset_guard.py — 公開LPの表示素材（CSS/JS/画像）の404を検知する番犬
====================================================================
旧 lp_drift_guard.py（LPドリフト番犬）の「3. 表示素材」だけを切り出したもの。
2026-10-14 に手動zipデプロイの -targets サイトを Netlify ごと削除し、公開LPが
https://taitan-pro-lp.netlify.app の1つだけになったので、2サイト間の本文突合は役目を終えた。
一方で素材チェックはメイン側も見ていた唯一の番犬だったので、ここに残す。

背景（2026-10-08）:
  lp/netlify.toml の `/` → `/beginner/index.html` が status=200 の書き換えだったため、
  トップでは beginner の相対 `style.css` が `/style.css` を見て404になり、
  2026-07-20〜10-08 の約2か月半、トップがCSSなしの素のHTMLで表示されていた
  （11ca994 で 301 に修正）。HTML自体は200なので link_guard（URLの生死）は緑、
  content_facts_guard はローカルファイルだけ——「ページは返るが見た目が壊れている」を
  見る番犬が他に無い。

見るもの:
  `/` と各ページについて、リダイレクトを追従した**最終URL基準で**
  <link rel=stylesheet> / <script src> / <img src|srcset> を解決し、
  同一オリジンのものが全部 200（かつ正しい Content-Type）で返るかを見る。
  外部（fonts.googleapis.com 等）は見ない。
  `/` を必ず含めるのは、書き換え・リダイレクトのような**URLとHTMLの対応が変わる設定**で
  壊れるのはその入口だからで、/beginner/ を直接見ても再現しない。

判定ポリシー:
  NG = 同一オリジンの表示素材が200以外／Content-Type 不一致／**ページを取得できなかった**
       → exit 1（Actionsが赤くなる）
  取得失敗を素通りさせない理由: 「見なかった」と「壊れていなかった」がどちらも緑になると、
  Issueの自動クローズが嘘をつく（[[feedback_watchdog_autoclose]]）。

使い方:
  python3 lp_asset_guard.py

レポートは data/lp_asset_guard_report.json に保存される。
"""

import json
import os
import sys
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_FILE = os.path.join(BASE_DIR, "data", "lp_asset_guard_report.json")

SITE = "https://taitan-pro-lp.netlify.app"

# 配られている全ページ。下限の4ページに lp/ の実体から自動で足す
# （手で並べるだけだと、LPを増やしたときに新しいページだけ誰も見ていない状態になる）。
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

# Content-Type も見る。200 でも中身が HTML（例: リダイレクト規則が素材パスまで
# 巻き込んでページに飛ばす）だと、ブラウザは nosniff でCSSとして読まないので
# 見た目は404と同じく壊れる。ステータスだけ見ると、それはまた素通りになる。
ASSET_TYPES = {
    "css": ("text/css",),
    "js": ("javascript", "ecmascript"),
    "img": ("image/",),
}


def fetch(path):
    """(html, 最終URL, error) を返す。取得できなかったことは**必ず呼び出し側に届ける**。
    最終URLはリダイレクト追従後のもので、素材の相対パスはこれを基準に解決する（ブラウザと同じ）。"""
    url = f"{SITE}{path}"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20,
                         allow_redirects=True)
    except requests.RequestException as e:
        return None, url, f"{url} の取得に失敗: {type(e).__name__}: {e}"[:200]
    if r.status_code != 200:
        return None, r.url, f"{url} が HTTP {r.status_code}"
    r.encoding = r.encoding or "utf-8"
    return r.text, r.url, None


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


def main():
    entries = ["/"] + [f"/{p}/" for p in PAGES]
    verified, broken = [], []
    cache = {}  # 絶対URL → (ok, 詳細)。共通素材をページごとに叩き直さない

    print(f"[表示素材] {SITE} の同一オリジンの CSS/JS/画像 を最終URL基準で確認")
    for path in entries:
        html, final_url, err = fetch(path)
        time.sleep(0.4)
        page_url = f"{SITE}{path}"
        if err:
            # 素材を見られなかった入口は「壊れていなかった」ではない
            broken.append({"entry": path, "page_url": page_url, "final_url": final_url,
                           "asset": "", "kind": "page", "reason": f"ページ取得失敗: {err}"})
            print(f" ❌ {path} ページ取得失敗")
            continue
        assets = collect_assets(html, final_url)
        bad = []
        for kind, url in assets:
            if url not in cache:
                cache[url] = check_asset(url, kind)
                time.sleep(0.2)
            ok, detail = cache[url]
            if not ok:
                bad.append({"entry": path, "page_url": page_url, "final_url": final_url,
                            "asset": url, "kind": kind, "reason": detail})
        broken += bad
        verified.append(path)
        hop = f" → {final_url}" if final_url != page_url else ""
        if bad:
            print(f" ❌ {path}{hop} 素材 {len(bad)}/{len(assets)}件が取得できず")
            for b in bad:
                print(f"     {b['kind']:3s} {b['reason']}: {b['asset']}")
        else:
            print(f"    {path}{hop} 素材 {len(assets)}件 すべて200")

    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "site": SITE,
            "entries": entries,
            # 「ページを取得して素材を全部叩き終えた入口」。自動クローズはこれしか信用しない。
            "verified": verified,
            "assets_checked": len(cache),
            "broken": broken,
        }, f, ensure_ascii=False, indent=1)

    print(f"\n[走査] {len(verified)}/{len(entries)}入口・{len(cache)}URL"
          f" → {os.path.relpath(REPORT_FILE, BASE_DIR)}")
    if broken:
        print(f"  ❌ 表示素材が取得できない入口: "
              f"{', '.join(sorted({b['entry'] for b in broken}))}（{len(broken)}件）")
        return 1
    print("表示素材すべて200 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
