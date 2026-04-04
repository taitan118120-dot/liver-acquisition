"""
クラウド用 自動投稿スクリプト
GitHub Actions から実行される。Mac不要。
"""

import json
import os
import random
import tweepy


def main():
    # 環境変数からAPIキーを取得（GitHub Secretsから注入）
    client = tweepy.Client(
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )

    # 投稿コンテンツを読み込み
    with open("posts/twitter_posts.json", "r", encoding="utf-8") as f:
        posts = json.load(f)

    # growthフェーズのみ（募集・宣伝は封印）
    growth_posts = [p for p in posts if p.get("phase") == "growth"]

    # 直近の投稿IDを確認（重複防止）
    recent_file = "data/recent_post_ids.txt"
    recent_ids = set()
    if os.path.exists(recent_file):
        with open(recent_file, "r") as f:
            recent_ids = set(f.read().strip().split("\n"))

    # まだ投稿してないものを選ぶ
    available = [p for p in growth_posts if p["id"] not in recent_ids]
    if not available:
        # 全部投稿済み → リセットしてローテーション
        recent_ids = set()
        available = growth_posts

    post = random.choice(available)

    # 投稿
    response = client.create_tweet(text=post["text"])
    print(f"投稿成功: {post['id']} → {response.data['id']}")

    # 投稿済みIDを記録
    recent_ids.add(post["id"])
    os.makedirs("data", exist_ok=True)
    with open(recent_file, "w") as f:
        f.write("\n".join(recent_ids))


if __name__ == "__main__":
    main()
