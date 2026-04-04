"""
公開リスト自動追加スクリプト

仕組み:
  検索でターゲットを見つける → 公開リストに追加
  → 相手に「リストに追加されました」通知が届く
  → プロフィールを見に来る → フォロー/DM

2026年X API仕様準拠:
  - 自動いいね/自動リプライは一切なし
  - アクション数はランダム変動（Jitter）
  - 深夜帯(JST 02:00-07:00)は完全停止
"""

import os
import sys
import json
import random
import time
import logging
from datetime import datetime, timezone, timedelta

import tweepy

# ============================================================
# ログ設定
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ============================================================
# 定数
# ============================================================
JST = timezone(timedelta(hours=9))

# 公開リストID（環境変数 or ここに直書き）
LIST_ID = os.environ.get("X_LIST_ID", "")

# 1日の追加件数（ランダム）
DAILY_MIN = 20
DAILY_MAX = 30

# 1件ごとの待機時間（秒）
WAIT_MIN = 30 * 60   # 30分
WAIT_MAX = 60 * 60   # 60分

# 深夜帯（JST）: この時間帯は停止
QUIET_HOUR_START = 2   # 02:00
QUIET_HOUR_END = 7     # 07:00

# 検索キーワード
SEARCH_KEYWORDS = [
    "配信初心者",
    "Pococha 始めた",
    "Pococha デビュー",
    "#初配信",
    "#配信初心者",
    "#ぽこちゃ始めました",
    "#ぽこちゃ",
    "石川県 配信",
    "金沢 ライブ",
    "配信 楽しかった",
    "初配信 緊張",
    "配信 始めた",
]

# NGワード（プロフィールにこれがある人はスキップ）
NG_WORDS = [
    "所属", "専属", "カーブアウト", "carveout",
    "起業家", "事業家", "ceo", "代表取締役", "経営者", "社長",
    "副業", "稼ぐ", "稼げる", "月収", "不労所得", "自動収益",
    "コンサル", "投資", "fx", "仮想通貨", "バイナリー", "mlm",
    "ネットワークビジネス", "情報商材",
    "公式", "株式会社", "合同会社", "official",
]

# ============================================================
# ログファイル（処理済みユーザー記録）
# ============================================================
PROCESSED_FILE = "data/list_processed.json"


def load_processed():
    """処理済みユーザーIDのセットを返す"""
    if not os.path.exists(PROCESSED_FILE):
        return set()
    with open(PROCESSED_FILE, "r") as f:
        return set(json.load(f))


def save_processed(processed: set):
    os.makedirs("data", exist_ok=True)
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(processed), f)


# ============================================================
# 深夜帯チェック
# ============================================================
def is_quiet_hours():
    """JST 02:00〜07:00 ならTrue"""
    now_jst = datetime.now(JST)
    return QUIET_HOUR_START <= now_jst.hour < QUIET_HOUR_END


# ============================================================
# NGフィルター
# ============================================================
def is_ng_user(user) -> bool:
    """NGターゲットならTrue"""
    bio = (user.description or "").lower()
    if any(w in bio for w in NG_WORDS):
        return True

    metrics = getattr(user, "public_metrics", None)
    if metrics:
        followers = metrics.get("followers_count", 0)
        following = metrics.get("following_count", 0)
        tweets = metrics.get("tweet_count", 0)

        # 幽霊アカウント
        if followers == 0 and tweets < 3:
            return True
        # 業者（フォロー/フォロワー比が異常）
        if following > 0 and followers > 0 and following / followers > 8:
            return True
        # フォロワー多すぎ（通知見ない）
        if followers > 10000:
            return True

    return False


# ============================================================
# Rate Limit対応
# ============================================================
def handle_rate_limit(e: tweepy.TooManyRequests):
    """Rate Limit到達時、リセットまで待機"""
    reset_time = int(e.response.headers.get("x-rate-limit-reset", 0))
    if reset_time:
        wait = max(reset_time - int(time.time()), 0) + 5
        log.warning(f"Rate Limit到達。{wait}秒待機...")
        time.sleep(wait)
    else:
        log.warning("Rate Limit到達。15分待機...")
        time.sleep(15 * 60)


# ============================================================
# メイン処理
# ============================================================
def main():
    # --- バリデーション ---
    if not LIST_ID:
        log.error("LIST_ID が設定されていません。環境変数 X_LIST_ID を設定してください。")
        sys.exit(1)

    # --- 深夜帯チェック ---
    if is_quiet_hours():
        now_jst = datetime.now(JST)
        log.info(f"深夜帯のため停止 (JST {now_jst.strftime('%H:%M')})")
        return

    # --- API認証 ---
    client = tweepy.Client(
        bearer_token=os.environ.get("TWITTER_BEARER_TOKEN", ""),
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
        wait_on_rate_limit=False,  # 自前でハンドリング
    )

    # --- 今日の追加目標（ランダム）---
    daily_target = random.randint(DAILY_MIN, DAILY_MAX)
    log.info(f"今日の目標: {daily_target}件")

    # --- 処理済みユーザー読み込み ---
    processed = load_processed()
    log.info(f"処理済みユーザー: {len(processed)}人")

    # --- 検索 & リスト追加ループ ---
    added_count = 0
    keywords_shuffled = random.sample(SEARCH_KEYWORDS, len(SEARCH_KEYWORDS))

    for keyword in keywords_shuffled:
        if added_count >= daily_target:
            break

        if is_quiet_hours():
            log.info("深夜帯に入ったため停止")
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
        except tweepy.TooManyRequests as e:
            handle_rate_limit(e)
            continue
        except tweepy.TwitterServerError:
            log.warning("X API サーバーエラー。30秒待機...")
            time.sleep(30)
            continue
        except Exception as e:
            log.error(f"検索エラー: {e}")
            continue

        if not tweets.data:
            log.info("  検索結果なし")
            continue

        users = {u.id: u for u in tweets.includes.get("users", [])}

        for tweet in tweets.data:
            if added_count >= daily_target:
                break

            user = users.get(tweet.author_id)
            if not user:
                continue

            # 処理済みスキップ
            if str(user.id) in processed:
                continue

            # NGフィルター
            if is_ng_user(user):
                log.info(f"  ❌ NG @{user.username}")
                processed.add(str(user.id))
                continue

            # --- リストに追加 ---
            try:
                client.add_list_member(
                    id=LIST_ID,
                    user_id=user.id,
                )
                added_count += 1
                processed.add(str(user.id))
                log.info(f"  ✅ [{added_count}/{daily_target}] @{user.username} をリストに追加")

                # --- ランダム待機（Jitter）---
                wait = random.randint(WAIT_MIN, WAIT_MAX)
                jitter = random.randint(-120, 120)  # ±2分のジッター
                total_wait = max(wait + jitter, 60)  # 最低1分
                log.info(f"  ⏳ 次の追加まで {total_wait // 60}分{total_wait % 60}秒 待機")
                time.sleep(total_wait)

            except tweepy.TooManyRequests as e:
                handle_rate_limit(e)
            except tweepy.Forbidden as e:
                log.warning(f"  ⚠️ 追加失敗(Forbidden) @{user.username}: {e}")
                processed.add(str(user.id))
            except tweepy.TwitterServerError:
                log.warning("  ⚠️ サーバーエラー。30秒待機...")
                time.sleep(30)
            except Exception as e:
                log.error(f"  ⚠️ 追加エラー @{user.username}: {e}")

    # --- 結果保存 ---
    save_processed(processed)

    log.info(f"\n{'='*40}")
    log.info(f"完了: {added_count}件 リストに追加")
    log.info(f"処理済み累計: {len(processed)}人")
    log.info(f"{'='*40}")


if __name__ == "__main__":
    main()
