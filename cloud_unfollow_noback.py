"""
フォローバックしない人の自動アンフォロー
7日以上フォローしてフォロバがない人を解除

目的:
- フォロー/フォロワー比を健全に保つ（1.5以下が理想）
- フォロー上限5000人に到達しないよう管理
- 1ラン10-15人アンフォロー（安全ペース）
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

UNFOLLOW_MIN = 8
UNFOLLOW_MAX = 12
WAIT_MIN = 3 * 60
WAIT_MAX = 8 * 60

# フォロー後何日でフォロバ判定するか
GRACE_DAYS = 7

FOLLOW_LOG_FILE = "data/follow_log.json"
UNFOLLOW_LOG_FILE = "data/unfollow_log.json"
WHITELIST_FILE = "data/unfollow_whitelist.json"


def load_json(path, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    with open(path, "r") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs("data", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    client = tweepy.Client(
        bearer_token=os.environ.get("TWITTER_BEARER_TOKEN", ""),
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
        wait_on_rate_limit=True,
    )

    # 自分のユーザーIDを取得
    me = client.get_me()
    my_id = me.data.id
    log.info(f"自分のID: {my_id}")

    # 自分がフォローしている人を取得
    following_ids = set()
    paginator = tweepy.Paginator(
        client.get_users_following,
        my_id,
        max_results=1000,
        user_fields=["id", "username"],
    )
    for response in paginator:
        if response.data:
            for user in response.data:
                following_ids.add(str(user.id))
    log.info(f"フォロー中: {len(following_ids)}人")

    # 自分のフォロワーを取得
    follower_ids = set()
    paginator = tweepy.Paginator(
        client.get_users_followers,
        my_id,
        max_results=1000,
        user_fields=["id"],
    )
    for response in paginator:
        if response.data:
            for user in response.data:
                follower_ids.add(str(user.id))
    log.info(f"フォロワー: {len(follower_ids)}人")

    # フォローバックしていない人 = following - followers
    no_followback = following_ids - follower_ids
    log.info(f"フォロバなし: {len(no_followback)}人")

    # ホワイトリスト（手動で保護したいアカウント）を除外
    whitelist = set(load_json(WHITELIST_FILE, []))
    candidates = list(no_followback - whitelist)
    random.shuffle(candidates)

    # フォローログから日付チェック（猶予期間内はスキップ）
    follow_log = load_json(FOLLOW_LOG_FILE, {})
    now = datetime.now(JST)
    cutoff = now - timedelta(days=GRACE_DAYS)

    eligible = []
    for uid in candidates:
        follow_date_str = follow_log.get(uid)
        if follow_date_str:
            try:
                follow_date = datetime.fromisoformat(follow_date_str)
                if follow_date > cutoff:
                    continue  # まだ猶予期間中
            except (ValueError, TypeError):
                pass
        eligible.append(uid)

    log.info(f"猶予期間切れ: {len(eligible)}人")

    target = min(random.randint(UNFOLLOW_MIN, UNFOLLOW_MAX), len(eligible))
    unfollowed = 0
    unfollow_log = load_json(UNFOLLOW_LOG_FILE, {})

    for uid in eligible[:target]:
        try:
            client.unfollow_user(int(uid))
            unfollowed += 1
            unfollow_log[uid] = now.isoformat()
            log.info(f"  ✅ [{unfollowed}/{target}] アンフォロー: {uid}")

            wait = random.randint(WAIT_MIN, WAIT_MAX)
            log.info(f"  ⏳ {wait // 60}分待機")
            time.sleep(wait)

        except tweepy.TooManyRequests:
            log.warning("Rate Limit。停止")
            break
        except Exception as e:
            log.error(f"  ⚠️ {uid}: {e}")

    save_json(UNFOLLOW_LOG_FILE, unfollow_log)
    log.info(f"\n完了: {unfollowed}人アンフォロー")


if __name__ == "__main__":
    main()
