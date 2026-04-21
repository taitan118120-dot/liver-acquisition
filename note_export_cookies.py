#!/usr/bin/env python3
"""
Note.com Cookieエクスポータ（ローカル実行用）
===============================================
GitHub Actions のボット検出でログインが弾かれるため、
ローカルで一度ログインして取得した Cookie を JSON で出力する。
出力された JSON を GitHub Secret `NOTE_COOKIES_JSON` に貼り付ける。

使い方:
  python3 note_export_cookies.py
    → Chromiumが開くので手動でログイン（CAPTCHAがあれば解く）
    → ログイン完了を検知したら note_cookies.json に書き出し、標準出力にも表示

Cookie が 1～3ヶ月程度で失効するため、ログインエラーが出たら再実行する。
"""

import json
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright が未インストールです。以下で導入してください:")
    print("  pip install playwright && playwright install chromium")
    sys.exit(1)


OUTPUT_FILE = Path(__file__).parent / "note_cookies.json"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(locale="ja-JP")
        page = ctx.new_page()

        print("Chromium を起動しました。note.com にアクセスし、手動でログインしてください。")
        print("ログイン完了後、このスクリプトが自動的に Cookie を取得します。")
        page.goto("https://note.com/login", wait_until="domcontentloaded", timeout=60000)

        # ログイン完了＝URLが/loginから外れる、を最大5分待つ
        deadline = time.time() + 300
        while time.time() < deadline:
            if "/login" not in page.url:
                break
            time.sleep(2)
        else:
            print("\n[ERROR] 5分以内にログインが完了しませんでした。中断します。")
            browser.close()
            sys.exit(1)

        # ログイン直後のJSロードと追加Cookie発行を待つ
        time.sleep(3)
        try:
            page.goto("https://note.com/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
        except Exception:
            pass

        cookies = ctx.cookies()
        browser.close()

    # 必要なCookieのみ保持（note.com関連）
    filtered = [c for c in cookies if "note.com" in c.get("domain", "")]
    if not filtered:
        print("[ERROR] note.com の Cookie が取得できませんでした。")
        sys.exit(1)

    payload = json.dumps(filtered, ensure_ascii=False)
    OUTPUT_FILE.write_text(payload, encoding="utf-8")

    print(f"\n✅ {len(filtered)}個のCookieを {OUTPUT_FILE} に保存しました。")
    print("\n--- GitHub Secret `NOTE_COOKIES_JSON` に以下を貼り付け ---")
    print(payload)
    print("--- ここまで ---\n")
    print("GitHub の Settings → Secrets and variables → Actions → New repository secret で")
    print("Name: NOTE_COOKIES_JSON, Secret: 上記のJSON を登録してください。")


if __name__ == "__main__":
    main()
