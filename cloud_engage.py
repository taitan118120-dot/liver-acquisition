"""
クラウド用 自動エンゲージメント（フォロー+リプライ）スクリプト
GitHub Actions から実行される。Mac不要。

ルール:
- いいね: 0
- フォロー: 1日15〜30人（人間らしいアカウントのみ）
- リプライ: 1日10件まで（絵文字入り・口語体）
- 検索: 返信率が高いキーワード重視
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

# 返信率が高い検索キーワード（日常系・感情系が反応しやすい）
TARGET_KEYWORDS = [
    # 配信系（メイン）
    "初配信 緊張",
    "配信 楽しかった",
    "Pococha 始めた",
    "Pococha デビュー",
    "#初配信",
    "#配信初心者",
    "#ぽこちゃ始めました",
    # 石川県（地域特化）
    "石川県 配信",
    "金沢 ライブ",
    # 夢・挑戦系（返信率高い）
    "何か新しいこと始めたい",
    "自分を変えたい",
    "新しい挑戦",
    "推しに会いたい",
]

# NGワード（業者・企業・副業系を排除）
NG_WORDS = [
    # 事務所・所属
    "所属", "専属", "カーブアウト", "carveout",
    # 副業・ビジネス系（業者排除）
    "起業家", "事業家", "ceo", "代表取締役", "経営者", "社長",
    "副業", "稼ぐ", "稼げる", "月収", "不労所得", "自動収益",
    "コンサル", "投資", "fx", "仮想通貨", "バイナリー", "mlm",
    "ネットワークビジネス", "情報商材", "LINE@", "公式LINE",
    "アフィリエイト", "物販", "せどり",
    # 企業
    "公式", "株式会社", "合同会社", "official", "PR",
    # bot系（フォローNGだがリプライには使わない）
    "相互フォロー", "相互100",
]

# フォロー用キーワード（フォロバ率が高いやつ）
FOLLOW_KEYWORDS = [
    "#フォロバ100",
    "#フォロバします",
    "#いいねした人全員フォロー",
    "#相互フォロー募集",
    # 配信系
    "#配信初心者",
    "#Pococha",
    "#ぽこちゃ始めました",
    "初配信 緊張",
]

# リプライ用キーワード（リプ返しやすい人を探す）
REPLY_KEYWORDS = [
    "初配信 緊張",
    "配信 楽しかった",
    "Pococha 始めた",
    "Pococha デビュー",
    "#初配信",
    "#配信初心者",
    "石川県 配信",
    "金沢 ライブ",
    "何か新しいこと始めたい",
]

FOLLOW_RANGE = (15, 30)
REPLY_LIMIT_PER_DAY = 10
EXECUTIONS_PER_DAY = 3
FOLLOW_PER_EXEC_MIN = FOLLOW_RANGE[0] // EXECUTIONS_PER_DAY
FOLLOW_PER_EXEC_MAX = FOLLOW_RANGE[1] // EXECUTIONS_PER_DAY
REPLY_PER_EXEC = REPLY_LIMIT_PER_DAY // EXECUTIONS_PER_DAY


# ============================================================
# リプライ生成（フリック入力風・自然な口語）
# ============================================================
def generate_reply(tweet_text, user_name):
    """
    相手の投稿の事実だけに触れる。石川県最優先。
    エージェント視点。フリック入力で打ったような自然さ。
    """
    text = tweet_text.lower()

    # 石川県・金沢関連 → 最優先
    if any(w in text for w in ["石川", "金沢", "能登", "加賀", "兼六園"]):
        return random.choice([
            "え、石川なんですね！自分も石川なんで親近感わきました笑",
            "金沢いいっすよね〜🙌 地元一緒かもです！",
            "お、石川！自分も石川関わりあるんで勝手に嬉しいです笑",
        ])

    # Pococha関連
    if "pococha" in text or "ぽこちゃ" in text or "ポコチャ" in text:
        return random.choice([
            "ぽこちゃ自分もめっちゃ見てます〜！頑張ってください🙌",
            "お、Pocochaやってるんですね！最初ほんとドキドキしますよね笑",
            "ぽこちゃ楽しいですよね〜 応援してます！",
        ])

    # 初配信・初心者
    if any(w in text for w in ["初配信", "始めた", "初心者", "デビュー", "初めて"]):
        return random.choice([
            "お、始めたんすね！最初って緊張しますよね笑 応援してます🙌",
            "おお〜！自分も最初そうだったなあ 頑張ってください！",
            "始めたばっかの時って大変だけど一番楽しい時期ですよね😆",
        ])

    # 配信した・配信終わり
    if any(w in text for w in ["配信した", "配信終わり", "枠閉じ", "配信お疲れ"]):
        return random.choice([
            "おつかれさまです〜！今日もおつかれっす🙌",
            "おつです！ちゃんと続けてるのほんとすごい",
        ])

    # 緊張・不安系
    if any(w in text for w in ["緊張", "不安", "怖い", "ドキドキ"]):
        return random.choice([
            "わかります笑 でもやってみると意外と大丈夫ですよ！",
            "それめっちゃわかる〜 最初誰でもそうなんで大丈夫っす🙌",
        ])

    # 楽しかった系
    if any(w in text for w in ["楽しかった", "楽しい", "嬉しい", "ありがとう"]):
        return random.choice([
            "いいっすね〜！楽しめてるのが一番😆",
            "それ最高じゃないですか！🙌",
        ])

    # 挑戦・新しいこと
    if any(w in text for w in ["挑戦", "始めたい", "変えたい", "新しい"]):
        return random.choice([
            "お〜いいっすね！応援してます🙌",
            "動いてる人ほんと尊敬します！頑張ってください💪",
        ])

    # 汎用
    return random.choice([
        "わかります〜！気になったんでつい🙌",
        "いいっすね！フォローさせてもらいました〜",
    ])


# ============================================================
# フォロー対象チェック
# ============================================================
def is_ng(bio):
    if not bio:
        return False
    bio_lower = bio.lower()
    return any(w in bio_lower for w in NG_WORDS)


def is_real_person(user):
    """人間らしいアカウントかチェック（業者・bot排除）"""
    bio = (user.description or "").lower()

    # NGワードチェック
    if is_ng(bio):
        return False

    # フォロワー数チェック（極端に多い or 0は除外）
    metrics = getattr(user, "public_metrics", None)
    if metrics:
        followers = metrics.get("followers_count", 0)
        following = metrics.get("following_count", 0)
        tweets = metrics.get("tweet_count", 0)

        # フォロワー0でツイート0 → 幽霊アカウント
        if followers == 0 and tweets < 5:
            return False

        # フォロー数がフォロワーの10倍以上 → 業者
        if following > 0 and followers > 0 and following / followers > 10:
            return False

        # フォロワー1万以上 → フォロバしてくれない
        if followers > 10000:
            return False

    return True


# ============================================================
# ログ管理
# ============================================================
LOG_FILE = "data/daily_counts.json"


def load_daily_counts():
    if not os.path.exists(LOG_FILE):
        return {"date": "", "follows": 0, "replies": 0}
    with open(LOG_FILE, "r") as f:
        data = json.load(f)
    if data.get("date") != str(date.today()):
        return {"date": str(date.today()), "follows": 0, "replies": 0}
    return data


def save_daily_counts(counts):
    os.makedirs("data", exist_ok=True)
    counts["date"] = str(date.today())
    with open(LOG_FILE, "w") as f:
        json.dump(counts, f)


# ============================================================
# メイン
# ============================================================
def main():
    client = tweepy.Client(
        bearer_token=os.environ["TWITTER_BEARER_TOKEN"],
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

    followed = 0
    replied = 0

    # --- フォロー（フォロバ率高いキーワードで検索）---
    if follow_target > 0:
        fkw = random.choice(FOLLOW_KEYWORDS)
        print(f"👤 フォロー検索: {fkw}")

        f_tweets = client.search_recent_tweets(
            query=f"{fkw} -is:retweet lang:ja",
            max_results=min(follow_target + 10, 100),
            tweet_fields=["author_id"],
            user_fields=["username", "name", "description", "public_metrics"],
            expansions=["author_id"],
        )

        if f_tweets.data:
            f_users = {u.id: u for u in f_tweets.includes.get("users", [])}
            for tweet in f_tweets.data:
                if followed >= follow_target:
                    break
                user = f_users.get(tweet.author_id)
                if not user or not is_real_person(user):
                    continue
                try:
                    client.follow_user(user.id)
                    followed += 1
                    counts["follows"] += 1
                    print(f"  ✅ フォロー @{user.username}")
                    time.sleep(3)
                except Exception as e:
                    print(f"  ⚠️ @{user.username}: {e}")

    # --- リプライ（リプ返しやすい人を検索）---
    if reply_target > 0:
        rkw = random.choice(REPLY_KEYWORDS)
        print(f"💬 リプライ検索: {rkw}")

        r_tweets = client.search_recent_tweets(
            query=f"{rkw} -is:retweet lang:ja",
            max_results=20,
            tweet_fields=["author_id", "text"],
            user_fields=["username", "name", "description"],
            expansions=["author_id"],
        )

        if r_tweets.data:
            r_users = {u.id: u for u in r_tweets.includes.get("users", [])}
            for tweet in r_tweets.data:
                if replied >= reply_target:
                    break
                user = r_users.get(tweet.author_id)
                if not user:
                    continue
                if is_ng(user.description):
                    continue
                if random.random() < 0.5:
                    continue  # 全員にリプしない、ランダムに選ぶ

                reply_text = generate_reply(tweet.text, user.name)
                try:
                    client.create_tweet(
                        text=f"@{user.username} {reply_text}",
                        in_reply_to_tweet_id=tweet.id,
                    )
                    replied += 1
                    counts["replies"] += 1
                    print(f"  💬 @{user.username}: {reply_text[:40]}...")
                    time.sleep(5)
                except Exception as e:
                    print(f"  ⚠️ @{user.username}: {e}")

    # --- 完了 ---

    save_daily_counts(counts)
    print(f"\n🎯 完了 → フォロー: {followed}  リプライ: {replied}")
    print(f"📈 本日累計 → フォロー: {counts['follows']}  リプライ: {counts['replies']}")


if __name__ == "__main__":
    main()
