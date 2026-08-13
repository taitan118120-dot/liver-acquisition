#!/usr/bin/env python3
"""build_pdf.py — 特典PDF（リードマグネット）を原稿HTMLから焼く
================================================================
lead_magnet/*.html → lp/shared/*.pdf

背景（2026-08-12）:
  実在しない「京都コレクション」が lead_magnet/agency_starter_guide.html と、
  そこから焼いた **配布中の lp/shared/agency_starter_guide.pdf の実体** に残っていた。
  修正のたびに手元で playwright を叩いていたのに、**そのビルド手順が
  リポジトリのどこにもコミットされていなかった**。
  つまり「どう焼いたか」が人の記憶にしか無く、
    - 焼き直しの条件（余白0・背景印刷・CSSのページサイズ優先）が毎回うろ覚え
    - 誰かが別の設定で焼くと紙面が崩れる
    - CI・番犬から「焼き直す」手段を呼べない
  という状態だった。これはHTMLの文言と同じくらい構造的な弱点なので、正本を置く。

焼き直しの手順（この3つはセットで1つの作業）:
  1. python3 lead_magnet/build_pdf.py
  2. 変わったPDFをコミット
  3. line_bot/messages.py の GUIDE_PDF_SHA / AGENCY_GUIDE_PDF_SHA を
     **そのコミットのSHA**へ更新（jsDelivrはSHA固定で配っているので、
     ここを上げないと直したPDFは誰にも届かない）
  → 1〜3 の抜けは content_facts_guard.py が毎日検査して赤くする。

使い方:
  python3 lead_magnet/build_pdf.py                      # 全部
  python3 lead_magnet/build_pdf.py agency_starter_guide # 1本だけ

依存:
  pip install playwright && python3 -m playwright install chromium
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(HERE)
OUT_DIR = os.path.join(BASE_DIR, "lp", "shared")

# 紙面の設計はHTML側の `@page { size: A4; margin: 0 }` と .page の実寸が正本。
# ここで用紙やマージンを指定し直すと **HTMLの設計と二重管理**になり、
# 片方だけ直したときに紙面が崩れる。だからブラウザ側は「CSSに従え」とだけ言う。
PDF_OPTIONS = dict(
    prefer_css_page_size=True,  # @page size: A4 を使う（format 指定と併用不可）
    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
    print_background=True,      # 表紙の背景色・カード地・罫線が出るのに必須
)


def build(stem, page):
    src = os.path.join(HERE, f"{stem}.html")
    dst = os.path.join(OUT_DIR, f"{stem}.pdf")
    if not os.path.exists(src):
        raise SystemExit(f"原稿が無い: {src}")

    # file:// で開く。相対パス（../lp/shared/logo.jpg）の画像を読ませるため、
    # HTML文字列の set_content ではなく必ずファイルとして開くこと。
    page.goto("file://" + src, wait_until="networkidle")
    # 画像のデコード完了を待つ。networkidle だけだと表紙のロゴが
    # 抜けたPDFが焼けることがある。
    page.wait_for_function(
        "Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)")
    page.pdf(path=dst, **PDF_OPTIONS)
    print(f"  ✅ {os.path.relpath(src, BASE_DIR)} → "
          f"{os.path.relpath(dst, BASE_DIR)} ({os.path.getsize(dst):,} bytes)")


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "playwright が無い: pip install playwright && "
            "python3 -m playwright install chromium")

    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    stems = wanted or sorted(
        f[:-5] for f in os.listdir(HERE) if f.endswith(".html"))
    if not stems:
        raise SystemExit(f"原稿HTMLが1本も無い: {HERE}")

    os.makedirs(OUT_DIR, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            for stem in stems:
                build(stem, page)
        finally:
            browser.close()

    print("\n焼き直したら、コミットして line_bot/messages.py の *_PDF_SHA を"
          "そのコミットのSHAへ更新すること（jsDelivrはSHA固定配信）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
