"""
Instagram自動投稿スケジューラ

GitHub Actionsから実行される。
1. 未投稿のコンテンツがなければGeminiで自動生成（ブログ/X投稿/リミックス）
2. 次の未投稿コンテンツをInstagram Graph APIで投稿

使い方:
  python ig_scheduler.py                          # 次の1件を投稿（未投稿なければスキップ）
  python ig_scheduler.py --generate               # 自動生成 + 投稿
  python ig_scheduler.py --generate --source blog  # ブログから生成 + 投稿
  python ig_scheduler.py --generate --source twitter  # X投稿から生成 + 投稿
  python ig_scheduler.py --generate --source auto  # 自動選択（デフォルト）
  python ig_scheduler.py --test                   # テスト投稿（dry-run）
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: F401 - configを先にimportしてキャッシュに載せる

from ig_content_generator import generate_posts, load_posts
from ig_poster import post_next


MAX_RETRY = 3  # この回数失敗したら投稿をスキップ


def run(generate_if_empty=False, source_type="auto", dry_run=False):
    """スケジュール実行のメイン処理"""
    posts = load_posts()

    # 失敗回数が上限に達した投稿をスキップ対象にする
    unposted = [
        p for p in posts
        if not p["posted"] and p.get("image_path") and p.get("fail_count", 0) < MAX_RETRY
    ]
    failed = [p for p in posts if not p["posted"] and p.get("fail_count", 0) >= MAX_RETRY]

    print(f"投稿キュー: 全{len(posts)}件 / 未投稿{len(unposted)}件 / スキップ済{len(failed)}件\n")
    for fp in failed:
        print(f"  [SKIP] {fp['id']}: {fp.get('fail_count', 0)}回失敗 - {fp.get('last_error', '不明')}")

    # 未投稿がなければ生成（スキップ済みは数えない）
    if not unposted and generate_if_empty:
        print("未投稿コンテンツがないため、新規生成します...\n")
        generate_posts(source_type=source_type, count=1, dry_run=dry_run)
        # 再読み込み
        posts = load_posts()
        unposted = [
            p for p in posts
            if not p["posted"] and p.get("image_path") and p.get("fail_count", 0) < MAX_RETRY
        ]

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
    parser.add_argument("--source", choices=["blog", "twitter", "auto"], default="auto",
                        help="コンテンツソース（default: auto）")
    parser.add_argument("--test", action="store_true",
                        help="テスト実行（投稿しない）")
    args = parser.parse_args()

    dry_run = args.test
    success = run(
        generate_if_empty=args.generate,
        source_type=args.source,
        dry_run=dry_run,
    )

    if success:
        print("\n投稿完了!")
    elif not dry_run:
        print("\n投稿に失敗しました。ログを確認してください。")
        sys.exit(1)


if __name__ == "__main__":
    main()
