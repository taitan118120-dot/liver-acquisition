#!/usr/bin/env python3
"""公開済みnote記事のCTAにLINE登録特典（リードマグネット）の1段落を外科的に挿入する。

- 挿入位置: 本文末尾側の lin.ee リンクを含む <p> ブロックの直前
- 冪等: 本文に「スタートダッシュガイド」が既にあればスキップ
- 機構は note_cta_publish.py と同じ（Chrome cookie + Playwright + reCAPTCHA + PUT）

使い方:
  python3 note_leadmagnet_publish.py <key> [<key> ...]   # 指定記事のみ
  python3 note_leadmagnet_publish.py --all               # data/published_note_keys.json 全件
  python3 note_leadmagnet_publish.py --verify <key>      # 検証のみ(GET)
"""
import json
import os
import sys
import time

from note_cta_publish import NOTE_API, RECAPTCHA_SITEKEY, UA, chrome_cookies, get_note, req_session

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEYS_FILE = os.path.join(BASE_DIR, "data", "published_note_keys.json")
LOG_FILE = os.path.join(BASE_DIR, "data", "leadmagnet_update_log.json")

LM_HTML = (
    "<p>🎁 <strong>友だち追加特典</strong>：『ライバー新人期スタートダッシュガイド』——"
    "最初の30日でやることを全部まとめた非売品PDFを、LINE登録した方全員に無料でお渡ししています。</p>"
)

# publish_one の既定マーカー。呼び出し側が別の施策（内部リンク・冒頭CTA）で使うときは
# expect_marker で自分の追加物を指定する。
LM_MARK = "スタートダッシュガイド"


def transform(key, html):
    if LM_MARK in html:
        return None  # 済み
    pos = html.rfind("lin.ee/xchCfdn")
    if pos == -1:
        return None  # CTAなし記事は触らない
    p_start = html.rfind("<p", 0, pos)
    if p_start == -1:
        raise ValueError(f"lin.ee前の<p>が見つからない (key={key})")
    return html[:p_start] + LM_HTML + html[p_start:]


def verify(key, marker=LM_MARK):
    s = req_session()
    d = get_note(s, key)
    body = d["body"]
    print(f"  status={d['status']}  eyecatch={'OK' if d.get('eyecatch') else 'MISSING!'}  "
          f"body_len={len(body)}  {marker[:12]}={marker in body}")
    return d


def publish_one(key, transform_fn=None, expect_marker=LM_MARK):
    """記事本文を transform_fn で書き換えて再公開する。

    expect_marker: 反映確認に使う文字列。transform_fn を差し替える呼び出し側は
        自分が挿入したマーカーを渡すこと（None で本文チェックを省略）。
    """
    from playwright.sync_api import sync_playwright
    s = req_session()
    d = get_note(s, key, draft=False)
    note_id = d["id"]
    title = d["name"]
    old_body = d["body"]
    new_body = (transform_fn or transform)(key, old_body)
    if new_body is None:
        print("  skip（済み or CTAなし）")
        return "skip"
    tags = [h["hashtag"]["name"].lstrip("#") for h in d.get("hashtag_notes", [])][:10]
    print(f"  id={note_id} title={title[:24]}")
    print(f"  body {len(old_body)} -> {len(new_body)}  tags={len(tags)}")

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
            browser.close(); raise RuntimeError(f"draft_save失敗: {ds}")

        page.goto(f"https://editor.note.com/notes/{key}/publish",
                  wait_until="domcontentloaded", timeout=40000)
        # CSPでwait_for_function(eval)が使えないため、evaluateでポーリングする。
        # grecaptchaはenterprise版に移行している可能性があるので両対応。
        for _ in range(20):
            try:
                ready = page.evaluate(
                    "()=>{const g=(window.grecaptcha&&window.grecaptcha.enterprise)||window.grecaptcha;"
                    "return !!(g&&typeof g.execute==='function');}")
                if ready:
                    break
            except Exception:
                pass
            time.sleep(1)
        time.sleep(2)
        try:
            rc = page.evaluate("""async (sitekey) => {
                const g=(window.grecaptcha&&window.grecaptcha.enterprise)||window.grecaptcha;
                if(!g||typeof g.execute!=='function') return {error:'no grecaptcha'};
                try{
                    const t=await g.execute(sitekey,{action:'note_post'});
                    const r=await fetch('/api/v3/challenges/verifications',{method:'POST',
                      headers:{'Content-Type':'application/json','Accept':'application/json','X-Requested-With':'XMLHttpRequest'},
                      credentials:'include',
                      body:JSON.stringify({g_recaptcha_token_v3:t,g_recaptcha_action_v3:'note_post',via:'note_post'})});
                    return {status:r.status, body:(await r.text()).slice(0,200)};
                }catch(e){return {error:String(e)}}
            }""", RECAPTCHA_SITEKEY)
        except Exception as e:
            rc = {"error": str(e)}
        print(f"  recaptcha verifications: {rc}")

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
            raise RuntimeError(f"PUT失敗: {pr}")

    time.sleep(2)
    print("  --- verify ---")
    # 本文検証はここで例外を投げない。この時点で記事は既に「タグ0の公開状態」であり、
    # 先に中断すると下のタグ復元が走らず、タグ0のまま公開され続けてしまう（実測 before:0）。
    body_err = None
    try:
        dv = verify(key)  # note_facts_publish が差し替えるので引数は1つのまま
        if not dv.get("eyecatch"):
            print("  !!! WARNING: eyecatch が消えた可能性。要復元")
        if expect_marker:
            hit = expect_marker in dv["body"]
            print(f"  marker『{expect_marker[:16]}』= {hit}")
            if not hit:
                body_err = f"verify失敗: 『{expect_marker}』が本文に反映されていない"
    except Exception as e:
        body_err = f"verify失敗: {type(e).__name__}: {e}"
    if body_err:
        print(f"  !! {body_err} → タグ復元まで終えてから中断する")

    # 公開PUTはhashtagsを無視してタグ0にする既知問題があるため、UI経由で復元する。
    # 検証結果によらず必ず通す（上のtry/exceptはそのためにある）。
    from note_tag_guard import ensure_tags
    tg = ensure_tags(key, hashtags=tags, title=title)
    print(f"  tag_guard: {tg}")
    if body_err:
        raise RuntimeError(body_err)
    if not tg.get("ok"):
        raise RuntimeError(f"タグ復元失敗: {tg}")
    return "ok"


# ── 例外記事の修復用transform ──
# 2026-07-12判明: #78〜82は死にリンク lin.ee/816qtxyj（404）を使用、
# #48/#60/#94はLINE CTA自体が無かった。
DEAD_LINK = "lin.ee/816qtxyj"

# 末尾CTAの文言は既存記事に合わせる（公開117本が「👉 公式LINEで無料相談：」で統一されている）
CTA_TAIL_HTML = (
    LM_HTML +
    '<p>👉 公式LINEで無料相談：<a href="https://lin.ee/xchCfdn" target="_blank" '
    'rel="nofollow noopener">https://lin.ee/xchCfdn</a></p>'
)


def transform_fix_dead_link(key, html):
    """死にリンクを正リンクへ置換してから特典段落を挿入"""
    if DEAD_LINK not in html and LM_MARK in html:
        return None
    html = html.replace(DEAD_LINK, "lin.ee/xchCfdn")
    out = transform(key, html)
    return out if out is not None else html


def transform_append_cta(key, html):
    """LINE CTAが無い記事の末尾に特典段落＋LINEリンクを追加"""
    if LM_MARK in html:
        return None
    return html + CTA_TAIL_HTML


def _load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def run_all():
    with open(KEYS_FILE, encoding="utf-8") as f:
        keys = json.load(f)
    log = _load_log()
    ok = skip = fail = 0
    for i, key in enumerate(keys, 1):
        if log.get(key) in ("ok", "skip"):
            continue
        print(f"[{i}/{len(keys)}] {key}")
        try:
            log[key] = publish_one(key)
            ok += log[key] == "ok"
            skip += log[key] == "skip"
        except Exception as e:
            print(f"  [FAIL] {e}")
            log[key] = f"fail: {e}"
            fail += 1
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=1)
        time.sleep(8)  # note側への負荷と連投検知を避ける
    print(f"[DONE] ok={ok} skip={skip} fail={fail}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__); raise SystemExit(1)
    if args[0] == "--verify":
        for k in args[1:]:
            print(f"[verify {k}]"); verify(k)
    elif args[0] == "--all":
        run_all()
    elif args[0] == "--fix-dead-link":
        for k in args[1:]:
            print(f"[fix-dead-link {k}]"); publish_one(k, transform_fix_dead_link)
    elif args[0] == "--append-cta":
        for k in args[1:]:
            print(f"[append-cta {k}]"); publish_one(k, transform_append_cta)
    else:
        for k in args:
            print(f"[publish {k}]"); publish_one(k)
