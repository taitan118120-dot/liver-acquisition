"""
Instagram Graph API への投稿エンジン（自己完結版）。

手順は Meta 公式の「コンテンツ公開API」に沿う:
  1. 画像を公開URLにする（Graph API は image_url に到達できる必要がある）
  2. メディアコンテナを作成 (/{ig-id}/media)
  3. 公開 (/{ig-id}/media_publish)

非公式ツールは使わない＝BAN対象外の正規ルート。
"""

import time

import requests

import config

GRAPH = "https://graph.facebook.com/" + config.GRAPH_API_VERSION


class TokenExpiredError(Exception):
    """アクセストークン期限切れ。"""


class PostError(Exception):
    """投稿失敗。"""


# ---------------------------------------------------------------------------
# 1) 画像を公開URLにする
# ---------------------------------------------------------------------------
def _verify_url(url, timeout=10):
    try:
        r = requests.get(url, timeout=timeout, stream=True)
        ok = r.status_code == 200 and "image" in r.headers.get("content-type", "")
        r.close()
        return ok
    except Exception:
        return False


def upload_public(image_path):
    """catbox.moe → 0x0.st の順で公開URLを取得。成功したURLを返す。"""
    # catbox.moe（無料・キー不要・恒久保存）
    try:
        with open(image_path, "rb") as f:
            r = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": f},
                timeout=60,
            )
        if r.status_code == 200 and r.text.startswith("http"):
            url = r.text.strip()
            if _verify_url(url):
                return url
    except Exception as e:  # noqa: BLE001
        print(f"  [catbox失敗] {e}")

    # 0x0.st（フォールバック）
    try:
        with open(image_path, "rb") as f:
            r = requests.post(
                "https://0x0.st",
                files={"file": f},
                headers={"User-Agent": "nail-app/1.0"},
                timeout=60,
            )
        if r.status_code == 200 and r.text.strip().startswith("http"):
            url = r.text.strip()
            if _verify_url(url):
                return url
    except Exception as e:  # noqa: BLE001
        print(f"  [0x0失敗] {e}")

    raise PostError("画像の公開アップロードに失敗しました（catbox/0x0 とも不可）")


# ---------------------------------------------------------------------------
# 2) メディアコンテナ作成
# ---------------------------------------------------------------------------
def create_container(image_url, caption):
    url = f"{GRAPH}/{config.IG_BUSINESS_ID}/media"
    payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": config.IG_ACCESS_TOKEN,
    }
    r = requests.post(url, data=payload, timeout=60)
    data = r.json()
    if "id" in data:
        return data["id"]
    err = data.get("error", {})
    _raise_from_error(err, data)


# ---------------------------------------------------------------------------
# 3) 公開
# ---------------------------------------------------------------------------
def publish(container_id):
    # コンテナ処理待ち（画像取得が非同期のことがある）
    _wait_ready(container_id)
    url = f"{GRAPH}/{config.IG_BUSINESS_ID}/media_publish"
    payload = {"creation_id": container_id, "access_token": config.IG_ACCESS_TOKEN}
    r = requests.post(url, data=payload, timeout=60)
    data = r.json()
    if "id" in data:
        return data["id"]
    _raise_from_error(data.get("error", {}), data)


def _wait_ready(container_id, max_wait=60):
    url = f"{GRAPH}/{container_id}"
    waited = 0
    while waited < max_wait:
        r = requests.get(
            url,
            params={"fields": "status_code", "access_token": config.IG_ACCESS_TOKEN},
            timeout=30,
        )
        status = r.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise PostError("メディアコンテナ処理がエラーになりました")
        time.sleep(3)
        waited += 3
    # タイムアウトしても publish を試みる（FINISHED前でも通ることがある）


def _raise_from_error(err, raw):
    code = err.get("code")
    msg = err.get("message", str(raw))
    # 190 = トークン無効/期限切れ, 102 = セッション
    if code in (190, 102) or "access token" in msg.lower():
        raise TokenExpiredError(msg)
    raise PostError(f"[{code}] {msg}")


# ---------------------------------------------------------------------------
# まとめ: 写真パス + キャプション → 投稿
# ---------------------------------------------------------------------------
def post_photo(image_path, caption):
    """成功時は投稿ID(str)を返す。失敗時は例外。"""
    if not config.is_configured():
        raise PostError(
            "Instagramの設定が未完了です（IG_ACCESS_TOKEN / IG_BUSINESS_ID）。"
            " アカウント作成後に nail_app/.env へ入れてください。"
        )
    image_url = upload_public(image_path)
    print(f"  公開URL: {image_url}")
    container_id = create_container(image_url, caption)
    print(f"  コンテナ: {container_id}")
    post_id = publish(container_id)
    print(f"  投稿完了: {post_id}")
    return post_id
