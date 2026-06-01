#!/usr/bin/env python3
"""
Note.com Cookieエクスポータ（ログイン検知強化版）
===================================================
Chromium を開き、ユーザが手動でログインするのを待つ。
`/api/v2/current_user` が 200 を返したら認証済みと判定し、
XSRF-TOKEN 発行のため複数ページを訪問してから Cookie を書き出す。

使い方:
  python3 note_export_cookies.py
    → Chromium が開く
    → 手動でログイン（CAPTCHA があれば解く）
    → 認証完了を検知すると note_cookies.json を書き出す
    → 標準出力に貼り付け用 JSON を表示

出力された JSON を GitHub Secret `NOTE_COOKIES_JSON` に登録する。
Cookie は 1〜3 ヶ月程度で失効するので、ログインエラー時は再実行。
"""

import json
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright が未インストールです:")
    print("  pip install playwright && playwright install chromium")
    sys.exit(1)

OUTPUT_FILE = Path(__file__).parent / "note_cookies.json"


def log(m):
    print(m, flush=True)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = browser.new_context(
            locale="ja-JP",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()

        log("=" * 60)
        log("Chromium起動。note.com にログインしてください（CAPTCHA 対応可）")
        log("最大 30 分待機します")
        log("=" * 60)

        page.goto("https://note.com/login", wait_until="domcontentloaded", timeout=60000)

        # /api/v2/current_user が 200 を返すまで = 認証成功
        deadline = time.time() + 1800
        authenticated = False
        while time.time() < deadline:
            try:
                r = ctx.request.get("https://note.com/api/v2/current_user", timeout=10000)
                if r.status == 200:
                    try:
                        data = r.json().get("data", {})
                        urlname = data.get("urlname") or data.get("url_name") or ""
                        log(f"[✓] 認証成功: urlname={urlname}")
                    except Exception:
                        log("[✓] 認証成功")
                    authenticated = True
                    break
            except Exception:
                pass
            time.sleep(3)

        if not authenticated:
            log("[ERROR] 30 分以内にログインを検知できませんでした")
            browser.close()
            sys.exit(1)

        # XSRF-TOKEN 発行のため複数ページ訪問
        log("XSRF-TOKEN 発行のため各ページ訪問中...")
        for url in [
            "https://note.com/",
            "https://note.com/settings/account",
            "https://editor.note.com/new",
            "https://note.com/notes",
        ]:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
            except Exception as e:
                log(f"  [WARN] {url}: {e}")

        all_cookies = ctx.cookies()
        browser.close()

    filtered = [c for c in all_cookies if "note.com" in c.get("domain", "")]
    names = sorted({c["name"] for c in filtered})
    log(f"取得Cookie: {names}")

    if "_note_session_v5" not in names:
        log("[ERROR] セッションCookie無し（ログインが完了していない可能性）")
        sys.exit(1)

    if "XSRF-TOKEN" not in names:
        log("[WARN] XSRF-TOKEN は含まれていません（CI側の HTTP→Playwright フォールバックで対処）")

    payload = json.dumps(filtered, ensure_ascii=False)
    OUTPUT_FILE.write_text(payload, encoding="utf-8")
    log(f"\n✅ {len(filtered)}個のCookieを {OUTPUT_FILE} に保存しました")
    log("")
    log("--- GitHub Secret `NOTE_COOKIES_JSON` に貼り付け ---")
    print(payload)
    log("--- ここまで ---")
    log("")
    log("GitHub → Settings → Secrets and variables → Actions → `NOTE_COOKIES_JSON` を Update")


if __name__ == "__main__":
    main()
