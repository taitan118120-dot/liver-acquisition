"""
クラウド用 自動エンゲージメントスクリプト
2026年2月API仕様変更対応版

できること:
- 自動投稿（別スクリプト）
- いいね（控えめに）
- リード検索・保存

できないこと（API制限）:
- 自動リプライ → 相手から@されてないと弾かれる
- 大量フォロー → 凍結リスク
"""

import os
import random
import time
import json
from datetime import date
import tweepy


# ============================================================
# 設定
# ============================================================

# 検索キーワード（リード発見用）
SEARCH_KEYWORDS = [
    "初配信 緊張",
    "配信 楽しかった",
    "Pococha 始めた",
    "Pococha デビュー",
    "#初配信",
    "#配信初心者",
    "#ぽこちゃ始めました",
    "石川県 配信",
    "金沢 ライブ",
]

NG_WORDS = [
    "所属", "専属", "カーブアウト", "carveout",
    "起業家", "事業家", "ceo", "代表取締役", "経営者", "社長",
    "副業", "稼ぐ", "稼げる", "月収", "不労所得", "自動収益",
    "コンサル", "投資", "fx", "仮想通貨", "バイナリー", "mlm",
    "ネットワークビジネス", "情報商材",
    "公式", "株式会社", "合同会社", "official",
]

# いいね設定（控えめに）
LIKE_PER_EXEC = 5  # 1回あたり5件
LIKE_LIMIT_PER_DAY = 15  # 1日上限15件

LOG_FILE = "data/daily_counts.json"


def load_daily_counts():
    if not os.path.exists(LOG_FILE):
        return {"date": "", "likes": 0}
    with open(LOG_FILE, "r") as f:
        data = json.load(f)
    if data.get("date") != str(date.today()):
        return {"date": str(date.today()), "likes": 0}
    return data


def save_daily_counts(counts):
    os.makedirs("data", exist_ok=True)
    counts["date"] = str(date.today())
    with open(LOG_FILE, "w") as f:
        json.dump(counts, f)


def is_ng(bio):
    if not bio:
        return False
    return any(w in bio.lower() for w in NG_WORDS)


def main():
    client = tweepy.Client(
        bearer_token=os.environ["TWITTER_BEARER_TOKEN"],
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )

    counts = load_daily_counts()
    remaining_likes = LIKE_LIMIT_PER_DAY - counts.get("likes", 0)

    if remaining_likes <= 0:
        print("今日の上限に達済み")
        return

    keyword = random.choice(SEARCH_KEYWORDS)
    print(f"検索: {keyword}")

    tweets = client.search_recent_tweets(
        query=f"{keyword} -is:retweet lang:ja",
        max_results=20,
        tweet_fields=["author_id", "text"],
        user_fields=["username", "name", "description", "public_metrics"],
        expansions=["author_id"],
    )

    if not tweets.data:
        print("検索結果なし")
        return

    users = {u.id: u for u in tweets.includes.get("users", [])}
    liked = 0

    for tweet in tweets.data:
        if liked >= min(LIKE_PER_EXEC, remaining_likes):
            break

        user = users.get(tweet.author_id)
        if not user:
            continue
        if is_ng(user.description):
            continue

        try:
            client.like(tweet.id)
            liked += 1
            counts["likes"] = counts.get("likes", 0) + 1
            print(f"  ❤️ いいね @{user.username}: {tweet.text[:40]}...")
            time.sleep(5)
        except Exception as e:
            print(f"  ⚠️ @{user.username}: {e}")

    # リード候補をCSVに保存（将来のDM用）
    leads_file = "data/leads.csv"
    os.makedirs("data", exist_ok=True)
    write_header = not os.path.exists(leads_file)
    with open(leads_file, "a", encoding="utf-8") as f:
        if write_header:
            f.write("username,name,bio,found_date,keyword\n")
        for tweet in tweets.data:
            user = users.get(tweet.author_id)
            if not user or is_ng(user.description):
                continue
            bio = (user.description or "").replace(",", " ").replace("\n", " ")[:100]
            f.write(f"{user.username},{user.name},{bio},{date.today()},{keyword}\n")

    save_daily_counts(counts)
    print(f"\n完了 → いいね: {liked}件 / 本日累計: {counts.get('likes', 0)}件")


if __name__ == "__main__":
    main()
