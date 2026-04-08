"""
クラウド用 リード検索・保存スクリプト
副業・配信に興味ある層を検索してリード候補をCSVに蓄積する。

いいね機能は削除（非効率のため）。
"""

import os
import random
import json
from datetime import date
import tweepy


# ============================================================
# 設定
# ============================================================

# 検索キーワード（リード発見用）- 副業・在宅層も含める
SEARCH_KEYWORDS = [
    # 配信系（既存）
    "初配信 緊張",
    "配信 楽しかった",
    "Pococha 始めた",
    "Pococha デビュー",
    "#初配信",
    "#配信初心者",
    "#ぽこちゃ始めました",
    # 副業・在宅系（新規層の取り込み）
    "副業 始めたい",
    "在宅ワーク 探してる",
    "副業 何がいい",
    "在宅 副業",
    "#副業初心者",
    "#在宅ワーク",
    "#副業探し",
    # お金・仕事系（潜在層）
    "手取り 少ない",
    "給料 上がらない",
    "仕事 辞めたい 副業",
    "バイト代 足りない",
]

NG_WORDS = [
    # 事務所・企業
    "所属", "専属", "カーブアウト", "carveout",
    "公式", "株式会社", "合同会社", "official",
    # ビジネス勧誘・MLM
    "起業家", "事業家", "ceo", "代表取締役", "経営者", "社長",
    "稼げる", "月収", "不労所得", "自動収益", "権利収入", "継続収入",
    "コンサル", "投資", "fx", "仮想通貨", "バイナリー", "mlm",
    "ネットワークビジネス", "情報商材", "オンラインサロン",
    "月収100万", "月収50万", "脱サラ成功", "自由な生活",
    "公式line", "line@", "line登録", "プレゼント企画", "無料配布",
    "コピトレ", "自動売買", "ea", "シグナル配信",
    "物販スクール", "転売スクール", "起業塾", "ビジネスコミュニティ",
    "アフィリエイト", "note販売", "brain",
    "固定ツイ見て", "プロフ見て", "詳しくはプロフ",
    "dm待ってます", "気軽にdm", "相談乗ります",
    # 相互系
    "相互フォロー", "相互100", "フォロバ100", "#相互",
    # スパム
    "懸賞", "当選", "プレゼント応募",
]

# ツイート本文のNGワード
NG_TWEET_WORDS = [
    "公式line", "line登録", "無料プレゼント", "期間限定",
    "詳しくはプロフ", "固定ツイ見て", "プロフのリンク",
    "月収", "万円達成", "実績公開", "コンサル生",
    "スクール", "セミナー", "ウェビナー",
]

LEADS_FILE = "data/leads.csv"
SEEN_FILE = "data/engage_seen.json"


def is_ng(bio, tweet_text=""):
    """プロフィールとツイート本文の両方でNG判定"""
    bio_lower = (bio or "").lower()
    if any(w in bio_lower for w in NG_WORDS):
        return True

    money_emojis = sum(1 for e in ["💰", "🔥", "✨", "💎", "🌈", "📈", "💵", "🏆"] if e in bio_lower)
    if money_emojis >= 3:
        return True

    if bio_lower.count("http") + bio_lower.count("lin.ee") + bio_lower.count("lit.link") >= 2:
        return True

    tweet_lower = tweet_text.lower()
    if any(w in tweet_lower for w in NG_TWEET_WORDS):
        return True

    return False


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r") as f:
        return set(json.load(f))


def save_seen(seen):
    os.makedirs("data", exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def main():
    client = tweepy.Client(
        bearer_token=os.environ["TWITTER_BEARER_TOKEN"],
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )

    seen = load_seen()

    # 複数キーワードで検索（2つランダム選択）
    keywords = random.sample(SEARCH_KEYWORDS, min(2, len(SEARCH_KEYWORDS)))
    new_leads = 0

    for keyword in keywords:
        print(f"検索: {keyword}")

        try:
            tweets = client.search_recent_tweets(
                query=f"{keyword} -is:retweet lang:ja",
                max_results=30,
                tweet_fields=["author_id", "text"],
                user_fields=["username", "name", "description", "public_metrics"],
                expansions=["author_id"],
            )
        except Exception as e:
            print(f"  検索エラー: {e}")
            continue

        if not tweets.data:
            print("  検索結果なし")
            continue

        users = {u.id: u for u in tweets.includes.get("users", [])}

        # リード候補をCSVに保存
        os.makedirs("data", exist_ok=True)
        write_header = not os.path.exists(LEADS_FILE)
        with open(LEADS_FILE, "a", encoding="utf-8") as f:
            if write_header:
                f.write("username,name,bio,found_date,keyword\n")
            for tweet in tweets.data:
                user = users.get(tweet.author_id)
                if not user:
                    continue
                if str(user.id) in seen:
                    continue
                if is_ng(user.description, tweet_text=tweet.text):
                    seen.add(str(user.id))
                    continue

                bio = (user.description or "").replace(",", " ").replace("\n", " ")[:100]
                f.write(f"{user.username},{user.name},{bio},{date.today()},{keyword}\n")
                seen.add(str(user.id))
                new_leads += 1

    save_seen(seen)
    print(f"\n完了 → 新規リード: {new_leads}件")


if __name__ == "__main__":
    main()
