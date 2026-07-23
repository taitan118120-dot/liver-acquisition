#!/usr/bin/env python3
"""note_cover_guard.py
Note記事のカバー画像（アイキャッチ）付け忘れを push 時点で検知する番犬。

背景:
  blog/articles_note/ に記事(.md)を追加したとき、対応する
  blog/images/{番号}_*.png を付け忘れると、note_auto_poster.py が
  「カバー画像なし」で公開を中止し exit 3 で失敗する。
  ただしこの失敗は「翌日の自動投稿ジョブ」まで顕在化しないため、
  原因コミットから時間が経ってから気づくことになっていた（#120-122で発生）。

動作:
  blog/articles_note/ の全記事番号について blog/images/{番号}_*.png の
  存在を照合し、欠落があれば一覧を出して exit 1（CIを赤くする）。
  カバー解決は note_set_eyecatch.resolve_image を流用（poster と同じ判定）。

使い方:
  python3 note_cover_guard.py          # 検査のみ。欠落あれば exit 1
  python3 note_cover_guard.py --json   # 結果を data/note_cover_guard_report.json にも出力
"""
import glob
import json
import os
import re
import sys

import note_set_eyecatch

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTICLES_DIR = os.path.join(BASE_DIR, "blog", "articles_note")
REPORT_PATH = os.path.join(BASE_DIR, "data", "note_cover_guard_report.json")

# 記事ファイル名の先頭番号を取る（例: 120_xxx.md → 120）
NUM_RE = re.compile(r"^(\d+)_")


def list_articles():
    """(番号, ファイル名) のリストを番号順で返す。"""
    out = []
    for path in glob.glob(os.path.join(ARTICLES_DIR, "*.md")):
        name = os.path.basename(path)
        m = NUM_RE.match(name)
        if not m:
            # 番号なしファイルは投稿対象外とみなしスキップ（例: README等）
            continue
        out.append((int(m.group(1)), name))
    return sorted(out, key=lambda x: x[0])


def check():
    """カバー欠落記事の一覧を返す。"""
    missing = []
    articles = list_articles()
    for num, name in articles:
        # poster と完全に同じ解決ロジックで判定する
        if not note_set_eyecatch.resolve_image(num):
            missing.append({"num": num, "article": name})
    return articles, missing


def main():
    write_json = "--json" in sys.argv[1:]
    articles, missing = check()

    print(f"Note カバー画像 番犬: 記事{len(articles)}本を検査")

    if write_json:
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump({"total": len(articles), "missing": missing},
                      f, ensure_ascii=False, indent=2)

    if not missing:
        print("✅ 全記事にカバー画像あり")
        sys.exit(0)

    print(f"\n❌ カバー画像が欠落している記事 {len(missing)}本:")
    for m in missing:
        print(f"  - #{m['num']}  {m['article']}")
        print(f"      → blog/images/{m['num']}_*.png を追加してください")
    print("\n対処:")
    print("  1. 記事内容に合う画像を blog/images/{番号}_slug.png として追加")
    print("     （テキストだけのカードは禁止。既存イラスト素材の流用可）")
    print("  2. python3 note_cover_guard.py がローカルで緑になることを確認")
    sys.exit(1)


if __name__ == "__main__":
    main()
