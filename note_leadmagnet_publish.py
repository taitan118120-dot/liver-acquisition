#!/usr/bin/env python3
"""公開済みnote記事のCTAにLINE登録特典（リードマグネット）の1段落を外科的に挿入する。

- 挿入位置: 本文末尾側の lin.ee リンクを含む <p> ブロックの直前
- 冪等: 本文に「スタートダッシュガイド」が既にあればスキップ
- 公開の3段は note_publish_core.publish_via_editor が正本（cookieはChromeから取る）

使い方:
  python3 note_leadmagnet_publish.py <key> [<key> ...]   # 指定記事のみ
  python3 note_leadmagnet_publish.py --all               # data/published_note_keys.json 全件
  python3 note_leadmagnet_publish.py --verify <key>      # 検証のみ(GET)
"""
import json
import os
import sys
import time

from note_cta_publish import chrome_cookies, get_note, req_session
from note_publish_core import editor_browser, publish_via_editor

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


def publish_one(key, transform_fn=None, expect_marker=LM_MARK, title_fn=None):
    """記事本文を transform_fn で書き換えて再公開する。

    expect_marker: 反映確認に使う文字列。transform_fn を差し替える呼び出し側は
        自分が挿入したマーカーを渡すこと（None で本文チェックを省略）。
    title_fn: タイトルも書き換えたいときに (key, title) -> 新タイトル or None を渡す。
        既定（None）では**現在のタイトルをそのまま通す**ので、本文だけを直す
        従来の呼び出しは何も変わらない。
        タイトルを直す必要が実際にある: 2026-08-28 に「初見リスナーを常連化する」
        のような呼び捨てが3本のタイトルに残っていた。しかもタイトルは
        note_internal_links_publish.related_html がリンク文言として**他記事の本文へ
        コピーする**ので、直さないと違反が他記事へ増殖し続ける。
    """
    s = req_session()
    d = get_note(s, key, draft=False)
    note_id = d["id"]
    title = d["name"]
    old_body = d["body"]
    new_body = (transform_fn or transform)(key, old_body)
    new_title = title_fn(key, title) if title_fn else None
    # 本文・タイトルのどちらかが変われば公開しなおす。
    # 「本文は既に直っているがタイトルだけ違反」を skip で落とさないための順序。
    if new_body is None and (not new_title or new_title == title):
        print("  skip（済み or CTAなし）")
        return "skip"
    if new_body is None:
        new_body = old_body
    if new_title and new_title != title:
        print(f"  title 変更: {title[:34]} -> {new_title[:34]}")
        title = new_title
    tags = [h["hashtag"]["name"].lstrip("#") for h in d.get("hashtag_notes", [])][:10]
    print(f"  id={note_id} title={title[:24]}")
    print(f"  body {len(old_body)} -> {len(new_body)}  tags={len(tags)}")

    with editor_browser(chrome_cookies()) as page:
        publish_via_editor(page, note_id, key, title, new_body, tags,
                           disable_comment=d.get("disable_comment", False),
                           limited=d.get("is_limited", False))

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
