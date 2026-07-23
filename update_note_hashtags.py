#!/usr/bin/env python3
"""Update hashtags on already-published Note articles via Playwright UI (publish page)."""
import json
import os
import sys
import time
from pathlib import Path

with open("note_cookies.json", encoding="utf-8") as f:
    os.environ["NOTE_COOKIES_JSON"] = f.read()

import note_auto_poster as nap
from playwright.sync_api import sync_playwright

ARTICLES = [
    (1, "n56e9a993492d"),
    (2, "n2dc730f02053"),
    (3, "n455d6d379ce6"),
    (4, "n80252e1ef58c"),
    (5, "n80a29386b5a8"),
    (6, "n490e9578f165"),
    (7, "n3755103dc22e"),
    (8, "nddb6b019f91f"),
    (9, "n79d526cf01a9"),
    (13, "n75af519474d1"),
    (15, "n03be7c901596"),
    (16, "na36a4968c3bc"),
    (44, "nec84b0c1dc2e"),
    (45, "na128c4f02806"),
    (46, "n9bf3240d2dbd"),
    (47, "ndb58de31b4de"),
    (48, "n6194f89cb2aa"),
    (49, "n19e20c40b3f1"),
    (50, "nadf7bf475ea9"),
    (51, "n205ef04edcbb"),
    (52, "nd29c18b06dcc"),
    (53, "ne8d3dbf2befc"),
    (54, "nf58c6a743c2a"),
]


def update_one(page, num, key):
    hashtags = nap.get_hashtags_for_article(num)
    print(f"  hashtags={hashtags}")

    # Open editor first (loads cookies properly), then go to publish
    edit_url = f"https://editor.note.com/notes/{key}/edit/"
    page.goto(edit_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    # Click 公開に進む
    page.locator('button:has-text("公開に進む")').first.click()
    page.wait_for_timeout(5000)

    # Find hashtag input
    tag_input = page.locator('input[placeholder="ハッシュタグを追加する"]').first
    if tag_input.count() == 0:
        print("  [ERR] ハッシュタグ入力欄が見つからず")
        return False

    # Type each hashtag and press Enter
    for tag in hashtags[:10]:
        try:
            tag_input.click()
            page.wait_for_timeout(300)
            tag_input.fill(tag)
            page.wait_for_timeout(500)
            tag_input.press("Enter")
            page.wait_for_timeout(800)
            print(f"    + #{tag}")
        except Exception as e:
            print(f"    [WARN] tag {tag} 失敗: {e}")

    page.wait_for_timeout(2000)

    # Click 更新する / 投稿する / 公開する
    clicked = False
    for sel in [
        'button:has-text("更新する")',
        'button:has-text("投稿する")',
        'button:has-text("公開する")',
    ]:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                loc.click()
                print(f"  [PW] 公開ボタン: {sel}")
                clicked = True
                page.wait_for_timeout(5000)
                break
        except Exception:
            continue

    if not clicked:
        print("  [WARN] 更新/投稿ボタン見つからず")
    return clicked


def main():
    cookies = json.loads(Path("note_cookies.json").read_text())
    for c in cookies:
        c["sameSite"] = (c.get("sameSite") or "Lax").capitalize()

    only = sys.argv[1] if len(sys.argv) > 1 else None
    targets = [a for a in ARTICLES if (only is None or str(a[0]) == only)]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="ja-JP",
            viewport={"width": 1280, "height": 1400},
        )
        ctx.add_cookies(cookies)
        page = ctx.new_page()

        results = []
        for num, key in targets:
            print(f"\n=== #{num} key={key} ===")
            try:
                ok = update_one(page, num, key)
            except Exception as e:
                print(f"  [ERR] {e}")
                ok = False
            results.append((num, ok))
            time.sleep(2)

        browser.close()

    print("\n=== RESULT ===")
    for num, ok in results:
        print(f"  #{num}: {'OK' if ok else 'NG'}")


if __name__ == "__main__":
    main()
