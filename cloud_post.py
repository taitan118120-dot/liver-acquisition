"""
クラウド用 自動投稿スクリプト
GitHub Actions から実行される。Mac不要。

改善版:
- ハッシュタグ自動付与（投稿内容に合わせて選択）
- スレッド投稿対応（thread フィールドがある投稿）
- 投稿タイプのバランス管理
"""

import json
import os
import random
import tweepy


# ハッシュタグプール（投稿内容に応じて2-3個選ぶ）
HASHTAG_POOL = {
    "副業": ["#副業", "#在宅ワーク", "#在宅副業", "#副業初心者", "#副業探し"],
    "配信": ["#ライブ配信", "#配信初心者", "#Pococha", "#ライバー"],
    "収入": ["#副収入", "#収入アップ", "#お金の話", "#家計管理"],
    "自由": ["#自由な働き方", "#フリーランス", "#脱サラ", "#在宅"],
    "大学生": ["#大学生", "#大学生の日常", "#バイト代"],
    "主婦": ["#主婦", "#ママ", "#在宅ママ", "#主婦副業"],
    "転職": ["#転職", "#転職活動", "#仕事辞めたい", "#働き方改革"],
    "共感": ["#共感したらRT", "#わかる", "#あるある"],
    "日常": ["#日常", "#つぶやき", "#今日のひとこと"],
}

# 投稿テキストに含まれるキーワードからカテゴリを判定
KEYWORD_TO_CATEGORY = {
    "副業": "副業", "在宅": "副業", "稼": "収入", "収入": "収入", "月": "収入",
    "配信": "配信", "ライバー": "配信", "Pococha": "配信", "ライブ": "配信",
    "自由": "自由", "満員電車": "自由", "会社員": "転職", "辞め": "転職",
    "あるある": "共感", "わかる": "共感", "共感": "共感",
    "大学生": "大学生", "主婦": "主婦", "シングル": "主婦", "ママ": "主婦",
}


def pick_hashtags(text, max_tags=3):
    """投稿テキストに合ったハッシュタグを2-3個選ぶ"""
    matched_categories = set()
    for keyword, category in KEYWORD_TO_CATEGORY.items():
        if keyword in text:
            matched_categories.add(category)

    if not matched_categories:
        matched_categories = {"日常", "共感"}

    # マッチしたカテゴリからランダムにタグを選ぶ
    candidates = []
    for cat in matched_categories:
        candidates.extend(HASHTAG_POOL.get(cat, []))

    # 必ず1つは広めのリーチ用タグを追加
    broad_tags = ["#副業", "#在宅ワーク", "#自由な働き方", "#副業初心者"]
    candidates.extend(broad_tags)

    # 重複排除してランダム選択
    candidates = list(set(candidates))
    num_tags = random.randint(2, min(max_tags, len(candidates)))
    return random.sample(candidates, num_tags)


def append_hashtags(text, hashtags):
    """テキストにハッシュタグを追加（280文字制限考慮）"""
    tag_str = "\n\n" + " ".join(hashtags)
    # Xの文字数制限（日本語は半角2文字換算で280文字≒全角140文字）
    if len(text) + len(tag_str) > 140:
        # タグを1個に減らす
        tag_str = "\n\n" + hashtags[0]
    if len(text) + len(tag_str) > 140:
        return text  # 入らない場合はタグなし
    return text + tag_str


def post_thread(client, thread_texts):
    """スレッド（連続ツイート）を投稿"""
    prev_id = None
    tweet_ids = []
    for i, text in enumerate(thread_texts):
        if i == 0:
            resp = client.create_tweet(text=text)
        else:
            resp = client.create_tweet(
                text=text,
                in_reply_to_tweet_id=prev_id,
            )
        prev_id = resp.data["id"]
        tweet_ids.append(prev_id)
        print(f"  スレッド {i+1}/{len(thread_texts)} 投稿成功")
    return tweet_ids


def main():
    # 環境変数からAPIキーを取得（GitHub Secretsから注入）
    client = tweepy.Client(
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )

    # 投稿コンテンツを読み込み
    with open("posts/twitter_posts.json", "r", encoding="utf-8") as f:
        posts = json.load(f)

    # growthフェーズのみ（募集・宣伝は封印）
    growth_posts = [p for p in posts if p.get("phase") == "growth"]

    # 直近の投稿IDを確認（重複防止）
    recent_file = "data/recent_post_ids.txt"
    recent_ids = set()
    if os.path.exists(recent_file):
        with open(recent_file, "r") as f:
            recent_ids = set(f.read().strip().split("\n"))

    # まだ投稿してないものを選ぶ
    available = [p for p in growth_posts if p["id"] not in recent_ids]
    if not available:
        # 全部投稿済み → リセットしてローテーション
        recent_ids = set()
        available = growth_posts

    post = random.choice(available)

    # スレッド投稿かチェック
    if "thread" in post:
        # スレッドの最初のツイートにハッシュタグ付与
        thread_texts = list(post["thread"])
        hashtags = pick_hashtags(thread_texts[0])
        thread_texts[0] = append_hashtags(thread_texts[0], hashtags)
        tweet_ids = post_thread(client, thread_texts)
        print(f"スレッド投稿成功: {post['id']} ({len(tweet_ids)}件)")
    else:
        # 通常投稿: ハッシュタグを自動付与
        hashtags = pick_hashtags(post["text"])
        text_with_tags = append_hashtags(post["text"], hashtags)
        response = client.create_tweet(text=text_with_tags)
        print(f"投稿成功: {post['id']} → {response.data['id']}")
        print(f"  ハッシュタグ: {' '.join(hashtags)}")

    # 投稿済みIDを記録
    recent_ids.add(post["id"])
    os.makedirs("data", exist_ok=True)
    with open(recent_file, "w") as f:
        f.write("\n".join(recent_ids))


if __name__ == "__main__":
    main()
