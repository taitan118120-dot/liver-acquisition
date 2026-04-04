"""
エンゲージメント自動化モジュール

フォロワー獲得のために、ターゲット層のツイートに「いいね」や
リプライを自動で行う。フォロワー0の状態からアカウントを育てるための機能。

使い方:
  python3 engager.py --like              いいね自動化
  python3 engager.py --reply             リプライ自動化
  python3 engager.py --follow            関連アカウントフォロー
  python3 engager.py --all               全部実行
  python3 engager.py --dry-run --all     ドライラン
  python3 engager.py --manual            手動用リスト出力（API不要）
"""

import argparse
import csv
import os
import random
import time
from datetime import datetime

import config


# ============================================================
# エンゲージメント設定
# ============================================================
ENGAGE_KEYWORDS = [
    "ライブ配信 始めたい",
    "ライバー なりたい",
    "配信者 なりたい",
    "ライブ配信 興味",
    "副業 在宅",
    "Pococha 始めたい",
    "17LIVE やってみたい",
    "配信 楽しそう",
    "ライバー 事務所",
    "在宅ワーク 探してる",
]

# リプライテンプレート（自然な感じで）
REPLY_TEMPLATES = {
    "interest": [
        "ライブ配信いいですよね！自分のペースで始められるのが魅力です",
        "配信に興味あるんですね！最初は誰でも不安ですが、意外とすぐ慣れますよ",
        "いいですね！最近は副業で始める人もすごく増えてます",
    ],
    "question": [
        "何か気になることがあればお気軽に聞いてください！配信のことなら詳しいので",
        "詳しい話、よかったらDMでお話しできますよ！",
    ],
    "encouragement": [
        "応援してます！配信頑張ってください",
        "素敵な配信ですね！これからも楽しみにしてます",
    ],
}

# レート制限
ENGAGE_RATE_LIMIT = {
    "likes_per_hour": 15,
    "replies_per_hour": 5,
    "follows_per_hour": 10,
    "interval_sec": 30,  # アクション間の最小間隔
}

ENGAGE_LOG_CSV = "data/engage_log.csv"


def log_engagement(action, target_username, target_url, detail=""):
    """エンゲージメントログを記録"""
    os.makedirs(os.path.dirname(ENGAGE_LOG_CSV), exist_ok=True)

    write_header = not os.path.exists(ENGAGE_LOG_CSV)
    with open(ENGAGE_LOG_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["timestamp", "action", "username", "url", "detail"])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            action, target_username, target_url, detail,
        ])


# ============================================================
# 手動モード（API不要）
# ============================================================
def manual_mode():
    """手動エンゲージメント用のリストを出力"""
    print(f"\n{'='*60}")
    print("  手動エンゲージメント用リスト")
    print(f"{'='*60}")

    print("\n■ X検索用キーワード（これで検索していいね・リプライ）:")
    print("  以下をXの検索窓にコピペして検索してください\n")
    for i, kw in enumerate(ENGAGE_KEYWORDS, 1):
        print(f"  {i}. {kw}")

    print(f"\n■ 検索URL（クリックですぐ検索）:")
    for kw in ENGAGE_KEYWORDS[:5]:
        url = f"https://x.com/search?q={kw.replace(' ', '%20')}&f=live"
        print(f"  {kw}: {url}")

    print(f"\n■ リプライ例文（コピペ用）:")
    for category, templates in REPLY_TEMPLATES.items():
        label = {"interest": "興味ありそうな人へ", "question": "質問してる人へ",
                 "encouragement": "配信中の人へ"}.get(category, category)
        print(f"\n  【{label}】")
        for t in templates:
            print(f"  ・{t}")

    print(f"\n■ 1日の目安アクション数:")
    print(f"  いいね: 30〜50回")
    print(f"  リプライ: 10〜15回")
    print(f"  フォロー: 20〜30回")
    print(f"\n  ※一気にやらず、朝・昼・夜に分けてやるとアカウント凍結リスクが下がります")


# ============================================================
# 自動いいね（API使用）
# ============================================================
def auto_like(dry_run=False, limit=None):
    """ターゲット層のツイートに自動いいね"""
    if not config.TWITTER_BEARER_TOKEN and not dry_run:
        print("[ERROR] Twitter APIキーが設定されていません。")
        print("  → 手動モード（--manual）を使ってください。")
        return

    max_likes = limit or ENGAGE_RATE_LIMIT["likes_per_hour"]
    liked = 0

    if dry_run:
        print(f"[DRY RUN] 自動いいねシミュレート (上限: {max_likes}件)")
        for kw in ENGAGE_KEYWORDS[:3]:
            print(f"  検索: '{kw}' → 5件にいいね")
            liked += 5
        print(f"  合計: {liked}件にいいね（ドライラン）")
        return

    import tweepy

    client = tweepy.Client(
        bearer_token=config.TWITTER_BEARER_TOKEN,
        consumer_key=config.TWITTER_API_KEY,
        consumer_secret=config.TWITTER_API_SECRET,
        access_token=config.TWITTER_ACCESS_TOKEN,
        access_token_secret=config.TWITTER_ACCESS_TOKEN_SECRET,
    )

    for keyword in ENGAGE_KEYWORDS:
        if liked >= max_likes:
            break

        try:
            tweets = client.search_recent_tweets(
                query=f"{keyword} -is:retweet lang:ja",
                max_results=10,
            )
            if not tweets.data:
                continue

            for tweet in tweets.data:
                if liked >= max_likes:
                    break
                try:
                    client.like(tweet.id)
                    liked += 1
                    print(f"  [いいね {liked}] {tweet.text[:50]}...")
                    log_engagement("like", "", "", tweet.text[:100])
                    time.sleep(ENGAGE_RATE_LIMIT["interval_sec"])
                except Exception as e:
                    print(f"  [エラー] いいね失敗: {e}")

        except Exception as e:
            print(f"  [エラー] 検索失敗 '{keyword}': {e}")

    print(f"\n合計: {liked}件にいいね")


# ============================================================
# 自動リプライ（API使用）
# ============================================================
def auto_reply(dry_run=False, limit=None):
    """ターゲット層のツイートに自動リプライ"""
    if not config.TWITTER_BEARER_TOKEN and not dry_run:
        print("[ERROR] Twitter APIキーが設定されていません。")
        return

    max_replies = limit or ENGAGE_RATE_LIMIT["replies_per_hour"]
    replied = 0

    if dry_run:
        print(f"[DRY RUN] 自動リプライシミュレート (上限: {max_replies}件)")
        for kw in ENGAGE_KEYWORDS[:2]:
            reply = random.choice(REPLY_TEMPLATES["interest"])
            print(f"  検索: '{kw}' → リプライ: {reply[:40]}...")
            replied += 1
        print(f"  合計: {replied}件にリプライ（ドライラン）")
        return

    import tweepy

    client = tweepy.Client(
        consumer_key=config.TWITTER_API_KEY,
        consumer_secret=config.TWITTER_API_SECRET,
        access_token=config.TWITTER_ACCESS_TOKEN,
        access_token_secret=config.TWITTER_ACCESS_TOKEN_SECRET,
    )

    interest_keywords = ["ライブ配信 始めたい", "ライバー なりたい", "配信 興味"]

    for keyword in interest_keywords:
        if replied >= max_replies:
            break

        try:
            tweets = client.search_recent_tweets(
                query=f"{keyword} -is:retweet lang:ja",
                max_results=10,
            )
            if not tweets.data:
                continue

            for tweet in tweets.data:
                if replied >= max_replies:
                    break
                reply_text = random.choice(REPLY_TEMPLATES["interest"])
                try:
                    client.create_tweet(text=reply_text, in_reply_to_tweet_id=tweet.id)
                    replied += 1
                    print(f"  [リプライ {replied}] → {reply_text[:40]}...")
                    log_engagement("reply", "", "", reply_text)
                    time.sleep(ENGAGE_RATE_LIMIT["interval_sec"] * 3)
                except Exception as e:
                    print(f"  [エラー] リプライ失敗: {e}")

        except Exception as e:
            print(f"  [エラー] 検索失敗 '{keyword}': {e}")

    print(f"\n合計: {replied}件にリプライ")


# ============================================================
# 自動フォロー（API使用）
# ============================================================
def auto_follow(dry_run=False, limit=None):
    """ターゲット層のアカウントを自動フォロー"""
    if not config.TWITTER_BEARER_TOKEN and not dry_run:
        print("[ERROR] Twitter APIキーが設定されていません。")
        return

    max_follows = limit or ENGAGE_RATE_LIMIT["follows_per_hour"]

    if dry_run:
        print(f"[DRY RUN] 自動フォローシミュレート (上限: {max_follows}件)")
        print(f"  関連キーワード投稿者 {max_follows}件をフォロー（ドライラン）")
        return

    import tweepy

    client = tweepy.Client(
        consumer_key=config.TWITTER_API_KEY,
        consumer_secret=config.TWITTER_API_SECRET,
        access_token=config.TWITTER_ACCESS_TOKEN,
        access_token_secret=config.TWITTER_ACCESS_TOKEN_SECRET,
    )

    followed = 0
    for keyword in ENGAGE_KEYWORDS:
        if followed >= max_follows:
            break

        try:
            tweets = client.search_recent_tweets(
                query=f"{keyword} -is:retweet lang:ja",
                max_results=10,
                expansions=["author_id"],
            )
            if not tweets.data:
                continue

            users = {u.id: u for u in (tweets.includes.get("users", []))}

            for tweet in tweets.data:
                if followed >= max_follows:
                    break
                user = users.get(tweet.author_id)
                if not user:
                    continue
                try:
                    client.follow_user(user.id)
                    followed += 1
                    print(f"  [フォロー {followed}] @{user.username}")
                    log_engagement("follow", user.username, f"https://x.com/{user.username}", "")
                    time.sleep(ENGAGE_RATE_LIMIT["interval_sec"])
                except Exception as e:
                    print(f"  [エラー] フォロー失敗: {e}")

        except Exception as e:
            print(f"  [エラー] 検索失敗: {e}")

    print(f"\n合計: {followed}件フォロー")


def main():
    parser = argparse.ArgumentParser(description="エンゲージメント自動化")
    parser.add_argument("--like", action="store_true", help="自動いいね")
    parser.add_argument("--reply", action="store_true", help="自動リプライ")
    parser.add_argument("--follow", action="store_true", help="自動フォロー")
    parser.add_argument("--all", action="store_true", help="全部実行")
    parser.add_argument("--manual", action="store_true", help="手動用リスト出力（API不要）")
    parser.add_argument("--dry-run", action="store_true", help="ドライラン")
    parser.add_argument("--limit", type=int, help="アクション上限数")
    args = parser.parse_args()

    if args.manual:
        manual_mode()
        return

    if args.all or args.like:
        print("\n=== 自動いいね ===")
        auto_like(dry_run=args.dry_run, limit=args.limit)

    if args.all or args.reply:
        print("\n=== 自動リプライ ===")
        auto_reply(dry_run=args.dry_run, limit=args.limit)

    if args.all or args.follow:
        print("\n=== 自動フォロー ===")
        auto_follow(dry_run=args.dry_run, limit=args.limit)

    if not any([args.all, args.like, args.reply, args.follow, args.manual]):
        parser.print_help()


if __name__ == "__main__":
    main()
