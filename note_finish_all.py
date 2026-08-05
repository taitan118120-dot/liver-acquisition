#!/usr/bin/env python3
"""残り全記事のCTA更新＋タグ維持を冪等に完了させる。
各記事:
  - cta未済なら fetch-PUT で本文更新（タグは0になる）
  - 元タグ>0 で現タグ<元 なら UI でタグ復元
最後に全34本を検証。
"""
import sys, json, time
sys.path.insert(0, "/tmp"); from note_map import KEY_FILE
import note_cta_publish as P
import note_ui_publish as U

def cur_state(s, key):
    import time as t
    d = s.get(f"https://note.com/api/v3/notes/{key}?ts={int(t.time()*1000)}", timeout=20).json()["data"]
    tags = [h["hashtag"]["name"] for h in d.get("hashtag_notes", [])]
    return {"cta": "まずはLINEで気軽に" in d["body"], "old": "オンライン無料相談" in d["body"],
            "tags": len(tags), "eye": bool(d.get("eyecatch")), "body_len": len(d["body"])}

def main():
    log = open("/tmp/note_finish_all.log", "a", encoding="utf-8")
    def pr(*a):
        msg = " ".join(str(x) for x in a); print(msg); log.write(msg+"\n"); log.flush()

    s = P.req_session()
    pr("\n===== START", time.strftime("%H:%M:%S"), "=====")
    for key, fn in KEY_FILE:
        bk = json.load(open(f"data/note_html_backup/{key}.json", encoding="utf-8"))
        bk_tags = [h["hashtag"]["name"].lstrip("#") for h in bk.get("hashtag_notes", [])][:10]
        st = cur_state(s, key)
        pr(f"\n[{key}] {fn[:24]} cta={st['cta']} tags={st['tags']}/{len(bk_tags)} eye={st['eye']}")

        # 1) body
        if not st["cta"]:
            pr("  -> body update")
            try:
                P.publish_one(key)
            # publish_one は NotePublishError（RuntimeError）で落ちる。旧実装の SystemExit も残す
            except (SystemExit, Exception) as e:
                pr("  !! body update FAILED:", e); continue
            time.sleep(4)
            st = cur_state(s, key)

        # 2) tag restore
        if len(bk_tags) > 0 and st["tags"] < len(bk_tags):
            pr(f"  -> tag restore ({st['tags']} -> {len(bk_tags)})")
            try:
                U.update(key, bk_tags, change_body=False)
            except SystemExit as e:
                pr("  !! tag restore FAILED:", e)
            time.sleep(4)

    # final verify
    pr("\n===== FINAL VERIFY =====")
    bad = []
    for key, fn in KEY_FILE:
        bk = json.load(open(f"data/note_html_backup/{key}.json", encoding="utf-8"))
        bkn = len(bk.get("hashtag_notes", []))
        bkn = min(bkn, 10)
        st = cur_state(s, key)
        ok = st["cta"] and not st["old"] and (st["tags"] >= bkn) and st["eye"] == bool(bk.get("eyecatch"))
        flag = "OK " if ok else "BAD"
        if not ok: bad.append((key, fn))
        pr(f"  {flag} {fn[:26]:26} cta={st['cta']} old_gone={not st['old']} tags={st['tags']}/{bkn} eye={st['eye']}")
    pr(f"\nDONE. bad={len(bad)} {[b[1] for b in bad]}")
    pr("===== END", time.strftime("%H:%M:%S"), "=====")
    log.close()

if __name__ == "__main__":
    main()
