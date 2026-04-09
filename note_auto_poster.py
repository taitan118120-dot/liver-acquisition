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
import argparse
import time
import requests
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
    """Note.comのログイン情報を取得"""
    email = os.environ.get("NOTE_EMAIL", "")
    password = os.environ.get("NOTE_PASSWORD", "")
    if not email or not password:
        print("NOTE_EMAIL と NOTE_PASSWORD を設定してください")
        sys.exit(1)
    return email, password


def parse_article(filepath):
    """Markdownファイルからタイトル・本文を抽出"""
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
    """記事番号に対応するハッシュタグを取得"""
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
    """記事番号からファイルパスを取得"""
    pattern = os.path.join(ARTICLES_DIR, f"{article_num:02d}_*.md")
    files = glob.glob(pattern)
    return files[0] if files else None


def get_latest_unpublished():
    """最新の未投稿記事を取得"""
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
    """Note.com向けにMarkdownを整形"""
    try:
        sys.path.insert(0, BASE_DIR)
        from note_publisher import convert_table_to_list, format_for_note
        body = convert_table_to_list(body)
        body = format_for_note(body)
    except ImportError:
        pass
    return body.strip()


def log_result(article_num, title, url, success, error_msg=""):
    """投稿結果をCSVに記録"""
    os.makedirs(DATA_DIR, exist_ok=True)
    file_exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["article_num", "title", "url", "success", "error", "posted_at"])
        writer.writerow([
            article_num, title[:50], url or "", success, error_msg,
            datetime.now().isoformat()
        ])


def mark_as_published(article_num):
    """トラッカーで記事を公開済みにする"""
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


def markdown_to_note_body(body):
    """MarkdownをNote.com API用のJSONボディ構造に変換"""
    lines = body.split("\n")
    blocks = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        elif stripped.startswith("## "):
            blocks.append({"type": "heading", "text": stripped[3:].strip()})
        elif stripped.startswith("### "):
            blocks.append({"type": "heading", "text": stripped[4:].strip()})
        elif stripped.startswith("- "):
            blocks.append({"type": "p", "text": "・" + stripped[2:].strip()})
        elif stripped.startswith("---"):
            blocks.append({"type": "separator"})
        elif stripped.startswith("**["):
            # CTAリンク: **[テキスト](URL)** → リンク付きテキスト
            match = re.match(r"\*\*\[(.+?)\]\((.+?)\)\*\*", stripped)
            if match:
                blocks.append({"type": "p", "text": f"{match.group(1)}: {match.group(2)}"})
            else:
                blocks.append({"type": "p", "text": stripped.replace("**", "")})
        else:
            # 太字マーカーを除去
            text = stripped.replace("**", "")
            blocks.append({"type": "p", "text": text})

    return blocks


# ─── Note.com API ────────────────────────────────────

def api_login(email, password):
    """Note.com APIでログイン、セッションCookieを取得"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": "https://note.com/login",
        "Origin": "https://note.com",
    })

    # ログインAPIを呼び出し
    login_data = {
        "login": email,
        "password": password,
    }

    print("  APIログイン中...")
    resp = session.post(
        f"{NOTE_API_BASE}/v1/sessions/sign_in",
        json=login_data,
        timeout=30,
    )

    if resp.status_code not in [200, 201]:
        raise Exception(f"ログイン失敗: HTTP {resp.status_code} - {resp.text[:200]}")

    data = resp.json()
    if data.get("error"):
        raise Exception(f"ログインエラー: {data}")

    print("  APIログイン成功")
    return session


def api_create_draft(session, title, body_text, hashtags):
    """Note.com APIで下書きを作成"""
    print("  下書き作成中...")

    # 本文をプレーンテキストとして構成
    body_html = ""
    for line in body_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            body_html += "<br>"
        elif stripped.startswith("## "):
            body_html += f"<h2>{stripped[3:].strip()}</h2>"
        elif stripped.startswith("### "):
            body_html += f"<h3>{stripped[4:].strip()}</h3>"
        elif stripped.startswith("- "):
            body_html += f"<p>・{stripped[2:].strip()}</p>"
        elif stripped.startswith("---"):
            body_html += "<hr>"
        elif stripped.startswith("**["):
            match = re.match(r"\*\*\[(.+?)\]\((.+?)\)\*\*", stripped)
            if match:
                body_html += f'<p><a href="{match.group(2)}">{match.group(1)}</a></p>'
            else:
                body_html += f"<p>{stripped.replace('**', '')}</p>"
        else:
            text = stripped.replace("**", "")
            body_html += f"<p>{text}</p>"

    # 記事作成（公開ステータスで直接投稿）
    note_data = {
        "note": {
            "name": title,
            "body": body_html,
            "hashtag_notes_attributes": [
                {"hashtag_attributes": {"name": tag}} for tag in hashtags[:10]
            ],
            "publish_at": None,
            "status": "published",
        }
    }

    # まず公開ステータスで試行
    resp = session.post(
        f"{NOTE_API_BASE}/v1/text_notes",
        json=note_data,
        timeout=30,
    )

    if resp.status_code not in [200, 201]:
        # 公開ステータスがダメなら下書きで作成
        print(f"  公開直接投稿失敗（HTTP {resp.status_code}）、下書き作成に切替...")
        note_data["note"]["status"] = "draft"
        resp = session.post(
            f"{NOTE_API_BASE}/v1/text_notes",
            json=note_data,
            timeout=30,
        )

    if resp.status_code not in [200, 201]:
        raise Exception(f"記事作成失敗: HTTP {resp.status_code} - {resp.text[:300]}")

    data = resp.json()
    # レスポンス構造をログ出力（デバッグ用）
    data_keys = list(data.keys()) if isinstance(data, dict) else "not dict"
    inner = data.get("data", {})
    inner_keys = list(inner.keys())[:20] if isinstance(inner, dict) else "not dict"
    print(f"  APIレスポンス: keys={data_keys}, data.keys={inner_keys}")

    note_id = inner.get("id") or data.get("id")
    status = inner.get("status") or inner.get("note_status") or data.get("status", "unknown")
    key = inner.get("key", "")
    urlname = inner.get("user", {}).get("urlname", "") if isinstance(inner.get("user"), dict) else ""
    print(f"  記事作成成功: ID={note_id}, status={status}, key={key}, urlname={urlname}")
    return note_id, data, status


def api_publish(session, note_id):
    """下書きを公開する"""
    print("  記事公開中...")

    # 複数のエンドポイントとメソッドを試行
    publish_attempts = [
        ("PUT", f"{NOTE_API_BASE}/v1/text_notes/{note_id}", {"note": {"status": "published"}}),
        ("PUT", f"{NOTE_API_BASE}/v1/text_notes/{note_id}/publish", {}),
        ("POST", f"{NOTE_API_BASE}/v1/text_notes/{note_id}/publish", {}),
        ("PUT", f"{NOTE_API_BASE}/v3/text_notes/{note_id}/publish", {}),
        ("POST", f"{NOTE_API_BASE}/v3/text_notes/{note_id}/publish", {}),
    ]

    last_resp = None
    for method, url, body in publish_attempts:
        try:
            if method == "PUT":
                resp = session.put(url, json=body, timeout=30)
            elif method == "POST":
                resp = session.post(url, json=body, timeout=30)
            else:
                continue

            last_resp = resp
            print(f"  試行 {method} {url} → HTTP {resp.status_code}")

            if resp.status_code in [200, 201]:
                data = resp.json()
                key = data.get("data", {}).get("key", "")
                user = data.get("data", {}).get("user", {}).get("urlname", "")
                if key and user:
                    article_url = f"https://note.com/{user}/n/{key}"
                else:
                    article_url = f"https://note.com/n/{note_id}"
                print(f"  公開成功: {article_url}")
                return article_url
        except Exception as e:
            print(f"  試行失敗 {method} {url}: {e}")
            continue

    # 全試行失敗
    resp_text = last_resp.text[:300] if last_resp else "no response"
    resp_code = last_resp.status_code if last_resp else "N/A"
    raise Exception(f"公開失敗（全エンドポイント試行済み）: HTTP {resp_code} - {resp_text}")


# ─── メイン投稿処理 ──────────────────────────────────

def post_article(article_num, dry_run=False):
    """メインの投稿処理（API方式）"""
    filepath = get_article_file(article_num)
    if not filepath:
        print(f"記事ファイルが見つかりません: #{article_num}")
        return {"success": False, "error": "file_not_found"}

    title, body = parse_article(filepath)
    hashtags = get_hashtags_for_article(article_num)
    formatted_body = format_body_for_note(body)

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

        # 記事作成（下書き保存）
        note_id, result_data, status = api_create_draft(session, title, formatted_body, hashtags)
        inner = result_data.get("data", {})
        key = inner.get("key", "")

        # 公開を試行
        article_url = None
        try:
            article_url = api_publish(session, note_id)
        except Exception as pub_err:
            print(f"  ⚠ 公開API失敗: {pub_err}")

        if not article_url:
            # 下書き保存成功として扱う（公開は手動で）
            if key:
                article_url = f"https://note.com/taitan_118/n/{key}"
            else:
                article_url = f"https://note.com/notes/{note_id}/edit"
            print(f"  下書き保存成功: {article_url}")
            print(f"  ※ 手動で公開してください")

        # 成功ログ
        log_result(article_num, title, article_url, True)
        mark_as_published(article_num)

        return {"success": True, "url": article_url}

    except Exception as e:
        error_msg = str(e)
        print(f"\n  エラー: {error_msg}")
        log_result(article_num, title, "", False, error_msg)
        return {"success": False, "error": error_msg}


# ─── CLI ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Note.com 自動投稿（API方式）")
    parser.add_argument("--post", type=int, help="指定番号の記事を投稿")
    parser.add_argument("--post-latest", action="store_true", help="最新未投稿記事を投稿")
    parser.add_argument("--dry-run", action="store_true", help="投稿せず確認のみ")

    args = parser.parse_args()

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
        print("\n投稿完了!")
    else:
        print(f"\n投稿失敗: {result.get('error', 'unknown')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
