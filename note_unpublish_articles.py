#!/usr/bin/env python3
"""公開済みnote記事を下書きに戻す（非公開化）。

確定ファクトと矛盾する記事を公開から下ろすための道具。
下ろす前に本文・タイトル・タグ・eyecatchを blog/articles_note_unpublished/ にJSONで退避するので、
あとから内容を復元・再利用できる。

機構は note_cta_publish.py と同じ（Chrome cookie + Playwright + XSRF）。
change_status API が使えない場合は PUT /v1/text_notes/{id} status=draft にフォールバックする。

使い方:
  python3 note_unpublish_articles.py --dry-run <key> [<key> ...]   # 退避のみ、公開状態は触らない
  python3 note_unpublish_articles.py <key> [<key> ...]
  python3 note_unpublish_articles.py --verify <key>                # 現在のstatusを確認
"""
import json
import os
import sys
import time

import note_keys_registry
from note_cta_publish import NOTE_API, UA, chrome_cookies, get_note, req_session

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, "blog", "articles_note_unpublished")


def backup(d):
    """下書きに戻す前に本文一式をローカルへ退避する。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    key = d["key"]
    payload = {
        "key": key,
        "id": d["id"],
        "name": d["name"],
        "body": d["body"],
        "tags": [h["hashtag"]["name"] for h in d.get("hashtag_notes", [])],
        "eyecatch": d.get("eyecatch"),
        "publish_at": d.get("publish_at"),
        "unpublished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    path = os.path.join(BACKUP_DIR, f"{key}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"  backup -> {os.path.relpath(path, BASE_DIR)} ({len(d['body'])}字)")
    return path


def verify(key):
    s = req_session()
    d = get_note(s, key, draft=False)
    print(f"  status={d['status']}  title={d['name'][:40]}")
    return d


def unpublish_one(key, dry_run=False):
    from playwright.sync_api import sync_playwright

    s = req_session()
    d = get_note(s, key, draft=False)
    note_id = d["id"]
    print(f"  id={note_id} status={d['status']} title={d['name'][:36]}")
    backup(d)

    if d["status"] != "published":
        print("  already not published — skip")
        # 既に下書きなのに公開キー台帳に残っているケースを取りこぼさない
        if not dry_run:
            note_keys_registry.remove(key, reason="already draft")
        return d
    if dry_run:
        print("  [dry-run] change_status は実行しない")
        return d

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(user_agent=UA, locale="ja-JP",
                                  viewport={"width": 1400, "height": 900})
        ctx.add_cookies(chrome_cookies())
        page = ctx.new_page()
        page.goto(f"https://editor.note.com/notes/{key}/edit",
                  wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        time.sleep(3)

        js = """async ({url, method, payload}) => {
            const m=document.cookie.match(/XSRF-TOKEN=([^;]+)/);
            const h={"Content-Type":"application/json","Accept":"application/json","X-Requested-With":"XMLHttpRequest"};
            if(m)h["X-XSRF-TOKEN"]=decodeURIComponent(m[1]);
            const r=await fetch(url,{method:method,headers:h,credentials:"include",body:JSON.stringify(payload)});
            return {status:r.status, body:(await r.text()).slice(0,300)};
        }"""

        res = page.evaluate(js, {
            "url": f"{NOTE_API}/v2/notes/{key}/change_status",
            "method": "POST",
            "payload": {"status": "draft"},
        })
        print(f"  change_status: {res['status']} {res['body'][:120]}")

        if res["status"] not in (200, 201, 204):
            # フォールバック: 本文ごとPUTでdraftに落とす
            tags = [h["hashtag"]["name"].lstrip("#") for h in d.get("hashtag_notes", [])][:10]
            res = page.evaluate(js, {
                "url": f"{NOTE_API}/v1/text_notes/{note_id}",
                "method": "PUT",
                "payload": {
                    "status": "draft", "name": d["name"],
                    "free_body": d["body"], "pay_body": "", "body_length": len(d["body"]),
                    "price": 0, "hashtags": tags,
                    "disable_comment": bool(d.get("disable_comment", False)),
                    "send_notifications_flag": False,
                    "limited": bool(d.get("is_limited", False)),
                },
            })
            print(f"  PUT draft (fallback): {res['status']} {res['body'][:120]}")

        browser.close()
        if res["status"] not in (200, 201, 204):
            raise SystemExit(f"非公開化に失敗 (key={key}): {res}")

    time.sleep(2)
    print("  --- verify ---")
    d = verify(key)
    # 公開から下ろせたら公開キー台帳からも外す（一括処理が死にキーを踏まないように）
    if d["status"] != "published":
        note_keys_registry.remove(key, reason="unpublish")
    return d


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    if args[0] == "--verify":
        for k in args[1:]:
            print(f"[verify {k}]")
            verify(k)
    else:
        dry = args[0] == "--dry-run"
        keys = args[1:] if dry else args
        for k in keys:
            print(f"[unpublish {k}]")
            unpublish_one(k, dry_run=dry)
