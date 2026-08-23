#!/usr/bin/env python3
"""note_stock_guard.py — Note記事の在庫番犬
==========================================
毎日1本のNote自動投稿（note_daily_post.yml）が **在庫切れで止まる前に** 鳴く。

背景（2026-08-23）:
  未投稿記事が0本になり、その日の note_daily_post が exit 3 で失敗した。
  poster 側にも「残り3本以下」の警告はあるが、これは**投稿ジョブのログの中**にしか
  出ない。緑のランのログを毎日読む運用は続かないので、実際には
  「赤くなって初めて在庫切れに気づく」＝**もう1本も残っていない**状態でしか
  分からなかった。書き溜めには時間がかかるので、気づいた時点では手遅れになる。

動作:
  未投稿かつカバー画像がある記事（＝実際に投稿できる本数）を数え、
  1日1本ペースで何日分あるかを見る。しきい値（既定7日＝1週間分）を切ったら
  exit 1 で赤くし、Issue で通知する。補充されたら Issue は自動クローズされる
  （[[feedback_watchdog_autoclose]] 「直ったら閉じる」までが番犬）。

  在庫の数え方は note_auto_poster が正本。ここで独自に数え直すと、
  投稿側の走査順・重複ガードと静かにズレる（ズレた番犬は信用されなくなる）。

使い方:
  python3 note_stock_guard.py              # 既定しきい値(7日)で検査
  python3 note_stock_guard.py --min-days 10
  python3 note_stock_guard.py --json       # レポートJSONも書き出す
"""

import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_FILE = os.path.join(BASE_DIR, "data", "note_stock_guard_report.json")

# 投稿ペース（note_daily_post.yml の cron が 1日1回なのでこの値）
POSTS_PER_DAY = 1
DEFAULT_MIN_DAYS = 7


def collect():
    """(postable, no_cover) を返す。数え方の正本は note_auto_poster。"""
    sys.path.insert(0, BASE_DIR)
    import note_auto_poster as poster

    queue = poster.get_unpublished_queue()
    postable, no_cover = [], []
    for num in queue:
        (postable if poster._resolve_cover_image(num) else no_cover).append(num)
    return postable, no_cover


def article_title(num):
    import note_set_eyecatch
    return note_set_eyecatch.resolve_article_title(num)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-days", type=int, default=DEFAULT_MIN_DAYS,
                    help=f"この日数分を切ったら赤くする（既定 {DEFAULT_MIN_DAYS}）")
    ap.add_argument("--json", action="store_true", help="レポートJSONを書き出す")
    args = ap.parse_args()

    postable, no_cover = collect()
    days_left = len(postable) // POSTS_PER_DAY

    report = {
        "days_left": days_left,
        "min_days": args.min_days,
        "postable": [{"num": n, "title": article_title(n)} for n in postable],
        "no_cover": [{"num": n, "title": article_title(n)} for n in no_cover],
    }
    if args.json:
        os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)

    print(f"[在庫] 投稿できる記事 {len(postable)}本（= {days_left}日分）"
          f" / しきい値 {args.min_days}日")
    for n in postable:
        print(f"   - #{n} {article_title(n)[:44]}")
    if no_cover:
        # カバー画像が無い記事は投稿対象から飛ばされる＝在庫として数えられない。
        # note_cover_guard.py が別途これを赤くするので、ここでは表示だけする。
        print(f"[カバー画像なし] {len(no_cover)}本（在庫に数えていません）")
        for n in no_cover:
            print(f"   - #{n} {article_title(n)[:44]}")

    if days_left < args.min_days:
        print(f"\n❌ 在庫が {args.min_days}日分を切りました。"
              f" blog/articles_note/ に記事を追加してください")
        return 1
    print("\n✅ 在庫は足りています")
    return 0


if __name__ == "__main__":
    sys.exit(main())
