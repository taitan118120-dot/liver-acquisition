#!/usr/bin/env python3
"""公開済みnote記事の本文に、太字化されなかった生Markdownの ** が残っていないか全数点検する。

対象は data/note_key_map.json ではなくアカウントの全公開記事一覧（note_key_map は
未登録の記事があり取りこぼすため）。

使い方: python3 note_asterisk_scan.py [--json out.json]
"""
import json
import re
import sys
import time

from note_cta_publish import NOTE_API, get_note, req_session

URLNAME = "taitan_118"

TAG_RE = re.compile(r"<[^>]+>")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def strip_tags(html):
    return TAG_RE.sub("", html)


def all_published(s):
    """アカウントの全公開記事 (key, title) を返す"""
    out, page = [], 1
    while True:
        r = s.get(f"{NOTE_API}/v2/creators/{URLNAME}/contents?kind=note&page={page}", timeout=25)
        r.raise_for_status()
        d = r.json()["data"]
        for n in d["contents"]:
            out.append({"key": n["key"], "title": n["name"]})
        if d.get("isLastPage"):
            break
        page += 1
        time.sleep(0.8)
    return out


def scan():
    s = req_session()
    notes = all_published(s)
    km = {v["key"]: no for no, v in json.load(open("data/note_key_map.json")).items()}
    print(f"公開記事 {len(notes)} 本を点検します\n")
    hits, errors = [], []
    for i, n in enumerate(notes, 1):
        key = n["key"]
        try:
            d = get_note(s, key, draft=False)
        except Exception as e:
            errors.append({"key": key, "title": n["title"], "error": str(e)})
            print(f"[{i:>3}] {key}  ERROR {e}")
            time.sleep(1.2)
            continue
        text = strip_tags(d["body"])
        cnt = text.count("**")
        if cnt:
            pairs = BOLD_RE.findall(text)
            hits.append({"no": km.get(key), "key": key, "title": d["name"],
                         "count": cnt, "pairs": len(pairs),
                         "samples": [p[:80] for p in pairs[:8]]})
            print(f"[{i:>3}] {key}  ** x{cnt} (対 {len(pairs)})  #{km.get(key)} {d['name'][:34]}")
            for p in pairs[:4]:
                print(f"        -> **{p[:70]}**")
        time.sleep(1.2)
    print(f"\n該当 {len(hits)} 本 / 全 {len(notes)} 本  (エラー {len(errors)})")
    return {"hits": hits, "errors": errors, "total": len(notes)}


if __name__ == "__main__":
    res = scan()
    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        json.dump(res, open(out, "w"), ensure_ascii=False, indent=2)
        print(f"saved: {out}")
