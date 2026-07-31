#!/usr/bin/env python3
"""note_profile_update.py — note.com のクリエイター名（表示名）とプロフィール文を更新する

なぜ必要か
----------
記事本文は note_auto_poster / note_facts_fix_* 系で一括更新できるが、
**クリエイター名（nickname）とプロフィール文（profile）は記事更新の対象外**で、
全記事ページの <title> と著者欄に旧表記のまま露出し続ける。
2026-07-31 に「たいたん☕️❤️＠150名所属ライバー事務所代表」が残っているのを発見して作成。

なぜ Playwright なのか
----------------------
プロフィール編集は `https://note.com/settings/profile` の React フォームで、
`input[name=editNickname]` / `textarea[name=editBiography]` に入力して「保存」を押す。
GET /api/v2/current_user は読めるが、書き込み側の公開エンドポイントは不明かつ
部分PUTで他フィールドを飛ばすリスクがあるため、UI 経由が安全。
認証は note_tag_guard の cookie 機構（Chrome cookie / NOTE_COOKIES_JSON）を流用する。

CLI
---
  python3 note_profile_update.py --show            # 現在値の表示のみ
  python3 note_profile_update.py --dry-run         # 変換結果を出すが保存しない
  python3 note_profile_update.py                   # 実際に保存して検証
"""
import argparse
import json
import sys
import time

import note_tag_guard as g

SETTINGS_URL = "https://note.com/settings/profile"
API_ME = "https://note.com/api/v2/current_user"

# 旧→新（[[project_taitan_pro_note_facts]] の確定ファクトに合わせる）
REPLACEMENTS = [
    ("＠150名所属", "＠200名所属"),
    ("@150名所属", "@200名所属"),
    ("所属150名超", "所属200名"),
    ("所属150名", "所属200名"),
    ("150名超", "200名"),
    # 「11代理店を束ねる」は確定ファクト「11の配信代理店と提携」に反する（運営表現はNG）
    ("11代理店を束ねる", "11の配信代理店と提携する"),
]


def transform(text: str) -> str:
    out = text
    for old, new in REPLACEMENTS:
        out = out.replace(old, new)
    return out


def fetch_current():
    s = g.make_session()
    r = s.get(API_ME, timeout=20, headers={"Cache-Control": "no-cache"})
    r.raise_for_status()
    d = r.json()["data"]
    return d["nickname"], d["profile"]


def save_via_ui(nickname: str, profile: str):
    from playwright.sync_api import sync_playwright
    g.refresh_cookies()
    calls = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(user_agent=g.UA, locale="ja-JP",
                                  viewport={"width": 1280, "height": 1600},
                                  bypass_csp=True)
        ctx.add_cookies(g._load_pw_cookies())
        page = ctx.new_page()
        page.on("request", lambda req: calls.append((req.method, req.url))
                if req.method in ("POST", "PUT", "PATCH") else None)
        page.goto(SETTINGS_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)

        nick = page.locator('input[name="editNickname"]').first
        bio = page.locator('textarea[name="editBiography"]').first
        if nick.count() == 0 or bio.count() == 0:
            raise RuntimeError("プロフィール編集フォームが見つからない（未ログインの可能性）")
        nick.fill(nickname)
        page.wait_for_timeout(400)
        bio.fill(profile)
        page.wait_for_timeout(600)

        save = page.locator('button:has-text("保存")').first
        if save.count() == 0:
            raise RuntimeError("保存ボタンが見つからない")
        save.click()
        page.wait_for_timeout(7000)
        browser.close()
    return calls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    nickname, profile = fetch_current()
    print("── 現在値 ──")
    print("nickname:", nickname)
    print("profile :", profile)
    if args.show:
        return 0

    new_nick, new_profile = transform(nickname), transform(profile)
    print("\n── 変換後 ──")
    print("nickname:", new_nick)
    print("profile :", new_profile)

    if new_nick == nickname and new_profile == profile:
        print("\n変更なし。何もしない。")
        return 0
    if args.dry_run:
        print("\n[dry-run] 保存しない。")
        return 0

    print("\n保存中…")
    calls = save_via_ui(new_nick, new_profile)
    for m, u in calls:
        print(f"  {m} {u}")

    time.sleep(3)
    v_nick, v_profile = fetch_current()
    print("\n── 検証（公開API） ──")
    print("nickname:", v_nick)
    print("profile :", v_profile)
    ok = v_nick == new_nick and v_profile == new_profile
    print("\n結果:", "OK 反映済み" if ok else "NG 反映されていない")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
