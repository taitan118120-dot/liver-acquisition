#!/usr/bin/env python3
"""
Note.com 自動投稿（API方式）
================================
生成済みのMarkdown記事をNote.comに自動投稿する。
非公式APIを使用してreCAPTCHA問題を回避。

使い方:
  python3 note_auto_poster.py --post-latest            # 最新未投稿記事を投稿
  python3 note_auto_poster.py --post 27                 # 指定番号の記事を投稿
  python3 note_auto_poster.py --post-latest --dry-run   # 投稿せず確認のみ

環境変数:
  NOTE_EMAIL    - Note.comログインメール
  NOTE_PASSWORD - Note.comログインパスワード

必要:
  pip install requests
"""

import os
import re
import sys
import csv
import glob
import json
import time
import argparse
import requests
from urllib.parse import unquote
from datetime import datetime

# ─── パス設定 ─────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTICLES_DIR = os.path.join(BASE_DIR, "blog", "articles_note")
DATA_DIR = os.path.join(BASE_DIR, "data")
TRACKER_FILE = os.path.join(DATA_DIR, "note_keyword_tracker.json")
LOG_FILE = os.path.join(DATA_DIR, "note_auto_post_log.csv")

NOTE_API_BASE = "https://note.com/api"

# ─── ユーティリティ ───────────────────────────────────

def get_credentials():
    email = os.environ.get("NOTE_EMAIL", "")
    password = os.environ.get("NOTE_PASSWORD", "")
    if not email or not password:
        print("NOTE_EMAIL と NOTE_PASSWORD を設定してください")
        sys.exit(1)
    return email, password


def parse_article(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    lines = content.split("\n")
    title = ""
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title = line.lstrip("# ").strip()
            body_start = i + 1
            break
    body = "\n".join(lines[body_start:]).strip()
    return title, body


def get_hashtags_for_article(article_num):
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            tracker = json.load(f)
        for item in tracker.get("used", []):
            if item.get("article_number") == article_num:
                try:
                    from note_article_generator import SEO_KEYWORDS
                    for cat_keywords in SEO_KEYWORDS.values():
                        for kw in cat_keywords:
                            if kw["slug"] == item.get("slug"):
                                return kw["hashtags"]
                except ImportError:
                    pass
    try:
        from note_publisher import HASHTAG_MAP, DEFAULT_HASHTAGS
        basename = os.path.splitext(os.path.basename(get_article_file(article_num)))[0]
        return HASHTAG_MAP.get(basename, DEFAULT_HASHTAGS)
    except ImportError:
        pass
    return ["ライバー", "ライブ配信", "副業", "Pococha"]


def get_article_file(article_num):
    pattern = os.path.join(ARTICLES_DIR, f"{article_num:02d}_*.md")
    files = glob.glob(pattern)
    return files[0] if files else None


def get_latest_unpublished():
    if not os.path.exists(TRACKER_FILE):
        pattern = os.path.join(ARTICLES_DIR, "*.md")
        files = sorted(glob.glob(pattern))
        if files:
            match = re.match(r"(\d+)_", os.path.basename(files[-1]))
            return int(match.group(1)) if match else None
        return None
    with open(TRACKER_FILE, "r", encoding="utf-8") as f:
        tracker = json.load(f)
    for item in reversed(tracker.get("used", [])):
        if not item.get("published", False):
            return item["article_number"]
    return None


def format_body_for_note(body):
    try:
        sys.path.insert(0, BASE_DIR)
        from note_publisher import convert_table_to_list, format_for_note
        body = convert_table_to_list(body)
        body = format_for_note(body)
    except ImportError:
        pass
    return body.strip()


def log_result(article_num, title, url, success, error_msg=""):
    os.makedirs(DATA_DIR, exist_ok=True)
    file_exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["article_num", "title", "url", "success", "error", "posted_at"])
        writer.writerow([article_num, title[:50], url or "", success, error_msg, datetime.now().isoformat()])


def mark_as_published(article_num):
    if not os.path.exists(TRACKER_FILE):
        return
    with open(TRACKER_FILE, "r", encoding="utf-8") as f:
        tracker = json.load(f)
    for item in tracker.get("used", []):
        if item.get("article_number") == article_num:
            item["published"] = True
            item["published_at"] = datetime.now().isoformat()
    with open(TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(tracker, f, ensure_ascii=False, indent=2)


def markdown_to_html(body_text):
    """MarkdownをNote.com用HTMLに変換"""
    html = ""
    for line in body_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            html += "<br>"
        elif stripped.startswith("## "):
            html += f"<h2>{stripped[3:].strip()}</h2>"
        elif stripped.startswith("### "):
            html += f"<h3>{stripped[4:].strip()}</h3>"
        elif stripped.startswith("- "):
            item_text = convert_inline_markdown(stripped[2:].strip())
            html += f"<p>・{item_text}</p>"
        elif stripped.startswith("---"):
            html += "<hr>"
        else:
            converted = convert_inline_markdown(stripped)
            html += f"<p>{converted}</p>"
    return html


def convert_inline_markdown(text):
    """Markdownのインライン要素（太字・リンク）をHTMLに変換"""
    # 太字リンク: **[text](url)** → <a href="url"><strong>text</strong></a>
    text = re.sub(
        r"\*\*\[(.+?)\]\((.+?)\)\*\*",
        r'<a href="\2"><strong>\1</strong></a>',
        text,
    )
    # 通常リンク: [text](url) → <a href="url">text</a>
    text = re.sub(
        r"\[(.+?)\]\((.+?)\)",
        r'<a href="\2">\1</a>',
        text,
    )
    # ベアURL（https://...）→ <a href="url">url</a>
    text = re.sub(
        r'(?<!["\(])(?<!=)(https?://[^\s<>\)]+)',
        r'<a href="\1">\1</a>',
        text,
    )
    # 太字: **text** → <strong>text</strong>
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return text


# ─── Note.com API ────────────────────────────────────

def setup_xsrf_token(session):
    """Cookie内のXSRF-TOKENをリクエストヘッダーに設定"""
    for cookie in session.cookies:
        if cookie.name == "XSRF-TOKEN":
            token = unquote(cookie.value)
            session.headers["X-XSRF-TOKEN"] = token
            print(f"  X-XSRF-TOKEN設定済み")
            return
    print("  ⚠ XSRF-TOKENがCookieに見つかりません")


def api_login(email, password):
    """Note.com APIでログイン"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": "https://note.com/login",
        "Origin": "https://note.com",
    })

    # ログイン前にトップページGETでXSRF-TOKEN Cookieを取得
    try:
        session.get("https://note.com", timeout=15)
        setup_xsrf_token(session)
    except Exception:
        pass

    print("  APIログイン中...")
    resp = session.post(
        f"{NOTE_API_BASE}/v1/sessions/sign_in",
        json={"login": email, "password": password},
        timeout=30,
    )

    if resp.status_code not in [200, 201]:
        raise Exception(f"ログイン失敗: HTTP {resp.status_code} - {resp.text[:200]}")

    # ログイン後にXSRF-TOKENを再設定（ログインで新しいトークンが発行される場合がある）
    setup_xsrf_token(session)

    print("  APIログイン成功")
    return session


def api_create_draft(session, title, body_html, hashtags):
    """下書きを作成"""
    print("  下書き作成中...")

    note_data = {
        "note": {
            "name": title,
            "body": body_html,
            "hashtag_notes_attributes": [
                {"hashtag_attributes": {"name": tag}} for tag in hashtags[:10]
            ],
            "publish_at": None,
            "status": "draft",
        }
    }

    resp = session.post(f"{NOTE_API_BASE}/v1/text_notes", json=note_data, timeout=30)

    if resp.status_code not in [200, 201]:
        raise Exception(f"下書き作成失敗: HTTP {resp.status_code} - {resp.text[:300]}")

    data = resp.json()
    inner = data.get("data", {})
    note_id = inner.get("id")
    note_key = inner.get("key", "")
    print(f"  下書き作成成功: ID={note_id}, key={note_key}")
    return note_id, note_key, data


def api_publish(session, note_key):
    """下書きを公開する（note_keyを使用）。公開失敗時はNoneを返す（下書き保存は成功扱い）"""
    print(f"  記事公開中... (key={note_key})")

    publish_attempts = [
        ("PUT",  f"{NOTE_API_BASE}/v2/notes/{note_key}/publish"),
        ("POST", f"{NOTE_API_BASE}/v2/notes/{note_key}/publish"),
        ("PUT",  f"{NOTE_API_BASE}/v1/notes/{note_key}/publish"),
        ("POST", f"{NOTE_API_BASE}/v1/notes/{note_key}/publish"),
    ]

    last_resp = None
    for method, url in publish_attempts:
        try:
            if method == "PUT":
                resp = session.put(url, json={}, timeout=30)
            else:
                resp = session.post(url, json={}, timeout=30)

            last_resp = resp
            print(f"  試行 {method} {url} → HTTP {resp.status_code}")

            if resp.status_code in [200, 201]:
                data = resp.json()
                inner = data.get("data", {})
                key = inner.get("key", note_key)
                user = inner.get("user", {}).get("urlname", "") if isinstance(inner.get("user"), dict) else ""
                if key and user:
                    article_url = f"https://note.com/{user}/n/{key}"
                elif key:
                    article_url = f"https://note.com/n/{key}"
                else:
                    article_url = f"https://note.com/n/{note_key}"
                print(f"  公開成功: {article_url}")
                return article_url
            elif resp.status_code == 422:
                print(f"  422レスポンス: {resp.text[:200]}")
        except Exception as e:
            print(f"  試行失敗 {method} {url}: {e}")
            continue

    # 公開API失敗 → 下書き保存は成功しているのでNoneを返す（例外を投げない）
    resp_text = last_resp.text[:300] if last_resp else "no response"
    resp_code = last_resp.status_code if last_resp else "N/A"
    print(f"  ⚠ 公開API失敗（HTTP {resp_code}）。下書きとして保存済み。手動で公開してください。")
    return None


# ─── 投稿済み記事のキーマッピング ─────────────────────
PUBLISHED_KEYS = {
    5: "n31f7f5d3ba48", 6: "n37b2e994b9b2", 7: "n19a9e86e6019",
    8: "nb1b3f5bd6cc3", 9: "n78acd5d8f43e", 10: "n2be76b2b0c1a",
    11: "nd74263b56cae", 12: "n8e969fafe3a0", 13: "n460d10f2e1f6",
    14: "ne44420f9b831", 15: "n434daa26e8a1", 16: "n59a8a10dc58f",
    17: "n9461e5e71d6d", 18: "n8f3f5e3cb15e", 19: "nfe4de4feea5f",
    20: "n1e8e1bbab7e9", 21: "na4f9b5f4f42d", 22: "n0f9e5e3c33c5",
    23: "n48d6e4ecaebb", 24: "nc998ae516bdf", 25: "ne7911c5b9ce9",
    26: "n9197ae57ed8a", 27: "ncf76e2e16aff", 28: "n86c0f997ca68",
    29: "na737000db46a", 30: "n7d6b128296e8", 31: "n04dff5a7bd9c",
    32: "n84121e6b7eab", 33: "ne57e6ea14042", 34: "n6b2f4704cdcc",
    35: "n699ef655effb", 36: "nc02030acfe75",
}


def resolve_note_ids(session, urlname="taitan_118"):
    """投稿済み記事の数値IDを取得"""
    print(f"  投稿済み記事のID解決中...")
    id_map = {}
    page = 1
    while True:
        resp = session.get(
            f"{NOTE_API_BASE}/v2/creators/{urlname}/contents",
            params={"kind": "note", "page": page, "size": 50},
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"  ⚠ 記事一覧取得失敗: HTTP {resp.status_code}")
            break
        data = resp.json()
        contents = data.get("data", {}).get("contents", [])
        if not contents:
            break
        for note in contents:
            key = note.get("key", "")
            note_id = note.get("id")
            if key and note_id:
                id_map[key] = note_id
        page += 1
    print(f"  {len(id_map)}件の記事IDを取得")
    return id_map


def api_update_article(session, note_key, note_id, title, body_html, hashtags):
    """既存記事をAPIで更新（数値IDを使用）"""
    print(f"  記事更新中... (key={note_key}, id={note_id})")

    note_data = {
        "note": {
            "name": title,
            "body": body_html,
            "hashtag_notes_attributes": [
                {"hashtag_attributes": {"name": tag}} for tag in hashtags[:10]
            ],
        }
    }

    # 数値IDで更新（note_keyでは404になる）
    update_attempts = [
        ("PUT",   f"{NOTE_API_BASE}/v1/text_notes/{note_id}"),
        ("PATCH", f"{NOTE_API_BASE}/v1/text_notes/{note_id}"),
        ("PUT",   f"{NOTE_API_BASE}/v1/notes/{note_id}"),
    ]

    for method, url in update_attempts:
        try:
            if method == "PUT":
                resp = session.put(url, json=note_data, timeout=30)
            elif method == "PATCH":
                resp = session.patch(url, json=note_data, timeout=30)
            else:
                resp = session.post(url, json=note_data, timeout=30)

            print(f"    {method} .../{note_id} → HTTP {resp.status_code}")

            if resp.status_code in [200, 201]:
                print(f"  更新成功")
                return True
            elif resp.status_code == 422:
                detail = resp.text[:200]
                print(f"    422: {detail}")
                # XSRF-TOKEN不足の場合、再取得を試みる
                if "invalid" in detail.lower() or "不正" in detail:
                    setup_xsrf_token(session)
        except Exception as e:
            print(f"    失敗: {e}")
            continue

    print(f"  ⚠ API更新失敗")
    return False


def update_article(article_num, session=None, note_id_map=None, dry_run=False):
    """既存記事を更新"""
    note_key = PUBLISHED_KEYS.get(article_num)
    if not note_key:
        print(f"  記事#{article_num} はPUBLISHED_KEYSに登録されていません")
        return {"success": False, "error": "not_published"}

    # 数値IDを解決
    note_id = note_id_map.get(note_key) if note_id_map else None
    if not note_id and not dry_run:
        print(f"  ⚠ 数値IDが見つかりません (key={note_key})")
        return {"success": False, "error": "note_id_not_found"}

    filepath = get_article_file(article_num)
    if not filepath:
        print(f"  記事ファイルが見つかりません: #{article_num}")
        return {"success": False, "error": "file_not_found"}

    title, body = parse_article(filepath)
    hashtags = get_hashtags_for_article(article_num)
    formatted_body = format_body_for_note(body)
    body_html = markdown_to_html(formatted_body)

    print(f"  #{article_num:02d} {title[:50]}")
    print(f"  文字数: {len(formatted_body)}文字 / HTML: {len(body_html)}文字")

    if dry_run:
        print("  [dry-run] 更新スキップ")
        return {"success": True, "dry_run": True}

    try:
        success = api_update_article(session, note_key, note_id, title, body_html, hashtags)
        if success:
            return {"success": True, "key": note_key}
        else:
            return {"success": False, "error": "api_update_failed"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_all_articles(dry_run=False):
    """全投稿済み記事を更新"""
    email, password = get_credentials()
    session = api_login(email, password)

    # 数値IDを一括取得
    note_id_map = {} if dry_run else resolve_note_ids(session)

    results = {"success": 0, "fail": 0, "skip": 0}
    total = len(PUBLISHED_KEYS)

    print(f"\n{'='*50}")
    print(f"  Note.com 記事一括更新（API方式）")
    print(f"  対象: {total}記事")
    print(f"{'='*50}\n")

    for i, (num, key) in enumerate(sorted(PUBLISHED_KEYS.items()), 1):
        print(f"── {i}/{total} ──────────────────────────")
        result = update_article(num, session=session, note_id_map=note_id_map, dry_run=dry_run)

        if result.get("dry_run"):
            results["skip"] += 1
        elif result.get("success"):
            results["success"] += 1
        else:
            results["fail"] += 1
            print(f"  エラー: {result.get('error')}")

        # レート制限対策
        if i < total and not dry_run:
            time.sleep(2)

    print(f"\n{'='*50}")
    print(f"  完了: 成功 {results['success']} / 失敗 {results['fail']} / スキップ {results['skip']}")
    print(f"{'='*50}")
    return results


# ─── メイン投稿処理 ──────────────────────────────────

def post_article(article_num, dry_run=False):
    filepath = get_article_file(article_num)
    if not filepath:
        print(f"記事ファイルが見つかりません: #{article_num}")
        return {"success": False, "error": "file_not_found"}

    title, body = parse_article(filepath)
    hashtags = get_hashtags_for_article(article_num)
    formatted_body = format_body_for_note(body)
    body_html = markdown_to_html(formatted_body)

    print(f"\n{'='*50}")
    print(f"  Note.com 自動投稿（API方式）")
    print(f"{'='*50}")
    print(f"  記事: #{article_num}")
    print(f"  タイトル: {title}")
    print(f"  文字数: {len(formatted_body)}文字")
    print(f"  ハッシュタグ: {' '.join('#' + t for t in hashtags[:10])}")

    if dry_run:
        print("\n  [dry-run] 投稿スキップ")
        return {"success": True, "dry_run": True}

    email, password = get_credentials()

    try:
        # APIでログイン
        session = api_login(email, password)

        # 下書き作成
        note_id, note_key, result_data = api_create_draft(session, title, body_html, hashtags)

        if not note_key:
            raise Exception("note_keyが取得できませんでした")

        # 公開（失敗してもNoneが返るだけで例外にならない）
        article_url = api_publish(session, note_key)

        if article_url:
            # 公開成功
            log_result(article_num, title, article_url, True)
            mark_as_published(article_num)
            return {"success": True, "url": article_url}
        else:
            # 下書き保存成功（公開は手動で）
            draft_url = f"https://note.com/notes/{note_key}/edit"
            log_result(article_num, title, draft_url, True, "下書き保存済み（手動公開が必要）")
            mark_as_published(article_num)
            return {"success": True, "url": draft_url, "draft_only": True}

    except Exception as e:
        error_msg = str(e)
        print(f"\n  エラー: {error_msg}")
        log_result(article_num, title, "", False, error_msg)
        return {"success": False, "error": error_msg}


# ─── CLI ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Note.com 自動投稿・更新（API方式）")
    parser.add_argument("--post", type=int, help="指定番号の記事を投稿")
    parser.add_argument("--post-latest", action="store_true", help="最新未投稿記事を投稿")
    parser.add_argument("--update", type=int, nargs="+", help="指定番号の記事を更新")
    parser.add_argument("--update-all", action="store_true", help="全投稿済み記事を更新")
    parser.add_argument("--dry-run", action="store_true", help="投稿/更新せず確認のみ")
    args = parser.parse_args()

    if args.update_all:
        update_all_articles(dry_run=args.dry_run)
        return

    if args.update:
        session = None
        note_id_map = {}
        if not args.dry_run:
            email, password = get_credentials()
            session = api_login(email, password)
            note_id_map = resolve_note_ids(session)
        for num in args.update:
            result = update_article(num, session=session, note_id_map=note_id_map, dry_run=args.dry_run)
            if not result.get("success") and not result.get("dry_run"):
                print(f"  更新失敗: {result.get('error')}")
        return

    if args.post:
        article_num = args.post
    elif args.post_latest:
        article_num = get_latest_unpublished()
        if article_num is None:
            print("未投稿の記事がありません")
            sys.exit(0)
    else:
        parser.print_help()
        return

    result = post_article(article_num, dry_run=args.dry_run)
    if result.get("success"):
        if result.get("draft_only"):
            print("\n下書き保存完了（公開APIが利用不可のため手動公開が必要です）")
        else:
            print("\n投稿完了!")
    else:
        print(f"\n投稿失敗: {result.get('error', 'unknown')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
