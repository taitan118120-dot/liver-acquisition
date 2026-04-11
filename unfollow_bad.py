"""
誤フォローしてしまった海外bot/非ターゲットを一括アンフォローする
ワンショットスクリプト。workflow_dispatchから実行。
"""

import os
import time
import logging
import tweepy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# 2026-04-10ランで誤フォローした8アカウント(全員非日本語話者bot)
BAD_USERNAMES = [
    "harrypotterasf",
    "bradblank12",
    "ft_cv201",
    "366Bluesky",
    "jjmdem",
    "naniarumusic",
    "hinapooran",
    "discbeat",
]


def main():
    client = tweepy.Client(
        bearer_token=os.environ.get("TWITTER_BEARER_TOKEN", ""),
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
        wait_on_rate_limit=False,
    )

    for username in BAD_USERNAMES:
        try:
            # user_auth=True を明示しないと bearer token が先行して 401 になる
            user = client.get_user(username=username, user_auth=True)
            if not user.data:
                log.warning(f"取得失敗: @{username}")
                continue
            client.unfollow_user(user.data.id)
            log.info(f"  🗑 unfollow @{username} (id={user.data.id})")
            time.sleep(5)
        except tweepy.TooManyRequests:
            log.warning("Rate Limit。10分待機")
            time.sleep(10 * 60)
        except Exception as e:
            log.error(f"  ⚠️ @{username}: {e}")

    log.info("完了")


if __name__ == "__main__":
    main()
