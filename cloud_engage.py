"""
クラウド用 自動エンゲージメント（フォロー+いいね）スクリプト
GitHub Actions から実行される。Mac不要。
"""

import os
import random
import time
import tweepy


SEARCH_KEYWORDS = [
    # ライバー候補を探す
    "自撮り 盛れた", "フォロワー増やしたい",
    "副業 始めたい", "TikTok 撮った",
    "インフルエンサー なりたい", "SNS 頑張る",
    # ライバー業界
    "推しライバー", "ライブ配信 見てる",
    "Pococha 楽しい", "配信 面白かった",
    # ハッシュタグ
    "#自撮り", "#フォロバ100", "#フォロバ",
    "#副業探してます", "#副業初心者",
    "#お洒落さんと繋がりたい", "#カフェ好きさんと繋がりたい",
    "#低身長コーデ", "#古着女子", "#淡色女子",
    "#TikToker", "#インスタグラマー",
]

NG_WORDS = [
    "所属", "専属", "カーブアウト", "carveout",
    "起業家", "事業家", "ceo", "代表取締役", "経営者", "社長",
    "公式", "株式会社", "合同会社", "official",
    "コンサル", "投資", "fx", "仮想通貨", "バイナリー", "mlm",
    "ネットワークビジネス",
]


def is_ng(bio):
    """NGターゲットかチェック"""
    if not bio:
        return False
    bio_lower = bio.lower()
    return any(w in bio_lower for w in NG_WORDS)


def main():
    # ベアラートークンのURLエンコードを修正
    bearer = os.environ.get("TWITTER_BEARER_TOKEN", "")
    import urllib.parse
    bearer = urllib.parse.unquote(bearer)

    client = tweepy.Client(
        bearer_token=bearer,
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )

    keyword = random.choice(SEARCH_KEYWORDS)
    print(f"検索: {keyword}")

    tweets = client.search_recent_tweets(
        query=f"{keyword} -is:retweet lang:ja",
        max_results=10,
        tweet_fields=["author_id"],
        user_fields=["username", "name", "description"],
        expansions=["author_id"],
    )

    if not tweets.data:
        print("検索結果なし")
        return

    users = {u.id: u for u in tweets.includes.get("users", [])}
    acted = 0

    for tweet in tweets.data:
        if acted >= 6:
            break

        user = users.get(tweet.author_id)
        if not user:
            continue

        if is_ng(user.description):
            print(f"  [NG] @{user.username}")
            continue

        try:
            client.follow_user(user.id)
            client.like(tweet.id)
            acted += 1
            print(f"  [OK] フォロー+いいね: @{user.username}")
            time.sleep(5)
        except Exception as e:
            print(f"  [エラー] @{user.username}: {e}")

    print(f"\n合計: {acted}件 フォロー+いいね")


if __name__ == "__main__":
    main()
