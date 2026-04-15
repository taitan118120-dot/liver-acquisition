"""
クラウド用 自動投稿スクリプト
GitHub Actions から実行される。Mac不要。

改善版:
- ハッシュタグ自動付与（投稿内容に合わせて選択）
- スレッド投稿対応（thread フィールドがある投稿）
- 投稿タイプのバランス管理
- 堅牢なエラーハンドリング・リトライ・重複防止
"""

import hashlib
import json
import os
import random
import sys
import time

import tweepy


# ハッシュタグプール（ニッチタグ重視 — 小規模アカウントでも上位表示を狙う）
HASHTAG_POOL = {
    "副業": ["#スマホ副業", "#在宅副業", "#副業初心者", "#おうち副業"],
    "配信": ["#ライバー初心者", "#配信初心者", "#Pococha初心者", "#ぽこちゃ", "#配信デビュー"],
    "収入": ["#配信で稼ぐ", "#スマホで稼ぐ", "#副収入"],
    "自由": ["#おうちワーク", "#在宅ワーママ", "#スキマ時間"],
    "大学生": ["#大学生副業", "#バイト以外の収入"],
    "主婦": ["#主婦副業", "#在宅ママ", "#ママの働き方"],
    "転職": ["#仕事辞めたい", "#新しい働き方"],
    "共感": ["#配信者あるある", "#ライバーあるある"],
    "日常": ["#今日の配信", "#配信日記"],
}

# 投稿テキストに含まれるキーワードからカテゴリを判定
KEYWORD_TO_CATEGORY = {
    "副業": "副業", "在宅": "副業", "稼": "収入", "収入": "収入", "月": "収入",
    "配信": "配信", "ライバー": "配信", "Pococha": "配信", "ライブ": "配信",
    "自由": "自由", "満員電車": "自由", "会社員": "転職", "辞め": "転職",
    "あるある": "共感", "わかる": "共感", "共感": "共感",
    "大学生": "大学生", "主婦": "主婦", "シングル": "主婦", "ママ": "主婦",
}

# リトライ設定
MAX_RETRIES = 3
RETRY_WAIT_SEC = 5

# 投稿済みテキストハッシュファイル（完全な重複防止用）
POSTED_HASHES_FILE = "data/posted_text_hashes.txt"
RECENT_IDS_FILE = "data/recent_post_ids.txt"


def text_hash(text):
    """テキストのハッシュを返す（重複検出用）"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_posted_hashes():
    """投稿済みテキストハッシュを読み込む"""
    if os.path.exists(POSTED_HASHES_FILE):
        with open(POSTED_HASHES_FILE, "r") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def save_posted_hash(h):
    """投稿済みテキストハッシュを追記"""
    os.makedirs("data", exist_ok=True)
    with open(POSTED_HASHES_FILE, "a") as f:
        f.write(h + "\n")


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

    # 必ず1つはリーチ用タグを追加（ニッチ寄りで競合が少ないもの）
    broad_tags = ["#ライバー", "#ライブ配信", "#配信初心者"]
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


def create_tweet_with_retry(client, **kwargs):
    """リトライ付きツイート投稿。403/重複/レート制限に対応"""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.create_tweet(**kwargs)
            return response
        except tweepy.errors.Forbidden as e:
            last_error = e
            error_detail = str(e)
            print(f"  [WARN] 403 Forbidden (試行 {attempt}/{MAX_RETRIES}): {error_detail}")
            # 重複ツイートエラーの場合はリトライしても無駄
            if "duplicate" in error_detail.lower() or "already" in error_detail.lower():
                print("  → 重複ツイートのためスキップ")
                raise
            if attempt < MAX_RETRIES:
                wait = RETRY_WAIT_SEC * attempt
                print(f"  → {wait}秒後にリトライ...")
                time.sleep(wait)
        except tweepy.errors.TooManyRequests as e:
            last_error = e
            # レート制限: reset時間まで待つ
            reset_time = int(e.response.headers.get("x-rate-limit-reset", 0))
            if reset_time:
                wait = max(reset_time - int(time.time()), 1)
                wait = min(wait, 120)  # 最大2分待つ
            else:
                wait = 60
            print(f"  [WARN] レート制限 (試行 {attempt}/{MAX_RETRIES}): {wait}秒待機")
            if attempt < MAX_RETRIES:
                time.sleep(wait)
        except tweepy.errors.TwitterServerError as e:
            last_error = e
            print(f"  [WARN] サーバーエラー (試行 {attempt}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_WAIT_SEC * attempt)

    raise last_error


def post_thread(client, thread_texts):
    """スレッド（連続ツイート）を投稿"""
    prev_id = None
    tweet_ids = []
    for i, text in enumerate(thread_texts):
        kwargs = {"text": text}
        if prev_id:
            kwargs["in_reply_to_tweet_id"] = prev_id
        resp = create_tweet_with_retry(client, **kwargs)
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
    if not growth_posts:
        print("[ERROR] growth投稿が0件です")
        sys.exit(1)

    # 直近の投稿IDを確認（重複防止）
    recent_ids = set()
    if os.path.exists(RECENT_IDS_FILE):
        with open(RECENT_IDS_FILE, "r") as f:
            recent_ids = set(line.strip() for line in f if line.strip())

    # 投稿済みテキストハッシュ（完全な重複防止）
    posted_hashes = load_posted_hashes()

    # まだ投稿してないものを選ぶ
    available = [p for p in growth_posts if p["id"] not in recent_ids]
    if not available:
        # 全部投稿済み → リセットしてローテーション
        print("[INFO] 全投稿済み → ローテーションリセット")
        recent_ids = set()
        available = growth_posts

    # シャッフルして順に試す（1つ失敗しても別の投稿で再挑戦）
    random.shuffle(available)

    success = False
    for post in available:
        try:
            if "thread" in post:
                # スレッドの最初のツイートにハッシュタグ付与
                thread_texts = list(post["thread"])
                hashtags = pick_hashtags(thread_texts[0])
                thread_texts[0] = append_hashtags(thread_texts[0], hashtags)

                # 最初のツイートが重複していないかチェック
                h = text_hash(thread_texts[0])
                if h in posted_hashes:
                    print(f"[SKIP] テキスト重複: {post['id']}")
                    continue

                tweet_ids = post_thread(client, thread_texts)
                print(f"スレッド投稿成功: {post['id']} ({len(tweet_ids)}件)")
                save_posted_hash(h)
            else:
                # 通常投稿: ハッシュタグを自動付与
                hashtags = pick_hashtags(post["text"])
                text_with_tags = append_hashtags(post["text"], hashtags)

                # テキスト重複チェック
                h = text_hash(text_with_tags)
                if h in posted_hashes:
                    print(f"[SKIP] テキスト重複: {post['id']}")
                    continue

                response = create_tweet_with_retry(client, text=text_with_tags)
                print(f"投稿成功: {post['id']} → {response.data['id']}")
                print(f"  ハッシュタグ: {' '.join(hashtags)}")
                save_posted_hash(h)

            # 投稿済みIDを記録
            recent_ids.add(post["id"])
            os.makedirs("data", exist_ok=True)
            with open(RECENT_IDS_FILE, "w") as f:
                f.write("\n".join(sorted(recent_ids)))

            success = True
            break

        except tweepy.errors.Forbidden as e:
            print(f"[WARN] 投稿 {post['id']} が403エラー: {e}")
            print("  → 別の投稿で再挑戦します")
            continue
        except tweepy.errors.TooManyRequests:
            print("[ERROR] レート制限に達しました。次回の実行まで待機します。")
            # レート制限は全投稿に影響するので、正常終了扱い
            sys.exit(0)
        except tweepy.errors.TwitterServerError as e:
            print(f"[WARN] サーバーエラー: {e} → 別の投稿で再挑戦")
            continue

    if not success:
        print("[ERROR] すべての投稿候補が失敗しました")
        # 投稿ハッシュをリセット（ハッシュタグ違いで再投稿可能にする）
        if os.path.exists(POSTED_HASHES_FILE):
            os.remove(POSTED_HASHES_FILE)
            print("[INFO] テキストハッシュをリセットしました")
        sys.exit(1)

    print("[OK] 投稿完了")


if __name__ == "__main__":
    main()
