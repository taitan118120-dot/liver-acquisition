"""
Instagram自動投稿スケジューラ

GitHub Actionsから実行される。
1. 未投稿のコンテンツがなければGeminiで自動生成
2. 次の未投稿コンテンツをInstagram Graph APIで投稿

使い方:
  python ig_scheduler.py              # 次の1件を投稿
  python ig_scheduler.py --generate   # コンテンツ生成 + 投稿
  python ig_scheduler.py --test       # テスト投稿（dry-run）
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ig_content_generator import generate_all, load_posts
from ig_poster import post_next


def run(generate_if_empty=False, dry_run=False):
    """スケジュール実行のメイン処理"""
    posts = load_posts()
    unposted = [p for p in posts if not p["posted"] and p.get("image_path")]

    print(f"投稿キュー: 全{len(posts)}件 / 未投稿{len(unposted)}件\n")

    # 未投稿がなければ生成
    if not unposted and generate_if_empty:
        print("未投稿コンテンツがないため、新規生成します...\n")
        generate_all(dry_run=dry_run)
        # 再読み込み
        posts = load_posts()
        unposted = [p for p in posts if not p["posted"] and p.get("image_path")]

    if not unposted:
        print("[INFO] 投稿するコンテンツがありません。")
        print("  `python ig_content_generator.py --generate` でコンテンツを生成してください。")
        return False

    # 次の1件を投稿
    return post_next(dry_run=dry_run)


def main():
    parser = argparse.ArgumentParser(description="Instagram自動投稿スケジューラ")
    parser.add_argument("--generate", action="store_true",
                        help="未投稿がなければ自動生成してから投稿")
    parser.add_argument("--test", action="store_true",
                        help="テスト実行（投稿しない）")
    args = parser.parse_args()

    dry_run = args.test
    success = run(generate_if_empty=args.generate, dry_run=dry_run)

    if success:
        print("\n投稿完了!")
    elif not dry_run:
        print("\n投稿に失敗しました。ログを確認してください。")
        sys.exit(1)


if __name__ == "__main__":
    main()
