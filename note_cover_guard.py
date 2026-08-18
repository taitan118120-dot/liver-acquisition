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

  2026-08-18追記: ローカルに画像があっても「note上のアイキャッチが空のまま
  公開されている」ことがある（note editor のUI変更で自動設定が5日間失敗し、
  #137-141 がカバー無しで公開されていた）。ローカル照合だけでは気づけないので
  --published で公開中の記事のeyecatchも実際に叩いて確認する。

使い方:
  python3 note_cover_guard.py              # ローカル照合のみ。欠落あれば exit 1
  python3 note_cover_guard.py --json       # 結果を data/note_cover_guard_report.json にも出力
  python3 note_cover_guard.py --published  # 公開中の記事のeyecatchもnote APIで確認
"""
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import note_set_eyecatch

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTICLES_DIR = os.path.join(BASE_DIR, "blog", "articles_note")
REPORT_PATH = os.path.join(BASE_DIR, "data", "note_cover_guard_report.json")

NOTE_URLNAME = "taitan_118"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

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


def check_published():
    """公開中の記事を note の公開APIで舐めて、eyecatchが空のものを返す。

    戻り値 (total, missing, unchecked)。ネットワークが死んでいるときは
    unchecked=True にして「欠落0」と誤判定しないようにする。
    """
    notes, page = [], 1
    while page <= 20:
        url = (f"https://note.com/api/v2/creators/{NOTE_URLNAME}"
               f"/contents?kind=note&page={page}")
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))["data"]
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as e:
            print(f"  ⚠️ 公開記事の取得に失敗（page {page}）: {str(e)[:80]}")
            return len(notes), [], True
        notes.extend(data.get("contents", []))
        if data.get("isLastPage"):
            break
        page += 1
        time.sleep(0.4)

    missing = [{"key": n["key"], "title": (n.get("name") or "")[:60],
                "published_at": (n.get("publishAt") or "")[:10]}
               for n in notes if not n.get("eyecatch")]
    return len(notes), missing, False


def main():
    args = sys.argv[1:]
    write_json = "--json" in args
    with_published = "--published" in args

    articles, missing = check()
    print(f"Note カバー画像 番犬: 記事{len(articles)}本を検査")

    pub_total, pub_missing, pub_unchecked = 0, [], False
    if with_published:
        pub_total, pub_missing, pub_unchecked = check_published()
        state = "確認できず" if pub_unchecked else f"欠落{len(pub_missing)}本"
        print(f"公開中の記事{pub_total}本のアイキャッチを確認: {state}")

    if write_json:
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump({"total": len(articles), "missing": missing,
                       "published_total": pub_total,
                       "published_missing": pub_missing,
                       "published_unchecked": pub_unchecked},
                      f, ensure_ascii=False, indent=2)

    if missing:
        print(f"\n❌ カバー画像が欠落している記事 {len(missing)}本:")
        for m in missing:
            print(f"  - #{m['num']}  {m['article']}")
            print(f"      → blog/images/{m['num']}_*.png を追加してください")
        print("\n対処:")
        print("  1. python3 note_cover_make.py {番号} でカバーを作る")
        print("     （写真＋大きな見出しの合成。文字だけのカードは禁止）")
        print("  2. python3 note_cover_guard.py がローカルで緑になることを確認")

    if pub_missing:
        print(f"\n❌ 公開中なのにアイキャッチが空の記事 {len(pub_missing)}本:")
        for m in pub_missing:
            print(f"  - {m['key']} ({m['published_at']}) {m['title']}")
        print("\n対処: python3 note_set_eyecatch.py {記事番号} {note_key}")

    if missing or pub_missing:
        sys.exit(1)

    print("✅ ローカル・公開中ともにカバー画像あり" if with_published
          else "✅ 全記事にカバー画像あり")
    sys.exit(0)


if __name__ == "__main__":
    main()
