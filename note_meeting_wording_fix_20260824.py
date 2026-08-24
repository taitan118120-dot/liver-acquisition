#!/usr/bin/env python3
"""公開済みnote記事から自社導線の「オンライン面談」「無料面談」を外科的に消す（2026-08-24）。

背景 [[feedback_no_online_meeting_wording]]:
  4392b4f で着地先（LP2本 #flow STEP3・公式LINE Bot）から「面談」表記を全廃し
  「LINE通話で個別に相談」に統一した。公開済みnote記事には旧表現が残っていて、
  広告・記事から来た読者が着地先で「面談」という語に出会わない状態だった。

方針（ユーザー確認済み・2026-08-24）:
  - 直すのは **自社導線** を指す用法だけ。
  - 「他社を含めて3社の面談を受けて比較しよう」のような読者への助言（一般論）は残す。
  - 「面談」単体はリッチメニューのボタン名＝送信キーワードなので触らない。

実装は note_cta_publish.py と同じ3段（note_publish_core が正本）:
  draft_save → reCAPTCHA v3 verifications → PUT status=published
  公開PUTは hashtags を無視してタグを0にする既知問題があるため、
  note_tag_guard.ensure_tags でUI経由で復元する [[project_note_tag_guard]]。

使い方:
  python3 note_meeting_wording_fix_20260824.py --scan        # 読み取りのみ。対象を洗い出す
  python3 note_meeting_wording_fix_20260824.py --all         # 対象を全部更新
  python3 note_meeting_wording_fix_20260824.py <key> [...]   # 個別指定
  python3 note_meeting_wording_fix_20260824.py --verify <key>
"""
import sys, json, os, time
import requests, browser_cookie3
from note_publish_core import (NOTE_API_BASE as NOTE_API, NOTE_UA as UA,
                               editor_browser, publish_via_editor)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEYS_FILE = os.path.join(BASE_DIR, "data", "published_note_keys.json")
KEYMAP_FILE = os.path.join(BASE_DIR, "data", "note_key_map.json")

# ローカル原稿(blog/articles_note)に当てたのと同じ置換。順序に意味がある
# （長いものを先に当てないと、短い方が先に食って別文が残る）。
REPLACEMENTS = [
    ("まずは15分の無料面談で、あなたに合った配信スタイルを一緒に考えましょう。",
     "まずはLINE通話で15分ほど、あなたに合った配信スタイルを一緒に考えましょう。"),
    ("まずは15分の無料面談で、あなたに合った始め方を一緒に考えましょう。",
     "まずはLINE通話で15分ほど、あなたに合った始め方を一緒に考えましょう。"),
    ("まずは15分の無料オンライン面談で、あなたに合ったプランを一緒に考えましょう。",
     "まずはLINE通話で15分ほど、あなたに合ったプランを一緒に考えましょう。"),
    ("15分の無料面談で、あなたの可能性を一緒に探しましょう。",
     "LINE通話で15分ほど、あなたの可能性を一緒に探しましょう。"),
    ("事務所に相談する（15分の無料面談）", "事務所に相談する（LINE通話で15分）"),
    ("まずは気になる事務所の無料面談を受けてみて、",
     "まずは気になる事務所に相談してみて、"),
    ("いきなり一人で始めるのは非効率</strong>です。事務所の無料面談で：",
     "いきなり一人で始めるのは非効率</strong>です。事務所への相談で："),
    ("いきなり一人で始めるのは非効率**です。事務所の無料面談で：",
     "いきなり一人で始めるのは非効率**です。事務所への相談で："),
    # 箇条書き（note本文はHTML。素のMarkdown形も一応残す）
    ("オンライン面談で全国対応", "LINE通話で全国対応"),
    # 自社が提供する面談の言い換え
    ("仕組みの説明だけのオンライン面談をご用意しています。",
     "仕組みの説明だけのLINE通話もご用意しています。"),
    ("仕組みの説明だけのオンライン面談</strong>をご用意しています。",
     "仕組みの説明だけのLINE通話</strong>もご用意しています。"),
    ("仕組みの説明だけのオンライン面談**をご用意しています。",
     "仕組みの説明だけのLINE通話**もご用意しています。"),
    ("A. まずは公式LINEで無料相談。オンライン面談（15分程度）で配信プランを一緒に決めて、",
     "A. まずは公式LINEでご相談ください。LINE通話で15分ほど配信プランを一緒に決めて、"),
    ("契約条件を面談時にすべて説明し、書面でも明示",
     "契約条件をLINE通話ですべて説明し、書面でも明示"),
    ("TAITAN PROの面談（LINEでの相談からでOK）では、この記事に書いた質問すべてに",
     "TAITAN PROでは、LINE通話でのご相談（チャットだけでもOK）で、この記事に書いた質問すべてに"),
    ("気軽にLINEください。面談だけでOKです。",
     "気軽にLINEください。話を聞くだけでOKです。"),
    ("月1回のオンライン面談", "月1回のLINE通話での個別相談"),
]

# 直してはいけない一般論（残すと決めた用法）。scan の目視用。
KEEP_CONTEXTS = ("3社のオンライン面談", "オンライン面談を複数受けて",
                 "ステップ3：オンライン面談を提案")


def transform(body):
    for old, new in REPLACEMENTS:
        body = body.replace(old, new)
    return body


def chrome_cookies():
    return [{"name": c.name, "value": c.value,
             "domain": c.domain or ".note.com", "path": c.path or "/",
             "httpOnly": False, "secure": True, "sameSite": "Lax"}
            for c in browser_cookie3.chrome(domain_name="note.com")]


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


def load_keys():
    with open(KEYS_FILE, encoding="utf-8") as f:
        return json.load(f)


def title_of(key):
    try:
        with open(KEYMAP_FILE, encoding="utf-8") as f:
            for num, rec in json.load(f).items():
                if rec.get("key") == key:
                    return f"#{num} {rec.get('title','')[:30]}"
    except Exception:
        pass
    return key


def scan():
    """公開本文を読んで、置換が実際に効く記事だけを返す（書き込みなし）。"""
    s = req_session()
    hits, keep_only, failed = [], [], []
    keys = load_keys()
    for i, key in enumerate(keys, 1):
        try:
            d = get_note(s, key, draft=False)
        except Exception as e:
            failed.append((key, str(e)[:60]))
            continue
        body = d["body"]
        new = transform(body)
        if new != body:
            hits.append(key)
            print(f"  [対象] {title_of(key)}  ({key})")
        elif "面談" in body:
            ctx = [c for c in KEEP_CONTEXTS if c in body]
            keep_only.append((key, ctx))
        if i % 20 == 0:
            print(f"  … {i}/{len(keys)} 走査")
        time.sleep(0.3)
    print(f"\n対象 {len(hits)} 件 / 一般論のみで据え置き {len(keep_only)} 件 / 取得失敗 {len(failed)} 件")
    for k, ctx in keep_only:
        print(f"  [据え置き] {title_of(k)} {ctx or '(面談を含むが自社導線ではない)'}")
    for k, e in failed:
        print(f"  [取得失敗] {k}: {e}")
    return hits, failed


def verify(key):
    s = req_session()
    d = get_note(s, key)
    body = d["body"]
    tags = [h["hashtag"]["name"] for h in d.get("hashtag_notes", [])]
    left = [o for o, _ in REPLACEMENTS if o in body]
    print(f"  status={d['status']}  eyecatch={'OK' if d.get('eyecatch') else 'MISSING!'}  "
          f"tags={len(tags)}  body_len={len(body)}  旧表現残り={len(left)}")
    if left:
        print(f"    !!! 残っている: {left}")
    return d, not left, bool(d.get("eyecatch")), len(tags)


def publish_one(key):
    s = req_session()
    d = get_note(s, key, draft=False)
    note_id, title, old_body = d["id"], d["name"], d["body"]
    new_body = transform(old_body)
    if new_body == old_body:
        print("  変更なし。スキップ")
        return None
    tags = [h["hashtag"]["name"].lstrip("#") for h in d.get("hashtag_notes", [])][:10]
    print(f"  id={note_id} title={title[:30]}")
    print(f"  body {len(old_body)} -> {len(new_body)}  tags={tags}")

    with editor_browser(chrome_cookies()) as page:
        publish_via_editor(page, note_id, key, title, new_body, tags,
                           disable_comment=d.get("disable_comment", False),
                           limited=d.get("is_limited", False))

    time.sleep(2)
    print("  --- verify ---")
    dv, clean, eye, ntags = verify(key)
    if not eye:
        print("  !!! WARNING: eyecatch が消えた可能性。要復元")

    from note_tag_guard import ensure_tags
    tg = ensure_tags(key, hashtags=tags, title=title)
    print(f"  tag_guard: {tg}")
    if not tg.get("ok"):
        print(f"  !!! WARNING: タグ復元失敗 {tg}")
    return clean


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__); raise SystemExit(1)
    if args[0] == "--scan":
        scan()
    elif args[0] == "--verify":
        for k in args[1:]:
            print(f"[verify {k}]"); verify(k)
    elif args[0] == "--all":
        targets, _ = scan()
        print(f"\n=== {len(targets)} 件を更新します ===")
        ok = ng = 0
        for i, k in enumerate(targets, 1):
            print(f"\n[{i}/{len(targets)} publish {k}] {title_of(k)}")
            try:
                r = publish_one(k)
                if r: ok += 1
                elif r is False: ng += 1
            except Exception as e:
                ng += 1
                print(f"  !!! 失敗: {e}")
            time.sleep(2)
        print(f"\n成功 {ok} / 失敗・要確認 {ng}")
        if ng:
            raise SystemExit(1)
    else:
        for k in args:
            print(f"[publish {k}]"); publish_one(k)
