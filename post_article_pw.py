#!/usr/bin/env python3
"""記事番号を指定して Playwright UI 経由で公開する。
note_auto_poster.py の _playwright_full_post を再利用。
"""
import json, sys, os

# 環境変数にCookieをセット
with open("note_cookies.json", encoding="utf-8") as f:
    os.environ["NOTE_COOKIES_JSON"] = f.read()

# note_auto_poster を import して再利用
import note_auto_poster as nap

ARTICLE_NUM = int(sys.argv[1]) if len(sys.argv) > 1 else 48

filepath = nap.get_article_file(ARTICLE_NUM)
if not filepath:
    print(f"記事ファイル見つからず: #{ARTICLE_NUM}"); sys.exit(1)

title, body = nap.parse_article(filepath)
hashtags = nap.get_hashtags_for_article(ARTICLE_NUM)
body_fmt = nap.format_body_for_note(body)
body_html = nap.markdown_to_html(body_fmt)

print(f"記事: #{ARTICLE_NUM} タイトル: {title}")
print(f"文字数: {len(body_fmt)}")
print(f"ハッシュタグ: {hashtags[:10]}")
print()

result = nap._playwright_full_post(title, body_html, hashtags, publish=True)
print()
print("=== RESULT ===")
print(json.dumps(result, ensure_ascii=False, indent=2))

if result.get("url") and not result.get("draft_only"):
    print(f"\n✅ 公開成功: {result['url']}")
    nap.log_result(ARTICLE_NUM, title, result['url'], True, "Playwright UI経由で公開")
    nap.mark_as_published(ARTICLE_NUM)
elif result.get("url") and result.get("draft_only"):
    print(f"\n⚠ 下書き保存のみ（公開失敗）: {result['url']}")
    nap.log_result(ARTICLE_NUM, title, result['url'], True, "下書き保存（手動公開が必要）")
else:
    print("\n✗ 投稿失敗")
    sys.exit(1)
