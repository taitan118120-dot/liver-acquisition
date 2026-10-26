"""公開LPの URL を IndexNow で Bing 等の検索エンジンへ通知する。

背景（2026-10-26）: taitan-pro-lp.netlify.app は Google に1ページもインデックスされていなかった
（site: 検索0件）。被リンクがほぼ Note（外部リンクは nofollow）だけで、クローラーが辿り着けていない。
Google は Search Console でのサイトマップ送信が必要（手動）だが、Bing / Yandex / Seznam / Naver は
IndexNow で即時通知できる。ChatGPT の検索は Bing のインデックスを使うので GEO 経路にも効く。

キーファイルは lp/<KEY>.txt（中身はキーそのもの）。Netlify で
https://taitan-pro-lp.netlify.app/<KEY>.txt として配信されている必要がある。

使い方:
  python lp_indexnow.py           # sitemap.xml の全URLを通知
  python lp_indexnow.py --dry-run # 送信せず対象URLだけ表示
"""
import re
import sys
from pathlib import Path

import requests

HOST = "taitan-pro-lp.netlify.app"
KEY = "a2a355f081d62dbff9341e54b4d51b1f"
LP_DIR = Path(__file__).resolve().parent / "lp"


def sitemap_urls():
    xml = (LP_DIR / "sitemap.xml").read_text(encoding="utf-8")
    return re.findall(r"<loc>([^<]+)</loc>", xml)


def main():
    urls = sitemap_urls()
    print("\n".join(urls))
    if "--dry-run" in sys.argv:
        return 0

    # 公開側でキーファイルが見えないと IndexNow は 403 を返すので、先に確かめて原因を明示する
    key_url = f"https://{HOST}/{KEY}.txt"
    r = requests.get(key_url, timeout=20)
    if r.status_code != 200 or r.text.strip() != KEY:
        print(f"::error::キーファイルが公開されていない: {key_url} → {r.status_code}")
        return 1

    r = requests.post(
        "https://api.indexnow.org/indexnow",
        json={"host": HOST, "key": KEY, "keyLocation": key_url, "urlList": urls},
        timeout=30,
    )
    print(f"IndexNow → {r.status_code} {r.text[:200]}")
    # 200=受理 / 202=受理（キー検証待ち）。それ以外は失敗として赤にする
    return 0 if r.status_code in (200, 202) else 1


if __name__ == "__main__":
    sys.exit(main())
