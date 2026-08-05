#!/usr/bin/env python3
"""note記事の公開/再公開の共通コア。

note の editor は「下書き保存 → reCAPTCHA v3 の検証 → PUT で公開」という順序で動く。
この3段は全公開スクリプトで同一なのに、以前は6箇所にコピペされていて、note側の仕様が
変わるたびに同じ1行修正を6ファイルへ手で配る羽目になっていた（2026-08-05の
verifications 403 がまさにそれ）。以後この手の修正はこのファイルだけを直す。

依存は playwright の page オブジェクトのみ。cookie の取得（browser_cookie3 や環境変数）は
呼び出し側の責務にしてある。note_auto_poster.py は GitHub Actions 上でも動き、CI には
browser_cookie3 が入っていないため、このモジュールからは絶対に import しないこと。

主なAPI:
  publish_via_editor(page, note_id, key, title, body, tags, ...)  # 3段まとめて実行
  editor_browser(cookies, ...)                                     # browser生成のcontextmanager
"""
import time
from contextlib import contextmanager

NOTE_API_BASE = "https://note.com/api"
RECAPTCHA_SITEKEY = "6LefXTAsAAAAADYVISEItAl0IX1rgSGQ-asNy56w"
NOTE_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

EDITOR_BASE = "https://editor.note.com"


class NotePublishError(RuntimeError):
    """draft_save / PUT が 2xx を返さなかった。"""


# ── ブラウザ内 fetch。XSRF-TOKEN は cookie から拾って自前で載せる ──
_JS_FETCH = """async ({url, method, payload}) => {
    const m = document.cookie.match(/XSRF-TOKEN=([^;]+)/);
    const xsrf = m ? decodeURIComponent(m[1]) : null;
    const h = {"Content-Type":"application/json","Accept":"application/json",
               "X-Requested-With":"XMLHttpRequest"};
    if (xsrf) h["X-XSRF-TOKEN"] = xsrf;
    const r = await fetch(url, {method: method, headers: h, credentials: "include",
                               body: JSON.stringify(payload)});
    return {status: r.status, body: await r.text(), xsrf: !!xsrf};
}"""

# grecaptcha は enterprise 版に移行している可能性があるので両対応で取得する。
_JS_GRECAPTCHA_READY = ("()=>{const g=(window.grecaptcha&&window.grecaptcha.enterprise)"
                        "||window.grecaptcha; return !!(g&&typeof g.execute==='function');}")

_JS_VERIFICATIONS = """async ({sitekey, url}) => {
    const g = (window.grecaptcha && window.grecaptcha.enterprise) || window.grecaptcha;
    if (!g || typeof g.execute !== 'function') return {error: 'no grecaptcha'};
    try {
        const t = await g.execute(sitekey, {action: 'note_post'});
        const r = await fetch(url, {method: 'POST',
          headers: {'Content-Type':'application/json','Accept':'application/json',
                    'X-Requested-With':'XMLHttpRequest'},
          credentials: 'include',
          body: JSON.stringify({g_recaptcha_token_v3: t, g_recaptcha_action_v3: 'note_post',
                                via: 'note_post'})});
        return {status: r.status, body: (await r.text()).slice(0, 200)};
    } catch (e) { return {error: String(e)} }
}"""


@contextmanager
def editor_browser(cookies, *, user_agent=NOTE_UA, headless=True, bypass_csp=False):
    """cookie を注入した chromium の page を貸し出す。抜けるとき必ず browser を閉じる。

    cookies: playwright の add_cookies 形式（name/value/domain/path/...）のリスト。
             どう集めるかは呼び出し側の責務（browser_cookie3・環境変数・note_tag_guard など）。
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        try:
            ctx_kwargs = {"user_agent": user_agent, "locale": "ja-JP",
                          "viewport": {"width": 1400, "height": 900}}
            if bypass_csp:
                ctx_kwargs["bypass_csp"] = True
            ctx = browser.new_context(**ctx_kwargs)
            ctx.add_cookies(cookies)
            yield ctx.new_page()
        finally:
            browser.close()


def open_editor(page, key, *, timeout=60000, settle=3):
    """editor の編集画面を開き、XSRF-TOKEN が発行されるまで落ち着かせる。"""
    page.goto(f"{EDITOR_BASE}/notes/{key}/edit", wait_until="domcontentloaded", timeout=timeout)
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    time.sleep(settle)


def draft_save(page, note_id, title, body, *, api_base=NOTE_API_BASE):
    """editor の定期保存と同じ draft_save。ここが通らないと本文は反映されない。"""
    return page.evaluate(_JS_FETCH, {
        "url": f"{api_base}/v1/text_notes/draft_save?id={note_id}", "method": "POST",
        "payload": {"body": body, "body_length": len(body), "name": title}})


def run_recaptcha_verification(page, key, *, api_base=NOTE_API_BASE, goto_publish=True,
                               log_prefix="  "):
    """publish ページで reCAPTCHA v3 token を取り、challenges/verifications へ送る。

    URLは https://note.com/api を絶対指定する。publish ページは editor.note.com 配信で、
    そのCloudFrontは /api/* をoriginに流さず403(HTMLのエラーページ)を返すため、相対
    '/api/...' だと100%失敗する（2026-08-05に実測で確定）。note公式のeditorも
    axios baseURL="https://note.com/api" で叩いている。

    失敗しても例外にはしない（意図的に握りつぶす）。note公式のpublish処理もこの呼び出しを
    .catch(()=>{}) で捨て、レスポンス本体を読まずにPUTへ進む実装であり、検証が通らなくても
    後続PUTは成功する。ただし note が検証必須に切り替えたらPUTが4xxで落ちることになるので、
    その予兆を拾えるようWARNは必ず出す。
    """
    if goto_publish:
        page.goto(f"{EDITOR_BASE}/notes/{key}/publish",
                  wait_until="domcontentloaded", timeout=40000)
    # CSPで wait_for_function(eval) が使えない環境があるため evaluate でポーリングする。
    for _ in range(20):
        try:
            if page.evaluate(_JS_GRECAPTCHA_READY):
                break
        except Exception:
            pass
        time.sleep(1)
    time.sleep(2)
    try:
        rc = page.evaluate(_JS_VERIFICATIONS, {
            "sitekey": RECAPTCHA_SITEKEY,
            "url": f"{api_base}/v3/challenges/verifications"})
    except Exception as e:
        rc = {"error": str(e)}
    if rc.get("status") != 200:
        print(f"{log_prefix}[WARN] recaptcha verifications 異常（PUTは続行）: {rc}")
    else:
        print(f"{log_prefix}recaptcha verifications: {rc}")
    return rc


def put_publish(page, note_id, title, body, tags=(), *, api_base=NOTE_API_BASE,
                status="published", send_notifications=False, disable_comment=False,
                limited=False):
    """PUT /v1/text_notes/{id}。note側は hashtags を無視してタグを0にする既知問題があるので、
    タグ復元は呼び出し側が note_tag_guard.ensure_tags で行うこと。eyecatch は触らない。"""
    payload = {
        "status": status, "name": title,
        "free_body": body, "pay_body": "", "body_length": len(body),
        "price": 0, "hashtags": list(tags)[:10],
        "disable_comment": bool(disable_comment),
        "send_notifications_flag": bool(send_notifications),
        "limited": bool(limited),
    }
    return page.evaluate(_JS_FETCH, {
        "url": f"{api_base}/v1/text_notes/{note_id}", "method": "PUT", "payload": payload})


def publish_via_editor(page, note_id, key, title, body, tags=(), *,
                       api_base=NOTE_API_BASE, status="published", recaptcha=True,
                       send_notifications=False, disable_comment=False, limited=False,
                       goto_edit=True, raise_on_put_error=True, log_prefix="  "):
    """draft_save → reCAPTCHA verifications → PUT を1本で流す。

    page:        cookie注入済みの playwright page（editor_browser か呼び出し側が用意する）
    goto_edit:   False なら既に編集画面にいる前提でナビゲーションを省く
                 （note_auto_poster の新規投稿は自分でUI経由の下書き作成を済ませている）
    recaptcha:   下書き保存だけしたいとき（status="draft"）は False
    raise_on_put_error: False なら PUT の非2xx を戻り値で返すだけにして呼び出し側に委ねる

    戻り値: {"draft_save": {...}, "recaptcha": {...} or None, "put": {...}}
            各要素は {"status": int, "body": str, "xsrf": bool}。body は切り詰めない
            （呼び出し側が JSON として読むことがあるため）。
    draft_save 失敗時は常に NotePublishError。
    """
    if goto_edit:
        open_editor(page, key)

    ds = draft_save(page, note_id, title, body, api_base=api_base)
    print(f"{log_prefix}draft_save: {ds['status']}")
    if ds["status"] not in (200, 201):
        raise NotePublishError(f"draft_save失敗: status={ds['status']} body={ds['body'][:300]}")

    rc = None
    if recaptcha:
        try:
            rc = run_recaptcha_verification(page, key, api_base=api_base,
                                            log_prefix=log_prefix)
        except Exception as e:
            # ここで公開を止める理由はない（上の docstring 参照）
            rc = {"error": str(e)}
            print(f"{log_prefix}[WARN] recaptcha/verifications 失敗（続行）: {e}")

    pr = put_publish(page, note_id, title, body, tags, api_base=api_base, status=status,
                     send_notifications=send_notifications, disable_comment=disable_comment,
                     limited=limited)
    print(f"{log_prefix}PUT: {pr['status']}")
    if raise_on_put_error and pr["status"] not in (200, 201):
        raise NotePublishError(f"PUT失敗: status={pr['status']} body={pr['body'][:400]}")

    return {"draft_save": ds, "recaptcha": rc, "put": pr}
