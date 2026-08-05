#!/usr/bin/env python3
"""既存のnote公開記事を、本文だけ外科的に書き換えて再公開する。
- Chromeログインcookie(browser_cookie3)を Playwright に注入（ログイン不要）
- draft_save → reCAPTCHA v3 verifications → PUT status=published
- hashtags は既存(hashtag_notes)を維持、フォロワー通知はOFF、eyecatchは触らない

使い方: python3 note_cta_publish.py <key> [<key> ...]
        python3 note_cta_publish.py --verify <key>   # 検証のみ(GET)
"""
import sys, json, time, re
import requests, browser_cookie3
from note_cta_transform import transform

NOTE_API = "https://note.com/api"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
RECAPTCHA_SITEKEY = "6LefXTAsAAAAADYVISEItAl0IX1rgSGQ-asNy56w"


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
    from playwright.sync_api import sync_playwright
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

    pw_cookies = chrome_cookies()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="ja-JP",
                                  viewport={"width": 1400, "height": 900})
        ctx.add_cookies(pw_cookies)
        page = ctx.new_page()
        page.goto(f"https://editor.note.com/notes/{key}/edit",
                  wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        time.sleep(3)

        # draft_save
        ds = page.evaluate("""async ({url, payload}) => {
            const m=document.cookie.match(/XSRF-TOKEN=([^;]+)/);
            const h={"Content-Type":"application/json","Accept":"application/json","X-Requested-With":"XMLHttpRequest"};
            if(m)h["X-XSRF-TOKEN"]=decodeURIComponent(m[1]);
            const r=await fetch(url,{method:"POST",headers:h,credentials:"include",body:JSON.stringify(payload)});
            return {status:r.status, body:(await r.text()).slice(0,300)};
        }""", {"url": f"{NOTE_API}/v1/text_notes/draft_save?id={note_id}",
               "payload": {"body": new_body, "body_length": len(new_body), "name": title}})
        print(f"  draft_save: {ds['status']}")
        if ds["status"] not in (200, 201):
            browser.close(); raise SystemExit(f"draft_save失敗: {ds}")

        # reCAPTCHA v3 verifications on publish page
        page.goto(f"https://editor.note.com/notes/{key}/publish",
                  wait_until="domcontentloaded", timeout=40000)
        try:
            page.wait_for_function(
                "typeof window.grecaptcha!=='undefined' && typeof window.grecaptcha.execute==='function'",
                timeout=20000)
        except Exception as e:
            print(f"  grecaptcha wait: {e}")
        time.sleep(2)
        # verifications のURLは https://note.com/api を絶対指定する。このページは
        # editor.note.com 配信で、そのCloudFrontは /api/* をoriginに流さず403(HTMLのエラー
        # ページ)を返すため、相対 '/api/...' だと100%失敗する（2026-08-05に実測で確定）。
        # note公式のeditorも axios baseURL="https://note.com/api" で叩いている。
        rc = page.evaluate("""async ({sitekey, url}) => {
            if(typeof grecaptcha==='undefined') return {error:'no grecaptcha'};
            return new Promise((res)=>{ grecaptcha.ready(async()=>{ try{
                const t=await grecaptcha.execute(sitekey,{action:'note_post'});
                const r=await fetch(url,{method:'POST',
                  headers:{'Content-Type':'application/json','Accept':'application/json','X-Requested-With':'XMLHttpRequest'},
                  credentials:'include',
                  body:JSON.stringify({g_recaptcha_token_v3:t,g_recaptcha_action_v3:'note_post',via:'note_post'})});
                res({status:r.status, body:(await r.text()).slice(0,200)});
            }catch(e){res({error:String(e)})}})});
        }""", {"sitekey": RECAPTCHA_SITEKEY,
               "url": f"{NOTE_API}/v3/challenges/verifications"})
        # ここは失敗しても中断しない（意図的に握りつぶす）。note公式のpublish処理も
        # この呼び出しを .catch(()=>{}) で捨て、レスポンス本体も読まずにPUTへ進む実装。
        # よって検証が通らなくても後続PUTは成功する。ただし note が検証必須に切り替えたら
        # PUTが4xxで落ちることになるので、その予兆を拾えるようWARNは必ず出す。
        if rc.get("status") != 200:
            print(f"  [WARN] recaptcha verifications 異常（PUTは続行）: {rc}")
        else:
            print(f"  recaptcha verifications: {rc}")

        # PUT publish
        put_payload = {
            "status": "published", "name": title,
            "free_body": new_body, "pay_body": "", "body_length": len(new_body),
            "price": 0, "hashtags": tags,
            "disable_comment": bool(d.get("disable_comment", False)),
            "send_notifications_flag": False, "limited": bool(d.get("is_limited", False)),
        }
        pr = page.evaluate("""async ({url, payload}) => {
            const m=document.cookie.match(/XSRF-TOKEN=([^;]+)/);
            const h={"Content-Type":"application/json","Accept":"application/json","X-Requested-With":"XMLHttpRequest"};
            if(m)h["X-XSRF-TOKEN"]=decodeURIComponent(m[1]);
            const r=await fetch(url,{method:"PUT",headers:h,credentials:"include",body:JSON.stringify(payload)});
            return {status:r.status, body:(await r.text()).slice(0,400)};
        }""", {"url": f"{NOTE_API}/v1/text_notes/{note_id}", "payload": put_payload})
        print(f"  PUT: {pr['status']}")
        browser.close()
        if pr["status"] not in (200, 201):
            raise SystemExit(f"PUT失敗: {pr}")

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
