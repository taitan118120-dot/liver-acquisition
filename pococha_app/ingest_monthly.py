"""月次レポート(/monthly_liver_report)のJSON → SQLite 取り込み.

使い方:
    python3 ingest_monthly.py data/monthly/monthly_11874524_2026-05.json
    python3 ingest_monthly.py data/monthly/*.json
    cat report.json | python3 ingest_monthly.py -
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from db import connect

COLS = [
    "user_id", "month", "final_rank", "max_rank",
    "total_dia", "time_dia", "hype_dia",
    "stream_min", "stream_days", "support_points",
    "comments", "comment_people", "likes", "like_people",
    "viewed_min", "listeners", "daily_best", "monthly_rank",
    "followers", "captured_at",
]


def ingest_one(conn, payload):
    rec = {k: payload.get(k) for k in COLS}
    rec["user_id"] = int(rec["user_id"]) if rec["user_id"] is not None else None
    if rec["user_id"] is None or not rec["month"]:
        raise ValueError(f"user_id/month が空: {rec}")

    placeholders = ",".join(["?"] * len(COLS))
    update = ",".join(f"{c}=excluded.{c}" for c in COLS if c not in ("user_id", "month"))
    conn.execute(
        f"INSERT INTO monthly_reports ({','.join(COLS)}) VALUES ({placeholders}) "
        f"ON CONFLICT(user_id, month) DO UPDATE SET {update}",
        [rec[c] for c in COLS],
    )
    return rec["user_id"], rec["month"]


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)

    paths = []
    for a in args:
        if a == "-":
            paths.append("-")
        else:
            paths.extend(sorted(glob.glob(a)) or [a])

    conn = connect()
    n = 0
    for p in paths:
        raw = sys.stdin.read() if p == "-" else open(p, encoding="utf-8").read()
        payload = json.loads(raw)
        uid, month = ingest_one(conn, payload)
        print(f"  取り込み: user_id={uid} month={month}  ({p if p!='-' else 'stdin'})")
        n += 1
    conn.commit()
    conn.close()
    print(f"完了: {n}件")


if __name__ == "__main__":
    main()
