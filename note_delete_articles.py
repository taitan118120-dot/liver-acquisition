#!/usr/bin/env python3
"""note_delete_articles.py
Note記事をPlaywright APIRequestContext経由で削除する。

UI経路ではなく、editor.note.com を一度開いて XSRF-TOKEN を取得し、
DELETE /v1/text_notes/{numeric_id} を叩く方式。

使い方:
  python3 note_delete_articles.py n32e19bc0275b necfcd86dd8ba n2d38df3d89d4
"""
import json
import os
import re
import sys
import time
from urllib.parse import unquote

import note_keys_registry

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_cookies():
    with open(os.path.join(BASE_DIR, "note_cookies.json"), encoding="utf-8") as f:
        cookies = json.load(f)
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
    return pw_cookies


def delete_one(note_key, headless=True):
    print(f"\n── 削除開始: {note_key} ──")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
            locale="ja-JP",
            viewport={"width": 1400, "height": 900},
        )
        ctx.add_cookies(load_cookies())
        page = ctx.new_page()

        # editor.note.com を開いて note_id (数値) と XSRF-TOKEN を取得
        edit_url = f"https://editor.note.com/notes/{note_key}/edit"
        print(f"  [PW] open {edit_url}")

        # API応答からnote_idを拾う
        note_id = None

        def _on_response(resp):
            nonlocal note_id
            if note_id is not None:
                return
            url = resp.url
            # /api/v1/text_notes?key=... or /api/v3/notes?key=... 等
            if ("/v1/text_notes" in url or "/v3/notes" in url) and resp.request.method == "GET":
                try:
                    body = resp.text()
                    data = json.loads(body)
                    # data.id か data.data.id を辿る
                    for path in [
                        ("data", "id"),
                        ("note", "id"),
                        ("id",),
                    ]:
                        cur = data
                        ok = True
                        for k in path:
                            if isinstance(cur, dict) and k in cur:
                                cur = cur[k]
                            else:
                                ok = False
                                break
                        if ok and isinstance(cur, int):
                            note_id = cur
                            print(f"  [PW] note_id 取得: {note_id} (from {url[:60]})")
                            return
                except Exception:
                    pass

        page.on("response", _on_response)

        try:
            page.goto(edit_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"  [PW] goto失敗: {e}")
            browser.close()
            return {"ok": False, "reason": "goto failed"}

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        time.sleep(3)

        # note_id がレスポンスから取れていない場合、ページのHTMLから抽出を試みる
        if note_id is None:
            html = page.content()
            # __NEXT_DATA__ や inline JSON から id を探す
            m = re.search(r'"id":\s*(\d{6,12})\s*,\s*"key":\s*"' + re.escape(note_key) + r'"', html)
            if m:
                note_id = int(m.group(1))
                print(f"  [PW] note_id 抽出 (HTML): {note_id}")

        if note_id is None:
            # 別アプローチ: API直接叩き（draft_save等から逆算）
            try:
                api_resp = ctx.request.get(f"https://note.com/api/v1/text_notes?key={note_key}",
                                           headers={"Accept": "application/json"})
                api_body = api_resp.text()
                data = json.loads(api_body)
                if isinstance(data, dict):
                    cur = data.get("data") or data
                    if isinstance(cur, dict) and "id" in cur:
                        note_id = cur["id"]
                        print(f"  [PW] note_id (API direct): {note_id}")
            except Exception as e:
                print(f"  [PW] API direct fetch失敗: {e}")

        if note_id is None:
            print("  [PW] ❌ note_id 取得不可")
            browser.close()
            return {"ok": False, "reason": "note_id_not_found"}

        # XSRF-TOKEN取得
        browser_cookies = ctx.cookies()
        xsrf = None
        for c in browser_cookies:
            if c["name"] == "XSRF-TOKEN":
                xsrf = unquote(c["value"])
                break

        headers = {
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": edit_url,
            "Origin": "https://editor.note.com",
        }
        if xsrf:
            headers["X-XSRF-TOKEN"] = xsrf

        # 複数のエンドポイントを順に試す
        endpoints = [
            ("DELETE", f"https://note.com/api/v3/notes/{note_key}"),
            ("DELETE", f"https://note.com/api/v3/notes/{note_id}"),
            ("DELETE", f"https://note.com/api/v1/notes/{note_id}"),
            ("DELETE", f"https://note.com/api/v1/text_notes/{note_id}"),
            ("DELETE", f"https://note.com/api/v2/text_notes/{note_id}"),
            ("POST",   f"https://note.com/api/v3/notes/{note_key}/delete"),
            ("POST",   f"https://note.com/api/v1/text_notes/{note_id}/delete"),
        ]

        last_status = None
        last_body = ""
        for method, url in endpoints:
            print(f"  [PW] {method} {url}")
            try:
                if method == "DELETE":
                    r = ctx.request.delete(url, headers=headers)
                else:
                    r = ctx.request.post(url, headers=headers, data="{}")
                last_status = r.status
                last_body = r.text()[:160]
                print(f"      → status={last_status} body={last_body!r}")
                if last_status in (200, 204):
                    print(f"  [PW] ✅ 削除成功")
                    browser.close()
                    # 削除できたら公開キー台帳からも外す（一括処理が死にキーを踏まないように）
                    note_keys_registry.remove(note_key, reason="delete")
                    return {"ok": True, "status": last_status,
                            "note_id": note_id, "endpoint": f"{method} {url}"}
            except Exception as e:
                print(f"      → 例外: {e}")

        browser.close()
        return {"ok": False, "status": last_status, "note_id": note_id, "body": last_body}


def main():
    keys = sys.argv[1:]
    if not keys:
        print(__doc__)
        sys.exit(1)

    print(f"\n対象 {len(keys)} 件: {keys}")

    results = []
    for k in keys:
        try:
            r = delete_one(k, headless=True)
        except Exception as e:
            r = {"ok": False, "reason": f"例外: {e}"}
        results.append((k, r))
        time.sleep(2)

    print("\n" + "=" * 60)
    print("結果サマリー")
    print("=" * 60)
    for k, r in results:
        status = "✅" if r.get("ok") else "❌"
        info = f"id={r.get('note_id')} status={r.get('status')} {r.get('reason') or ''}"
        print(f"  {k}: {status} {info[:100]}")


if __name__ == "__main__":
    main()
