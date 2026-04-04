"""
クラウド用 自動エンゲージメント（フォロー+リプライ）スクリプト
GitHub Actions から実行される。Mac不要。

ルール:
- いいね: 0（やらない）
- フォロー: 1日15〜30人
- リプライ: 1日10件まで
- 検索: 配信初心者, Pococha, 石川県
- リプライは相手の投稿の事実だけに触れる
- 石川県の話題は最優先で拾う
- 業界の裏方(エージェント)視点で短く返す
- 自然な口語体(フリック入力風)
"""

import os
import random
import time
import json
from datetime import datetime, date
import tweepy
import urllib.parse


# ============================================================
# 設定
# ============================================================
TARGET_KEYWORDS = [
    "配信初心者",
    "Pococha",
    "Pococha 始めた",
    "Pococha 配信",
    "石川県",
    "金沢",
    "配信 始めた",
    "#配信初心者",
    "#Pococha",
    "#ぽこちゃ",
]

NG_WORDS = [
    "所属", "専属", "カーブアウト", "carveout",
    "起業家", "事業家", "ceo", "代表取締役", "経営者", "社長",
    "公式", "株式会社", "合同会社", "official",
    "コンサル", "投資", "fx", "仮想通貨", "バイナリー", "mlm",
    "ネットワークビジネス",
]

FOLLOW_RANGE = (15, 30)  # 1日のフォロー数の範囲
REPLY_LIMIT_PER_DAY = 10
LIKE_COUNT = 0  # いいねしない

# 1日3回実行 → 1回あたりのフォロー数
EXECUTIONS_PER_DAY = 3
FOLLOW_PER_EXEC_MIN = FOLLOW_RANGE[0] // EXECUTIONS_PER_DAY  # 5
FOLLOW_PER_EXEC_MAX = FOLLOW_RANGE[1] // EXECUTIONS_PER_DAY  # 10
REPLY_PER_EXEC = REPLY_LIMIT_PER_DAY // EXECUTIONS_PER_DAY   # 3


# ============================================================
# リプライ生成（AI風・テンプレートベース）
# ============================================================
def generate_reply(tweet_text, user_name):
    """
    相手の投稿テキストにある事実だけに触れて、
    エージェント視点で短く返す。自然な口語体。
    """
    text = tweet_text.lower()

    # 石川県・金沢関連 → 最優先
    if any(w in text for w in ["石川", "金沢", "能登", "加賀", "兼六園"]):
        ishikawa_replies = [
            "石川いいですよね、配信者さんも最近増えてきてる印象あります",
            "金沢周辺のライバーさん何人か見てるけどまだまだ少ないから今がチャンスかも",
            "石川からだと競合少ないから意外と伸びやすいんですよね",
            "北陸の配信者さんって独自のポジション取れるから強いんですよ",
        ]
        return random.choice(ishikawa_replies)

    # Pococha関連
    if "pococha" in text or "ぽこちゃ" in text or "ポコチャ" in text:
        pococha_replies = [
            "Pococha始めたんですね、最初の1ヶ月が一番大変だけどそこ超えると楽しくなりますよ",
            "ぽこちゃは時間ダイヤあるから初心者でも収益出やすいの良いですよね",
            "Pocochaのランク戦、最初は仕組みわからんかもだけど慣れたら戦略立てるの面白くなる",
            "配信枠の雰囲気作りが一番大事、最初はゆるくでいいと思う",
        ]
        return random.choice(pococha_replies)

    # 配信始めた・初心者
    if any(w in text for w in ["始めた", "初心者", "デビュー", "初配信", "初めて"]):
        beginner_replies = [
            "始めたばっかの時期が一番伸びしろあるから楽しみですね",
            "最初は誰も来なくて当たり前なんで、焦らずでいいですよ",
            "配信3ヶ月続けられる人って全体の2割くらいしかいないから、続けるだけで差つく",
            "初期のうちにリスナーとの距離感掴めると後が楽になりますよ",
        ]
        return random.choice(beginner_replies)

    # 配信の感想・報告系
    if any(w in text for w in ["配信した", "配信終わり", "枠閉じ", "ランク", "イベント"]):
        activity_replies = [
            "お疲れ様です、コンスタントに枠開けてるの大事ですよね",
            "配信の振り返りちゃんとやってるの偉い、伸びる人ってだいたいそう",
            "枠の時間帯とか曜日で数字変わるから色々試してみるの良いですよ",
        ]
        return random.choice(activity_replies)

    # 汎用（どのカテゴリにも当てはまらない場合）
    general_replies = [
        "なるほど、気になるツイートだったのでつい反応しちゃいました",
        "面白い視点ですね、配信業界からすると参考になります",
    ]
    return random.choice(general_replies)


# ============================================================
# NGチェック
# ============================================================
def is_ng(bio):
    if not bio:
        return False
    bio_lower = bio.lower()
    return any(w in bio_lower for w in NG_WORDS)


# ============================================================
# ログ管理
# ============================================================
LOG_FILE = "data/daily_counts.json"

def load_daily_counts():
    """今日のアクション数を読み込む"""
    if not os.path.exists(LOG_FILE):
        return {"date": "", "follows": 0, "replies": 0}
    with open(LOG_FILE, "r") as f:
        data = json.load(f)
    if data.get("date") != str(date.today()):
        return {"date": str(date.today()), "follows": 0, "replies": 0}
    return data

def save_daily_counts(counts):
    """今日のアクション数を保存"""
    os.makedirs("data", exist_ok=True)
    counts["date"] = str(date.today())
    with open(LOG_FILE, "w") as f:
        json.dump(counts, f)


# ============================================================
# メイン
# ============================================================
def main():
    # OAuth 1.0aのみで認証（ベアラートークンは使わない）
    client = tweepy.Client(
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )

    counts = load_daily_counts()
    remaining_follows = FOLLOW_RANGE[1] - counts["follows"]
    remaining_replies = REPLY_LIMIT_PER_DAY - counts["replies"]

    if remaining_follows <= 0 and remaining_replies <= 0:
        print("今日の上限に達済み。スキップ。")
        return

    follow_target = min(
        random.randint(FOLLOW_PER_EXEC_MIN, FOLLOW_PER_EXEC_MAX),
        remaining_follows
    )
    reply_target = min(REPLY_PER_EXEC, remaining_replies)

    keyword = random.choice(TARGET_KEYWORDS)
    print(f"検索: {keyword}")
    print(f"今日の残り → フォロー: {remaining_follows}  リプライ: {remaining_replies}")
    print(f"今回の目標 → フォロー: {follow_target}  リプライ: {reply_target}")

    tweets = client.search_recent_tweets(
        query=f"{keyword} -is:retweet lang:ja",
        max_results=min(follow_target + 5, 100),
        tweet_fields=["author_id", "text"],
        user_fields=["username", "name", "description"],
        expansions=["author_id"],
    )

    if not tweets.data:
        print("検索結果なし")
        return

    users = {u.id: u for u in tweets.includes.get("users", [])}
    followed = 0
    replied = 0

    for tweet in tweets.data:
        if followed >= follow_target and replied >= reply_target:
            break

        user = users.get(tweet.author_id)
        if not user:
            continue

        if is_ng(user.description):
            print(f"  [NG] @{user.username}")
            continue

        # フォロー
        if followed < follow_target:
            try:
                client.follow_user(user.id)
                followed += 1
                counts["follows"] += 1
                print(f"  [フォロー {followed}] @{user.username}")
                time.sleep(3)
            except Exception as e:
                print(f"  [フォローエラー] @{user.username}: {e}")

        # リプライ（全員にはしない。ランダムに選ぶ）
        if replied < reply_target and random.random() < 0.4:
            reply_text = generate_reply(tweet.text, user.name)
            try:
                client.create_tweet(
                    text=f"@{user.username} {reply_text}",
                    in_reply_to_tweet_id=tweet.id,
                )
                replied += 1
                counts["replies"] += 1
                print(f"  [リプライ {replied}] @{user.username}: {reply_text[:40]}...")
                time.sleep(5)
            except Exception as e:
                print(f"  [リプライエラー] @{user.username}: {e}")

    save_daily_counts(counts)
    print(f"\n完了 → フォロー: {followed}  リプライ: {replied}")
    print(f"本日累計 → フォロー: {counts['follows']}  リプライ: {counts['replies']}")


if __name__ == "__main__":
    main()
