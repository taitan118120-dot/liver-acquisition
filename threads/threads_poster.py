"""
Threads (Meta) 公式API 投稿モジュール

Threads Graph API (https://graph.threads.net) を使って本垢に投稿する。
公式APIなのでBAN対象外。自動フォロー/自動DM/自動いいねは一切やらない
（Pull戦略・コールドDM廃止の方針に従う）。

投稿フローは2段階:
  1) コンテナ作成  POST /{user_id}/threads        -> creation_id
  2) 公開          POST /{user_id}/threads_publish -> media id

使い方:
  python threads/threads_poster.py --next            # キューから次の1本を投稿
  python threads/threads_poster.py --next --dry-run  # 投稿せず内容だけ表示
  python threads/threads_poster.py --text "本文"      # 任意テキストを即投稿
  python threads/threads_poster.py --whoami          # トークンに紐づくアカウント確認

必要な環境変数:
  THREADS_USER_ID       Threadsの数値ユーザーID（/me で取得、SETUP_GUIDE参照）
  THREADS_ACCESS_TOKEN  長期アクセストークン（60日、自動更新可）
"""

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from datetime import datetime

import requests

GRAPH_BASE = "https://graph.threads.net/v1.0"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
POSTS_FILE = os.path.join(SCRIPT_DIR, "threads_posts.json")
LOG_CSV = os.path.join(PROJECT_ROOT, "data", "threads_post_log.csv")

# Threadsの本文上限は500文字
MAX_LEN = 500

# 型の配分は threads_content.py が正本。生成側と投稿側で目標がズレると
# 「storyを多く作ったのにliverばかり出る」が起きるので必ず同じ値を使う。
# 生成側が壊れても投稿は止めたくないので、読めなければ同値でフォールバックする。
try:
    sys.path.insert(0, SCRIPT_DIR)
    from threads_content import TARGET_MIX
except Exception:
    TARGET_MIX = {"story": 0.60, "liver": 0.25, "agency": 0.15}

# 配分を見るときに遡る投稿数。短いと1本ごとに型が振れ、長いと過去の
# liver偏重（2026-08-07以前の在庫）を取り戻そうとして偏り続ける。
MIX_WINDOW = 20


def _token():
    tok = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not tok:
        print("[ERROR] THREADS_ACCESS_TOKEN が未設定です。threads/SETUP_GUIDE.md を参照。")
        sys.exit(2)
    return tok


def _user_id(token):
    uid = os.environ.get("THREADS_USER_ID", "").strip()
    if uid:
        return uid
    # 未設定なら /me から解決
    info = whoami(token, quiet=True)
    if info and info.get("id"):
        return info["id"]
    print("[ERROR] THREADS_USER_ID が未設定で /me からも解決できませんでした。")
    sys.exit(2)


def whoami(token, quiet=False):
    """トークンに紐づくThreadsアカウントを返す。"""
    try:
        r = requests.get(
            f"{GRAPH_BASE}/me",
            params={"fields": "id,username,threads_profile_picture_url", "access_token": token},
            timeout=30,
        )
        data = r.json()
    except requests.RequestException as e:
        if not quiet:
            print(f"[ERROR] /me 取得失敗: {e}")
        return None
    if "id" not in data:
        if not quiet:
            print(f"[ERROR] /me 応答にidなし: {data}")
        return None
    if not quiet:
        print(f"  アカウント: @{data.get('username','?')}  (id={data['id']})")
    return data


def _text_hash(text):
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


def _load_posts():
    if not os.path.exists(POSTS_FILE):
        return []
    with open(POSTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_posts(posts):
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def _already_posted_hashes():
    """ログCSVから投稿済みのtext_hashを集める（重複投稿防止）。"""
    hashes = set()
    if not os.path.exists(LOG_CSV):
        return hashes
    try:
        with open(LOG_CSV, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status") == "ok" and row.get("text_hash"):
                    hashes.add(row["text_hash"])
    except Exception:
        pass
    return hashes


def _log(text_hash, status, media_id, note=""):
    os.makedirs(os.path.dirname(LOG_CSV), exist_ok=True)
    new = not os.path.exists(LOG_CSV)
    with open(LOG_CSV, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "text_hash", "status", "media_id", "note"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), text_hash, status, media_id, note])


def post_text(token, user_id, text, link=None, reply_control="everyone", dry_run=False,
              reply_to_id=None):
    """テキスト投稿（任意でlink_attachmentのリンクプレビュー付き）。
    reply_to_id を渡すとその投稿への返信として出す。
    成功時 media_id を返す。失敗時 None。
    """
    text = (text or "").strip()
    if not text:
        print("[ERROR] 本文が空です")
        return None
    if len(text) > MAX_LEN:
        print(f"[WARN] 本文{len(text)}字 > {MAX_LEN}字。末尾を切り詰めます。")
        text = text[: MAX_LEN - 1] + "…"

    th = _text_hash(text)
    if dry_run:
        print("=== DRY RUN（投稿しません）===")
        print(text)
        if link:
            print(f"[link] {link}")
        if reply_to_id:
            print(f"[reply_to] {reply_to_id}")
        print(f"[reply_control] {reply_control}  [hash] {th}  [len] {len(text)}")
        return "dry-run"

    # 1) コンテナ作成
    params = {
        "media_type": "TEXT",
        "text": text,
        "reply_control": reply_control,
        "access_token": token,
    }
    if link:
        params["link_attachment"] = link
    if reply_to_id:
        params["reply_to_id"] = reply_to_id
    try:
        r = requests.post(f"{GRAPH_BASE}/{user_id}/threads", data=params, timeout=60)
        cdata = r.json()
    except requests.RequestException as e:
        print(f"[ERROR] コンテナ作成リクエスト失敗: {e}")
        _log(th, "error", "", f"create_request:{e}")
        return None
    creation_id = cdata.get("id")
    if not creation_id:
        print(f"[ERROR] コンテナ作成失敗: {cdata}")
        _log(th, "error", "", f"create:{cdata}")
        return None

    # テキスト投稿はほぼ即時だが、推奨どおり少し待つ
    time.sleep(5)

    # 2) 公開
    try:
        r2 = requests.post(
            f"{GRAPH_BASE}/{user_id}/threads_publish",
            data={"creation_id": creation_id, "access_token": token},
            timeout=60,
        )
        pdata = r2.json()
    except requests.RequestException as e:
        print(f"[ERROR] 公開リクエスト失敗: {e}")
        _log(th, "error", "", f"publish_request:{e}")
        return None
    media_id = pdata.get("id")
    if not media_id:
        print(f"[ERROR] 公開失敗: {pdata}")
        _log(th, "error", "", f"publish:{pdata}")
        return None

    print(f"[OK] 投稿完了 media_id={media_id}")
    _log(th, "ok", media_id, "")
    return media_id


def _recent_angles(posts, window=MIX_WINDOW):
    """直近に実際に投稿した型の並び。posted_atがある分は時系列、無い分はキュー順。"""
    done = [p for p in posts if p.get("posted") and p.get("angle")]
    done.sort(key=lambda p: p.get("posted_at") or "")
    return [p["angle"] for p in done[-window:]]


def _pick_by_mix(candidates, posts):
    """TARGET_MIX から最も不足している型を選ぶ。同じ型の中ではキュー順（＝FIFO）。

    以前はキュー全体を素通しのFIFOで消化していた。生成側の配分をstory主体に
    直しても、キューの並び順次第で実際に世に出る比率は別物になる
    （2026-08-10時点の未投稿4本は story2/agency2 で、FIFOだと今後2日の
    半分が平均17viewsのagencyだった）。実際に出る比率をここで担保する。
    """
    by_angle = {}
    for p in candidates:
        by_angle.setdefault(p.get("angle") or "", []).append(p)

    known = {a: v for a, v in by_angle.items() if a in TARGET_MIX}
    if not known:
        return candidates[0]  # angle不明（手動投入など）はFIFOのまま

    recent = _recent_angles(posts)
    total = len(recent) + 1  # これから出す1本を含めた分母で評価する
    # 不足＝目標本数−実績本数。大きいものから出す。
    deficit = {
        a: TARGET_MIX[a] * total - recent.count(a)
        for a in known
    }
    best = max(known, key=lambda a: (deficit[a], TARGET_MIX[a]))
    share = {a: f"{100 * recent.count(a) / len(recent):.0f}%" for a in TARGET_MIX} if recent else {}
    print(f"  [MIX] 直近{len(recent)}本の型配分 {share} → 今回は {best}"
          f"（不足 {deficit[best]:+.1f}本）")
    return known[best][0]


def cmd_next(dry_run=False, require_reply_link=False):
    """キュー(threads_posts.json)から未投稿を1本投稿する。

    先頭から順ではなく、TARGET_MIX に対していちばん不足している型を選ぶ。
    実測で story 245views / liver 38 / agency 17 と8倍以上の差があるので、
    「何を出すか」ではなく「どの型を出すか」が伸びの主因になる。

    require_reply_link=True のときは reply_link を持つ投稿だけを対象にする。
    CTA返信(reply_to_id)の動作確認を、通常の順番待ちをせずに1本試すための入口。
    """
    token = _token()
    user_id = _user_id(token)
    posts = _load_posts()
    if not posts:
        print("[INFO] キューが空です。threads/threads_content.py で生成するか手動で追加してください。")
        return 0

    done = _already_posted_hashes()
    candidates = []
    for p in posts:
        text = p.get("text", "")
        if not text:
            continue
        if p.get("posted"):
            continue
        if _text_hash(text) in done:
            p["posted"] = True  # ログ上は投稿済み、フラグを同期
            continue
        if require_reply_link and not (p.get("reply_link") or "").strip():
            continue
        candidates.append(p)

    target = _pick_by_mix(candidates, posts) if candidates else None

    if target is None:
        if require_reply_link:
            print("[INFO] reply_link付きの未投稿キューがありません。")
        else:
            print("[INFO] 未投稿のキューがありません。")
        _save_posts(posts)
        return 0

    media_id = post_text(
        token,
        user_id,
        target["text"],
        link=target.get("link"),
        reply_control=target.get("reply_control", "everyone"),
        dry_run=dry_run,
    )
    if dry_run:
        _post_link_reply(token, user_id, target, media_id, dry_run=True)
        return 0
    if media_id:
        target["posted"] = True
        target["posted_at"] = datetime.now().isoformat(timespec="seconds")
        target["media_id"] = media_id
        _save_posts(posts)
        _post_link_reply(token, user_id, target, media_id)
        _save_posts(posts)
        return 0
    return 1


def _post_link_reply(token, user_id, target, media_id, dry_run=False):
    """CTAリンクを本文ではなく自分への1件目の返信として出す。

    本文にlink_attachmentを付けた投稿はリーチが半分以下になる（data/threads_insights.csv
    の実測: リンクあり中央値10views / なし25.5）。リンクを返信に逃がせば
    本投稿のリーチを落とさずに導線を残せる。
    """
    reply_text = (target.get("reply_text") or "").strip()
    reply_link = (target.get("reply_link") or "").strip()
    if not reply_link or not reply_text:
        if not dry_run:
            return
        print("  [INFO] reply_link/reply_text なし → CTA返信は出ません")
        return
    print("  → CTAを返信として投稿")
    if not dry_run:
        time.sleep(5)
    rid = post_text(
        token, user_id, reply_text, link=reply_link,
        reply_control=target.get("reply_control", "everyone"),
        reply_to_id=media_id,
        dry_run=dry_run,
    )
    if rid:
        target["reply_media_id"] = rid
        print(f"  [OK] CTA返信 reply_media_id={rid}")
    else:
        # 本投稿は成功しているのでジョブ自体は失敗させないが、原因のAPI応答は
        # 直前の post_text が [ERROR] 行にJSONごと出しているのでログを見ること
        print("  [REPLY-FAILED] CTA返信の投稿に失敗（本投稿は成功済み）")


def main():
    ap = argparse.ArgumentParser(description="Threads 公式API 投稿")
    ap.add_argument("--next", action="store_true", help="キューから次の1本を投稿")
    ap.add_argument("--text", help="任意テキストを即投稿")
    ap.add_argument("--link", help="--text と併用するリンクプレビューURL")
    ap.add_argument("--whoami", action="store_true", help="トークンのアカウント確認")
    ap.add_argument("--dry-run", action="store_true", help="投稿せず内容のみ表示")
    ap.add_argument("--require-reply-link", action="store_true",
                    help="--next と併用。reply_link を持つ投稿だけを対象にする（CTA返信の動作確認用）")
    args = ap.parse_args()

    if args.whoami:
        token = _token()
        whoami(token)
        return

    if args.text:
        token = _token()
        user_id = _user_id(token)
        rc = post_text(token, user_id, args.text, link=args.link, dry_run=args.dry_run)
        sys.exit(0 if rc else 1)

    if args.next:
        sys.exit(cmd_next(dry_run=args.dry_run, require_reply_link=args.require_reply_link))

    ap.print_help()


if __name__ == "__main__":
    main()
