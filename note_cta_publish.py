#!/usr/bin/env python3
"""既存のnote公開記事を、本文だけ外科的に書き換えて再公開する。
- Chromeログインcookie(browser_cookie3)を Playwright に注入（ログイン不要）
- draft_save → reCAPTCHA v3 verifications → PUT status=published（note_publish_core が正本）
- hashtags は既存(hashtag_notes)を維持、フォロワー通知はOFF、eyecatchは触らない

使い方: python3 note_cta_publish.py <key> [<key> ...]
        python3 note_cta_publish.py --verify <key>   # 検証のみ(GET)
"""
import sys, json, time, re
import requests, browser_cookie3
from note_cta_transform import transform
from note_publish_core import (NOTE_API_BASE as NOTE_API, NOTE_UA as UA,
                               RECAPTCHA_SITEKEY, editor_browser, publish_via_editor)


def chrome_cookies():
    cks = []
    for c in browser_cookie3.chrome(domain_name="note.com"):
        cks.append({"name": c.name, "value": c.value,
                    "domain": c.domain or ".note.com", "path": c.path or "/",
                    "httpOnly": False, "secure": True, "sameSite": "Lax"})
    return cks


def req_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json",
                      "Content-Type": "application/json", "Referer": "https://note.com/",
                      "Origin": "https://note.com", "X-Requested-With": "XMLHttpRequest"})
    for c in chrome_cookies():
        s.cookies.set(c["name"], c["value"], domain=c["domain"])
    return s


def get_note(s, key, draft=True):
    q = "?draft=true&draft_reedit=false&" if draft else "?"
    r = s.get(f"{NOTE_API}/v3/notes/{key}{q}ts={int(time.time()*1000)}", timeout=25)
    r.raise_for_status()
    return r.json()["data"]


def verify(key):
    s = req_session()
    d = get_note(s, key)
    body = d["body"]
    tags = [h["hashtag"]["name"] for h in d.get("hashtag_notes", [])]
    print(f"  status={d['status']}  eyecatch={'OK' if d.get('eyecatch') else 'MISSING!'}  "
          f"tags={len(tags)}  body_len={len(body)}  "
          f"cta_left={'オンライン無料相談' in body}  newcta={'まずはLINEで気軽に' in body}")
    return d


def publish_one(key):
    s = req_session()
    d = get_note(s, key, draft=False)  # 公開済み本文を変換元にする（古い下書き混入を避ける）
    note_id = d["id"]
    title = d["name"]
    old_body = d["body"]
    new_body = transform(key, old_body)
    tags = [h["hashtag"]["name"].lstrip("#") for h in d.get("hashtag_notes", [])][:10]
    eyecatch_before = d.get("eyecatch")
    print(f"  id={note_id} title={title[:24]}")
    print(f"  body {len(old_body)} -> {len(new_body)}  tags={tags}")

    with editor_browser(chrome_cookies()) as page:
        publish_via_editor(page, note_id, key, title, new_body, tags,
                           disable_comment=d.get("disable_comment", False),
                           limited=d.get("is_limited", False))

    # verify live
    time.sleep(2)
    print("  --- verify ---")
    dv = verify(key)
    if not dv.get("eyecatch"):
        print("  !!! WARNING: eyecatch が消えた可能性。要復元")

    # 公開PUTはhashtagsを無視してタグ0にする既知問題があるため、UI経由で復元する。
    # ensure_tags は冪等（MIN_TAGS以上なら即return）なので、呼び出し元
    # （note_finish_all）がバックアップから別途復元しても二重更新にはならない。
    from note_tag_guard import ensure_tags
    tg = ensure_tags(key, hashtags=tags, title=title)
    print(f"  tag_guard: {tg}")
    if not tg.get("ok"):
        # 例外にすると note_finish_all のバックアップ復元まで巻き添えで止まるため警告に留める
        print(f"  !!! WARNING: タグ復元失敗 {tg}")
    return dv


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__); raise SystemExit(1)
    if args[0] == "--verify":
        for k in args[1:]:
            print(f"[verify {k}]"); verify(k)
    else:
        for k in args:
            print(f"[publish {k}]"); publish_one(k)
