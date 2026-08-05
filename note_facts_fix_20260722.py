#!/usr/bin/env python3
"""「削除済み」とされながら公開され続けていた記事のうち、残す判断になった5本から
確定ファクト違反・禁止表現を外科的に除去する（2026-07-22）。

対象と主な違反:
  na36a4968c3bc #16 還元率        業界相場の具体%（70〜90%/80%/10〜30%）
  n84121e6b7eab #32 移籍          リスナー呼び捨て
  n699ef655effb #35 契約書10項目  違反なし（ローカル原稿復元のみ）
  ndc2f493ebdde #63 TikTok1000人  所属50名（旧表記）／「挫折する人が9割」／「17日」断定
  n3e73861d21f5 #71 コアファン    月収100万円の内訳具体数字／「必ず10〜30人」／リスナー呼び捨て

機構は note_cta_publish.py と同じ（Chrome cookie + Playwright + reCAPTCHA + PUT + tag復元）。
タイトルも変える記事があるため、publish は本ファイル内に持つ。

使い方:
  python3 note_facts_fix_20260722.py --dry-run [<key> ...]
  python3 note_facts_fix_20260722.py [<key> ...]     # 省略時は対象5本すべて
"""
import re
import sys
import time

from note_cta_publish import NOTE_API, RECAPTCHA_SITEKEY, UA, chrome_cookies, get_note, req_session

# ── 記事ごとの本文置換ルール（旧文字列 -> 新文字列）──
BODY_RULES = {
    # #16 還元率の真実：業界相場の具体%を落として質的表現へ
    "na36a4968c3bc": [
        ("・還元率80% = 稼いだ報酬の20%を事務所に取られる",
         "・還元率が100%未満 = 稼いだ報酬の一部を事務所に取られる"),
        ("悪質な事務所は10〜30%を搾取している",
         "悪質な事務所はライバーの報酬から手数料を抜いている"),
        ("一方で、悪質な事務所は還元率70〜90%、つまりライバーの報酬から10〜30%を搾取しています。",
         "一方で、悪質な事務所は還元率を100%未満に設定し、ライバーが稼いだ報酬から手数料を差し引いています。"),
        ("・還元率が70〜90%（10〜30%を事務所が取る）",
         "・還元率が100%未満（差額を事務所が取る）"),
        ("月10万円稼いでいるライバーの場合、還元率80%の事務所だと毎月2万円が搾取されています。年間にすると24万円。これは決して小さな金額ではありません。",
         "還元率が100%未満の事務所では、稼いだぶんだけ毎月確実に手取りが目減りしていきます。1年、2年と活動を続けるほど、その差は無視できない金額になります。"),
        ("・悪質な事務所: 還元率70〜90%（10〜30%を搾取）",
         "・悪質な事務所: 還元率が100%未満（差額を事務所が取る）"),
    ],

    # #32 移籍：ファクト違反なし。呼称のみ
    "n84121e6b7eab": [],

    # #35 契約書10項目：違反なし
    "n699ef655effb": [],

    # #63 TikTokフォロワー1000人：旧所属数・挫折率・日数の断定
    "ndc2f493ebdde": [
        ("<strong>TikTokのフォロワー1,000人の壁で挫折する人が9割</strong>",
         "<strong>TikTokのフォロワー1,000人の壁は、多くの人がつまずくポイント</strong>"),
        ("所属ライバー50名のTikTokフォロワー成長データから、<strong>平均17日でフォロワー1,000人</strong>を達成した再現性のある方法を全公開します。",
         "所属ライバー200名のTikTokフォロワー成長データから、<strong>フォロワー1,000人</strong>までの伸ばし方を全公開します。"
         "（伸びるスピードはジャンル・投稿頻度・運によって変わります）"),
        ("17日でフォロワー1,000人｜所属ライバー50名の実証ステップ",
         "フォロワー1,000人までのロードマップ｜所属ライバー200名の実証ステップ"),
        ("ここから本題。<strong>やった人ほぼ全員が17日前後で1,000人を達成</strong>したロードマップです。",
         "ここから本題。うちの所属ライバーが実際に踏んでいるロードマップです。"),
        ("冒頭：「TikTokフォロワー1000人を17日で達成した方法」",
         "冒頭：「TikTokフォロワー1000人を達成した方法」"),
    ],

    # #71 コアファン：月収100万円の内訳具体数字・断定表現
    "n3e73861d21f5": [
        ("月収100万円のライバーには、必ず10〜30人のコアファンがいます。",
         "月収の大きいライバーには、必ずと言っていいほど「毎回来てくれるコアファン」がいます。"),
        ("A. <strong>月収目標で逆算</strong>してください。月収10万円なら5〜10人、月収50万円なら15〜30人、月収100万円なら30〜50人が目安。少数精鋭の方が、関係性は深く長続きします。",
         "A. <strong>明確な正解はありません</strong>。目安は「名前と近況をちゃんと覚えていられる範囲」まで。"
         "数を追って一人ひとりが薄くなるより、少数精鋭の方が関係性は深く長続きします。"),
    ],
}

# ── <p id="..."> 単位で差し替える／削除するルール ──
# （箇条書きの行ごと消す必要があるものはこちら）
PARA_RULES = {
    "n3e73861d21f5": {
        # 月収100万円の内訳（トップファン3名=60万 等）は確定ファクトで禁止 → 質的表現に置換
        "1ff1b7bd-b5d9-4032-83fd-fcdaba5a7b9c": "<strong>ポイントは「人数」ではなく「濃さ」</strong>：",
        "e1c22da1-0c57-423d-9c55-3b0b2ac4e1cb": None,
        "44845b92-088d-4371-a8e3-8eeb74ed0578": None,
        "f3b933e6-a00d-4dd5-9065-8080f11d26d4": None,
        "248b27c0-7a06-4b32-9c76-1f73a2daff06":
            "つまり、<strong>収入の大半は、ごく少数のコアファン・トップファンが生み出している</strong>ということ。"
            "フォロワーの数を追うより、いま来てくれている人を大切にするほうが結果的に早い——理由はここにあります。",
    },
}

# ── タイトル変更（旧所属数などが入っているもの）──
TITLE_RULES = {
    "ndc2f493ebdde": (
        "TikTok LIVE フォロワー1000人を最速17日で集める方法｜事務所50名の実データ全公開【2026年版】",
        "TikTok LIVE フォロワー1000人を集める方法｜事務所200名の実データ全公開【2026年版】",
    ),
}

KEYS = ["na36a4968c3bc", "n84121e6b7eab", "n699ef655effb", "ndc2f493ebdde", "n3e73861d21f5"]

# 公開後の自己検証。ここに引っかかる文字列が残っていたら失敗扱い
FORBIDDEN = [
    "還元率70〜90%", "還元率80%", "10〜30%を搾取", "挫折する人が9割",
    "所属ライバー50名", "事務所50名", "必ず10〜30人",
    "トップファン3名：合計60万円", "コアファン15名＋トップファン3名",
    "月収100万円ライバーの内訳例",
]


def fix_listener_honorific(html):
    """リスナー呼び捨てを「リスナーさん」に統一する（既に「さん」付きは触らない）"""
    return re.sub(r"リスナー(?!さん)(?!ズ)", "リスナーさん", html)


def replace_para(html, para_id, new_inner):
    """<p name="ID" id="ID">…</p> の中身を差し替える。new_inner が None なら段落ごと削除。"""
    pat = re.compile(r'<p name="%s" id="%s">(.*?)</p>' % (re.escape(para_id), re.escape(para_id)),
                     re.DOTALL)
    m = pat.search(html)
    if not m:
        raise ValueError(f"段落が見つからない: {para_id}")
    if new_inner is None:
        return html[:m.start()] + html[m.end():]
    return html[:m.start()] + f'<p name="{para_id}" id="{para_id}">{new_inner}</p>' + html[m.end():]


def transform(key, html):
    out = html
    for old, new in BODY_RULES.get(key, []):
        if old not in out:
            raise ValueError(f"置換対象が見つからない (key={key}): {old[:40]}…")
        out = out.replace(old, new)
    for para_id, new_inner in PARA_RULES.get(key, {}).items():
        out = replace_para(out, para_id, new_inner)
    out = fix_listener_honorific(out)
    return out


def publish_one(key, dry_run=False):
    from playwright.sync_api import sync_playwright

    s = req_session()
    d = get_note(s, key, draft=False)
    note_id = d["id"]
    old_body = d["body"]
    new_body = transform(key, old_body)
    title = d["name"]
    if key in TITLE_RULES:
        old_t, new_t = TITLE_RULES[key]
        if title != old_t:
            raise ValueError(f"タイトルが想定と違う (key={key}): {title}")
        title = new_t
    tags = [h["hashtag"]["name"].lstrip("#") for h in d.get("hashtag_notes", [])][:10]

    print(f"  id={note_id} title={title[:40]}")
    print(f"  body {len(old_body)} -> {len(new_body)}  tags={len(tags)}")
    if new_body == old_body and title == d["name"]:
        print("  変更なし — skip")
        return "skip"
    if dry_run:
        for f in FORBIDDEN:
            if f in new_body:
                print(f"  [dry-run] !!! 変換後にも残存: {f}")
        print("  [dry-run] 公開はしない")
        return "dry"

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
        # verifications のURLは https://note.com/api を絶対指定する。このページは
        # editor.note.com 配信で、そのCloudFrontは /api/* をoriginに流さず403(HTMLのエラー
        # ページ)を返すため、相対 '/api/...' だと100%失敗する（2026-08-05に実測で確定）。
        try:
            rc = page.evaluate("""async ({sitekey, url}) => {
                const g=(window.grecaptcha&&window.grecaptcha.enterprise)||window.grecaptcha;
                if(!g||typeof g.execute!=='function') return {error:'no grecaptcha'};
                try{
                    const t=await g.execute(sitekey,{action:'note_post'});
                    const r=await fetch(url,{method:'POST',
                      headers:{'Content-Type':'application/json','Accept':'application/json','X-Requested-With':'XMLHttpRequest'},
                      credentials:'include',
                      body:JSON.stringify({g_recaptcha_token_v3:t,g_recaptcha_action_v3:'note_post',via:'note_post'})});
                    return {status:r.status, body:(await r.text()).slice(0,200)};
                }catch(e){return {error:String(e)}}
            }""", {"sitekey": RECAPTCHA_SITEKEY,
                   "url": f"{NOTE_API}/v3/challenges/verifications"})
        except Exception as e:
            rc = {"error": str(e)}
        # 失敗しても中断しない（note公式のpublishも .catch(()=>{}) で捨ててPUTへ進む）。
        # note が検証必須に切り替えたらPUTが4xxで落ちるので、予兆としてWARNだけ残す。
        if rc.get("status") != 200:
            print(f"  [WARN] recaptcha verifications 異常（PUTは続行）: {rc}")
        else:
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
    left = [f for f in FORBIDDEN if f in dv["body"]]
    print(f"  --- verify --- status={dv['status']} eyecatch={'OK' if dv.get('eyecatch') else 'MISSING!'} "
          f"残存禁止表現={left or 'なし'}")
    if left:
        raise RuntimeError(f"verify失敗: 禁止表現が残っている {left}")

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
    for k in keys:
        print(f"[fix {k}]")
        publish_one(k, dry_run=dry)
