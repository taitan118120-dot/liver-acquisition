"""
自動フォロースクリプト（安全版）
リスト追加と同じ安全基準で1日20人フォロー

- アクション数はランダム変動
- 深夜帯(JST 02:00-07:00)は停止
- 30〜60分間隔で1人ずつ
- 業者・bot排除フィルター
"""

import os
import json
import random
import time
import logging
from datetime import datetime, timezone, timedelta

import tweepy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# 1日のフォロー数
DAILY_MIN = 18
DAILY_MAX = 22

# 待機時間（秒）
WAIT_MIN = 30 * 60
WAIT_MAX = 60 * 60

QUIET_HOUR_START = 2
QUIET_HOUR_END = 7

SEARCH_KEYWORDS = [
    "配信初心者",
    "Pococha 始めた",
    "#初配信",
    "#配信初心者",
    "#ぽこちゃ",
    "石川県",
    "金沢",
    "配信 始めた",
    "配信 楽しかった",
    "ライバー 頑張る",
]

NG_WORDS = [
    "所属", "専属", "カーブアウト", "carveout",
    "起業家", "事業家", "ceo", "代表取締役", "経営者", "社長",
    "副業", "稼ぐ", "稼げる", "月収", "不労所得", "自動収益",
    "コンサル", "投資", "fx", "仮想通貨", "バイナリー", "mlm",
    "ネットワークビジネス", "情報商材",
    "公式", "株式会社", "合同会社", "official",
    "相互フォロー", "相互100",
]

PROCESSED_FILE = "data/follow_processed.json"


def load_processed():
    if not os.path.exists(PROCESSED_FILE):
        return set()
    with open(PROCESSED_FILE, "r") as f:
        return set(json.load(f))


def save_processed(processed):
    os.makedirs("data", exist_ok=True)
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(processed), f)


def is_quiet_hours():
    return QUIET_HOUR_START <= datetime.now(JST).hour < QUIET_HOUR_END


def is_good_target(user):
    """フォローすべき人間らしいアカウントか判定"""
    bio = (user.description or "").lower()
    if any(w in bio for w in NG_WORDS):
        return False

    metrics = getattr(user, "public_metrics", None)
    if metrics:
        followers = metrics.get("followers_count", 0)
        following = metrics.get("following_count", 0)
        tweets = metrics.get("tweet_count", 0)

        if followers == 0 and tweets < 3:
            return False
        if following > 0 and followers > 0 and following / followers > 8:
            return False
        if followers > 10000:
            return False
        # フォロバしてくれそうな人（フォロー数とフォロワー数が近い）
        if followers > 0 and following > 0:
            ratio = following / followers
            if 0.5 < ratio < 3.0:
                return True  # フォロバ率高そう

    return True


def main():
    if is_quiet_hours():
        log.info(f"深夜帯のため停止 (JST {datetime.now(JST).strftime('%H:%M')})")
        return

    client = tweepy.Client(
        bearer_token=os.environ.get("TWITTER_BEARER_TOKEN", ""),
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
        wait_on_rate_limit=False,
    )

    daily_target = random.randint(DAILY_MIN, DAILY_MAX)
    processed = load_processed()
    followed = 0

    log.info(f"目標: {daily_target}人フォロー")

    keywords = random.sample(SEARCH_KEYWORDS, len(SEARCH_KEYWORDS))

    for keyword in keywords:
        if followed >= daily_target:
            break
        if is_quiet_hours():
            log.info("深夜帯のため停止")
            break

        log.info(f"検索: {keyword}")

        try:
            tweets = client.search_recent_tweets(
                query=f"{keyword} -is:retweet lang:ja",
                max_results=20,
                tweet_fields=["author_id"],
                user_fields=["username", "name", "description", "public_metrics"],
                expansions=["author_id"],
            )
        except tweepy.TooManyRequests:
            log.warning("Rate Limit。15分待機")
            time.sleep(15 * 60)
            continue
        except Exception as e:
            log.error(f"検索エラー: {e}")
            continue

        if not tweets.data:
            continue

        users = {u.id: u for u in tweets.includes.get("users", [])}

        for tweet in tweets.data:
            if followed >= daily_target:
                break

            user = users.get(tweet.author_id)
            if not user or str(user.id) in processed:
                continue

            if not is_good_target(user):
                processed.add(str(user.id))
                continue

            try:
                client.follow_user(user.id)
                followed += 1
                processed.add(str(user.id))
                log.info(f"  ✅ [{followed}/{daily_target}] @{user.username}")

                wait = random.randint(WAIT_MIN, WAIT_MAX) + random.randint(-120, 120)
                wait = max(wait, 60)
                log.info(f"  ⏳ {wait // 60}分待機")
                time.sleep(wait)

            except tweepy.TooManyRequests:
                log.warning("Rate Limit。15分待機")
                time.sleep(15 * 60)
            except tweepy.Forbidden:
                log.warning(f"  ⚠️ Forbidden @{user.username}")
                processed.add(str(user.id))
            except Exception as e:
                log.error(f"  ⚠️ @{user.username}: {e}")

    save_processed(processed)
    log.info(f"\n完了: {followed}人フォロー")


if __name__ == "__main__":
    main()
