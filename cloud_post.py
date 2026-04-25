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

# Note記事画像のマッピング（投稿テキストにキーワード含まれていれば画像添付）
# blog/images/ 配下のpngファイル名を指定。マッチしない投稿は画像なし → 自動A/B
IMAGES_DIR = "blog/images"
IMAGE_KEYWORD_MAP = [
    # 強い固有語を上に並べる（先に当たったものが採用される）
    ("49_Pocochaダイヤ換金完全ガイド.png", ["ダイヤ", "換金"]),
    ("50_TikTokLIVE収益化完全ガイド.png", ["TikTok", "ティックトック"]),
    ("53_IRIAMVライバー始め方完全ガイド.png", ["IRIAM", "イリアム"]),
    ("52_Pocochaメーター期間完全攻略.png", ["メーター期間", "メーター"]),
    ("18_Pocochaランク上げ方.png", ["ランク上げ", "ランクアップ"]),
    ("48_Pocochaライバー始め方完全ガイド.png", ["Pocochaライバー始", "Pococha始", "ぽこちゃ始"]),
    ("02_Pococha稼げる.png", ["Pococha", "ぽこちゃ"]),
    ("12_ライバー確定申告.png", ["確定申告", "税金"]),
    ("17_ライバー面接対策.png", ["面接"]),
    ("19_ライバー機材おすすめ.png", ["機材", "マイク", "照明"]),
    ("33_ライブ配信アプリ比較.png", ["アプリ比較", "プラットフォーム", "17LIVE", "SHOWROOM"]),
    ("16_ライバー還元率.png", ["還元率"]),
    ("36_ライバーコラボ配信.png", ["コラボ配信", "コラボ"]),
    ("13_ライバーイベント攻略.png", ["イベント攻略", "イベント期間"]),
    ("32_ライバー事務所移籍.png", ["移籍"]),
    ("29_ライバー事務所怪しい見分け方.png", ["怪しい", "詐欺", "見分け方"]),
    ("35_ライバー事務所契約書注意点.png", ["契約書"]),
    ("40_ライバー事務所の仕組み報酬体系完全図解.png", ["報酬体系", "仕組み"]),
    ("27_ライバー事務所おすすめランキング.png", ["事務所ランキング", "事務所おすすめ"]),
    ("08_ライバー事務所フリー比較.png", ["事務所 vs", "フリー", "個人"]),
    ("24_ライバー事務所代理店.png", ["代理店"]),
    ("42_ライバー代理店スカウト術DM返信率.png", ["スカウト", "DM返信"]),
    ("39_ライバー代理店稼げる収入リアル.png", ["代理店稼", "代理店収入"]),
    ("38_ライバー代理店副業始め方ステップ.png", ["代理店副業"]),
    ("43_ライバー事務所開業方法代理店との違い.png", ["開業"]),
    ("03_事務所選び方.png", ["事務所選", "事務所の選"]),
    ("25_ライバーマネージャー.png", ["マネージャー"]),
    ("41_40代50代ライバー始め方.png", ["40代", "50代"]),
    ("22_30代ライバー.png", ["30代"]),
    ("10_大学生ライバー.png", ["大学生"]),
    ("11_主婦ライバー.png", ["主婦", "シングルマザー", "シンママ"]),
    ("15_ライバー男性.png", ["男性ライバー", "男ライバー", "メンズライバー"]),
    ("26_ライバー副業バレない.png", ["副業バレ", "会社にバレ"]),
    ("47_副業月5万在宅.png", ["月5万", "副業月"]),
    ("06_在宅副業おすすめ.png", ["在宅副業", "在宅ワーク"]),
    ("09_顔出しなしライバー.png", ["顔出しなし", "顔出し無し", "顔出し怖"]),
    ("21_ライバー伸びない原因.png", ["伸びない"]),
    ("14_ライバー辞めたい.png", ["辞めたい", "やめたい"]),
    ("31_ライバーメンタルケア.png", ["メンタル", "病む"]),
    ("54_ライブ配信緊張克服メンタル術.png", ["緊張"]),
    ("30_ライバーファン増やし方.png", ["ファン増", "リスナー増"]),
    ("34_ライバー容姿関係ない.png", ["容姿", "ブス", "ブサイク"]),
    ("46_ライバー向いてる人.png", ["向いてる人", "向いてない"]),
    ("45_ライバー時給.png", ["時給"]),
    ("37_ライバー月収平均2026.png", ["月収平均", "平均月収"]),
    ("05_ライバー収入現実.png", ["収入の現実", "収入リアル", "リアルな収入"]),
    ("51_ライバー経費完全リスト75項目.png", ["経費"]),
    ("28_ライバー1日スケジュール.png", ["1日スケジュール", "1日の流れ", "タイムスケジュール"]),
    ("20_ライバー配信ネタ.png", ["配信ネタ", "話すネタ", "何話"]),
    ("44_初配信コツ.png", ["初配信"]),
    ("04_配信初心者コツ.png", ["配信初心者", "配信のコツ"]),
    ("23_ライブ配信市場将来性.png", ["将来性", "市場"]),
    ("07_Pococha時間ダイヤ完全ガイド.png", ["時間ダイヤ"]),
    # 汎用フォールバック（最後）
    ("01_ライバー始め方.png", ["始め方", "始めたい", "ライブ配信始", "配信始め"]),
]


def find_image_for_text(text):
    """投稿テキストにマッチするNote画像のパスを返す。マッチなしならNone"""
    if not os.path.isdir(IMAGES_DIR):
        return None
    for image_file, keywords in IMAGE_KEYWORD_MAP:
        for kw in keywords:
            if kw in text:
                path = os.path.join(IMAGES_DIR, image_file)
                if os.path.exists(path):
                    return path
                break  # マップにあるが画像欠損 → 次のエントリへ
    return None


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


def upload_media(api_v1, image_path):
    """v1.1 API で画像をアップロードし media_id を返す。失敗時は None"""
    try:
        media = api_v1.media_upload(filename=image_path)
        return media.media_id
    except Exception as e:
        print(f"  [WARN] 画像アップロード失敗 ({image_path}): {e}")
        return None


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


def post_thread(client, thread_texts, first_media_id=None):
    """スレッド（連続ツイート）を投稿。先頭ツイートにのみ画像を添付"""
    prev_id = None
    tweet_ids = []
    for i, text in enumerate(thread_texts):
        kwargs = {"text": text}
        if prev_id:
            kwargs["in_reply_to_tweet_id"] = prev_id
        elif first_media_id:
            kwargs["media_ids"] = [first_media_id]
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

    # v1.1 API（media_upload は v2 にないため必須）
    auth_v1 = tweepy.OAuth1UserHandler(
        os.environ["TWITTER_API_KEY"],
        os.environ["TWITTER_API_SECRET"],
        os.environ["TWITTER_ACCESS_TOKEN"],
        os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )
    api_v1 = tweepy.API(auth_v1)

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

                # 画像マッチング（先頭ツイートのテキストで判定）
                image_path = find_image_for_text(thread_texts[0])
                media_id = upload_media(api_v1, image_path) if image_path else None
                if media_id:
                    print(f"  画像添付: {os.path.basename(image_path)}")

                tweet_ids = post_thread(client, thread_texts, first_media_id=media_id)
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

                # 画像マッチング
                image_path = find_image_for_text(post["text"])
                tweet_kwargs = {"text": text_with_tags}
                if image_path:
                    media_id = upload_media(api_v1, image_path)
                    if media_id:
                        tweet_kwargs["media_ids"] = [media_id]
                        print(f"  画像添付: {os.path.basename(image_path)}")

                response = create_tweet_with_retry(client, **tweet_kwargs)
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
