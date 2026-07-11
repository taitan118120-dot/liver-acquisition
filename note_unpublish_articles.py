#!/usr/bin/env python3
"""note公開記事を「下書きに戻す」(削除はしない)。

エンドポイントは記事管理UI(note.com/notes)の「下書きに戻す」と同じ:
  POST /api/v2/notes/{key}/change_status  {"status":"draft"}

- Chrome cookie + Playwright（XSRF-TOKEN取得のためnote.comを一度開く）
- 実行前に記事全データを data/unpublished_backup/{key}.json へ退避（復元用）
- 実行後 GET で status=draft を検証

使い方:
  python3 note_unpublish_articles.py <key> [<key> ...]
"""
import json
import os
import sys
import time

from note_cta_publish import NOTE_API, UA, chrome_cookies, get_note, req_session

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, "data", "unpublished_backup")


def backup(key, d):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"{key}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "key": key, "id": d["id"], "name": d["name"], "body": d["body"],
            "hashtags": [h["hashtag"]["name"] for h in d.get("hashtag_notes", [])],
            "eyecatch": d.get("eyecatch"), "publish_at": d.get("publish_at"),
        }, f, ensure_ascii=False, indent=1)
    print(f"  backup: {path}")


def main(keys):
    from playwright.sync_api import sync_playwright
    s = req_session()
    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="ja-JP",
                                  viewport={"width": 1400, "height": 900})
        ctx.add_cookies(chrome_cookies())
        page = ctx.new_page()
        page.goto("https://note.com/notes", wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)

        for i, key in enumerate(keys, 1):
            print(f"[{i}/{len(keys)}] {key}")
            try:
                d = get_note(s, key, draft=False)
                if d.get("status") == "draft":
                    print("  skip（既にdraft）")
                    results[key] = "skip"
                    continue
                backup(key, d)
                r = page.evaluate("""async (key) => {
                    const m=document.cookie.match(/XSRF-TOKEN=([^;]+)/);
                    const h={"Content-Type":"application/json","Accept":"application/json","X-Requested-With":"XMLHttpRequest"};
                    if(m)h["X-XSRF-TOKEN"]=decodeURIComponent(m[1]);
                    const r=await fetch(`https://note.com/api/v2/notes/${key}/change_status`,
                        {method:"POST",headers:h,credentials:"include",body:JSON.stringify({status:"draft"})});
                    return {status:r.status, body:(await r.text()).slice(0,200)};
                }""", key)
                print(f"  change_status -> {r['status']}")
                time.sleep(2)
                dv = get_note(req_session(), key)
                if dv.get("status") != "draft":
                    raise RuntimeError(f"statusが{dv.get('status')}のまま (api={r})")
                print("  ✅ 下書きに戻した")
                results[key] = "ok"
            except Exception as e:
                print(f"  [FAIL] {e}")
                results[key] = f"fail: {e}"
            time.sleep(5)
        browser.close()

    print("\n=== 結果 ===")
    for k, v in results.items():
        print(f"  {k}: {v}")
    return results


if __name__ == "__main__":
    keys = sys.argv[1:]
    if not keys:
        print(__doc__)
        raise SystemExit(1)
    main(keys)
