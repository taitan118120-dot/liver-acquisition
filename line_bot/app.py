"""
TAITAN PRO LINE Bot - Webhookサーバー
ステップ配信 + キーワード自動応答 + リッチメニュー

デプロイ: Render / Railway（無料枠）
"""

import os
import json
import hashlib
import hmac
import base64
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from config import LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, STEP_DELAYS
from messages import STEP_MESSAGES, AUTO_REPLIES, DEFAULT_REPLY

# --- データ保存 ---
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
LOG_FILE = os.path.join(DATA_DIR, "message_log.json")

os.makedirs(DATA_DIR, exist_ok=True)


def load_json(path, default=None):
    if default is None:
        default = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def log_message(user_id, direction, text):
    logs = load_json(LOG_FILE, [])
    logs.append({
        "timestamp": datetime.now().isoformat(),
        "user_id": user_id,
        "direction": direction,
        "text": text[:100],
    })
    save_json(LOG_FILE, logs)


# --- LINE API ---
def send_line_message(user_id, text):
    """LINE Messaging APIでプッシュメッセージを送信"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    body = json.dumps({
        "to": user_id,
        "messages": [{"type": "text", "text": text}],
    }).encode("utf-8")

    req = Request(url, data=body, headers=headers, method="POST")
    try:
        urlopen(req)
        log_message(user_id, "send", text)
        print(f"[SEND] {user_id[:8]}... -> {text[:50]}")
    except HTTPError as e:
        print(f"[ERROR] send failed: {e.code} {e.read().decode()}")


def reply_line_message(reply_token, text, user_id="unknown"):
    """LINE Messaging APIでリプライメッセージを送信"""
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    body = json.dumps({
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }).encode("utf-8")

    req = Request(url, data=body, headers=headers, method="POST")
    try:
        urlopen(req)
        log_message(user_id, "send", text)
    except HTTPError as e:
        print(f"[ERROR] reply failed: {e.code} {e.read().decode()}")


# --- ステップ配信（永続化対応）---
SCHEDULE_FILE = os.path.join(DATA_DIR, "step_schedule.json")


def _send_step_if_active(user_id, step_name, text):
    """ステップ送信前にユーザーがまだアクティブか確認"""
    try:
        users = load_json(USERS_FILE)
        user = users.get(user_id, {})
        if user.get("unfollowed"):
            print(f"[STEP] Skipped '{step_name}' for {user_id[:8]}... (unfollowed)")
            _remove_schedule(user_id, step_name)
            return
        send_line_message(user_id, text)
        # step_sent を記録
        if user_id in users:
            sent = users[user_id].get("step_sent", [])
            sent.append(step_name)
            users[user_id]["step_sent"] = sent
            save_json(USERS_FILE, users)
        _remove_schedule(user_id, step_name)
    except Exception as e:
        print(f"[ERROR] Step '{step_name}' failed for {user_id[:8]}...: {e}")


def _remove_schedule(user_id, step_name):
    """送信済みのスケジュールを削除"""
    schedules = load_json(SCHEDULE_FILE, [])
    schedules = [s for s in schedules if not (s["user_id"] == user_id and s["step"] == step_name)]
    save_json(SCHEDULE_FILE, schedules)


def schedule_step_messages(user_id):
    """友だち追加時にステップ配信をスケジュール（永続化対応）"""
    schedules = load_json(SCHEDULE_FILE, [])
    now = datetime.now()

    for step_name, delay in STEP_DELAYS.items():
        if step_name == "welcome":
            continue  # welcomeはfollow eventで即送信
        msg = STEP_MESSAGES.get(step_name)
        if not msg:
            continue

        send_at = (now + timedelta(seconds=delay)).isoformat()
        schedules.append({
            "user_id": user_id,
            "step": step_name,
            "send_at": send_at,
        })

        # Timer もセット（サーバーが落ちなければTimerで送信）
        t = threading.Timer(delay, _send_step_if_active, args=[user_id, step_name, msg["text"]])
        t.daemon = True
        t.start()
        print(f"[STEP] Scheduled '{step_name}' for {user_id[:8]}... at {send_at}")

    save_json(SCHEDULE_FILE, schedules)


def restore_pending_steps():
    """サーバー起動時に未送信のステップ配信を復元"""
    schedules = load_json(SCHEDULE_FILE, [])
    if not schedules:
        return

    now = datetime.now()
    restored = 0
    immediate = 0

    for s in schedules:
        send_at = datetime.fromisoformat(s["send_at"])
        msg = STEP_MESSAGES.get(s["step"])
        if not msg:
            continue

        if send_at <= now:
            # 送信時刻を過ぎている → 即送信
            threading.Thread(
                target=_send_step_if_active,
                args=[s["user_id"], s["step"], msg["text"]],
                daemon=True,
            ).start()
            immediate += 1
        else:
            # まだ先 → Timerで再スケジュール
            delay = (send_at - now).total_seconds()
            t = threading.Timer(delay, _send_step_if_active, args=[s["user_id"], s["step"], msg["text"]])
            t.daemon = True
            t.start()
            restored += 1

    print(f"[STEP] Restored {restored} pending, {immediate} immediate sends")


# --- キーワード応答 ---
def find_auto_reply(text):
    """ユーザーメッセージからキーワードを探して自動返信テキストを返す"""
    text_normalized = text.strip().lower()
    for keyword, reply in AUTO_REPLIES.items():
        if keyword.lower() in text_normalized:
            return reply
    return None


# --- 署名検証 ---
def verify_signature(body, signature):
    """LINE Webhookの署名を検証"""
    hash_value = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(hash_value).decode("utf-8")
    return hmac.compare_digest(expected, signature)


# --- Webhook Handler ---
class WebhookHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        """ヘルスチェック"""
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"TAITAN PRO LINE Bot is running")

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # 署名検証
        signature = self.headers.get("X-Line-Signature", "")
        if not LINE_CHANNEL_SECRET:
            print("[WARN] LINE_CHANNEL_SECRET is not set - signature verification skipped")
        elif not verify_signature(body, signature):
            print("[SECURITY] Invalid signature rejected")
            self.send_response(403)
            self.end_headers()
            return

        # レスポンス先に返す（LINEは200を期待）
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

        # イベント処理
        try:
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return

        for event in data.get("events", []):
            event_type = event.get("type")
            user_id = event.get("source", {}).get("userId", "")
            reply_token = event.get("replyToken", "")

            if event_type == "unfollow":
                # ブロック/友だち解除
                print(f"[UNFOLLOW] User left: {user_id[:8]}...")
                users = load_json(USERS_FILE)
                if user_id in users:
                    users[user_id]["unfollowed"] = True
                    users[user_id]["unfollow_date"] = datetime.now().isoformat()
                    save_json(USERS_FILE, users)
                continue

            elif event_type == "follow":
                # 友だち追加
                print(f"[FOLLOW] New user: {user_id[:8]}...")
                users = load_json(USERS_FILE)
                users[user_id] = {
                    "follow_date": datetime.now().isoformat(),
                    "step_sent": ["welcome"],
                    "unfollowed": False,
                }
                save_json(USERS_FILE, users)

                # Welcome メッセージ即送信
                welcome = STEP_MESSAGES["welcome"]["text"]
                reply_line_message(reply_token, welcome, user_id)
                log_message(user_id, "send", welcome)

                # ステップ配信スケジュール
                schedule_step_messages(user_id)

            elif event_type == "message":
                msg = event.get("message", {})
                if msg.get("type") != "text":
                    continue

                text = msg.get("text", "")
                log_message(user_id, "receive", text)
                print(f"[MSG] {user_id[:8]}...: {text[:50]}")

                # キーワード自動応答
                auto_reply = find_auto_reply(text)
                if auto_reply:
                    reply_line_message(reply_token, auto_reply, user_id)
                else:
                    reply_line_message(reply_token, DEFAULT_REPLY, user_id)

    def log_message(self, format, *args):
        """アクセスログを簡略化"""
        pass


# --- メイン ---
def main():
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("=" * 50)
        print("LINE Bot セットアップガイド")
        print("=" * 50)
        print()
        print("1. LINE Developers (https://developers.line.biz/) にアクセス")
        print("2. プロバイダー作成 → Messaging APIチャネル作成")
        print("3. Channel Secret と Channel Access Token を取得")
        print("4. 環境変数を設定:")
        print("   export LINE_CHANNEL_SECRET='your_secret'")
        print("   export LINE_CHANNEL_ACCESS_TOKEN='your_token'")
        print("5. このスクリプトを再実行")
        print()
        print("Render/Railwayにデプロイする場合は環境変数に設定してください。")
        return

    port = int(os.environ.get("PORT", 8080))

    # 未送信のステップ配信を復元
    restore_pending_steps()

    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    print(f"[START] TAITAN PRO LINE Bot running on port {port}")
    print(f"[INFO] Webhook URL: https://your-domain.com/")
    server.serve_forever()


if __name__ == "__main__":
    main()
