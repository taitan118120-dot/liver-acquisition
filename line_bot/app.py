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

from config import (
    LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, STEP_DELAYS, ADMIN_USER_ID,
    RICH_MENU_ID_AGENCY, STEP_NOT_ON_FOLLOW,
)
from messages import (
    STEP_MESSAGES, AUTO_REPLIES, AGENCY_REPLIES, DEFAULT_REPLY, source_thanks,
    find_source, make_meeting_offer, parse_slot_choice, MEETING_BOOKED,
    find_intent, INTENT_LABELS, INTENT_REPLIES, meeting_intro, step_text,
    slot_reprompt, MANUAL_FOLLOW_REPLY,
)
import rich_menu
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


_agency_rich_menu_id = None


def agency_rich_menu_id(refresh=False):
    """代理店向けリッチメニューのIDを解決する。

    環境変数 RICH_MENU_ID_AGENCY があればそれを使い、無ければ LINE 側の一覧から
    名前で引いて記憶する。環境変数を手で入れなくても動かすための仕掛けで、
    「メニュー作成」で作り直したときは refresh=True で引き直す。
    """
    global _agency_rich_menu_id
    if RICH_MENU_ID_AGENCY:
        return RICH_MENU_ID_AGENCY
    if _agency_rich_menu_id and not refresh:
        return _agency_rich_menu_id
    try:
        _agency_rich_menu_id = rich_menu.find_rich_menu_id("agency")
    except Exception as e:
        print(f"[ERROR] richmenu lookup failed: {e}")
        return None
    return _agency_rich_menu_id


def link_agency_rich_menu(user_id):
    """代理店希望者のリッチメニューを代理店向けに差し替える。

    デフォルト（ライバー向け）は全員に出ているので、ここでリンクした人だけが
    上書きされる。失敗してもデフォルトが出るだけなので会話は止めない。
    """
    menu_id = agency_rich_menu_id()
    if not menu_id:
        print("[RICHMENU] 代理店メニューが未作成のため差し替えをスキップ")
        return False

    url = f"https://api.line.me/v2/bot/user/{user_id}/richmenu/{menu_id}"
    req = Request(url, headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
                  method="POST")
    try:
        urlopen(req)
        print(f"[RICHMENU] {user_id[:8]}... -> agency")
        return True
    except HTTPError as e:
        print(f"[ERROR] richmenu link failed: {e.code} {e.read().decode()}")
        return False
    except Exception as e:
        # メニューの見た目の問題でしかないので、通信断でも返信処理は止めない
        print(f"[ERROR] richmenu link failed: {e}")
        return False


def notify_admin(text):
    """管理者に通知（ADMIN_USER_ID 未設定ならログのみ）"""
    if ADMIN_USER_ID:
        send_line_message(ADMIN_USER_ID, text)
    else:
        print(f"[NOTIFY] (admin未設定) {text[:100]}")


# --- ステップ配信（永続化対応）---
SCHEDULE_FILE = os.path.join(DATA_DIR, "step_schedule.json")

# 日程の聞き直し。他のステップと送信条件が逆で、
# 「面談を打診したのに日程が返ってきていない人」だけに送る。
SLOT_REMINDER_STEP = "slot_reminder"


def _send_step_if_active(user_id, step_name):
    """ステップ送信前にユーザーがまだアクティブか確認

    本文は「送信する直前」に希望の種別（ライバー/代理店）で選び直す。
    スケジュール時点ではまだ種別を聞けていないため、ここで解決しないと
    代理店希望の人にライバー向けのフォローが飛ぶ。
    """
    try:
        users = load_json(USERS_FILE)
        user = users.get(user_id, {})
        if user.get("unfollowed") or user.get("auto_paused") or user.get("meeting_scheduled"):
            reason = "unfollowed" if user.get("unfollowed") else "auto_paused"
            print(f"[STEP] Skipped '{step_name}' for {user_id[:8]}... ({reason})")
            _remove_schedule(user_id, step_name)
            return
        if step_name == SLOT_REMINDER_STEP:
            # 日程の聞き直しは逆に「面談フローに入ったまま止まっている人」が対象。
            # 打診が取り消された（管理者が状態を直した等）なら送らない。
            # 面談確定・auto_paused・ブロックは上の共通ガードで既に弾いている。
            if not user.get("meeting_offered"):
                print(f"[STEP] Skipped '{step_name}' for {user_id[:8]}... (not offered)")
                _remove_schedule(user_id, step_name)
                return
        # 面談フローに入った人（日程提示済み）には送らない。
        # 番号選択を通らずチャット手動調整→LINE通話で面談済みになるケースがあり、
        # その場合 auto_paused が立たないまま「その後いかがですか？」が飛んでしまう
        elif user.get("meeting_offered") or user.get("awaiting_slot"):
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
        text = step_text(step_name, user.get("intent"))
        if not text:
            _remove_schedule(user_id, step_name)
            return
        send_line_message(user_id, text)
        # step_sent を記録
        if user_id in users:
            sent = users[user_id].get("step_sent", [])
            sent.append(step_name)
            users[user_id]["step_sent"] = sent
            if step_name == SLOT_REMINDER_STEP:
                # 聞き直した以上、返ってきた日時をちゃんと拾えるようにしておく
                # （手動対応中の人はここまで来ないので、勝手に自動へは戻らない）
                users[user_id]["awaiting_slot"] = True
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
        if step_name in STEP_NOT_ON_FOLLOW:
            continue  # 起点がfollowではないステップ（面談打診の2日後など）
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
        t = threading.Timer(delay, _send_step_if_active, args=[user_id, step_name])
        t.daemon = True
        t.start()
        print(f"[STEP] Scheduled '{step_name}' for {user_id[:8]}... at {send_at}")

    save_json(SCHEDULE_FILE, schedules)


def schedule_slot_reminder(user_id):
    """面談を打診した時点から2日後に、日程の聞き直しを1回だけ予約する。

    起点が友だち追加ではないので schedule_step_messages とは別立てにしている。
    「面談」と何度送られても、送信済み・予約済みなら積まない（追客は1回だけ）。
    """
    users = load_json(USERS_FILE)
    if SLOT_REMINDER_STEP in users.get(user_id, {}).get("step_sent", []):
        return

    schedules = load_json(SCHEDULE_FILE, [])
    if any(s["user_id"] == user_id and s["step"] == SLOT_REMINDER_STEP for s in schedules):
        return

    delay = STEP_DELAYS[SLOT_REMINDER_STEP]
    send_at = (datetime.now() + timedelta(seconds=delay)).isoformat()
    schedules.append({
        "user_id": user_id,
        "step": SLOT_REMINDER_STEP,
        "send_at": send_at,
    })
    save_json(SCHEDULE_FILE, schedules)

    t = threading.Timer(delay, _send_step_if_active, args=[user_id, SLOT_REMINDER_STEP])
    t.daemon = True
    t.start()
    print(f"[STEP] Scheduled '{SLOT_REMINDER_STEP}' for {user_id[:8]}... at {send_at}")


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
                args=[s["user_id"], s["step"]],
                daemon=True,
            ).start()
            immediate += 1
        else:
            # まだ先 → Timerで再スケジュール
            delay = (send_at - now).total_seconds()
            t = threading.Timer(delay, _send_step_if_active, args=[s["user_id"], s["step"]])
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
            intent = INTENT_LABELS.get(u.get("intent"), "種別不明")
            lines.append(f"{uid[:8]} | {intent} | {u.get('source', '不明')} | {status}")
        if not lines:
            return "ユーザーはまだいません"
        return (
            "直近のユーザー（先頭8文字 | 希望 | 流入元 | 状態）:\n"
            + "\n".join(lines)
        )

    if t in ("メニュー確認", "メニュー状態"):
        # メニューが出ない時の切り分け用。作成済みか／デフォルトになっているか／
        # 画像が乗っているか／自分に何が出るはずか を一度に見る。
        menus = rich_menu.list_rich_menus()
        default_id = rich_menu.get_default_rich_menu()
        lines = [f"📋 リッチメニュー {len(menus)}件"]
        if not menus:
            lines.append("（1件もありません。「メニュー作成」を送ってください）")
        for m in menus:
            mark = "★デフォルト" if m["richMenuId"] == default_id else ""
            img = "画像あり" if rich_menu.has_image(m["richMenuId"]) else "⚠️画像なし＝表示されません"
            lines.append(f"・{m.get('name')} / {len(m.get('areas', []))}枠 / {img} {mark}")
        if menus and not default_id:
            lines.append("\n⚠️ デフォルト未設定です。誰にもメニューが出ません")

        mine = rich_menu.get_user_rich_menu(ADMIN_USER_ID) if ADMIN_USER_ID else None
        lines.append("")
        lines.append(f"自分に出るはずのメニュー: {'個別リンクあり' if mine else 'デフォルト'}")
        lines.append("")
        lines.append(
            "これで全部✅なのに表示されないときは、LINE公式アカウントマネージャー側の"
            "リッチメニュー（ホーム→リッチメニュー）が「表示する」になっていないか確認してください。"
            "そちらが優先され、APIで作ったメニューが隠れます。"
            "アプリの再起動（トーク画面を開き直す）でも直ることがあります。"
        )
        return "\n".join(lines)

    if t in ("メニュー作成", "メニュー更新"):
        # リッチメニューの作り直しをLINEから実行する。
        # 画像はリポジトリにコミット済み（assets/）、トークンは本番の環境変数にあるので、
        # 手元にトークンが無くてもこのコマンドだけで完結する。
        # 新しいメニューを作ってデフォルトに切り替えたあとで旧メニューを消す。
        # 逆順にすると、その隙間だけメニューが消えた状態が見えてしまう。
        old = [m["richMenuId"] for m in rich_menu.list_rich_menus()]
        try:
            created = rich_menu.deploy(["liver", "agency"])
        except Exception as e:
            return f"❌ メニュー作成に失敗しました\n{e}"
        if "liver" not in created or "agency" not in created:
            return (
                "❌ 一部しか作成できませんでした\n"
                f"作成できたもの: {', '.join(created) or 'なし'}\n"
                "Renderのログを確認してください（旧メニューは消していません）"
            )

        deleted = sum(1 for rid in old if rich_menu.delete_rich_menu(rid))
        agency_rich_menu_id(refresh=True)
        return (
            "✅ リッチメニューを作り直しました\n"
            f"ライバー向け（デフォルト）: {created['liver'][-6:]}\n"
            f"代理店向け: {created['agency'][-6:]}\n"
            f"古いメニューの削除: {deleted}/{len(old)}件\n\n"
            "続けて「メニュー同期」を送ると、すでに代理店希望と分かっている人にも反映されます"
        )

    if t in ("メニュー同期", "メニュー"):
        # 代理店メニューを用意する前に intent が付いた人へ後追いで差し替える。
        # 何度打っても差し替え済みは飛ばすので、実行が重複しても害はない。
        if not agency_rich_menu_id(refresh=True):
            return "代理店メニューがまだありません。先に「メニュー作成」を送ってください"
        users = load_json(USERS_FILE)
        done = skipped = failed = 0
        for uid, u in users.items():
            if u.get("intent") != "agency" or u.get("unfollowed"):
                continue
            if u.get("rich_menu") == "agency":
                skipped += 1
                continue
            if link_agency_rich_menu(uid):
                u["rich_menu"] = "agency"
                done += 1
            else:
                failed += 1
        save_json(USERS_FILE, users)
        return (
            "🔄 代理店メニューの差し替え\n"
            f"新たに差し替え: {done}人\n"
            f"すでに済み: {skipped}人\n"
            f"失敗: {failed}人"
        )

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


def find_auto_reply(text, intent=None):
    """ユーザーメッセージからキーワードを探して自動返信テキストを返す

    URL部分はキーワード判定から除外する。プロフィールリンクの共有
    （例: pococha.comのURL）は質問ではないので、URL内の文字列に
    反応して解説を送り返さない。

    代理店希望のユーザーには AGENCY_REPLIES を先に引く。「収入」「始め方」
    「費用」「副業」「事務所」は両方に存在する語なので、先に引かないと
    配信者向けの答えが返ってしまう。該当がなければ共通側にフォールバックする。
    """
    text_normalized = _URL_RE.sub(" ", text).strip().lower()
    if not text_normalized:
        # メッセージがURLだけ＝リンク共有。自動応答しない
        return None
    tables = [AGENCY_REPLIES, AUTO_REPLIES] if intent == "agency" else [AUTO_REPLIES]
    for table in tables:
        for keyword, reply in table.items():
            if keyword.lower() in text_normalized:
                return reply
    return None


def notify_manual_needed(user_id, text, reason):
    """担当の返信が要りそうな内容を管理者に知らせる（自動対応は止めない）

    以前はここで auto_paused を立てて手動対応に切り替えていたが、
    切り替わったことに担当が気づくまで誰も返事をしない時間ができるため廃止した。
    手動に切り替えるのは管理コマンド「停止 <ID先頭8文字>」を送ったときだけ。
    """
    name = get_display_name(user_id)
    notify_admin(
        f"💬 直接の返信が要りそうです（{reason}）\n"
        f"名前: {name or '(取得失敗)'}\n"
        f"ID: {user_id[:8]}\n"
        f"内容: {text[:200]}\n\n"
        "自動対応は続いています。止めるなら「停止 " + user_id[:8] + "」を送ってください。"
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
        self.wfile.write(b"TAITAN PRO LINE Bot is running (v23-slot-reminder)")

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
                    # welcome で希望の種別（ライバー/代理店）を質問済み、の印。
                    # このフラグが無いユーザー（この機能より前からの友だち）には
                    # 種別判定を走らせない＝会話の途中で突然聞き返さない
                    "intent_asked": True,
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
                    "welcomeを送信し、ライバー希望か代理店希望かを質問済みです。\n"
                    "返答が来たら種別に合った特典PDFを自動で送ります。"
                )

            elif event_type == "message":
                msg = event.get("message", {})
                if msg.get("type") != "text":
                    continue

                text = msg.get("text", "")
                log_message(user_id, "receive", text)
                print(f"[MSG] {user_id[:8]}...: {text[:50]}")

                # 管理者コマンド（一覧 / 停止 <ID> / 再開 <ID> / メニュー作成 / メニュー同期）
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
                        "intent_asked": True,
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
                        "welcomeを今送信しました（ライバー希望か代理店希望かを質問中）。"
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

                # 希望の種別（ライバー / 代理店パートナー）の記録。
                # welcome の①②③への返答を判定する。流入元アンケートより必ず先。
                # 判定できなければ聞き返さず通常処理に流す（いきなり質問から入る人がいるため）。
                if user_data.get("intent_asked") and not user_data.get("intent"):
                    intent = find_intent(text)
                    if intent:
                        user_data["intent"] = intent
                        user_data["intent_date"] = datetime.now().isoformat()
                        users[user_id] = user_data
                        save_json(USERS_FILE, users)
                        print(f"[INTENT] {user_id[:8]}... -> {intent}")
                        # 代理店希望者はリッチメニューも代理店向けに差し替える。
                        # 「両方」の人はライバー向け（＝代理店ボタンを含む）のままにする。
                        if intent == "agency":
                            user_data["rich_menu"] = (
                                "agency" if link_agency_rich_menu(user_id) else "liver"
                            )
                            users[user_id] = user_data
                            save_json(USERS_FILE, users)
                        reply_line_message(reply_token, INTENT_REPLIES[intent], user_id)
                        name = get_display_name(user_id)
                        notify_admin(
                            "🙋 希望の種別が分かりました\n"
                            f"名前: {name or '(取得失敗)'}\n"
                            f"ID: {user_id[:8]}\n"
                            f"希望: {INTENT_LABELS[intent]}\n\n"
                            "種別に合わせた特典PDFと案内は自動送信済みです。"
                        )
                        continue

                # 流入元の記録（まだ未記録のユーザーのみ。初回返答を判定）
                if not user_data.get("source"):
                    source = find_source(text)
                    if source:
                        user_data["source"] = source
                        user_data["source_date"] = datetime.now().isoformat()
                        print(f"[SOURCE] {user_id[:8]}... -> {source}")

                        intent = user_data.get("intent")
                        replies = [source_thanks(intent)]
                        # アンケート（種別→流入元）に最後まで答えてくれた直後が一番温度が高い。
                        # ここで打診しないと、案内どおり素直に番号で答えた人ほど
                        # 面談の話を一度もされないまま終わる（2026-08-27 実データで判明。
                        # 26人中オファー到達は7人、うち4人が日程を出していた＝打診不足）。
                        # intent/source の回答は auto_reply_count に入らないため、
                        # 「キーワード2回」の既存トリガーでは永久に発火しない。
                        offered_now = False
                        if not user_data.get("meeting_offered") and not user_data.get("meeting_scheduled"):
                            replies.append(
                                make_meeting_offer(meeting_intro(intent, nudge=True))
                            )
                            user_data["awaiting_slot"] = True
                            user_data["meeting_offered"] = True
                            offered_now = True

                        users[user_id] = user_data
                        save_json(USERS_FILE, users)
                        if offered_now:
                            schedule_slot_reminder(user_id)
                        reply_line_message(reply_token, replies, user_id)
                        name = get_display_name(user_id)
                        notify_admin(
                            "📍 流入元が分かりました\n"
                            f"名前: {name or '(取得失敗)'}\n"
                            f"ID: {user_id[:8]}\n"
                            f"流入元: {source}"
                            + ("\n\n続けてLINE通話の日程を打診しました（返答待ち）。"
                               if offered_now else "")
                        )
                        continue

                # 面談の日程候補への返答待ち
                if user_data.get("awaiting_slot"):
                    slot = parse_slot_choice(text)
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
                            f"希望: {INTENT_LABELS.get(user_data.get('intent'), '種別不明')}\n"
                            f"流入元: {user_data.get('source', '不明')}\n\n"
                            "このLINEチャットから確定の連絡をしてください。\n"
                            "（この人への自動送信は停止済みです）"
                        )
                        print(f"[MEETING] {user_id[:8]}... -> {slot}")
                        continue
                    # 日程と判定できない返信は、手動調整の相談や個別の返事のことが多い。
                    # 管理者には知らせるが、自動対応は止めずにそのまま続ける
                    # （勝手に手動へ切り替えると、担当が気づくまで無反応になるため）。
                    # ただし「収入」等のキーワード質問はBotがそのまま答えられるので通知しない。
                    # （アンケート直後に日程を打診するようになり awaiting_slot の期間が
                    #   長くなったため、これが無いと質問のたびに管理者通知が飛ぶ）
                    if not find_auto_reply(text, user_data.get("intent")):
                        notify_manual_needed(user_id, text, "日程の質問への自由文返信")
                    # → 下のキーワード応答／日程の案内し直しにそのまま流す

                # 「面談」キーワード → LINE内でご希望の日時をうかがう
                if "面談" in text or "めんだん" in text:
                    offer = make_meeting_offer(
                        meeting_intro(user_data.get("intent"))
                    )
                    user_data["awaiting_slot"] = True
                    user_data["meeting_offered"] = True
                    users[user_id] = user_data
                    save_json(USERS_FILE, users)
                    schedule_slot_reminder(user_id)
                    reply_line_message(reply_token, offer, user_id)
                    continue

                # キーワード自動応答
                auto_reply = find_auto_reply(text, user_data.get("intent"))
                if auto_reply:
                    count = user_data.get("auto_reply_count", 0) + 1
                    user_data["auto_reply_count"] = count
                    replies = [auto_reply]
                    # 2つ目の質問に答えたタイミングで日程も打診（質問だけで離脱させない）
                    offered_now = False
                    if count >= 2 and not user_data.get("meeting_offered"):
                        offer = make_meeting_offer(
                            meeting_intro(user_data.get("intent"), nudge=True)
                        )
                        user_data["awaiting_slot"] = True
                        user_data["meeting_offered"] = True
                        replies.append(offer)
                        offered_now = True
                    users[user_id] = user_data
                    save_json(USERS_FILE, users)
                    if offered_now:
                        schedule_slot_reminder(user_id)
                    reply_line_message(reply_token, replies, user_id)
                else:
                    # 日程を聞いたあとの自由回答（日時でもキーワードでもない）
                    # → 個別の相談・返事の可能性が高い。担当に知らせたうえで、
                    #   自動対応は止めずに日程の案内をもう一度だけ添えて返す
                    if user_data.get("awaiting_slot") or user_data.get("meeting_offered"):
                        if not user_data.get("awaiting_slot"):
                            notify_manual_needed(
                                user_id, text, "面談フロー中に自由メッセージ"
                            )
                        count = user_data.get("slot_reprompt_count", 0) + 1
                        user_data["slot_reprompt_count"] = count
                        users[user_id] = user_data
                        save_json(USERS_FILE, users)
                        if count == 1:
                            reply = slot_reprompt()
                        else:
                            reply = MANUAL_FOLLOW_REPLY
                        reply_line_message(reply_token, reply, user_id)
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
