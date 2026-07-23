"""
ネイル自動投稿アプリ（お母さん用）

使い方（お母さん）:
  1. スマホのホーム画面のアイコンを開く
  2. 「写真を選ぶ」でネイル写真を選ぶ
  3. あとは自動。文章とハッシュタグはAIが付けてInstagramに投稿されます。

技術:
  写真 → Gemini解析(vision.py) → ハッシュタグ生成(hashtags.py)
       → Instagram Graph APIで投稿(poster.py)
"""

import datetime
import json
import os
import traceback
import uuid

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

import config
import hashtags as htags
import poster
import vision

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
POSTS_LOG = os.path.join(BASE_DIR, "posts.json")
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}

os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("NAIL_SECRET", "nail-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25MB


# --------------------------------------------------------------------------
# ログ
# --------------------------------------------------------------------------
def load_posts():
    if not os.path.exists(POSTS_LOG):
        return []
    try:
        with open(POSTS_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_posts(posts):
    with open(POSTS_LOG, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def add_log(entry):
    posts = load_posts()
    posts.insert(0, entry)
    save_posts(posts[:200])


# --------------------------------------------------------------------------
# 認証（簡易）
# --------------------------------------------------------------------------
def logged_in():
    return session.get("auth") is True


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == config.APP_PASSWORD:
            session["auth"] = True
            return redirect(url_for("index"))
        return render_template("login.html", error="パスワードが違います")
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------------------
# 画面
# --------------------------------------------------------------------------
@app.route("/")
def index():
    if not logged_in():
        return redirect(url_for("login"))
    return render_template(
        "index.html",
        configured=config.is_configured(),
        auto_post=config.AUTO_POST,
        missing=config.missing_keys(),
        salon=config.SALON_NAME,
        area=config.SALON_AREA,
    )


@app.route("/history")
def history():
    if not logged_in():
        return redirect(url_for("login"))
    return render_template("history.html", posts=load_posts())


# --------------------------------------------------------------------------
# アップロード → 解析 → 投稿
# --------------------------------------------------------------------------
@app.route("/api/post", methods=["POST"])
def api_post():
    if not logged_in():
        return jsonify({"ok": False, "error": "ログインしてください"}), 401

    file = request.files.get("photo")
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "写真が選ばれていません"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"ok": False, "error": "画像ファイルを選んでください"}), 400

    # 保存
    fname = f"{datetime.datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}{ext}"
    fpath = os.path.join(UPLOAD_DIR, fname)
    file.save(fpath)

    ts = datetime.datetime.now().isoformat(timespec="seconds")

    # 1) AI解析
    try:
        result = vision.analyze_nail_image(fpath)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"AI解析に失敗: {e}", "photo": fname}), 500

    if not result.get("is_nail", True):
        return jsonify(
            {
                "ok": False,
                "error": "ネイルの写真ではないようです。もう一度お試しください。",
                "photo": fname,
            }
        ), 400

    # 2) キャプション組み立て（固定テンプレート＋任意メモ。AIは文章を作らない）
    memo = (request.form.get("memo") or "").strip()
    caption = build_caption(result, memo)

    # 3) 投稿 or 下書き
    if not config.AUTO_POST:
        add_log(
            {
                "time": ts,
                "photo": fname,
                "caption": caption,
                "status": "draft",
                "post_id": None,
            }
        )
        return jsonify(
            {"ok": True, "status": "draft", "caption": caption, "photo": fname}
        )

    try:
        post_id = poster.post_photo(fpath, caption)
    except poster.TokenExpiredError as e:
        add_log({"time": ts, "photo": fname, "caption": caption,
                 "status": "token_expired", "post_id": None})
        return jsonify(
            {"ok": False, "error": "Instagram連携の有効期限が切れています（要トークン更新）",
             "detail": str(e), "caption": caption, "photo": fname}
        ), 500
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        add_log({"time": ts, "photo": fname, "caption": caption,
                 "status": "failed", "post_id": None, "error": str(e)})
        return jsonify(
            {"ok": False, "error": f"投稿に失敗: {e}", "caption": caption, "photo": fname}
        ), 500

    add_log({"time": ts, "photo": fname, "caption": caption,
             "status": "posted", "post_id": post_id})
    return jsonify({"ok": True, "status": "posted", "caption": caption,
                    "photo": fname, "post_id": post_id})


def build_caption(result, memo=""):
    """固定テンプレート本文 ＋ 任意メモ ＋ ハッシュタグ を1つのキャプションに。
    AIは文章を作らない（design_tags からハッシュタグだけ生成）。
    """
    tags = htags.build_hashtags(result.get("design_tags", []))
    parts = [config.CAPTION_TEMPLATE.strip()]
    if memo.strip():
        parts.append(memo.strip())
    if config.SALON_NAME:
        parts.append(f"\n📍 {config.SALON_NAME}（{config.SALON_AREA}）")
    else:
        parts.append(f"\n📍 {config.SALON_AREA}")
    if config.SALON_BOOKING_URL:
        parts.append(f"ご予約 → {config.SALON_BOOKING_URL}")
    parts.append("\n" + tags)
    return "\n".join(p for p in parts if p).strip()


# --------------------------------------------------------------------------
# 静的（アップロード画像 / PWA）
# --------------------------------------------------------------------------
@app.route("/uploads/<path:name>")
def uploaded(name):
    return send_from_directory(UPLOAD_DIR, name)


@app.route("/manifest.json")
def manifest():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "manifest.json")


@app.route("/sw.js")
def service_worker():
    return send_from_directory(
        os.path.join(BASE_DIR, "static"), "sw.js", mimetype="application/javascript"
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5055))
    print(f"ネイル自動投稿アプリ起動: http://0.0.0.0:{port}")
    print(f"  設定OK: {config.is_configured()} / 自動投稿: {config.AUTO_POST}")
    if config.missing_keys():
        print(f"  未設定: {', '.join(config.missing_keys())}（.env に入れてください）")
    app.run(host="0.0.0.0", port=port, debug=False)
