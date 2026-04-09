#!/usr/bin/env python3
"""
Note.com 自動投稿（Playwright）
================================
生成済みのMarkdown記事をNote.comに自動投稿する。

使い方:
  python3 note_auto_poster.py --post-latest            # 最新未投稿記事を投稿
  python3 note_auto_poster.py --post 27                 # 指定番号の記事を投稿
  python3 note_auto_poster.py --post-latest --headed    # ブラウザ表示モード
  python3 note_auto_poster.py --post-latest --dry-run   # 投稿せず確認のみ

環境変数:
  NOTE_EMAIL    - Note.comログインメール
  NOTE_PASSWORD - Note.comログインパスワード

必要:
  pip install playwright
  playwright install chromium
"""

import os
import re
import sys
import csv
import glob
import json
import asyncio
import argparse
import random
from datetime import datetime

# ─── パス設定 ─────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTICLES_DIR = os.path.join(BASE_DIR, "blog", "articles_note")
DATA_DIR = os.path.join(BASE_DIR, "data")
TRACKER_FILE = os.path.join(DATA_DIR, "note_keyword_tracker.json")
LOG_FILE = os.path.join(DATA_DIR, "note_auto_post_log.csv")
SCREENSHOTS_DIR = os.path.join(DATA_DIR, "note_screenshots")
SESSION_FILE = os.path.join(DATA_DIR, "note_session.json")

# ─── Note.com セレクタ ────────────────────────────────
# Note.comのUI変更時はここを修正
SELECTORS = {
    # ログイン（Note.com 2026年版セレクタ）
    "login_email": '.o-login__mailField input, input[name="login"], input[type="email"], input[placeholder*="メール"], input[placeholder*="アドレス"]',
    "login_password": '.o-login__mailField input[type="password"], input[name="password"], input[type="password"]',
    "login_submit": '.o-login__button, button[data-type="primary"], button[type="submit"], button:has-text("ログイン")',

    # エディタ
    "editor_title": '.p-editor__title textarea, [placeholder*="タイトル"], .o-noteContentHeader__title textarea',
    "editor_body": '.ProseMirror, [contenteditable="true"], .p-editor__body [contenteditable]',

    # 公開設定
    "publish_menu": 'button:has-text("公開設定"), button:has-text("投稿の設定")',
    "hashtag_input": 'input[placeholder*="タグ"], input[placeholder*="ハッシュタグ"], .p-editor__hashtag input',
    "publish_button": 'button:has-text("投稿する"), button:has-text("公開")',
    "publish_confirm": 'button:has-text("投稿する")',
}

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
    # トラッカーからハッシュタグを取得
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            tracker = json.load(f)
        for item in tracker.get("used", []):
            if item.get("article_number") == article_num:
                # note_article_generatorのSEO_KEYWORDSからhashtags取得
                try:
                    from note_article_generator import SEO_KEYWORDS
                    for cat_keywords in SEO_KEYWORDS.values():
                        for kw in cat_keywords:
                            if kw["slug"] == item.get("slug"):
                                return kw["hashtags"]
                except ImportError:
                    pass

    # note_publisher.pyのHASHTAG_MAPからフォールバック
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
        # トラッカーがない場合は最大番号の記事
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

    # Markdown記号を削除（Note.comのリッチエディタ向け）
    # H2/H3はNote.comが認識するのでそのまま
    # 太字もNote.comペースト時に認識される
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


async def random_delay(min_sec=1.0, max_sec=3.0):
    """ランダムな待機（ボット検知対策）"""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def save_screenshot(page, name):
    """デバッグ用スクリーンショット保存"""
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(SCREENSHOTS_DIR, f"{ts}_{name}.png")
    await page.screenshot(path=path, full_page=False)
    print(f"  screenshot: {path}")


async def try_selector(page, selectors_str, timeout=10000):
    """カンマ区切りのセレクタを順番に試す"""
    for selector in selectors_str.split(", "):
        try:
            el = await page.wait_for_selector(selector.strip(), timeout=timeout)
            if el:
                return el
        except Exception:
            continue
    return None


# ─── Playwright 自動投稿 ──────────────────────────────

async def login_to_note(page, email, password):
    """Note.comにログイン"""
    print("  ログイン中...")

    # networkidleはCI環境で不安定なのでdomcontentloadedで待機後に追加待機
    await page.goto("https://note.com/login", wait_until="domcontentloaded")
    await random_delay(3, 5)

    # メールアドレス入力（リトライ付き）
    email_el = await try_selector(page, SELECTORS["login_email"], timeout=15000)
    if not email_el:
        # ページが完全にロードされていない可能性 → 追加待機してリトライ
        print("  メール欄が見つからないため5秒追加待機してリトライ...")
        await save_screenshot(page, "login_retry_wait")
        await asyncio.sleep(5)
        email_el = await try_selector(page, SELECTORS["login_email"], timeout=15000)
    if not email_el:
        await save_screenshot(page, "login_fail_email")
        raise Exception("ログインフォームのメール欄が見つかりません")

    await email_el.fill(email)
    await random_delay(0.5, 1.0)

    # パスワード入力
    pass_el = await try_selector(page, SELECTORS["login_password"])
    if not pass_el:
        await save_screenshot(page, "login_fail_password")
        raise Exception("ログインフォームのパスワード欄が見つかりません")

    await pass_el.fill(password)
    await random_delay(0.5, 1.0)

    # reCAPTCHAチェックボックスがある場合はクリック
    try:
        recaptcha_frame = page.frame_locator("iframe[src*='recaptcha'], iframe[title*='reCAPTCHA']")
        recaptcha_checkbox = recaptcha_frame.locator("#recaptcha-anchor, .recaptcha-checkbox-border")
        if await recaptcha_checkbox.count() > 0:
            print("  reCAPTCHA検出、チェックボックスをクリック...")
            await recaptcha_checkbox.first.click()
            await random_delay(2, 4)
            await save_screenshot(page, "after_recaptcha_click")
    except Exception as e:
        print(f"  reCAPTCHA処理スキップ: {e}")

    # ログインボタンクリック
    submit_el = await try_selector(page, SELECTORS["login_submit"])
    if not submit_el:
        await save_screenshot(page, "login_fail_submit")
        raise Exception("ログインボタンが見つかりません")

    await submit_el.click()
    await random_delay(2, 3)

    # ログイン完了を待つ（複数パターンに対応）
    try:
        await page.wait_for_url("**/dashboard**", timeout=20000)
    except Exception:
        # ダッシュボードではなくトップページや別ページに遷移する場合もある
        current_url = page.url
        if "login" not in current_url:
            print(f"  ログイン成功（リダイレクト先: {current_url}）")
        else:
            await save_screenshot(page, "login_fail_redirect")
            raise Exception("ログインに失敗しました（ログインページのまま）")

    print("  ログイン成功")
    await random_delay(1, 2)


async def create_article(page, title, body, hashtags):
    """記事を作成して公開"""
    print("  新規記事作成中...")

    # 新規記事エディタを開く
    await page.goto("https://note.com/new", wait_until="networkidle")
    await random_delay(2, 3)

    # タイトル入力
    print("  タイトル入力中...")
    title_el = await try_selector(page, SELECTORS["editor_title"], timeout=15000)
    if not title_el:
        await save_screenshot(page, "editor_fail_title")
        raise Exception("タイトル入力欄が見つかりません")

    await title_el.click()
    await page.keyboard.type(title, delay=20)
    await random_delay(1, 2)

    # 本文入力
    print("  本文入力中...")
    body_el = await try_selector(page, SELECTORS["editor_body"], timeout=10000)
    if not body_el:
        await save_screenshot(page, "editor_fail_body")
        raise Exception("本文入力欄が見つかりません")

    await body_el.click()
    await random_delay(0.5, 1.0)

    # 本文をJavaScript経由で直接入力（CI headless環境でも動作する）
    # ProseMirrorエディタに対してdispatchEventでテキストを挿入
    paste_success = await page.evaluate("""(text) => {
        const editor = document.querySelector('.ProseMirror, [contenteditable="true"]');
        if (!editor) return false;
        editor.focus();

        // DataTransfer経由でペーストイベントをシミュレート
        const dt = new DataTransfer();
        dt.setData('text/plain', text);
        const pasteEvent = new ClipboardEvent('paste', {
            clipboardData: dt,
            bubbles: true,
            cancelable: true,
        });
        editor.dispatchEvent(pasteEvent);
        return true;
    }""", body)
    await random_delay(2, 3)

    # ペーストイベントが効かなかった場合のフォールバック
    body_content = await body_el.text_content()
    if not body_content or len(body_content.strip()) < 100:
        print("  ペーストイベント失敗、insertTextで再試行...")
        await body_el.click()
        # execCommandでinsertText（Playwright insert_textの代替）
        await page.evaluate("""(text) => {
            const editor = document.querySelector('.ProseMirror, [contenteditable="true"]');
            if (editor) {
                editor.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('delete', false, null);
                document.execCommand('insertText', false, text);
            }
        }""", body)
        await random_delay(2, 3)

    # それでもダメならキーボード入力（最終手段）
    body_content = await body_el.text_content()
    if not body_content or len(body_content.strip()) < 100:
        print("  execCommand失敗、keyboard.typeで再試行（低速）...")
        await body_el.click()
        await page.keyboard.press("Control+KeyA")
        await page.keyboard.press("Delete")
        # 長文はチャンクに分割して入力
        chunk_size = 500
        for i in range(0, len(body), chunk_size):
            chunk = body[i:i+chunk_size]
            await page.keyboard.insert_text(chunk)
            await random_delay(0.2, 0.5)
        await random_delay(2, 3)

    # 公開設定
    print("  公開設定中...")
    await save_screenshot(page, "before_publish_settings")

    # ハッシュタグを入力（公開設定メニュー内）
    publish_menu = await try_selector(page, SELECTORS["publish_menu"], timeout=5000)
    if publish_menu:
        await publish_menu.click()
        await random_delay(1, 2)

        # ハッシュタグ入力
        tag_input = await try_selector(page, SELECTORS["hashtag_input"], timeout=5000)
        if tag_input:
            for tag in hashtags[:10]:  # Note.comはタグ10個まで
                await tag_input.fill(tag)
                await page.keyboard.press("Enter")
                await random_delay(0.3, 0.5)
            print(f"  ハッシュタグ設定: {' '.join('#' + t for t in hashtags[:10])}")

    # 投稿ボタンクリック
    print("  投稿中...")
    publish_btn = await try_selector(page, SELECTORS["publish_button"], timeout=5000)
    if not publish_btn:
        await save_screenshot(page, "publish_fail_button")
        raise Exception("投稿ボタンが見つかりません")

    await publish_btn.click()
    await random_delay(1, 2)

    # 確認ダイアログがある場合
    confirm_btn = await try_selector(page, SELECTORS["publish_confirm"], timeout=3000)
    if confirm_btn:
        await confirm_btn.click()

    # 投稿完了を待つ（URLが /n/ を含むページに遷移）
    try:
        await page.wait_for_url("**/n/**", timeout=20000)
        article_url = page.url
        print(f"  投稿成功: {article_url}")
        return article_url
    except Exception:
        await save_screenshot(page, "publish_fail_redirect")
        # URLが変わっていれば成功の可能性
        if "/n/" in page.url:
            return page.url
        raise Exception("投稿完了の確認に失敗しました")


async def post_article(article_num, headless=True, dry_run=False):
    """メインの投稿処理"""
    from playwright.async_api import async_playwright

    filepath = get_article_file(article_num)
    if not filepath:
        print(f"記事ファイルが見つかりません: #{article_num}")
        return {"success": False, "error": "file_not_found"}

    title, body = parse_article(filepath)
    hashtags = get_hashtags_for_article(article_num)
    formatted_body = format_body_for_note(body)

    print(f"\n{'='*50}")
    print(f"  Note.com 自動投稿")
    print(f"{'='*50}")
    print(f"  記事: #{article_num}")
    print(f"  タイトル: {title}")
    print(f"  文字数: {len(formatted_body)}文字")
    print(f"  ハッシュタグ: {' '.join('#' + t for t in hashtags[:10])}")

    if dry_run:
        print("\n  [dry-run] 投稿スキップ")
        return {"success": True, "dry_run": True}

    email, password = get_credentials()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ja-JP",
            permissions=["clipboard-read", "clipboard-write"],
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        # webdriver検知を回避
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)
        page = await context.new_page()

        try:
            # ログイン
            await login_to_note(page, email, password)

            # 記事作成＆投稿
            article_url = await create_article(page, title, formatted_body, hashtags)

            # 成功ログ
            log_result(article_num, title, article_url, True)
            mark_as_published(article_num)

            return {"success": True, "url": article_url}

        except Exception as e:
            error_msg = str(e)
            print(f"\n  エラー: {error_msg}")
            await save_screenshot(page, "error_final")
            log_result(article_num, title, "", False, error_msg)
            return {"success": False, "error": error_msg}

        finally:
            await browser.close()


# ─── CLI ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Note.com 自動投稿（Playwright）")
    parser.add_argument("--post", type=int, help="指定番号の記事を投稿")
    parser.add_argument("--post-latest", action="store_true", help="最新未投稿記事を投稿")
    parser.add_argument("--headed", action="store_true", help="ブラウザ表示モード（デバッグ用）")
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

    headless = not args.headed

    result = asyncio.run(post_article(article_num, headless=headless, dry_run=args.dry_run))

    if result.get("success"):
        print("\n投稿完了!")
    else:
        print(f"\n投稿失敗: {result.get('error', 'unknown')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
