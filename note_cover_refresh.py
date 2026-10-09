#!/usr/bin/env python3
"""note_cover_refresh.py
公開済み記事のアイキャッチを、ローカルで作り直したカバー（blog/images/{番号}_*.png）へ差し替える。

確定ファクト（所属数など）がカバーに焼き込まれているため、ファクトが変わったら
`note_cover_make.py <番号...> --no-bg` で作り直したあとにこれで公開側へ反映する。

note_set_eyecatch.set_eyecatch の検証は「eyecatch が uploads/images を含むか」だけなので、
既にカバーがある記事では**差し替えに失敗しても✅になる**。ここでは
  ① 差し替え前の公開 eyecatch URL を控え、公開APIで「URLが変わった」ことまで待つ
  ② タグ数を前後で突合し、減っていたら控えたタグで ensure_tags 復元
を足している。エディタの見出し画像操作は PUT を打たないので本来タグは動かないが、念のため。

使い方:
  python3 note_cover_refresh.py 215:n1234abcd 214:n5678efgh ...
  python3 note_cover_refresh.py --dry-run 215:n1234abcd
  python3 note_cover_refresh.py --force 166:n757225e527ab   # 差し替え済みの記事をもう一度差し替える
ログ: data/note_cover_refresh_log.json（成功済みの key は再実行時にスキップ＝再開可能）
  ※スキップは key 単位なので、一度差し替えた記事のカバーを作り直して再度上げるときは
    --force が要る（無いと「未完了 0 本」で何もせず終わる。2026-10-09 #166/#168-#170 で実際に発生）
"""
import json
import os
import sys
import time

import requests

import note_set_eyecatch
import note_tag_guard

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "data", "note_cover_refresh_log.json")


def public_note(key):
    """公開APIの現在値（キャッシュを避ける）。"""
    r = requests.get(f"https://note.com/api/v3/notes/{key}?ts={int(time.time() * 1000)}",
                     headers={"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"},
                     timeout=20)
    r.raise_for_status()
    d = r.json().get("data", {})
    tags = [t.get("hashtag", {}).get("name", "").lstrip("#")
            for t in (d.get("hashtag_notes") or [])]
    return {"eyecatch": d.get("eyecatch") or "", "status": d.get("status"),
            "tags": [t for t in tags if t]}


def wait_changed(key, old_eyecatch, tries=8, wait=8):
    for _ in range(tries):
        cur = public_note(key)
        if "uploads/images" in cur["eyecatch"] and cur["eyecatch"] != old_eyecatch:
            return cur
        time.sleep(wait)
    return None


def load_log():
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_log(log):
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)


def refresh_one(num, key, log):
    before = public_note(key)
    print(f"\n#{num} {key} before: tags={len(before['tags'])} status={before['status']}")
    r = note_set_eyecatch.set_eyecatch(num, key, headless=True)
    after = wait_changed(key, before["eyecatch"])
    entry = {"num": num, "before_eyecatch": before["eyecatch"],
             "before_tags": len(before["tags"]), "set_result": r,
             "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if not after:
        entry["ok"] = False
        entry["reason"] = "公開APIのeyecatchが変わらない（差し替え未反映）"
        print(f"  ❌ {entry['reason']}")
        log[key] = entry
        save_log(log)
        return False
    if len(after["tags"]) < len(before["tags"]):
        print(f"  ⚠ タグ減少 {len(before['tags'])}→{len(after['tags'])} → 復元")
        note_tag_guard.ensure_tags(key, hashtags=before["tags"], article_num=num,
                                   min_tags=len(before["tags"]))
        after = public_note(key)
    entry.update({"ok": len(after["tags"]) >= len(before["tags"])
                  and after["status"] == "published",
                  "after_eyecatch": after["eyecatch"], "after_tags": len(after["tags"]),
                  "after_status": after["status"]})
    print(f"  {'✅' if entry['ok'] else '❌'} tags={entry['after_tags']} "
          f"status={entry['after_status']} eyecatch={after['eyecatch'][:90]}")
    log[key] = entry
    save_log(log)
    return entry["ok"]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    pairs = []
    for a in args:
        n, k = a.split(":", 1)
        pairs.append((int(n), k))
    if not pairs:
        print(__doc__)
        return 1
    missing = [n for n, _ in pairs if not note_set_eyecatch.resolve_image(n)]
    if missing:
        print(f"カバー画像が無い: {missing}")
        return 1
    log = load_log()
    todo = [(n, k) for n, k in pairs if force or not log.get(k, {}).get("ok")]
    print(f"対象 {len(pairs)} 本 / 未完了 {len(todo)} 本")
    if dry:
        for n, k in todo:
            print(f"  #{n} {k} ← {os.path.basename(note_set_eyecatch.resolve_image(n))}")
        return 0
    note_tag_guard.refresh_cookies()
    fails = []
    for n, k in todo:
        try:
            ok = refresh_one(n, k, log)
        except Exception as e:
            print(f"  ❌ 例外: {e}")
            log[k] = {"num": n, "ok": False, "reason": f"例外: {e}"}
            save_log(log)
            ok = False
        if not ok:
            fails.append(n)
        time.sleep(3)
    print(f"\n完了: 成功 {len(todo) - len(fails)} / 失敗 {len(fails)} {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
