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
    # bot系
    "相互フォロー", "相互100", "フォロバ100",
]

FOLLOW_RANGE = (15, 30)
REPLY_LIMIT_PER_DAY = 10
EXECUTIONS_PER_DAY = 3
FOLLOW_PER_EXEC_MIN = FOLLOW_RANGE[0] // EXECUTIONS_PER_DAY
FOLLOW_PER_EXEC_MAX = FOLLOW_RANGE[1] // EXECUTIONS_PER_DAY
REPLY_PER_EXEC = REPLY_LIMIT_PER_DAY // EXECUTIONS_PER_DAY


# ============================================================
# リプライ生成（絵文字入り・口語体）
# ============================================================
def generate_reply(tweet_text, user_name):
    """
    相手の投稿の事実だけに触れる。
    石川県の話題は最優先。エージェント視点。
    絵文字入りで人間らしく。
    """
    text = tweet_text.lower()

    # 石川県・金沢関連 → 最優先
    if any(w in text for w in ["石川", "金沢", "能登", "加賀", "兼六園"]):
        return random.choice([
            "石川いいですよね〜！☺️ 配信者さんも最近増えてきてる印象あります✨",
            "金沢住みなんですね！🏯 あのエリアまだ配信者少ないから注目されやすいかもです🙌",
            "石川からの配信って珍しくて逆に目立つんですよね😊 応援してます！",
        ])

    # Pococha関連
    if "pococha" in text or "ぽこちゃ" in text or "ポコチャ" in text:
        return random.choice([
            "Pococha始めたんですね！🎉 最初の1ヶ月乗り越えたらめっちゃ楽しくなりますよ〜😊",
            "ぽこちゃいいですよね✨ 時間ダイヤあるから続けやすいのが最高🙌",
            "Pocochaのランク戦、慣れてくると戦略考えるのハマりますよ😆 頑張ってください！",
        ])

    # 初配信・初心者
    if any(w in text for w in ["初配信", "始めた", "初心者", "デビュー", "初めて"]):
        return random.choice([
            "始めたばっかなんですね！✨ 一番伸びしろある時期だから楽しみ〜😊",
            "初配信お疲れ様です🎉 最初ドキドキしますよね！でもすぐ慣れます💪",
            "おお！始めたんですね😆 3ヶ月続けたらガチで世界変わりますよ〜🔥",
        ])

    # 配信した・配信終わり
    if any(w in text for w in ["配信した", "配信終わり", "枠閉じ", "配信お疲れ"]):
        return random.choice([
            "配信お疲れ様です！🙌 コンスタントに枠開けてるの素敵✨",
            "お疲れ様〜！😊 今日の配信どうでした？楽しめてたら最高ですね🎵",
        ])

    # 緊張・不安系
    if any(w in text for w in ["緊張", "不安", "怖い", "ドキドキ"]):
        return random.choice([
            "緊張しますよね😂 でもそれだけ真剣ってことだから大丈夫！✨",
            "最初はみんなそうですよ〜☺️ やってみたら意外となんとかなります🙌",
        ])

    # 楽しかった系
    if any(w in text for w in ["楽しかった", "楽しい", "嬉しい", "ありがとう"]):
        return random.choice([
            "楽しめてるの最高ですね！😊✨ その気持ちが一番大事💪",
            "いいですね〜！🎵 楽しんでる人のところにリスナーは集まりますよ☺️",
        ])

    # 挑戦・新しいこと
    if any(w in text for w in ["挑戦", "始めたい", "変えたい", "新しい"]):
        return random.choice([
            "新しいこと始めるの素敵です！✨ 応援してます😊",
            "いいですね！🔥 動き出した人が一番強いですよ💪",
        ])

    # 汎用
    return random.choice([
        "素敵ですね！✨ つい反応しちゃいました😊",
        "いいですね〜！☺️ 気になったのでフォローさせてもらいました✨",
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

    keyword = random.choice(TARGET_KEYWORDS)
    print(f"🔍 検索: {keyword}")
    print(f"📊 今日の残り → フォロー: {remaining_follows}  リプライ: {remaining_replies}")

    tweets = client.search_recent_tweets(
        query=f"{keyword} -is:retweet lang:ja",
        max_results=min(follow_target + 10, 100),
        tweet_fields=["author_id", "text"],
        user_fields=["username", "name", "description", "public_metrics"],
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

        # 人間チェック
        if not is_real_person(user):
            print(f"  ❌ スキップ @{user.username}（業者/bot/非アクティブ）")
            continue

        # フォロー
        if followed < follow_target:
            try:
                client.follow_user(user.id)
                followed += 1
                counts["follows"] += 1
                print(f"  ✅ フォロー @{user.username}")
                time.sleep(3)
            except Exception as e:
                print(f"  ⚠️ フォローエラー @{user.username}: {e}")

        # リプライ（40%の確率で選択）
        if replied < reply_target and random.random() < 0.4:
            reply_text = generate_reply(tweet.text, user.name)
            try:
                client.create_tweet(
                    text=f"@{user.username} {reply_text}",
                    in_reply_to_tweet_id=tweet.id,
                )
                replied += 1
                counts["replies"] += 1
                print(f"  💬 リプライ @{user.username}: {reply_text[:40]}...")
                time.sleep(5)
            except Exception as e:
                print(f"  ⚠️ リプライエラー @{user.username}: {e}")

    save_daily_counts(counts)
    print(f"\n🎯 完了 → フォロー: {followed}  リプライ: {replied}")
    print(f"📈 本日累計 → フォロー: {counts['follows']}  リプライ: {counts['replies']}")


if __name__ == "__main__":
    main()
