"""
TAITAN PRO LINE Bot - Webhookサーバー
ステップ配信 + キーワード自動応答 + リッチメニュー

デプロイ: Render / Railway（無料枠）
"""

import os
import re
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

from config import LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, STEP_DELAYS, ADMIN_USER_ID
from messages import (
    STEP_MESSAGES, AUTO_REPLIES, DEFAULT_REPLY, SOURCE_THANKS, find_source,
    make_meeting_offer, parse_slot_choice, MEETING_BOOKED, MEETING_NUDGE_INTRO,
)
import state_sync

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
    state_sync.mark_dirty(path)


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


def reply_line_message(reply_token, texts, user_id="unknown"):
    """LINE Messaging APIでリプライメッセージを送信（str または list、最大5通）"""
    if isinstance(texts, str):
        texts = [texts]
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    body = json.dumps({
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": t} for t in texts[:5]],
    }).encode("utf-8")

    req = Request(url, data=body, headers=headers, method="POST")
    try:
        urlopen(req)
        for t in texts:
            log_message(user_id, "send", t)
    except HTTPError as e:
        print(f"[ERROR] reply failed: {e.code} {e.read().decode()}")


def get_display_name(user_id):
    """LINEプロフィールから表示名を取得（失敗時は空文字）"""
    url = f"https://api.line.me/v2/bot/profile/{user_id}"
    req = Request(url, headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"})
    try:
        with urlopen(req) as res:
            return json.loads(res.read().decode("utf-8")).get("displayName", "")
    except Exception:
        return ""


def notify_admin(text):
    """管理者に通知（ADMIN_USER_ID 未設定ならログのみ）"""
    if ADMIN_USER_ID:
        send_line_message(ADMIN_USER_ID, text)
    else:
        print(f"[NOTIFY] (admin未設定) {text[:100]}")


# --- ステップ配信（永続化対応）---
SCHEDULE_FILE = os.path.join(DATA_DIR, "step_schedule.json")


def _send_step_if_active(user_id, step_name, text):
    """ステップ送信前にユーザーがまだアクティブか確認"""
    try:
        users = load_json(USERS_FILE)
        user = users.get(user_id, {})
        if user.get("unfollowed") or user.get("auto_paused") or user.get("meeting_scheduled"):
            reason = "unfollowed" if user.get("unfollowed") else "auto_paused"
            print(f"[STEP] Skipped '{step_name}' for {user_id[:8]}... ({reason})")
            _remove_schedule(user_id, step_name)
            return
        # 面談フローに入った人（日程提示済み）には送らない。
        # 番号選択を通らずチャット手動調整→LINE通話で面談済みになるケースがあり、
        # その場合 auto_paused が立たないまま「その後いかがですか？」が飛んでしまう
        if user.get("meeting_offered") or user.get("awaiting_slot"):
            print(f"[STEP] Skipped '{step_name}' for {user_id[:8]}... (meeting flow)")
            _remove_schedule(user_id, step_name)
            return
        # 直近12時間以内にメッセージをくれた人＝会話が生きている相手にも送らない
        # （担当が手動でやり取り中の可能性が高く、放置者向けの文面が不自然になる）
        last = user.get("last_user_message_at")
        if last:
            try:
                idle = datetime.now() - datetime.fromisoformat(last)
                if idle < timedelta(hours=12):
                    print(f"[STEP] Skipped '{step_name}' for {user_id[:8]}... (recent conversation)")
                    _remove_schedule(user_id, step_name)
                    return
            except ValueError:
                pass
        # 再起動やstate復元で同じスケジュールが蘇っても二重送信しない
        if step_name in user.get("step_sent", []):
            print(f"[STEP] Skipped '{step_name}' for {user_id[:8]}... (already sent)")
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


def cancel_user_steps(user_id):
    """ユーザーの未送信ステップ配信をすべてキャンセル（面談確定時など）"""
    schedules = load_json(SCHEDULE_FILE, [])
    remaining = [s for s in schedules if s["user_id"] != user_id]
    if len(remaining) != len(schedules):
        save_json(SCHEDULE_FILE, remaining)
        print(f"[STEP] Cancelled all pending steps for {user_id[:8]}...")


def schedule_step_messages(user_id):
    """友だち追加時にステップ配信をスケジュール（永続化対応）"""
    schedules = load_json(SCHEDULE_FILE, [])
    # 再follow等での二重スケジュール防止
    schedules = [s for s in schedules if s["user_id"] != user_id]
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


# --- 管理者コマンド ---
def handle_admin_command(text):
    """管理者からのコマンドを処理。コマンドでなければ None（通常処理に流す）"""
    t = text.strip()

    if t in ("一覧", "リスト"):
        users = load_json(USERS_FILE)
        lines = []
        for uid, u in list(users.items())[-15:]:
            if u.get("unfollowed"):
                status = "❌ブロック"
            elif u.get("meeting_scheduled"):
                status = f"📅面談: {u.get('meeting_slot', '?')}"
            elif u.get("auto_paused"):
                status = "⏸手動対応中"
            else:
                status = "🤖自動対応中"
            lines.append(f"{uid[:8]} | {u.get('source', '不明')} | {status}")
        if not lines:
            return "ユーザーはまだいません"
        return "直近のユーザー（先頭8文字 | 流入元 | 状態）:\n" + "\n".join(lines)

    for cmd, pause in (("停止", True), ("再開", False)):
        if t.startswith(cmd):
            prefix = t[len(cmd):].strip()
            if not prefix:
                return f"使い方: {cmd} <ユーザーIDの先頭8文字>\n（「一覧」でID確認できます）"
            users = load_json(USERS_FILE)
            matches = [uid for uid in users if uid.startswith(prefix)]
            if len(matches) != 1:
                return f"該当ユーザーが{len(matches)}件です。「一覧」でIDを確認してください"
            uid = matches[0]
            users[uid]["auto_paused"] = pause
            users[uid]["awaiting_slot"] = False
            save_json(USERS_FILE, users)
            if pause:
                cancel_user_steps(uid)
                return f"✅ {uid[:8]}... への自動送信を停止しました（手動対応モード）"
            return f"✅ {uid[:8]}... への自動送信を再開しました"

    return None


# --- キーワード応答 ---
_URL_RE = re.compile(r"https?://\S+")


def find_auto_reply(text):
    """ユーザーメッセージからキーワードを探して自動返信テキストを返す

    URL部分はキーワード判定から除外する。プロフィールリンクの共有
    （例: pococha.comのURL）は質問ではないので、URL内の文字列に
    反応して解説を送り返さない。
    """
    text_normalized = _URL_RE.sub(" ", text).strip().lower()
    if not text_normalized:
        # メッセージがURLだけ＝リンク共有。自動応答しない
        return None
    for keyword, reply in AUTO_REPLIES.items():
        if keyword.lower() in text_normalized:
            return reply
    return None


def switch_to_manual(user_id, user_data, users, reply_token, text, reason):
    """自動対応をやめて手動対応に切り替える（以降の自動送信を全停止）"""
    user_data["awaiting_slot"] = False
    user_data["auto_paused"] = True
    users[user_id] = user_data
    save_json(USERS_FILE, users)
    cancel_user_steps(user_id)
    reply_line_message(
        reply_token,
        "メッセージありがとうございます！\n"
        "内容を確認して、担当からこのLINEでご連絡しますね😊",
        user_id,
    )
    name = get_display_name(user_id)
    notify_admin(
        f"✋ 手動対応に切り替えました（{reason}）\n"
        f"名前: {name or '(取得失敗)'}\n"
        f"ID: {user_id[:8]}\n"
        f"内容: {text[:200]}\n\n"
        "この人への自動送信は停止済みです。直接返信してください。"
    )


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
        self.wfile.write(b"TAITAN PRO LINE Bot is running (guide-v11-income-up-no-hours-limit)")

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

                # 管理者に即時通知（Botだけが知っているリードを作らない）
                name = get_display_name(user_id)
                notify_admin(
                    "🆕 新しい友だちが追加されました\n"
                    f"名前: {name or '(取得失敗)'}\n"
                    f"ID: {user_id[:8]}\n\n"
                    "welcomeと特典PDFは自動送信済みです。"
                )

            elif event_type == "message":
                msg = event.get("message", {})
                if msg.get("type") != "text":
                    continue

                text = msg.get("text", "")
                log_message(user_id, "receive", text)
                print(f"[MSG] {user_id[:8]}...: {text[:50]}")

                # 管理者コマンド（一覧 / 停止 <ID> / 再開 <ID>）
                if ADMIN_USER_ID and user_id == ADMIN_USER_ID:
                    admin_reply = handle_admin_command(text)
                    if admin_reply:
                        reply_line_message(reply_token, admin_reply, user_id)
                        continue

                users = load_json(USERS_FILE)
                user_data = users.get(user_id, {})

                # followイベント取りこぼしの回収（恒久対策）
                # Render無料枠のコールドスタート等でfollowを受信できなくても、
                # 初回メッセージが来た時点で新規ユーザーとして登録し、ウェルカムを送る。
                # これで「友だち追加されたのにBotが無反応・流入元も取れない」取りこぼしを防ぐ。
                if user_id and user_id != ADMIN_USER_ID and user_id not in users:
                    print(f"[RECOVER] follow未受信ユーザーを初回メッセージで回収: {user_id[:8]}...")
                    user_data = {
                        "follow_date": datetime.now().isoformat(),
                        "step_sent": ["welcome"],
                        "unfollowed": False,
                        "follow_recovered": True,
                    }
                    users[user_id] = user_data
                    save_json(USERS_FILE, users)
                    # ウェルカムはpushで送信（この後の返信でreply_tokenを使うため）
                    send_line_message(user_id, STEP_MESSAGES["welcome"]["text"])
                    schedule_step_messages(user_id)
                    name = get_display_name(user_id)
                    notify_admin(
                        "🆕 新しい友だちを回収しました（follow未受信→初回メッセージで登録）\n"
                        f"名前: {name or '(取得失敗)'}\n"
                        f"ID: {user_id[:8]}\n\n"
                        "welcomeと特典PDFは今送信しました。"
                    )

                # 最終受信時刻を記録（フォローアップの「会話中スキップ」判定に使う）
                if user_id and user_id != ADMIN_USER_ID and user_id in users:
                    user_data["last_user_message_at"] = datetime.now().isoformat()
                    users[user_id] = user_data
                    save_json(USERS_FILE, users)

                # 面談確定後・手動対応中は自動送信しない（担当が直接返信する）
                # meeting_scheduled は auto_paused とセットで立つはずだが、
                # 手動での状態修正等で片方だけになっても止まるよう両方見る
                if user_data.get("auto_paused") or user_data.get("meeting_scheduled"):
                    print(f"[PAUSED] {user_id[:8]}... (手動対応中、自動応答スキップ)")
                    continue

                # 流入元の記録（まだ未記録のユーザーのみ。初回返答を判定）
                if not user_data.get("source"):
                    source = find_source(text)
                    if source:
                        user_data["source"] = source
                        user_data["source_date"] = datetime.now().isoformat()
                        users[user_id] = user_data
                        save_json(USERS_FILE, users)
                        print(f"[SOURCE] {user_id[:8]}... -> {source}")
                        reply_line_message(reply_token, SOURCE_THANKS, user_id)
                        name = get_display_name(user_id)
                        notify_admin(
                            "📍 流入元が分かりました\n"
                            f"名前: {name or '(取得失敗)'}\n"
                            f"ID: {user_id[:8]}\n"
                            f"流入元: {source}"
                        )
                        continue

                # 面談の日程候補への返答待ち
                if user_data.get("awaiting_slot"):
                    slot = parse_slot_choice(text, user_data.get("slot_candidates", []))
                    if slot:
                        user_data["awaiting_slot"] = False
                        user_data["meeting_scheduled"] = True
                        user_data["meeting_slot"] = slot
                        user_data["meeting_date"] = datetime.now().isoformat()
                        user_data["auto_paused"] = True  # 以降の自動送信を全停止
                        users[user_id] = user_data
                        save_json(USERS_FILE, users)
                        cancel_user_steps(user_id)
                        reply_line_message(reply_token, MEETING_BOOKED.format(slot=slot), user_id)
                        name = get_display_name(user_id)
                        notify_admin(
                            "📅 面談希望が入りました！\n"
                            f"名前: {name or '(取得失敗)'}\n"
                            f"ID: {user_id[:8]}\n"
                            f"希望日時: {slot}\n"
                            f"流入元: {user_data.get('source', '不明')}\n\n"
                            "このLINEチャットから確定の連絡をしてください。\n"
                            "（この人への自動送信は停止済みです）"
                        )
                        print(f"[MEETING] {user_id[:8]}... -> {slot}")
                        continue
                    # 日程と判定できない返信は、手動調整の相談や個別の返事。
                    # キーワード応答に流すと文中の「ポコチャ」等の一語に
                    # 解説Botが反応してしまうので、必ず手動対応へ切り替える
                    switch_to_manual(
                        user_id, user_data, users, reply_token, text,
                        "日程候補への自由文返信",
                    )
                    continue

                # 「面談」キーワード → LINE内で日程候補を提示
                if "面談" in text or "めんだん" in text:
                    offer, cands = make_meeting_offer()
                    user_data["awaiting_slot"] = True
                    user_data["slot_candidates"] = cands
                    user_data["meeting_offered"] = True
                    users[user_id] = user_data
                    save_json(USERS_FILE, users)
                    reply_line_message(reply_token, offer, user_id)
                    continue

                # キーワード自動応答
                auto_reply = find_auto_reply(text)
                if auto_reply:
                    count = user_data.get("auto_reply_count", 0) + 1
                    user_data["auto_reply_count"] = count
                    replies = [auto_reply]
                    # 2つ目の質問に答えたタイミングで日程候補も提示（質問だけで離脱させない）
                    if count >= 2 and not user_data.get("meeting_offered"):
                        offer, cands = make_meeting_offer(MEETING_NUDGE_INTRO)
                        user_data["awaiting_slot"] = True
                        user_data["slot_candidates"] = cands
                        user_data["meeting_offered"] = True
                        replies.append(offer)
                    users[user_id] = user_data
                    save_json(USERS_FILE, users)
                    reply_line_message(reply_token, replies, user_id)
                else:
                    # 日程提示後の自由回答（番号でも日時でもキーワードでもない）
                    # → 個別の相談・返事の可能性が高いので自動対応をやめて手動に切り替える
                    if user_data.get("awaiting_slot") or user_data.get("meeting_offered"):
                        switch_to_manual(
                            user_id, user_data, users, reply_token, text,
                            "面談フロー中に自由メッセージ",
                        )
                        continue
                    # DEFAULT_REPLY は初回メッセージ時のみ送信
                    if not user_data.get("default_replied"):
                        reply_line_message(reply_token, DEFAULT_REPLY, user_id)
                        user_data["default_replied"] = True
                        users[user_id] = user_data
                        save_json(USERS_FILE, users)

    def log_message(self, format, *args):
        """アクセスログを簡略化"""
        pass


# --- 自己keepalive ---
# Render無料枠は「外部からのリクエスト」が15分ないとスリープする。
# GitHub Actionsのcron pingは実際には数時間おきにしか走らないことがある（cron遅延）ため、
# プロセス自身が公開URLを定期的に叩いてスリープを防ぐ。
# （自分の公開URL経由のアクセスはRenderのプロキシを通るので、外部リクエストとして扱われる）
# 万一プロセスが落ちて眠っても、Actionsのpingが次に走った時点で起こされ、以後は自走する。
SELF_URL = os.environ.get("SELF_URL", "https://liver-acquisition.onrender.com/")
SELF_PING_INTERVAL = 8 * 60  # 秒。15分のスリープ閾値より十分短く


def start_self_keepalive():
    from urllib.request import urlopen

    def _loop():
        while True:
            time.sleep(SELF_PING_INTERVAL)
            try:
                with urlopen(SELF_URL, timeout=30) as res:
                    res.read(64)
            except Exception as e:
                print(f"[KEEPALIVE] self-ping failed: {e}")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"[KEEPALIVE] self-ping every {SELF_PING_INTERVAL}s -> {SELF_URL}")


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

    # GitHubバックアップから状態を復元してから、同期スレッドを開始
    state_sync.pull_state(DATA_DIR)
    state_sync.start_sync_loop(DATA_DIR)

    # 未送信のステップ配信を復元
    restore_pending_steps()

    # スリープ防止の自己ping
    start_self_keepalive()

    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    print(f"[START] TAITAN PRO LINE Bot running on port {port}")
    print(f"[INFO] Webhook URL: https://your-domain.com/")
    server.serve_forever()


if __name__ == "__main__":
    main()
