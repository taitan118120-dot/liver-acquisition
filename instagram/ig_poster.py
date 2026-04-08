"""
Instagram Graph API 投稿モジュール

Instagram Graph APIを使ってフィード投稿を行う。
画像はimgBBにアップロードして公開URLを取得し、Graph APIに渡す。

使い方:
  python ig_poster.py --post <post_id>    # 指定IDの投稿を実行
  python ig_poster.py --dry-run <post_id> # 投稿内容を確認
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
POSTS_FILE = os.path.join(SCRIPT_DIR, "ig_posts.json")
POST_LOG_CSV = os.path.join(PROJECT_ROOT, "data", "ig_post_log.csv")


def _resolve_image_path(image_path):
    """画像パスを解決（相対パスならプロジェクトルートからの相対パスとして処理）"""
    if not image_path:
        return None
    if os.path.isabs(image_path):
        return image_path
    # 相対パスならプロジェクトルートから解決
    resolved = os.path.join(PROJECT_ROOT, image_path)
    if os.path.exists(resolved):
        return resolved
    # スクリプトディレクトリからも試す
    resolved2 = os.path.join(SCRIPT_DIR, os.path.basename(image_path))
    if os.path.exists(resolved2):
        return resolved2
    return os.path.join(PROJECT_ROOT, image_path)


def upload_image_to_imgbb(image_path):
    """画像をimgBBにアップロードして公開URLを取得"""
    imgbb_key = os.environ.get("IMGBB_API_KEY", "")
    if not imgbb_key:
        print("[ERROR] IMGBB_API_KEY が設定されていません。")
        print("  https://api.imgbb.com/ で無料APIキーを取得してください。")
        return None

    with open(image_path, "rb") as f:
        import base64
        image_data = base64.b64encode(f.read()).decode("utf-8")

    response = requests.post(
        "https://api.imgbb.com/1/upload",
        data={
            "key": imgbb_key,
            "image": image_data,
            "expiration": 86400,  # 24時間で自動削除
        },
    )

    if response.status_code == 200:
        url = response.json()["data"]["url"]
        print(f"  画像アップロード完了: {url}")
        return url

    print(f"[ERROR] imgBBアップロード失敗: {response.text}")
    return None


def create_media_container(image_url, caption):
    """Instagram Graph APIでメディアコンテナを作成"""
    url = f"{GRAPH_API_BASE}/{config.INSTAGRAM_BUSINESS_ID}/media"
    params = {
        "image_url": image_url,
        "caption": caption,
        "access_token": config.INSTAGRAM_ACCESS_TOKEN,
    }

    response = requests.post(url, params=params)
    data = response.json()

    if "id" in data:
        print(f"  メディアコンテナ作成: {data['id']}")
        return data["id"]

    print(f"[ERROR] コンテナ作成失敗: {data}")
    return None


def publish_media(container_id):
    """メディアコンテナを公開（実際の投稿）"""
    url = f"{GRAPH_API_BASE}/{config.INSTAGRAM_BUSINESS_ID}/media_publish"
    params = {
        "creation_id": container_id,
        "access_token": config.INSTAGRAM_ACCESS_TOKEN,
    }

    response = requests.post(url, params=params)
    data = response.json()

    if "id" in data:
        print(f"  投稿公開成功: {data['id']}")
        return data["id"]

    print(f"[ERROR] 投稿公開失敗: {data}")
    return None


def check_container_status(container_id):
    """コンテナのステータスを確認（処理完了を待つ）"""
    url = f"{GRAPH_API_BASE}/{container_id}"
    params = {
        "fields": "status_code",
        "access_token": config.INSTAGRAM_ACCESS_TOKEN,
    }

    for attempt in range(10):
        response = requests.get(url, params=params)
        data = response.json()
        status = data.get("status_code", "UNKNOWN")

        if status == "FINISHED":
            return True
        elif status == "ERROR":
            print(f"[ERROR] コンテナ処理エラー: {data}")
            return False

        print(f"  コンテナ処理中... ({status}) リトライ {attempt + 1}/10")
        time.sleep(3)

    print("[ERROR] コンテナ処理タイムアウト")
    return False


def post_to_instagram(image_path, caption, dry_run=False):
    """Instagram Graph APIでフィード投稿を実行。(success, error_msg) を返す。"""
    if dry_run:
        print(f"[DRY RUN] Instagram投稿:")
        print(f"  画像: {image_path}")
        print(f"  キャプション: {caption[:100]}...")
        return True, None

    if not config.INSTAGRAM_ACCESS_TOKEN or not config.INSTAGRAM_BUSINESS_ID:
        msg = "INSTAGRAM_ACCESS_TOKEN または INSTAGRAM_BUSINESS_ID が未設定"
        print(f"[ERROR] {msg}")
        return False, msg

    # 1. 画像を公開URLにアップロード
    image_url = upload_image_to_imgbb(image_path)
    if not image_url:
        return False, "imgBBへの画像アップロード失敗"

    # 2. メディアコンテナを作成
    container_id = create_media_container(image_url, caption)
    if not container_id:
        return False, "Instagramメディアコンテナ作成失敗"

    # 3. コンテナの処理完了を待つ
    if not check_container_status(container_id):
        return False, "コンテナ処理タイムアウトまたはエラー"

    # 4. 公開
    post_id = publish_media(container_id)
    if post_id:
        return True, None
    return False, "Instagram投稿公開失敗"


def log_post(post_id, caption, success):
    """投稿ログを記録"""
    os.makedirs(os.path.dirname(POST_LOG_CSV), exist_ok=True)

    write_header = not os.path.exists(POST_LOG_CSV)
    with open(POST_LOG_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["timestamp", "post_id", "success", "caption_preview"])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            post_id,
            success,
            caption[:100].replace("\n", " "),
        ])


def load_posts():
    """投稿キューを読み込み"""
    if not os.path.exists(POSTS_FILE):
        return []
    with open(POSTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_posts(posts):
    """投稿キューを保存"""
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def post_by_id(post_id, dry_run=False):
    """指定IDの投稿を実行"""
    posts = load_posts()
    target = next((p for p in posts if p["id"] == post_id), None)

    if not target:
        print(f"[ERROR] 投稿ID '{post_id}' が見つかりません。")
        return False

    if target["posted"] and not dry_run:
        print(f"[SKIP] {post_id} は投稿済みです。")
        return False

    print(f"投稿: {target['title']}")

    image_path = _resolve_image_path(target.get("image_path"))
    if not image_path or not os.path.exists(image_path):
        print(f"[ERROR] 画像ファイルが見つかりません: {target.get('image_path')}")
        return False

    success, error_msg = post_to_instagram(image_path, target["caption"], dry_run=dry_run)
    log_post(post_id, target["caption"], success)

    if success and not dry_run:
        target["posted"] = True
        save_posts(posts)

    return success


MAX_RETRY = 3  # この回数失敗したらスキップ


def post_next(dry_run=False):
    """未投稿の次のコンテンツを投稿（失敗回数が上限に達したものはスキップ）"""
    posts = load_posts()
    unposted = [
        p for p in posts
        if not p["posted"] and p.get("image_path") and p.get("fail_count", 0) < MAX_RETRY
    ]

    if not unposted:
        print("[INFO] 投稿可能なコンテンツがありません。")
        return False

    target = unposted[0]
    print(f"次の投稿: {target['title']} (失敗{target.get('fail_count', 0)}回目)")

    resolved_path = _resolve_image_path(target["image_path"])
    if not resolved_path or not os.path.exists(resolved_path):
        error_msg = f"画像ファイルが見つかりません: {target['image_path']}"
        print(f"[ERROR] {error_msg}")
        target["fail_count"] = target.get("fail_count", 0) + 1
        target["last_error"] = error_msg
        save_posts(posts)
        return False

    success, error_msg = post_to_instagram(resolved_path, target["caption"], dry_run=dry_run)
    if not dry_run:
        log_post(target["id"], target["caption"], success)

    if success and not dry_run:
        target["posted"] = True
        target.pop("fail_count", None)
        target.pop("last_error", None)
        save_posts(posts)
    elif not success and not dry_run:
        target["fail_count"] = target.get("fail_count", 0) + 1
        target["last_error"] = error_msg or "不明なエラー"
        save_posts(posts)
        print(f"[WARNING] 投稿失敗 ({target['fail_count']}/{MAX_RETRY}回): {error_msg}")
        if target["fail_count"] >= MAX_RETRY:
            print(f"[SKIP] {target['id']} は{MAX_RETRY}回失敗したため、以降スキップします。")

    return success


def main():
    parser = argparse.ArgumentParser(description="Instagram Graph API投稿")
    parser.add_argument("--post", metavar="POST_ID", help="指定IDの投稿を実行")
    parser.add_argument("--next", action="store_true", help="次の未投稿コンテンツを投稿")
    parser.add_argument("--dry-run", action="store_true", help="投稿せずに確認")
    args = parser.parse_args()

    if args.post:
        post_by_id(args.post, dry_run=args.dry_run)
    elif args.next:
        post_next(dry_run=args.dry_run)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
