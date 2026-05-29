"""過去配信のコメントJSON → SQLite 取り込み.

入力JSON: [{liver, stream_id, commenter, text, timing?, posted_at?, level?}, ...]

使い方:
    python3 ingest_comments.py cmt_part1.json cmt_part2.json ...
    cat dump.json | python3 ingest_comments.py -
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from db import connect


def ingest(items, source="history"):
    conn = connect()
    saved = 0
    for it in items:
        commenter = (it.get("commenter") or "").strip()
        text = (it.get("text") or "").strip()
        if not commenter or "*****" in commenter:
            continue
        liver = (it.get("liver") or "").strip()
        stream_id = (it.get("stream_id") or "").strip()
        timing = (it.get("timing") or "").strip()
        posted_at = (it.get("posted_at") or "").strip()
        level = (it.get("level") or "").strip()
        key = f"{liver}|{stream_id}|{commenter}|{text}|{posted_at or it.get('client_ts','')}"
        cur = conn.execute(
            """INSERT OR IGNORE INTO comments
                 (liver, stream_id, commenter, level, text, timing, posted_at, source, dedupe_key)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (liver, stream_id, commenter, level, text, timing, posted_at, source, key),
        )
        saved += cur.rowcount
    conn.commit()
    conn.close()
    return saved


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    total_in = total_saved = 0
    for src in args:
        raw = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
        items = json.loads(raw)
        if isinstance(items, dict):
            items = items.get("rows") or items.get("comments") or [items]
        total_in += len(items)
        total_saved += ingest(items)
    print(f"取り込み: 入力{total_in}件 / 新規保存{total_saved}件（重複/マスクは除外）")


if __name__ == "__main__":
    main()
