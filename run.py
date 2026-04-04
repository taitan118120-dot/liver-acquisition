"""
ライバー・代理店パートナー自動集客システム - メインエントリポイント

使い方:
  python run.py find          リード検索
  python run.py dm            DM送信
  python run.py dm --copy     コピペ用DM出力（API不要）
  python run.py post          テスト投稿
  python run.py post --auto   自動投稿スケジュール開始
  python run.py engage        エンゲージメント（いいね/リプライ/フォロー）
  python run.py engage --manual  手動用リスト出力（API不要）
  python run.py stats         統計表示
  python run.py followup      フォローアップ対象
  python run.py dashboard     ダッシュボードデータ更新
  python run.py all           全工程をドライラン実行
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        description="ライバー・代理店パートナー自動集客システム",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
コマンド一覧:
  find        X/Instagramでライバー候補を検索
  dm          DM送信（--copy でコピペモード）
  post        投稿（--auto で自動スケジュール）
  stats       リード統計表示
  followup    フォローアップ対象表示
  list        リード一覧表示
  dashboard   ダッシュボードデータ更新
  all         全工程をドライラン実行

例:
  python run.py find --dry-run          検索テスト
  python run.py dm --copy               コピペ用DM出力
  python run.py dm --dry-run            DM送信テスト
  python run.py post --dry-run          投稿テスト
  python run.py post --auto             自動投稿開始
  python run.py stats                   統計表示
        """,
    )

    sub = parser.add_subparsers(dest="command")

    # find
    find_parser = sub.add_parser("find", help="リード検索")
    find_parser.add_argument("--dry-run", action="store_true")
    find_parser.add_argument("--twitter-only", action="store_true")
    find_parser.add_argument("--instagram-only", action="store_true")

    # dm
    dm_parser = sub.add_parser("dm", help="DM送信")
    dm_parser.add_argument("--dry-run", action="store_true")
    dm_parser.add_argument("--copy", action="store_true", help="コピペモード（API不要）")
    dm_parser.add_argument("--platform", choices=["twitter", "instagram"])
    dm_parser.add_argument("--limit", type=int)

    # post
    post_parser = sub.add_parser("post", help="投稿")
    post_parser.add_argument("--dry-run", action="store_true")
    post_parser.add_argument("--auto", action="store_true", help="自動スケジュール実行")
    post_parser.add_argument("--platform", choices=["twitter", "instagram"])

    # engage
    engage_parser = sub.add_parser("engage", help="エンゲージメント自動化")
    engage_parser.add_argument("--like", action="store_true", help="自動いいね")
    engage_parser.add_argument("--reply", action="store_true", help="自動リプライ")
    engage_parser.add_argument("--follow", action="store_true", help="自動フォロー")
    engage_parser.add_argument("--all", action="store_true", help="全部実行")
    engage_parser.add_argument("--manual", action="store_true", help="手動用リスト（API不要）")
    engage_parser.add_argument("--dry-run", action="store_true")
    engage_parser.add_argument("--limit", type=int)

    # stats
    sub.add_parser("stats", help="統計表示")

    # followup
    sub.add_parser("followup", help="フォローアップ対象")

    # list
    list_parser = sub.add_parser("list", help="リード一覧")
    list_parser.add_argument("--status")
    list_parser.add_argument("--platform", choices=["twitter", "instagram"])

    # dashboard
    sub.add_parser("dashboard", help="ダッシュボードデータ更新")

    # all
    sub.add_parser("all", help="全工程ドライラン")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "find":
        from lead_finder import main as finder_main
        sys.argv = ["lead_finder.py"]
        if args.dry_run:
            sys.argv.append("--dry-run")
        if args.twitter_only:
            sys.argv.append("--twitter-only")
        if args.instagram_only:
            sys.argv.append("--instagram-only")
        finder_main()

    elif args.command == "dm":
        from dm_sender import main as dm_main
        sys.argv = ["dm_sender.py"]
        if args.dry_run:
            sys.argv.append("--dry-run")
        if args.copy:
            sys.argv.append("--copy-mode")
        if args.platform:
            sys.argv.extend(["--platform", args.platform])
        if args.limit:
            sys.argv.extend(["--limit", str(args.limit)])
        dm_main()

    elif args.command == "post":
        from post_scheduler import main as post_main
        sys.argv = ["post_scheduler.py"]
        if args.auto:
            sys.argv.append("--schedule")
        elif args.dry_run:
            sys.argv.append("--dry-run")
        else:
            sys.argv.append("--test")
        if args.platform:
            sys.argv.extend(["--platform", args.platform])
        post_main()

    elif args.command == "engage":
        from engager import main as engage_main
        sys.argv = ["engager.py"]
        if args.manual:
            sys.argv.append("--manual")
        elif args.all:
            sys.argv.append("--all")
        else:
            if args.like:
                sys.argv.append("--like")
            if args.reply:
                sys.argv.append("--reply")
            if args.follow:
                sys.argv.append("--follow")
        if getattr(args, "dry_run", False):
            sys.argv.append("--dry-run")
        if getattr(args, "limit", None):
            sys.argv.extend(["--limit", str(args.limit)])
        if not any([args.manual, args.all, args.like, args.reply, args.follow]):
            sys.argv.append("--manual")  # デフォルトは手動モード
        engage_main()

    elif args.command == "stats":
        from tracker import show_stats
        show_stats()

    elif args.command == "followup":
        from tracker import show_followup
        show_followup()

    elif args.command == "list":
        from tracker import list_leads
        list_leads(status=getattr(args, "status", None),
                   platform=getattr(args, "platform", None))

    elif args.command == "dashboard":
        from tracker import export_json
        export_json()

    elif args.command == "all":
        print("=" * 60)
        print("  全工程ドライラン実行")
        print("=" * 60)

        print("\n[1/4] リード検索...")
        from lead_finder import main as finder_main
        sys.argv = ["lead_finder.py", "--dry-run"]
        finder_main()

        print("\n[2/4] DM生成...")
        from dm_sender import copy_mode
        copy_mode(limit=2)

        print("\n[3/4] 投稿テスト...")
        from post_scheduler import post_next
        post_next("twitter", dry_run=True)

        print("\n[4/4] 統計表示...")
        from tracker import show_stats, export_json
        show_stats()
        export_json()

        print("\n全工程のドライラン完了！")


if __name__ == "__main__":
    main()
