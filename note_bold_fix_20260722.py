#!/usr/bin/env python3
"""公開記事の本文に残っていた「太字化されなかった生Markdownの **」を除去して再公開する
（2026-07-22。note_asterisk_scan.py で全108本を点検し検出した9本が対象）。

原因は2系統:
  (A) 見出し行が convert_inline_markdown を通っていなかった（note_auto_poster.py で修正済）
      → `## 「**月20万円**」…` の ** が生のまま公開されていた
  (B) ローカル原稿の一括置換（月10万円 → **月20万円**）が既存の **…** の内側で行われ、
      ** の数が奇数になって対応が崩れた
      → `**初月から**月20万円**を目指せます` → `<strong>初月から</strong>月20万円**を目指せます`
      ローカル原稿 blog/articles_note/*.md 側も本コミットで修正済み

機構は note_facts_fix_20260722.py と同じ（Chrome cookie + Playwright + reCAPTCHA + PUT）。
公開PUTはhashtagsを無視してタグを0にする既知問題があるため、note_tag_guard.ensure_tags で
必ずタグを復元し、eyecatchが消えていないかも公開後のGETで検証する。

使い方:
  python3 note_bold_fix_20260722.py --dry-run [<key> ...]
  python3 note_bold_fix_20260722.py [<key> ...]     # 省略時は対象9本すべて
"""
import re
import sys
import time

from note_cta_publish import NOTE_API, RECAPTCHA_SITEKEY, UA, chrome_cookies, get_note, req_session

# ── 記事ごとの本文置換ルール（旧HTML文字列 -> 新HTML文字列）──
BODY_RULES = {
    # #50 TikTokLIVE収益化：(B) 太字範囲が1つズレて末尾に ** が残っていた
    "nadf7bf475ea9": [
        ("「同じギフトでも先月と今月で手取りが違う」<strong>のはTikTokLIVEあるあるなので、</strong>"
         "月単位で平均化してKPI管理**するのが正解です。",
         "「同じギフトでも先月と今月で手取りが違う」のはTikTokLIVEあるあるなので、"
         "<strong>月単位で平均化してKPI管理</strong>するのが正解です。"),
    ],

    # #35 契約書10項目：(A) 「」（）を含む **…** が未変換のまま
    "n699ef655effb": [
        ("必ず**契約書（業務委託契約書）**を交わします。",
         "必ず<strong>契約書（業務委託契約書）</strong>を交わします。"),
        ("**「信頼しているからこそ、書面で確認する」**が正しいスタンスです。",
         "<strong>「信頼しているからこそ、書面で確認する」</strong>が正しいスタンスです。"),
    ],

    # #32 移籍：(A) ユーザーが最初に発見した箇所
    "n84121e6b7eab": [
        ("**「サポートがない」「還元率が低い」「マネージャーと合わない」**といった理由で",
         "<strong>「サポートがない」「還元率が低い」「マネージャーと合わない」</strong>といった理由で"),
    ],

    # #15 男性ライバー：(B) 太字範囲が総崩れ。代表の実績表記を正しい2つの太字に戻す
    "n03be7c901596": [
        ("<strong>ミクチャで8,000人中</strong>ミスターコン1位<strong>を獲得し、</strong>"
         "ポコチャではSランクを達成**した男性ライバー出身者です。",
         "<strong>ミクチャで8,000人中ミスターコン1位</strong>を獲得し、"
         "<strong>ポコチャではSランクを達成</strong>した男性ライバー出身者です。"),
    ],

    # #11 主婦ライバー：(B)
    "n091ee2617062": [
        ("<strong>初月から</strong>月20万円**を目指せます。",
         "<strong>初月から月20万円</strong>を目指せます。"),
    ],

    # #10 大学生ライバー：(B) + (A)見出し
    "n3e1a72579743": [
        ("<strong>初月から</strong>月20万円**も現実的です。",
         "<strong>初月から月20万円</strong>も現実的です。"),
        ("大学生がPocochaで**月20万円**稼ぐロードマップ",
         "大学生がPocochaで月20万円稼ぐロードマップ"),
    ],

    # #6 在宅副業おすすめ：(B)
    "n490e9578f165": [
        ("<strong>事務所サポートで初月から</strong>月20万円**が現実的",
         "<strong>事務所サポートで初月から月20万円</strong>が現実的"),
    ],

    # #5 ライバー収入現実：(A)見出し
    "n80a29386b5a8": [
        ("「**月20万円**」を達成するリアルなロードマップ",
         "「月20万円」を達成するリアルなロードマップ"),
    ],

    # #2 Pococha稼げる：(B) + (A)見出し
    "n2dc730f02053": [
        ("<strong>初月から</strong>月20万円**を達成することも十分可能です。",
         "<strong>初月から月20万円</strong>を達成することも十分可能です。"),
        ("**月20万円**を達成する5つの戦略",
         "月20万円を達成する5つの戦略"),
    ],
}

KEYS = list(BODY_RULES)

TAG_RE = re.compile(r"<[^>]+>")


def raw_asterisks(html):
    """タグを除去した本文テキストに残る ** の個数"""
    return TAG_RE.sub("", html).count("**")


def transform(key, html):
    out = html
    for old, new in BODY_RULES[key]:
        if out.count(old) != 1:
            raise ValueError(f"置換対象が{out.count(old)}件 (key={key}): {old[:50]}…")
        out = out.replace(old, new)
    return out


def publish_one(key, dry_run=False):
    from playwright.sync_api import sync_playwright

    s = req_session()
    d = get_note(s, key, draft=False)
    note_id = d["id"]
    old_body = d["body"]
    new_body = transform(key, old_body)
    title = d["name"]
    tags = [h["hashtag"]["name"].lstrip("#") for h in d.get("hashtag_notes", [])][:10]

    print(f"  id={note_id} title={title[:40]}")
    print(f"  body {len(old_body)} -> {len(new_body)}  "
          f"raw** {raw_asterisks(old_body)} -> {raw_asterisks(new_body)}  tags={len(tags)}")
    if raw_asterisks(new_body):
        raise ValueError(f"変換後にも ** が残っている (key={key})")
    if new_body == old_body:
        print("  変更なし — skip")
        return "skip"
    if dry_run:
        print("  [dry-run] 公開はしない")
        return "dry"

    eyecatch_before = d.get("eyecatch")
    pw_cookies = chrome_cookies()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
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

        js_fetch = """async ({url, method, payload}) => {
            const m=document.cookie.match(/XSRF-TOKEN=([^;]+)/);
            const h={"Content-Type":"application/json","Accept":"application/json","X-Requested-With":"XMLHttpRequest"};
            if(m)h["X-XSRF-TOKEN"]=decodeURIComponent(m[1]);
            const r=await fetch(url,{method:method,headers:h,credentials:"include",body:JSON.stringify(payload)});
            return {status:r.status, body:(await r.text()).slice(0,400)};
        }"""

        ds = page.evaluate(js_fetch, {
            "url": f"{NOTE_API}/v1/text_notes/draft_save?id={note_id}", "method": "POST",
            "payload": {"body": new_body, "body_length": len(new_body), "name": title}})
        print(f"  draft_save: {ds['status']}")
        if ds["status"] not in (200, 201):
            browser.close()
            raise RuntimeError(f"draft_save失敗: {ds}")

        page.goto(f"https://editor.note.com/notes/{key}/publish",
                  wait_until="domcontentloaded", timeout=40000)
        for _ in range(20):
            try:
                if page.evaluate(
                        "()=>{const g=(window.grecaptcha&&window.grecaptcha.enterprise)||window.grecaptcha;"
                        "return !!(g&&typeof g.execute==='function');}"):
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

        pr = page.evaluate(js_fetch, {
            "url": f"{NOTE_API}/v1/text_notes/{note_id}", "method": "PUT",
            "payload": {
                "status": "published", "name": title,
                "free_body": new_body, "pay_body": "", "body_length": len(new_body),
                "price": 0, "hashtags": tags,
                "disable_comment": bool(d.get("disable_comment", False)),
                "send_notifications_flag": False, "limited": bool(d.get("is_limited", False)),
            }})
        print(f"  PUT: {pr['status']}")
        browser.close()
        if pr["status"] not in (200, 201):
            raise RuntimeError(f"PUT失敗: {pr}")

    time.sleep(2)
    dv = get_note(req_session(), key, draft=False)
    left = raw_asterisks(dv["body"])
    eyecatch_after = dv.get("eyecatch")
    print(f"  --- verify --- status={dv['status']} "
          f"eyecatch={'OK' if eyecatch_after else 'MISSING!'} 残存**={left}")
    if left:
        raise RuntimeError(f"verify失敗: ** が {left} 個残っている")
    if eyecatch_before and not eyecatch_after:
        raise RuntimeError("verify失敗: eyecatchが消えた")

    # 公開PUTはhashtagsを無視してタグ0にする既知問題があるため、UI経由で復元する
    from note_tag_guard import ensure_tags
    tg = ensure_tags(key, hashtags=tags, title=title)
    print(f"  tag_guard: {tg}")
    if not tg.get("ok"):
        raise RuntimeError(f"タグ復元失敗: {tg}")
    return "ok"


if __name__ == "__main__":
    args = sys.argv[1:]
    dry = "--dry-run" in args
    keys = [a for a in args if not a.startswith("--")] or KEYS
    results = {}
    for k in keys:
        print(f"[bold-fix {k}]")
        try:
            results[k] = publish_one(k, dry_run=dry)
        except Exception as e:
            results[k] = f"FAIL: {e}"
            print(f"  !! {e}")
    print("\n=== 結果 ===")
    for k, v in results.items():
        print(f"  {k}: {v}")
    if any(str(v).startswith("FAIL") for v in results.values()):
        sys.exit(1)
