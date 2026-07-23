"""
ネイル自動投稿アプリ - 設定ファイル

■ お母さんのネイルサロン用 Instagram 自動投稿システムの設定。
■ 秘密情報（トークン等）は「環境変数」または同じフォルダの .env ファイルに書く。
  → このファイル自体には秘密情報を直書きしない（Git に上がらないように）。

必要なもの（アカウントを作ったら instagram_setup.md の手順で取得）:
  IG_ACCESS_TOKEN     … Instagram Graph API のアクセストークン（長期）
  IG_BUSINESS_ID      … Instagram ビジネスアカウントID（数字）
  GEMINI_API_KEY      … 写真解析＋文章生成に使う Google Gemini のキー
"""

import os

# --- .env を読む（あれば） ---------------------------------------------------
def _load_dotenv():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_dotenv()

# --- Instagram Graph API -----------------------------------------------------
IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
IG_BUSINESS_ID = os.environ.get("IG_BUSINESS_ID", "")
GRAPH_API_VERSION = os.environ.get("GRAPH_API_VERSION", "v21.0")

# --- Gemini（写真解析・文章生成） -------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# --- サロン情報（キャプション・タグに使う） ---------------------------------
SALON_NAME = os.environ.get("SALON_NAME", "")          # 例: "nail salon ○○"
SALON_AREA = os.environ.get("SALON_AREA", "石川県小松市")
SALON_BOOKING_URL = os.environ.get("SALON_BOOKING_URL", "")  # 予約リンク（LINE等・任意）

# --- キャプション本文（固定テンプレート。AIは文章を作らない） -----------------
# お母さんが写真ごとに「メモ」を入れれば、この下に一言だけ追加される。
CAPTION_TEMPLATE = os.environ.get("NAIL_CAPTION_TEMPLATE", "本日のネイル💅")

# --- アプリのログインパスワード（お母さん用・簡易） -------------------------
APP_PASSWORD = os.environ.get("NAIL_APP_PASSWORD", "nail")

# --- 完全自動投稿 ON/OFF -----------------------------------------------------
# True  … 写真を選んだら即投稿（お母さんの希望）
# False … 下書きにして「たいたん」が確認してから投稿
AUTO_POST = os.environ.get("NAIL_AUTO_POST", "true").lower() == "true"


def is_configured():
    """投稿に必要な設定が揃っているか。"""
    return bool(IG_ACCESS_TOKEN and IG_BUSINESS_ID)


def missing_keys():
    miss = []
    if not IG_ACCESS_TOKEN:
        miss.append("IG_ACCESS_TOKEN")
    if not IG_BUSINESS_ID:
        miss.append("IG_BUSINESS_ID")
    if not GEMINI_API_KEY:
        miss.append("GEMINI_API_KEY")
    return miss
