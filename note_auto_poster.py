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
    """記事ごとのハッシュタグを返す。
    Note露出を伸ばすため、固有タグ＋母集団の大きい汎用タグを混ぜて10個枠を埋める。
    """
    base_tags = None

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
                                base_tags = list(kw["hashtags"])
                                break
                        if base_tags:
                            break
                except ImportError:
                    pass

    if base_tags is None:
        try:
            from note_publisher import HASHTAG_MAP, DEFAULT_HASHTAGS
            basename = os.path.splitext(os.path.basename(get_article_file(article_num) or ""))[0]
            base_tags = list(HASHTAG_MAP.get(basename, DEFAULT_HASHTAGS))
        except ImportError:
            base_tags = ["ライバー", "ライブ配信", "副業", "Pococha"]

    # Note検索で母集団が大きいタグを混ぜて露出を広げる
    # 固有タグを先頭に残しつつ、10枠を汎用タグで埋める
    import random as _random
    general_pool = [
        "副業", "お金の勉強", "仕事について話そう", "毎日note",
        "働き方", "ビジネス", "スキルアップ", "キャリア",
        "最近の学び", "在宅ワーク",
    ]
    existing = {t for t in base_tags}
    extras = [t for t in general_pool if t not in existing]
    _random.shuffle(extras)

    merged = list(base_tags)
    for t in extras:
        if len(merged) >= 10:
            break
        merged.append(t)
    return merged[:10]


def get_article_file(article_num):
    pattern = os.path.join(ARTICLES_DIR, f"{article_num:02d}_*.md")
    files = glob.glob(pattern)
    return files[0] if files else None


def get_latest_unpublished():
    """未投稿の最新記事番号を返す。全て投稿済みならNone。"""
    published = get_published_article_nums()

    # trackerファイルがあればそこから未投稿を探す
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE, "r", encoding="utf-8") as f:
                tracker = json.load(f)
            for item in reversed(tracker.get("used", [])):
                num = item.get("article_number")
                if num and not item.get("published", False) and num not in published:
                    return num
        except (json.JSONDecodeError, KeyError):
            pass

    # trackerがない/見つからない場合、ファイルから探す
    pattern = os.path.join(ARTICLES_DIR, "*.md")
    files = sorted(glob.glob(pattern))
    # 未投稿の記事を新しい順に探す
    for filepath in reversed(files):
        match = re.match(r"(\d+)_", os.path.basename(filepath))
        if match:
            num = int(match.group(1))
            if num not in published:
                return num
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

class _HttpCsrfFailed(Exception):
    """HTTP経由で CSRF/422 によって下書き作成が不可能だったことを示す。
    post_article 側で捕まえて Playwright フォールバックへ切り替える。"""


def setup_xsrf_token(session):
    """Cookie内のXSRF-TOKENをリクエストヘッダーに設定"""
    for cookie in session.cookies:
        if cookie.name == "XSRF-TOKEN":
            token = unquote(cookie.value)
            session.headers["X-XSRF-TOKEN"] = token
            session.headers["X-CSRF-Token"] = token
            print(f"  X-XSRF-TOKEN設定済み")
            return True
    return False


def _clear_csrf_state(session):
    """CSRFヘッダーと XSRF-TOKEN cookie を全て削除する。422後の再取得前に使用。"""
    for h in ("X-XSRF-TOKEN", "X-CSRF-Token"):
        session.headers.pop(h, None)
    # domain/path が未知でも対応できるよう iterate して name 一致で削除
    for cookie in list(session.cookies):
        if cookie.name == "XSRF-TOKEN":
            try:
                session.cookies.clear(cookie.domain, cookie.path, cookie.name)
            except (KeyError, ValueError):
                pass


def _acquire_csrf_token(session, verbose=True):
    """CSRFトークンをヘッダーに設定する。
    (1) Cookie内の XSRF-TOKEN
    (2) HTMLページの <meta name="csrf-token"> パース
    (3) HTML取得による XSRF-TOKEN cookie 発行
    のいずれかで取得を試みる。Railsアプリのため POST系APIに必須。
    """
    if setup_xsrf_token(session):
        if verbose:
            print("  CSRF: Cookie由来のXSRF-TOKENを使用")
        return True

    # HTML系ページを順に訪問してCSRF取得を試みる
    # - Accept: text/html を明示してJSONでなくHTMLを受け取る
    # - editor.note.com は editor subdomain 用のCSRFが発行されることがある
    html_pages = [
        "https://note.com/",
        "https://editor.note.com/new",
        "https://note.com/settings/account",
        "https://note.com/notes",
    ]
    meta_re = re.compile(
        r'<meta[^>]*\bname\s*=\s*["\']csrf-token["\'][^>]*\bcontent\s*=\s*["\']([^"\']+)["\']',
        re.IGNORECASE,
    )
    for url in html_pages:
        try:
            r = session.get(
                url,
                timeout=20,
                headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
                allow_redirects=True,
            )
        except Exception as e:
            if verbose:
                print(f"  CSRF取得試行失敗 ({url}): {e}")
            continue

        # (a) レスポンスで XSRF-TOKEN cookie が発行されたか確認
        if setup_xsrf_token(session):
            if verbose:
                print(f"  CSRF: XSRF-TOKEN cookie 取得（{url}）")
            return True

        # (b) HTMLから <meta name="csrf-token"> をパース
        content_type = r.headers.get("Content-Type", "").lower()
        if "text/html" in content_type and r.text:
            m = meta_re.search(r.text)
            if m:
                token = m.group(1)
                session.headers["X-CSRF-Token"] = token
                session.headers["X-XSRF-TOKEN"] = token
                if verbose:
                    print(f"  CSRF: <meta csrf-token>から取得（{url}）")
                return True

    if verbose:
        cookie_names = sorted({c.name for c in session.cookies})
        print(f"  ⚠ CSRFトークンを取得できませんでした。現Cookie: {cookie_names}")
    return False


def _playwright_ui_login(email, password, headless=True):
    """Playwright で note.com/login に UI ログインしCookieリストを返す。
    /api/v1/sessions/sign_in が 422 を返す問題への恒久回避策。
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
            locale="ja-JP",
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        page = ctx.new_page()
        page.goto("https://note.com/login", wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)

        # メール入力
        email_sel_list = [
            'input[name="login"]', 'input[type="email"]',
            'input#email', 'input[placeholder*="メール"]', 'input[placeholder*="mail"]',
        ]
        filled_email = False
        for sel in email_sel_list:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.fill(email)
                    filled_email = True
                    break
            except Exception:
                continue
        if not filled_email:
            browser.close()
            raise Exception("メール入力欄が見つかりません（ログイン画面の仕様変更？）")

        # パスワード入力
        try:
            page.fill('input[type="password"]', password)
        except Exception as e:
            browser.close()
            raise Exception(f"パスワード入力欄が見つかりません: {e}")

        # 送信
        submitted = False
        for sel in ['button[type="submit"]',
                    'button:has-text("ログイン")',
                    'button:has-text("Login")']:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible() and btn.is_enabled():
                    btn.click()
                    submitted = True
                    break
            except Exception:
                continue
        if not submitted:
            page.keyboard.press("Enter")

        # ログイン後の遷移を待つ
        try:
            page.wait_for_url(lambda u: "/login" not in u, timeout=30000)
        except Exception:
            # URLが遷移しない場合 = エラー表示 or 2FA / CAPTCHA
            time.sleep(5)
            if "/login" in page.url:
                # 診断情報を保存（GitHub Actionsのartifactで回収可能）
                try:
                    diag_dir = os.path.join(BASE_DIR, "data", "login_diag")
                    os.makedirs(diag_dir, exist_ok=True)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    page.screenshot(path=os.path.join(diag_dir, f"login_fail_{ts}.png"), full_page=True)
                    with open(os.path.join(diag_dir, f"login_fail_{ts}.html"), "w", encoding="utf-8") as f:
                        f.write(page.content())
                    # ページ内のエラーメッセージらしき要素を抽出
                    err_texts = page.evaluate("""
                        () => {
                            const selectors = ['[class*=error]','[class*=Error]','[class*=alert]','.o-loginForm__message','p.error'];
                            const found = [];
                            for (const s of selectors) {
                                document.querySelectorAll(s).forEach(el => {
                                    const t = el.innerText?.trim();
                                    if (t) found.push(s + ': ' + t.slice(0,200));
                                });
                            }
                            return found.slice(0,5);
                        }
                    """)
                    print(f"  [診断] ページ内エラー要素: {err_texts}")
                    print(f"  [診断] スクショ保存: {diag_dir}/login_fail_{ts}.png")
                except Exception as diag_e:
                    print(f"  [診断] 診断保存失敗: {diag_e}")
                browser.close()
                raise Exception("ログイン後の遷移が確認できません（CAPTCHA/2FA/認証情報エラーの可能性。data/login_diag/ のスクショで確認）")

        time.sleep(3)
        cookies = ctx.cookies()
        browser.close()
    return cookies


def _session_from_cookies(cookies):
    """cookiesリスト(Playwright形式)をrequests.Sessionに注入して返す。"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": "https://note.com/",
        "Origin": "https://note.com",
    })
    for c in cookies:
        session.cookies.set(c["name"], c["value"], domain=c.get("domain", ".note.com"))
    cookie_names = sorted({c.name for c in session.cookies})
    print(f"  注入済みCookie: {cookie_names}")
    _acquire_csrf_token(session)
    return session


def _try_login_from_env_cookies():
    """環境変数 NOTE_COOKIES_JSON からCookieを読んでセッションを構築する。
    成功すれば requests.Session、失敗/未設定なら None を返す。
    ローカル環境では `python note_export_cookies.py` で生成したJSONを
    GitHub Secret `NOTE_COOKIES_JSON` に登録する運用。
    """
    raw = os.environ.get("NOTE_COOKIES_JSON", "").strip()
    if not raw:
        return None
    try:
        cookies = json.loads(raw)
        if not isinstance(cookies, list) or not cookies:
            print("  NOTE_COOKIES_JSONの形式が不正（リストではない/空）")
            return None
    except json.JSONDecodeError as e:
        print(f"  NOTE_COOKIES_JSONのJSONパース失敗: {e}")
        return None

    print(f"  Cookie認証を試行中... ({len(cookies)}個のCookie)")
    session = _session_from_cookies(cookies)
    try:
        verify = session.get(f"{NOTE_API_BASE}/v2/creators/my_page", timeout=15)
        if verify.status_code == 200:
            print("  Cookieログイン成功")
            return session
        print(f"  Cookie認証失敗: HTTP {verify.status_code}（Cookie失効の可能性。note_export_cookies.py で再エクスポートしてください）")
    except Exception as e:
        print(f"  Cookie認証確認失敗: {e}")
    return None


def api_login(email, password, max_retries=3):
    """ログイン。NOTE_COOKIES_JSON があればCookie注入を優先、
    無ければPlaywright UIログインにフォールバック（ローカルのみ）。
    APIの /v1/sessions/sign_in が 422 を返すため、UI 経由に切替（2026-04）。
    """
    # 1) Cookie方式（推奨：GitHub Actions上で確実に動作）
    session = _try_login_from_env_cookies()
    if session is not None:
        return session

    # CI環境ではPlaywright UIログインがreCAPTCHAで必ず失敗する。
    # 3回リトライで3分浪費＋診断ファイルでリポジトリが汚染されるため、
    # Cookie未設定/失効時は即座に中断し、明確な手順を提示する。
    if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true":
        raw = os.environ.get("NOTE_COOKIES_JSON", "").strip()
        hint = (
            "\n  対処手順:\n"
            "  1. ローカルで `python note_export_cookies.py` を実行\n"
            "  2. ブラウザが開くので手動ログイン（CAPTCHAがあれば解く）\n"
            "  3. 出力されたJSONをコピー\n"
            "  4. GitHub → Settings → Secrets and variables → Actions →\n"
            "     `NOTE_COOKIES_JSON` を New/Update で登録"
        )
        if not raw:
            raise Exception(f"NOTE_COOKIES_JSONが未設定のためログイン不可（CIでのUIログインはCAPTCHAで必ず失敗）{hint}")
        raise Exception(f"NOTE_COOKIES_JSONが無効または失効（Cookieは通常1〜3ヶ月で失効）{hint}")

    # 2) Playwright UIログイン（フォールバック：ローカル実行や初回時用）
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            print(f"  Playwright UIログイン中... (試行 {attempt}/{max_retries})")
            cookies = _playwright_ui_login(email, password, headless=True)
            if not cookies:
                raise Exception("Cookieが取得できませんでした")

            session = requests.Session()
            session.headers.update({
                "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Referer": "https://note.com/",
                "Origin": "https://note.com",
            })
            for c in cookies:
                session.cookies.set(c["name"], c["value"], domain=c.get("domain", ".note.com"))
            print(f"  Cookies注入: {[c['name'] for c in cookies][:8]}...")

            # CSRFトークンをヘッダーに設定（Cookie/HTMLどちらからでも取得）
            _acquire_csrf_token(session)

            # ログイン確認(my_page へのGETで200が返ることを確認)
            verify = session.get(f"{NOTE_API_BASE}/v2/creators/my_page", timeout=15)
            if verify.status_code != 200:
                raise Exception(f"ログイン確認失敗: HTTP {verify.status_code}")

            print("  UIログイン成功")
            return session

        except Exception as e:
            last_error = e
            print(f"  ログイン試行{attempt}失敗: {e}")
            if attempt < max_retries:
                wait = 5 * attempt
                print(f"  {wait}秒後にリトライ...")
                time.sleep(wait)

    raise Exception(f"ログイン{max_retries}回失敗: {last_error}")


def _api_login_legacy_disabled(email, password, max_retries=3):
    """旧API方式（/v1/sessions/sign_in）。現在422で使用不可。参考保持。"""
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Referer": "https://note.com/login",
                "Origin": "https://note.com",
            })

            print(f"  APIログイン中... (試行 {attempt}/{max_retries})")

            # ログイン前にログインページを取得してXSRF-TOKEN等のCookieを確立
            try:
                session.get("https://note.com/login", timeout=15)
            except Exception:
                pass

            # 取得したXSRF-TOKENをヘッダーに付与（POSTが422になる主因の一つ）
            import urllib.parse
            for cookie in session.cookies:
                if cookie.name == "XSRF-TOKEN":
                    session.headers["X-XSRF-TOKEN"] = urllib.parse.unquote(cookie.value)
                    print(f"  プリログインXSRF-TOKEN設定済み")
                    break

            resp = session.post(
                f"{NOTE_API_BASE}/v1/sessions/sign_in",
                json={"login": email, "password": password},
                timeout=30,
            )

            if resp.status_code not in [200, 201]:
                raise Exception(f"ログインHTTPエラー: {resp.status_code} - {resp.text[:200]}")

            # レスポンスボディを検証
            try:
                login_data = resp.json()
            except Exception:
                raise Exception(f"ログインレスポンスがJSONではありません: {resp.text[:200]}")

            # Cookieを確認
            cookie_names = [c.name for c in session.cookies]
            print(f"  Cookies: {cookie_names}")

            # XSRF-TOKENを設定
            setup_xsrf_token(session)

            # XSRF-TOKENが無い場合、GETで取得を試みる
            if "X-XSRF-TOKEN" not in session.headers:
                print("  XSRF-TOKEN未取得、GET /api/v2/creators/my_page で再取得...")
                session.get(f"{NOTE_API_BASE}/v2/creators/my_page", timeout=15)
                setup_xsrf_token(session)

            # 最終検証: XSRF-TOKENがなければリトライ
            if "X-XSRF-TOKEN" not in session.headers:
                raise Exception("XSRF-TOKENが取得できませんでした（Cookieが空）")

            print("  APIログイン成功")
            return session

        except Exception as e:
            last_error = e
            print(f"  ログイン試行{attempt}失敗: {e}")
            if attempt < max_retries:
                wait = attempt * 5
                print(f"  {wait}秒後にリトライ...")
                time.sleep(wait)

    raise Exception(f"ログイン{max_retries}回失敗: {last_error}")


def _make_draft_payload(title, body_html, hashtags):
    return {
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


def _playwright_api_call(cookies, url, method, payload=None, bootstrap_url="https://note.com/"):
    """ブラウザコンテキスト内で APIを叩く。
    Cookie認証は通るが HTTP 直叩きだと 422 が返るケース（CSRF周り）への恒久策。
    bootstrap_url を APIと同一 origin にした上で ctx.request (APIRequestContext) を使用し、
    ブラウザの cookie jar と session state を透過的に再利用する。
    """
    from playwright.sync_api import sync_playwright

    pw_cookies = []
    for c in cookies:
        pw_cookies.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".note.com"),
            "path": c.get("path", "/"),
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure": bool(c.get("secure", True)),
            "sameSite": (c.get("sameSite") or "Lax").capitalize(),
        })

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
            locale="ja-JP",
            viewport={"width": 1280, "height": 900},
        )
        ctx.add_cookies(pw_cookies)
        page = ctx.new_page()
        try:
            page.goto(bootstrap_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
        except Exception as e:
            print(f"  [PW] bootstrap goto 失敗（継続）: {e}")

        # bootstrap 後のブラウザ内 cookie を確認
        browser_cookies = ctx.cookies()
        print(f"  [PW] ブラウザ内Cookie名: {sorted({c['name'] for c in browser_cookies})}")

        # ctx.request（APIRequestContext）経由で叩く。ctxの cookie jar を自動参照する。
        headers = {
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": bootstrap_url,
            "Origin": "https://note.com",
        }
        # XSRF-TOKEN が取れていればヘッダーに設定
        xsrf = None
        for c in browser_cookies:
            if c["name"] == "XSRF-TOKEN":
                xsrf = unquote(c["value"])
                headers["X-XSRF-TOKEN"] = xsrf
                break

        req_kwargs = {"headers": headers}
        if payload is not None and method.upper() != "GET":
            req_kwargs["data"] = json.dumps(payload)
            headers["Content-Type"] = "application/json"

        api = ctx.request
        method_upper = method.upper()
        if method_upper == "POST":
            resp = api.post(url, **req_kwargs)
        elif method_upper == "PUT":
            resp = api.put(url, **req_kwargs)
        elif method_upper == "PATCH":
            resp = api.patch(url, **req_kwargs)
        elif method_upper == "DELETE":
            resp = api.delete(url, **req_kwargs)
        else:
            resp = api.get(url, **req_kwargs)

        status = resp.status
        body = resp.text()
        try:
            data = json.loads(body)
        except Exception:
            data = None

        # 診断：レスポンスヘッダのsubset
        try:
            resp_headers = resp.headers
            interesting = {k: v for k, v in resp_headers.items() if k.lower() in (
                "content-type", "location", "set-cookie", "www-authenticate", "x-request-id"
            )}
        except Exception:
            interesting = {}

        result = {
            "status": status,
            "body": body,
            "data": data,
            "xsrf_present": bool(xsrf),
            "resp_headers": interesting,
        }
        browser.close()
    return result


def _playwright_full_post(title, body_html, hashtags, publish=True):
    """Playwright で editor.note.com を使って完結させる。
    1. /new にアクセス → 自動で空下書き作成 → /notes/{key}/edit へ自動リダイレクト
    2. editor ページ内で XSRF-TOKEN が issue されるのを待つ
    3. page.evaluate で fetch() を叩いて draft_save
    4. publish API を試行（失敗しても下書きは保存済み）
    戻り値: {"key": ..., "id": ..., "url": article_url_or_draft_url, "draft_only": bool}
    """
    from playwright.sync_api import sync_playwright

    raw = os.environ.get("NOTE_COOKIES_JSON", "").strip()
    if not raw:
        raise Exception("NOTE_COOKIES_JSONが未設定のためPlaywrightフォールバック不可")
    cookies = json.loads(raw)

    pw_cookies = []
    for c in cookies:
        pw_cookies.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".note.com"),
            "path": c.get("path", "/"),
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure": bool(c.get("secure", True)),
            "sameSite": (c.get("sameSite") or "Lax").capitalize(),
        })

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
            locale="ja-JP",
            viewport={"width": 1400, "height": 900},
        )
        ctx.add_cookies(pw_cookies)
        page = ctx.new_page()

        # Step1: /new を開く → 自動で /notes/{key}/edit にリダイレクト
        print(f"  [PW] editor.note.com/new を開く...")
        page.goto("https://editor.note.com/new", wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_url(re.compile(r"/notes/[^/]+/edit"), timeout=30000)
        except Exception as e:
            browser.close()
            raise Exception(f"editor.note.com/new からのリダイレクトが起きず。ログイン状態を確認してください: {e}. URL={page.url}")

        cur_url = page.url
        m = re.search(r"/notes/([^/]+)/edit", cur_url)
        if not m:
            browser.close()
            raise Exception(f"note_keyの抽出失敗。URL={cur_url}")
        note_key = m.group(1)
        print(f"  [PW] 空下書き作成成功: key={note_key}, url={cur_url}")

        # Editor が XSRF-TOKEN を issue するのを待つ
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        time.sleep(3)

        browser_cookies = ctx.cookies()
        cookie_names = sorted({c["name"] for c in browser_cookies})
        print(f"  [PW] editor読込後のCookie: {cookie_names}")

        # Step2: draft_save で本文・タイトル・ハッシュタグを保存
        save_payload = {
            "body": body_html,
            "body_length": len(body_html),
            "name": title,
        }
        save_url = f"{NOTE_API_BASE}/v1/text_notes/draft_save?id={note_key}"
        print(f"  [PW] draft_save POST...")
        save_result = page.evaluate(
            """async ({url, payload}) => {
                const m = document.cookie.match(/XSRF-TOKEN=([^;]+)/);
                const xsrf = m ? decodeURIComponent(m[1]) : null;
                const headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                };
                if (xsrf) headers["X-XSRF-TOKEN"] = xsrf;
                const resp = await fetch(url, {
                    method: "POST",
                    headers: headers,
                    credentials: "include",
                    body: JSON.stringify(payload),
                });
                const body = await resp.text();
                return {status: resp.status, body: body, xsrf: !!xsrf};
            }""",
            {"url": save_url, "payload": save_payload}
        )
        print(f"  [PW] draft_save: status={save_result['status']}, xsrf={save_result['xsrf']}")
        if save_result["status"] not in (200, 201):
            browser.close()
            raise Exception(f"draft_save失敗: status={save_result['status']} body={save_result['body'][:300]}")

        # Step3: ハッシュタグ設定（別API）。失敗しても致命的でないので続行
        try:
            hashtag_payload = {
                "hashtag_notes_attributes": [
                    {"hashtag_attributes": {"name": tag}} for tag in hashtags[:10]
                ]
            }
            hashtag_url = f"{NOTE_API_BASE}/v1/text_notes/{note_key}"
            htg_result = page.evaluate(
                """async ({url, payload}) => {
                    const m = document.cookie.match(/XSRF-TOKEN=([^;]+)/);
                    const xsrf = m ? decodeURIComponent(m[1]) : null;
                    const headers = {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    };
                    if (xsrf) headers["X-XSRF-TOKEN"] = xsrf;
                    const resp = await fetch(url, {
                        method: "PUT",
                        headers: headers,
                        credentials: "include",
                        body: JSON.stringify(payload),
                    });
                    return {status: resp.status, body: await resp.text()};
                }""",
                {"url": hashtag_url, "payload": hashtag_payload}
            )
            print(f"  [PW] hashtag update: status={htg_result['status']}")
        except Exception as e:
            print(f"  [PW] hashtag update失敗（継続）: {e}")

        # Step4: publish
        article_url = None
        draft_only = False
        if publish:
            publish_urls = [
                f"{NOTE_API_BASE}/v2/notes/{note_key}/publish",
                f"{NOTE_API_BASE}/v1/notes/{note_key}/publish",
            ]
            published = False
            for purl in publish_urls:
                for method in ("PUT", "POST"):
                    try:
                        pub_result = page.evaluate(
                            """async ({url, method}) => {
                                const m = document.cookie.match(/XSRF-TOKEN=([^;]+)/);
                                const xsrf = m ? decodeURIComponent(m[1]) : null;
                                const headers = {
                                    "Content-Type": "application/json",
                                    "Accept": "application/json",
                                    "X-Requested-With": "XMLHttpRequest",
                                };
                                if (xsrf) headers["X-XSRF-TOKEN"] = xsrf;
                                const resp = await fetch(url, {
                                    method: method,
                                    headers: headers,
                                    credentials: "include",
                                    body: "{}",
                                });
                                return {status: resp.status, body: await resp.text()};
                            }""",
                            {"url": purl, "method": method}
                        )
                        print(f"  [PW] publish {method} {purl} → {pub_result['status']}")
                        if pub_result["status"] in (200, 201):
                            try:
                                pdata = json.loads(pub_result["body"])
                                inner = pdata.get("data", {})
                                user = inner.get("user", {}) if isinstance(inner.get("user"), dict) else {}
                                urlname = user.get("urlname", "")
                                if urlname:
                                    article_url = f"https://note.com/{urlname}/n/{note_key}"
                                else:
                                    article_url = f"https://note.com/n/{note_key}"
                            except Exception:
                                article_url = f"https://note.com/n/{note_key}"
                            published = True
                            break
                    except Exception as e:
                        print(f"  [PW] publish {method} {purl} 失敗: {e}")
                if published:
                    break
            if not published:
                draft_only = True
                article_url = f"https://note.com/notes/{note_key}/edit"

        browser.close()

    return {
        "key": note_key,
        "url": article_url,
        "draft_only": draft_only,
    }


def api_create_draft(session, title, body_html, hashtags, max_retries=2):
    """下書きを作成（リトライ・検証付き）。HTTPが 422で失敗した場合は Playwright 経由で再試行。"""
    last_error = None
    saw_422 = False

    for attempt in range(1, max_retries + 1):
        try:
            print(f"  下書き作成中... (試行 {attempt}/{max_retries})")
            note_data = _make_draft_payload(title, body_html, hashtags)

            # POST直前にCSRFトークンの有無を確認。無ければ再取得を試みる。
            if "X-XSRF-TOKEN" not in session.headers and "X-CSRF-Token" not in session.headers:
                print(f"  CSRFヘッダー未設定。再取得を試行...")
                _acquire_csrf_token(session)

            resp = session.post(f"{NOTE_API_BASE}/v1/text_notes", json=note_data, timeout=30)

            # 422はCSRF系/Origin系失敗典型。再取得して次試行で再実行させる。
            if resp.status_code == 422 and attempt < max_retries:
                saw_422 = True
                print(f"  422受信: {resp.text[:200]}")
                print(f"  CSRF再取得して再試行...")
                _clear_csrf_state(session)
                _acquire_csrf_token(session)

            if resp.status_code not in [200, 201]:
                if resp.status_code == 422:
                    saw_422 = True
                raise Exception(f"下書きHTTPエラー: {resp.status_code} - {resp.text[:300]}")

            try:
                data = resp.json()
            except Exception:
                raise Exception(f"下書きレスポンスがJSONではありません: {resp.text[:200]}")

            inner = data.get("data", {})
            note_id = inner.get("id")
            note_key = inner.get("key", "")

            if not note_id or not note_key:
                raise Exception(
                    f"下書きAPIがID/keyを返しませんでした (id={note_id}, key={note_key}). "
                    f"レスポンス: {json.dumps(data, ensure_ascii=False)[:300]}"
                )

            print(f"  下書き作成成功: ID={note_id}, key={note_key}")
            return note_id, note_key, data

        except Exception as e:
            last_error = e
            print(f"  下書き試行{attempt}失敗: {e}")
            if attempt < max_retries:
                time.sleep(3)

    # HTTP 全失敗時は _HttpCsrfFailed を投げて post_article 側で Playwright フォールバックさせる
    if saw_422 or "422" in str(last_error):
        raise _HttpCsrfFailed(str(last_error))
    raise Exception(f"下書き作成{max_retries}回失敗: {last_error}")


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
# 実際に公開済みの記事のみ（API確認済み 2026-04-09）
# 投稿済みの全記事（キーが不明な古い記事はダミー値）
PUBLISHED_KEYS = {
    1: "published", 2: "published", 3: "published", 4: "published",
    5: "published", 6: "published", 7: "published", 8: "published",
    9: "published", 10: "published", 11: "published", 12: "published",
    13: "published", 14: "published", 15: "published", 16: "published",
    17: "published", 18: "published", 19: "published", 20: "published",
    21: "published", 22: "published", 23: "published", 24: "published",
    25: "ne7911c5b9ce9", 26: "n9197ae57ed8a", 27: "ncf76e2e16aff",
    28: "n86c0f997ca68", 29: "na737000db46a", 30: "n7d6b128296e8",
    31: "n04dff5a7bd9c", 32: "n84121e6b7eab", 33: "ne57e6ea14042",
    34: "n6b2f4704cdcc", 35: "n699ef655effb", 36: "nc02030acfe75",
    37: "n17dbf76c743e", 38: "nplaceholder38",
    39: "n9b5e9d5abc25", 40: "n9bf9cb3baed8", 41: "n4857a2f79084",
    42: "n2a16d2f925ce", 43: "n01815f0e5285",
}


def get_published_article_nums():
    """投稿済み記事番号をPUBLISHED_KEYSとログから収集"""
    published = set(PUBLISHED_KEYS.keys())
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("success") == "True" and row.get("url"):
                    try:
                        published.add(int(row["article_num"]))
                    except (ValueError, KeyError):
                        pass
    return published


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
    # デバッグ: 最初の3件のkeyを表示
    for k, v in list(id_map.items())[:3]:
        print(f"    key={k} → id={v}")
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
                # CSRF系失敗の可能性 → HTML meta含む再取得
                _clear_csrf_state(session)
                _acquire_csrf_token(session)
        except Exception as e:
            print(f"    失敗: {e}")
            continue

    print(f"  ⚠ API更新失敗")
    return False


def update_article(article_num, session=None, note_id_map=None, dry_run=False):
    """既存記事を更新（新規下書き作成→公開で実質置換）"""
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
        # 新規下書き作成→公開（既存記事と同じタイトルで再投稿）
        note_id, note_key, _ = api_create_draft(session, title, body_html, hashtags)
        if not note_key:
            return {"success": False, "error": "draft_create_failed"}

        article_url = api_publish(session, note_key)
        if article_url:
            print(f"  再投稿成功: {article_url}")
            return {"success": True, "url": article_url}
        else:
            draft_url = f"https://note.com/notes/{note_key}/edit"
            print(f"  下書き保存済み（手動公開が必要）: {draft_url}")
            return {"success": True, "url": draft_url, "draft_only": True}
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

        # 下書き作成（HTTP）。422連発なら _HttpCsrfFailed が飛んでくるので Playwright 経路へ。
        try:
            note_id, note_key, result_data = api_create_draft(session, title, body_html, hashtags)
        except _HttpCsrfFailed as csrf_e:
            print(f"\n  HTTP経路がCSRFで失敗 → Playwright経路に切替: {csrf_e}")
            pw_result = _playwright_full_post(title, body_html, hashtags, publish=True)
            if pw_result["url"] and not pw_result["draft_only"]:
                log_result(article_num, title, pw_result["url"], True, "Playwright経由で公開")
                mark_as_published(article_num)
                return {"success": True, "url": pw_result["url"]}
            if pw_result["url"] and pw_result["draft_only"]:
                log_result(article_num, title, pw_result["url"], True, "Playwright経由で下書き保存（手動公開が必要）")
                mark_as_published(article_num)
                return {"success": True, "url": pw_result["url"], "draft_only": True}
            raise Exception("Playwrightフォールバックで公開URL取得失敗")

        if not note_key:
            raise Exception("note_keyが取得できませんでした")

        # 公開（失敗してもNoneが返るだけで例外にならない）
        article_url = api_publish(session, note_key)

        if article_url:
            log_result(article_num, title, article_url, True)
            mark_as_published(article_num)
            return {"success": True, "url": article_url}
        else:
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
        # 既に投稿済みの場合は警告して正常終了
        if article_num in get_published_article_nums():
            print(f"記事 #{article_num} は既に投稿済みです。スキップします。")
            sys.exit(0)
    elif args.post_latest:
        article_num = get_latest_unpublished()
        if article_num is None:
            print("未投稿の記事がありません（全て投稿済み）")
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
