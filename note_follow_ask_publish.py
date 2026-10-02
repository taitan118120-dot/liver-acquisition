#!/usr/bin/env python3
"""公開済みnote記事の最末尾に「noteのフォロー」依頼を追記して再公開する。

新規公開分は note_auto_poster.add_follow_ask が自動で入れる（2026-10-02〜）。
これはそれ以前に公開済みの記事向けの後付け。文面・マーカーは note_auto_poster が正本。

- 挿入位置: 本文の最末尾（LINE CTAの後ろ）
- 冪等: マーカー「noteのフォロー」が既にあればスキップ
- 機構は note_leadmagnet_publish.publish_one（検証・タグ復元込み）

使い方:
  python3 note_follow_ask_publish.py --top 30 [--csv data/note_pv_YYYYMMDD.csv] [--dry-run]
  python3 note_follow_ask_publish.py <key> [<key> ...]
"""
import argparse
import csv
import glob
import os
import time

from note_auto_poster import FOLLOW_ASK, FOLLOW_ASK_MARK, markdown_to_html

FOLLOW_ASK_HTML = markdown_to_html(FOLLOW_ASK)


def transform_follow(key, html):
    if FOLLOW_ASK_MARK in html:
        return None  # 済み
    return html.rstrip() + FOLLOW_ASK_HTML


def top_keys(csv_path, n):
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: int(r["pv_monthly"] or 0), reverse=True)
    return [(r["key"], r["title"]) for r in rows[:n]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keys", nargs="*")
    ap.add_argument("--top", type=int)
    ap.add_argument("--csv")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    targets = [(k, "") for k in a.keys if k.startswith("n")]
    if a.top:
        path = a.csv or sorted(glob.glob(os.path.join("data", "note_pv_2*.csv")))[-1]
        print(f"PV表: {path}")
        targets += top_keys(path, a.top)
    if not targets:
        print(__doc__)
        return

    if a.dry_run:
        for k, t in targets:
            print(f"  {k} {t[:50]}")
        print(f"[dry-run] {len(targets)}本。追記HTML:\n{FOLLOW_ASK_HTML}")
        return

    from note_leadmagnet_publish import publish_one
    results = {}
    for i, (key, t) in enumerate(targets):
        print(f"[follow-ask {i + 1}/{len(targets)} {key}] {t[:40]}")
        try:
            results[key] = publish_one(key, transform_fn=transform_follow,
                                       expect_marker=FOLLOW_ASK_MARK)
        except Exception as e:
            print(f"  !!! ERROR: {e}")
            results[key] = f"error: {e}"
        time.sleep(3)
    print("── 結果 ──")
    for k, v in results.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
