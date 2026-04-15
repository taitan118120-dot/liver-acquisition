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


def _verify_image_url(url, timeout=10):
    """アップロードした画像URLが本当にimage/*として配信されるか検証。
    Instagram Graph APIは Content-Type が image/* でないと 9004/2207052 を返す。
    """
    try:
        # HEAD で Content-Type を確認（一部CDNはHEADにContent-Typeを返さないのでGETにフォールバック）
        r = requests.head(url, allow_redirects=True, timeout=timeout)
        ct = r.headers.get("Content-Type", "")
        if not ct or "image" not in ct.lower():
            r = requests.get(url, stream=True, allow_redirects=True, timeout=timeout)
            ct = r.headers.get("Content-Type", "")
            # 先頭数バイトでマジックナンバー確認
            head_bytes = next(r.iter_content(16), b"")
            r.close()
            if head_bytes.startswith(b"\x89PNG") or head_bytes.startswith(b"\xff\xd8\xff") or head_bytes.startswith(b"GIF8"):
                return True
            if "image" in ct.lower():
                return True
            print(f"  [VERIFY] NG: Content-Type={ct!r} head={head_bytes[:8]!r}")
            return False
        return True
    except Exception as e:
        print(f"  [VERIFY] 検証失敗(続行): {e}")
        return True  # 検証自体が失敗したら判断できないので素通り


def upload_image_to_imgbb(image_path, max_retries=3):
    """画像をimgBBにアップロードして公開URLを取得（検証+リトライ付き）"""
    imgbb_key = os.environ.get("IMGBB_API_KEY", "")
    if not imgbb_key:
        print("[WARN] IMGBB_API_KEY が未設定、imgBBはスキップ")
        return None

    import base64
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    for attempt in range(max_retries):
        try:
            response = requests.post(
                "https://api.imgbb.com/1/upload",
                data={
                    "key": imgbb_key,
                    "image": image_data,
                    "expiration": 86400,  # 24時間で自動削除
                },
                timeout=60,
            )
        except requests.exceptions.RequestException as e:
            print(f"  [RETRY] imgBBリクエスト失敗: {e} ({attempt + 1}/{max_retries})")
            time.sleep(3 * (attempt + 1))
            continue

        if response.status_code != 200:
            print(f"  [RETRY] imgBB HTTP {response.status_code}: {response.text[:200]} ({attempt + 1}/{max_retries})")
            time.sleep(3 * (attempt + 1))
            continue

        try:
            data = response.json().get("data", {})
        except ValueError:
            print(f"  [RETRY] imgBB JSON解析失敗 ({attempt + 1}/{max_retries})")
            time.sleep(3 * (attempt + 1))
            continue

        # imgbb は data.image.url が最も確実な直接画像URL
        url = (
            data.get("image", {}).get("url")
            or data.get("url")
            or data.get("display_url")
        )
        if not url:
            print(f"  [RETRY] imgBBレスポンスからURL取れず ({attempt + 1}/{max_retries})")
            time.sleep(3 * (attempt + 1))
            continue

        # 配信URLが実際に image/* を返すか検証
        if _verify_image_url(url):
            print(f"  imgBBアップロード完了: {url}")
            return url

        print(f"  [RETRY] imgBB URL検証失敗 ({attempt + 1}/{max_retries}): {url}")
        time.sleep(3 * (attempt + 1))

    print("[WARN] imgBBアップロードが全て失敗または検証NG")
    return None


def upload_image_to_catbox(image_path, max_retries=2):
    """catbox.moe にアップロード（imgBBのフォールバック）。
    匿名で使える永続ホスティング。Instagram Graph APIが受け付けるCDN。
    """
    for attempt in range(max_retries):
        try:
            with open(image_path, "rb") as f:
                response = requests.post(
                    "https://catbox.moe/user/api.php",
                    data={"reqtype": "fileupload"},
                    files={"fileToUpload": f},
                    timeout=60,
                )
        except requests.exceptions.RequestException as e:
            print(f"  [RETRY] catbox失敗: {e} ({attempt + 1}/{max_retries})")
            time.sleep(3 * (attempt + 1))
            continue

        if response.status_code == 200 and response.text.startswith("https://"):
            url = response.text.strip()
            if _verify_image_url(url):
                print(f"  catboxアップロード完了: {url}")
                return url
            print(f"  [RETRY] catbox URL検証失敗: {url}")
        else:
            print(f"  [RETRY] catbox HTTP {response.status_code}: {response.text[:200]}")
        time.sleep(3 * (attempt + 1))

    print("[WARN] catboxアップロードが全て失敗")
    return None


def upload_image_to_github_raw(image_path):
    """GitHub raw URL を使う（リポジトリが public の場合のみ）。
    画像が既に main ブランチに push されている必要がある。
    """
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        return None
    # image_path をリポジトリ相対パスに正規化
    try:
        repo_root = PROJECT_ROOT
        rel_path = os.path.relpath(image_path, repo_root).replace(os.sep, "/")
    except Exception:
        return None
    if rel_path.startswith(".."):
        return None
    url = f"https://raw.githubusercontent.com/{repo}/main/{rel_path}"
    if _verify_image_url(url):
        print(f"  GitHub raw URLで配信: {url}")
        return url
    return None


def upload_image_public(image_path):
    """複数経路で画像をパブリックにアップロード（多層防御）。
    順番: imgBB → catbox → GitHub raw
    """
    url = upload_image_to_imgbb(image_path)
    if url:
        return url
    print("[FALLBACK] imgBB失敗 → catbox.moe を試行")
    url = upload_image_to_catbox(image_path)
    if url:
        return url
    print("[FALLBACK] catbox失敗 → GitHub raw URL を試行")
    url = upload_image_to_github_raw(image_path)
    if url:
        return url
    return None


class TokenExpiredError(Exception):
    """アクセストークン期限切れ（永続エラー）"""
    pass


class PermanentMediaError(Exception):
    """画像URLがInstagramに受け付けられない永続エラー（別URLでリトライ推奨）"""
    pass


def create_media_container(image_url, caption, max_retries=3):
    """Instagram Graph APIでメディアコンテナを作成（リトライ付き）。
    TokenExpiredError: トークン期限切れ時に送出。
    PermanentMediaError: 画像URL起因の永続エラー時に送出（別URLで再試行を促す）。
    """
    url = f"{GRAPH_API_BASE}/{config.INSTAGRAM_BUSINESS_ID}/media"
    payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": config.INSTAGRAM_ACCESS_TOKEN,
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(url, data=payload, timeout=60)
            data = response.json()
        except requests.exceptions.Timeout:
            print(f"  [RETRY] リクエストタイムアウト ({attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            return None
        except requests.exceptions.RequestException as e:
            print(f"  [RETRY] リクエストエラー: {e} ({attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            return None

        if "id" in data:
            print(f"  メディアコンテナ作成: {data['id']}")
            return data["id"]

        error = data.get("error", {})
        error_msg = error.get("message", str(data))
        error_code = error.get("code", "N/A")
        error_subcode = error.get("error_subcode", "N/A")

        # トークン期限切れは即座にraiseしてリトライしない
        if error_code == 190:
            print(f"[ERROR] トークン期限切れ (code={error_code}, subcode={error_subcode}): {error_msg}")
            raise TokenExpiredError(error_msg)

        # 画像URL起因の永続エラー（9004系）はリトライ無意味、別URLで再試行を促す
        # 2207052: Only photo or video can be accepted as media type
        # 2207003: The image is too small/large or invalid format
        # 2207026: The image cannot be downloaded
        if error_code == 9004 or error_subcode in (2207052, 2207003, 2207026) \
                or "only photo or video" in error_msg.lower() \
                or "cannot be downloaded" in error_msg.lower() \
                or "invalid image" in error_msg.lower():
            print(f"[PERMANENT] 画像URL拒否 (code={error_code}, subcode={error_subcode}): {error_msg}")
            raise PermanentMediaError(f"code={error_code}/subcode={error_subcode}: {error_msg}")

        # タイムアウト系エラーはリトライ（code=-2はGraph APIのタイムアウト）
        if error_code in (-2, 2) or "timeout" in error_msg.lower():
            print(f"  [RETRY] タイムアウト ({attempt + 1}/{max_retries}): {error_msg}")
            if attempt < max_retries - 1:
                time.sleep(10 * (attempt + 1))
                continue

        print(f"[ERROR] コンテナ作成失敗 (code={error_code}, subcode={error_subcode}): {error_msg}")
        return None

    return None


def publish_media(container_id, max_retries=3):
    """メディアコンテナを公開（実際の投稿、リトライ付き）"""
    url = f"{GRAPH_API_BASE}/{config.INSTAGRAM_BUSINESS_ID}/media_publish"
    payload = {
        "creation_id": container_id,
        "access_token": config.INSTAGRAM_ACCESS_TOKEN,
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(url, data=payload, timeout=60)
            data = response.json()
        except requests.exceptions.RequestException as e:
            print(f"  [RETRY] 公開リクエストエラー: {e} ({attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            return None

        if "id" in data:
            print(f"  投稿公開成功: {data['id']}")
            return data["id"]

        error = data.get("error", {})
        error_msg = error.get("message", str(data))
        error_code = error.get("code", "N/A")

        if error_code in (-2, 2) or "timeout" in error_msg.lower():
            print(f"  [RETRY] 公開タイムアウト ({attempt + 1}/{max_retries}): {error_msg}")
            if attempt < max_retries - 1:
                time.sleep(10 * (attempt + 1))
                continue

        print(f"[ERROR] 投稿公開失敗 (code={error_code}): {error_msg}")
        return None

    return None


def check_container_status(container_id):
    """コンテナのステータスを確認（処理完了を待つ）"""
    url = f"{GRAPH_API_BASE}/{container_id}"
    params = {
        "fields": "status_code",
        "access_token": config.INSTAGRAM_ACCESS_TOKEN,
    }

    for attempt in range(10):
        response = requests.get(url, params=params, timeout=30)
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
    """Instagram Graph APIでフィード投稿を実行。(success, error_msg, is_transient) を返す。
    is_transient=True: タイムアウト等の一時エラー（リトライ価値あり）
    is_transient=False: トークン切れ等の永続エラー（設定修正が必要）
    """
    if dry_run:
        print(f"[DRY RUN] Instagram投稿:")
        print(f"  画像: {image_path}")
        print(f"  キャプション: {caption[:100]}...")
        return True, None, False

    if not config.INSTAGRAM_ACCESS_TOKEN:
        msg = "INSTAGRAM_ACCESS_TOKEN が未設定（環境変数を確認してください）"
        print(f"[ERROR] {msg}")
        return False, msg, False

    if not config.INSTAGRAM_BUSINESS_ID:
        msg = "INSTAGRAM_BUSINESS_ID が未設定（環境変数を確認してください）"
        print(f"[ERROR] {msg}")
        return False, msg, False

    print(f"  トークン先頭: {config.INSTAGRAM_ACCESS_TOKEN[:10]}...")
    print(f"  ビジネスID: {config.INSTAGRAM_BUSINESS_ID}")

    # 画像URLは複数経路で最大 MAX_URL_ATTEMPTS 回まで試す
    # 1回目: imgBB(検証付き) / 失敗→ catbox / 失敗→ GitHub raw
    # Instagram側がcode=9004を返したら、次の経路で再アップロードして再挑戦
    MAX_URL_ATTEMPTS = 3
    used_urls = set()
    last_perm_error = None

    for url_attempt in range(MAX_URL_ATTEMPTS):
        image_url = upload_image_public(image_path)
        if not image_url:
            return False, "全ての画像ホスティングが失敗", True  # 一時扱い（次回実行で再試行）
        if image_url in used_urls:
            # 同じURLしか取れない=試行しても同じ結果、別経路強制
            # upload_image_public内で既にフォールバック試行済みなので諦める
            break
        used_urls.add(image_url)

        # 2. メディアコンテナを作成
        try:
            container_id = create_media_container(image_url, caption)
        except TokenExpiredError as e:
            return False, f"トークン期限切れ: {e}", False  # 永続エラー
        except PermanentMediaError as e:
            last_perm_error = str(e)
            print(f"[RETRY] 画像URL拒否 → 別ホスティング経路で再試行 ({url_attempt + 1}/{MAX_URL_ATTEMPTS})")
            # 次のループで別経路を試す（imgBB→catbox→raw の順に degraded）
            continue

        if not container_id:
            return False, "Instagramメディアコンテナ作成失敗", True  # タイムアウト系

        # 3. コンテナの処理完了を待つ
        if not check_container_status(container_id):
            return False, "コンテナ処理タイムアウトまたはエラー", True

        # 4. 公開
        post_id = publish_media(container_id)
        if post_id:
            return True, None, False
        return False, "Instagram投稿公開失敗", True

    # 全URL経路で永続エラー → 画像自体が invalid の可能性が高い
    return False, f"画像URLが全経路で拒否: {last_perm_error}", False  # 永続エラー扱い


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

    success, error_msg, _ = post_to_instagram(image_path, target["caption"], dry_run=dry_run)
    log_post(post_id, target["caption"], success)

    if success and not dry_run:
        target["posted"] = True
        save_posts(posts)

    return success


MAX_RETRY = 5  # 永続エラーのみカウント（一時エラーはカウントしない）


def post_next(dry_run=False):
    """未投稿の次のコンテンツを投稿。(success, is_transient) を返す。
    is_transient: 一時エラーかどうか（スケジューラのリトライ判断に使う）

    永続エラー発生時はキュー内の次の未投稿を自動で試す（最大3件まで）。
    これにより1つの壊れた投稿がキュー全体をブロックしない。
    """
    MAX_POST_CANDIDATES = 3  # 1回の実行で試す最大投稿数

    last_is_transient = False
    for candidate_idx in range(MAX_POST_CANDIDATES):
        posts = load_posts()
        unposted = [
            p for p in posts
            if not p["posted"] and p.get("image_path") and p.get("fail_count", 0) < MAX_RETRY
        ]

        if not unposted:
            if candidate_idx == 0:
                print("[INFO] 投稿可能なコンテンツがありません。")
            else:
                print(f"[INFO] {candidate_idx}件試行したが投稿可能なコンテンツ切れ")
            return False, last_is_transient

        target = unposted[0]
        print(f"次の投稿: {target['title']} (永続エラー{target.get('fail_count', 0)}回)")

        resolved_path = _resolve_image_path(target["image_path"])
        if not resolved_path or not os.path.exists(resolved_path):
            error_msg = f"画像ファイルが見つかりません: {target['image_path']}"
            print(f"[ERROR] {error_msg}")
            target["fail_count"] = MAX_RETRY  # 即スキップ扱い
            target["last_error"] = error_msg
            save_posts(posts)
            continue  # 次の候補へ

        success, error_msg, is_transient = post_to_instagram(
            resolved_path, target["caption"], dry_run=dry_run
        )
        if not dry_run:
            log_post(target["id"], target["caption"], success)
        last_is_transient = is_transient

        if success and not dry_run:
            target["posted"] = True
            target["posted_at"] = datetime.now().astimezone().isoformat()
            target.pop("fail_count", None)
            target.pop("last_error", None)
            save_posts(posts)
            return True, False

        if not dry_run:
            if is_transient:
                # 一時エラーはfail_countを増やさない（次回リトライ可能）
                target["last_error"] = f"[一時] {error_msg or '不明'}"
                print(f"[TRANSIENT] 一時エラー（fail_count据え置き）: {error_msg}")
                save_posts(posts)
                # 一時エラーは同じ投稿でまた試すべきなので即return
                return False, True
            else:
                # 永続エラー → fail_count を増やし、次の候補を試す
                target["fail_count"] = target.get("fail_count", 0) + 1
                target["last_error"] = error_msg or "不明なエラー"
                print(f"[PERMANENT] 永続エラー ({target['fail_count']}/{MAX_RETRY}回): {error_msg}")
                if target["fail_count"] >= MAX_RETRY:
                    print(f"[SKIP] {target['id']} は{MAX_RETRY}回永続エラーのため、以降スキップ。")
                save_posts(posts)
                print(f"[FALLBACK] 次の未投稿候補を試行します ({candidate_idx + 1}/{MAX_POST_CANDIDATES})")
                continue
        else:
            return False, is_transient

    print(f"[WARNING] {MAX_POST_CANDIDATES}件の候補全てで永続エラー")
    return False, False


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
