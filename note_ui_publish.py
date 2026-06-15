#!/usr/bin/env python3
"""note公開記事を publish-page UI 経由で再公開（ハッシュタグを確実に設定）。
- Chromeログインcookie(browser_cookie3)注入
- 任意で draft_save により本文を差し替え
- 公開ページUIで desired_tags のうち未設定のものを追加 → 更新する
使い方(単体テスト): python3 note_ui_publish.py <key> [--body]
desired_tags はバックアップの hashtag_notes から取得。
"""
import sys, json, time
import requests, browser_cookie3
from note_cta_transform import transform

NOTE_API="https://note.com/api"
UA=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

def chrome_cookies():
    out=[]
    for c in browser_cookie3.chrome(domain_name="note.com"):
        out.append({"name":c.name,"value":c.value,"domain":c.domain or ".note.com",
                    "path":c.path or "/","httpOnly":False,"secure":True,"sameSite":"Lax"})
    return out

def req_session():
    s=requests.Session()
    s.headers.update({"User-Agent":UA,"Accept":"application/json","Content-Type":"application/json",
                      "Referer":"https://note.com/","Origin":"https://note.com","X-Requested-With":"XMLHttpRequest"})
    for c in chrome_cookies(): s.cookies.set(c["name"],c["value"],domain=c["domain"])
    return s

def get_note(s,key):
    r=s.get(f"{NOTE_API}/v3/notes/{key}?draft=true&draft_reedit=false&ts={int(time.time()*1000)}",timeout=25)
    r.raise_for_status(); return r.json()["data"]

def update(key, desired_tags, change_body=False, shot=None):
    from playwright.sync_api import sync_playwright
    s=req_session(); d=get_note(s,key); note_id=d["id"]; title=d["name"]
    new_body=None
    if change_body:
        new_body=transform(key,d["body"])
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox","--disable-blink-features=AutomationControlled"])
        ctx=browser.new_context(user_agent=UA,locale="ja-JP",viewport={"width":1280,"height":1500})
        ctx.add_cookies(chrome_cookies())
        page=ctx.new_page()
        # body差し替え（draft_save）
        if new_body is not None:
            page.goto(f"https://editor.note.com/notes/{key}/edit",wait_until="domcontentloaded",timeout=60000)
            try: page.wait_for_load_state("networkidle",timeout=15000)
            except Exception: pass
            page.wait_for_timeout(2500)
            ds=page.evaluate("""async ({url,payload})=>{const m=document.cookie.match(/XSRF-TOKEN=([^;]+)/);
              const h={"Content-Type":"application/json","Accept":"application/json","X-Requested-With":"XMLHttpRequest"};
              if(m)h["X-XSRF-TOKEN"]=decodeURIComponent(m[1]);
              const r=await fetch(url,{method:"POST",headers:h,credentials:"include",body:JSON.stringify(payload)});
              return {status:r.status};}""",
              {"url":f"{NOTE_API}/v1/text_notes/draft_save?id={note_id}",
               "payload":{"body":new_body,"body_length":len(new_body),"name":title}})
            print(f"  draft_save: {ds['status']}")
        # publish UI
        page.goto(f"https://editor.note.com/notes/{key}/edit",wait_until="domcontentloaded",timeout=60000)
        page.wait_for_timeout(3000)
        page.locator('button:has-text("公開に進む")').first.click()
        page.wait_for_timeout(5000)
        # 既存タグchipを確認
        existing=set()
        try:
            chips=page.locator('a[href^="/hashtag/"], [class*="hashtag"]').all_text_contents()
            for t in chips:
                t=t.strip().lstrip("#")
                if t: existing.add(t)
        except Exception: pass
        print(f"  existing chips: {sorted(existing)}")
        tag_input=page.locator('input[placeholder="ハッシュタグを追加する"]').first
        if tag_input.count()==0:
            if shot: page.screenshot(path=shot)
            browser.close(); raise SystemExit("ハッシュタグ入力欄が見つからず")
        added=[]
        for tag in desired_tags[:10]:
            if tag in existing: continue
            try:
                tag_input.click(); page.wait_for_timeout(250)
                tag_input.fill(tag); page.wait_for_timeout(400)
                tag_input.press("Enter"); page.wait_for_timeout(700)
                added.append(tag)
            except Exception as e:
                print(f"    [WARN] {tag}: {e}")
        print(f"  added: {added}")
        page.wait_for_timeout(1500)
        clicked=False
        for sel in ['button:has-text("更新する")','button:has-text("投稿する")','button:has-text("公開する")']:
            loc=page.locator(sel).first
            if loc.count()>0 and loc.is_visible():
                loc.click(); print(f"  publish btn: {sel}"); clicked=True; page.wait_for_timeout(5000); break
        if shot: page.screenshot(path=shot)
        browser.close()
        if not clicked: raise SystemExit("更新ボタン見つからず")
    # verify
    time.sleep(2)
    s2=req_session(); dv=s2.get(f"{NOTE_API}/v3/notes/{key}?ts={int(time.time()*1000)}",timeout=20).json()["data"]
    tg=[h["hashtag"]["name"] for h in dv.get("hashtag_notes",[])]
    print(f"  VERIFY status={dv['status']} tags={len(tg)} eye={'Y' if dv.get('eyecatch') else 'N'} "
          f"cta_done={'まずはLINEで気軽に' in dv['body']}")
    return dv

if __name__=="__main__":
    key=sys.argv[1]; change_body="--body" in sys.argv
    bk=json.load(open(f"data/note_html_backup/{key}.json",encoding="utf-8"))
    desired=[h["hashtag"]["name"].lstrip("#") for h in bk.get("hashtag_notes",[])][:10]
    print(f"[{key}] desired_tags={desired} change_body={change_body}")
    update(key, desired, change_body=change_body, shot=f"/tmp/note_ui_{key}.png")
