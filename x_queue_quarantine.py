#!/usr/bin/env python3
"""x_queue_quarantine.py — X投稿キューから確定ファクト違反を隔離する
=====================================================================
2026-08-09。x_post_guard.py を投稿直前ゲートとして入れたので違反投稿が
公開されることはもう無いが、posts/twitter_posts.json 側には違反が
290本（全585本中）そのまま残っていた。放置すると:
  - cloud_post.py が毎回290本を除外してログを埋める
  - **posts/twitter_posts.json を別用途で読む経路に漏れる**
    （instagram/ig_content_generator.py がツイートをIG投稿のソースにしている、
      blog/generate_articles.py が記事ネタにしている）
    ＝ X では止まっても IG・ブログ側から同じ文面が出ていく

そこで違反分は posts/twitter_posts_blocked.json に理由付きで退避する。
削除ではなく退避にするのは、文面を直せば再利用できる資産だから
（288本は数ヶ月分のストック）。

使い方:
  python3 x_queue_quarantine.py --dry-run   # 何が動くか見るだけ
  python3 x_queue_quarantine.py             # 実行
"""

import argparse
import json
import os
import sys

from x_post_guard import details, post_body

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSTS_FILE = os.path.join(BASE_DIR, "posts", "twitter_posts.json")
BLOCKED_FILE = os.path.join(BASE_DIR, "posts", "twitter_posts_blocked.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(POSTS_FILE, encoding="utf-8") as f:
        posts = json.load(f)

    keep, moved = [], []
    for p in posts:
        d = details(post_body(p))
        if d:
            entry = dict(p)
            entry["blocked_reasons"] = [{"reason": r, "hit": h} for r, h in d]
            entry["blocked_at"] = "2026-08-09"
            moved.append(entry)
        else:
            keep.append(p)

    print(f"{len(posts)}本 → 残す {len(keep)} / 隔離 {len(moved)}")
    print(f"  growth 残り: {sum(1 for p in keep if p.get('phase') == 'growth')}本")

    if args.dry_run:
        for m in moved[:5]:
            print(f"  [隔離] {m['id']}: "
                  f"{', '.join(r['reason'] for r in m['blocked_reasons'])}")
        print("  ...(--dry-run のため書き込みなし)")
        return 0

    existing = []
    if os.path.exists(BLOCKED_FILE):
        with open(BLOCKED_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    known = {p.get("id") for p in existing}
    existing += [m for m in moved if m.get("id") not in known]

    with open(BLOCKED_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=4)
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(keep, f, ensure_ascii=False, indent=4)

    print(f"→ {os.path.relpath(BLOCKED_FILE, BASE_DIR)} に {len(existing)}本")
    print(f"→ {os.path.relpath(POSTS_FILE, BASE_DIR)} は {len(keep)}本")
    return 0


if __name__ == "__main__":
    sys.exit(main())
