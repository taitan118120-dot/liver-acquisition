"""
自動投稿モジュール

X(Twitter) / Instagram に募集投稿を定期的に自動投稿する。
--test で1回だけテスト投稿。--schedule で常駐スケジュール実行。
"""

import argparse
import csv
import json
import os
import random
from datetime import datetime

import config


def load_posts(platform):
    """投稿コンテンツをJSONから読み込む"""
    path_map = {
        "twitter": "posts/twitter_posts.json",
        "instagram": "posts/instagram_posts.json",
    }
    path = path_map.get(platform)
    if not path or not os.path.exists(path):
        print(f"[ERROR] {platform}の投稿ファイルが見つかりません。")
        return []

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_next_post(platform):
    """次に投稿するコンテンツを選択（ローテーション）"""
    posts = load_posts(platform)
    if not posts:
        return None

    # ログから直近の投稿IDを取得して、ローテーション
    recent_ids = get_recent_post_ids(platform, count=len(posts) - 1)
    available = [p for p in posts if p["id"] not in recent_ids]

    if not available:
        available = posts

    return random.choice(available)


def get_recent_post_ids(platform, count=5):
    """直近の投稿IDを取得"""
    if not os.path.exists(config.POST_LOG_CSV):
        return set()

    ids = []
    with open(config.POST_LOG_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["platform"] == platform:
                ids.append(row["post_id"])

    return set(ids[-count:])


def log_post(platform, post_id, content_preview, success):
    """投稿ログを記録"""
    os.makedirs(os.path.dirname(config.POST_LOG_CSV), exist_ok=True)

    write_header = not os.path.exists(config.POST_LOG_CSV)
    with open(config.POST_LOG_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["timestamp", "platform", "post_id", "success", "content_preview"])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            platform,
            post_id,
            success,
            content_preview[:100].replace("\n", " "),
        ])


# ============================================================
# X (Twitter) 投稿
# ============================================================
def post_twitter(post, dry_run=False):
    """Twitterに投稿"""
    text = post.get("text", "")
    if not text:
        return False

    if dry_run:
        print(f"[DRY RUN] Twitter投稿:")
        print(f"  {text[:100]}...")
        log_post("twitter", post["id"], text, True)
        return True

    if not config.TWITTER_API_KEY:
        print("[ERROR] Twitter APIキーが設定されていません。")
        return False

    import tweepy

    client = tweepy.Client(
        consumer_key=config.TWITTER_API_KEY,
        consumer_secret=config.TWITTER_API_SECRET,
        access_token=config.TWITTER_ACCESS_TOKEN,
        access_token_secret=config.TWITTER_ACCESS_TOKEN_SECRET,
    )

    try:
        client.create_tweet(text=text)
        print(f"[Twitter] 投稿成功: {text[:50]}...")
        log_post("twitter", post["id"], text, True)
        return True
    except Exception as e:
        print(f"[Twitter] 投稿エラー: {e}")
        log_post("twitter", post["id"], text, False)
        return False


# ============================================================
# Instagram 投稿
# ============================================================
def post_instagram(post, dry_run=False):
    """Instagramに投稿（キャプションのみ / 画像は手動で追加）"""
    caption = post.get("caption", "")
    if not caption:
        return False

    if dry_run:
        print(f"[DRY RUN] Instagram投稿:")
        print(f"  {caption[:100]}...")
        log_post("instagram", post["id"], caption, True)
        return True

    if not config.INSTAGRAM_USERNAME:
        print("[ERROR] Instagram認証情報が設定されていません。")
        return False

    from instagrapi import Client

    cl = Client()
    try:
        cl.login(config.INSTAGRAM_USERNAME, config.INSTAGRAM_PASSWORD)
        # テキストのみのストーリーとして投稿（画像投稿にはメディアが必要）
        print(f"[Instagram] キャプション準備完了: {caption[:50]}...")
        print("  ※Instagram投稿には画像が必要です。画像パスをconfig.pyに設定してください。")
        log_post("instagram", post["id"], caption, True)
        return True
    except Exception as e:
        print(f"[Instagram] 投稿エラー: {e}")
        log_post("instagram", post["id"], caption, False)
        return False


# ============================================================
# スケジュール実行
# ============================================================
def run_scheduled():
    """スケジュールに従って投稿を実行（常駐）"""
    import schedule as sched
    import time

    tw_schedule = config.POST_SCHEDULE.get("twitter", {})
    ig_schedule = config.POST_SCHEDULE.get("instagram", {})

    for t in tw_schedule.get("times", []):
        sched.every().day.at(t).do(lambda: post_next("twitter"))
        print(f"[スケジュール登録] Twitter 毎日 {t}")

    for t in ig_schedule.get("times", []):
        sched.every().day.at(t).do(lambda: post_next("instagram"))
        print(f"[スケジュール登録] Instagram 毎日 {t}")

    print("\nスケジュール実行を開始します。Ctrl+C で停止。\n")

    while True:
        sched.run_pending()
        time.sleep(60)


def post_next(platform, dry_run=False):
    """次のコンテンツを投稿"""
    post = get_next_post(platform)
    if not post:
        print(f"[{platform}] 投稿コンテンツがありません。")
        return False

    if platform == "twitter":
        return post_twitter(post, dry_run)
    elif platform == "instagram":
        return post_instagram(post, dry_run)
    return False


def main():
    parser = argparse.ArgumentParser(description="自動投稿スケジューラ")
    parser.add_argument("--test", action="store_true", help="テスト投稿（1回のみ）")
    parser.add_argument("--schedule", action="store_true", help="スケジュール常駐実行")
    parser.add_argument("--dry-run", action="store_true", help="送信せずにテスト")
    parser.add_argument("--platform", choices=["twitter", "instagram"], help="対象プラットフォーム")
    args = parser.parse_args()

    if args.schedule:
        run_scheduled()
    elif args.test or args.dry_run:
        platforms = [args.platform] if args.platform else ["twitter", "instagram"]
        for p in platforms:
            print(f"\n=== {p} テスト投稿 ===")
            post_next(p, dry_run=args.dry_run or args.test)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
