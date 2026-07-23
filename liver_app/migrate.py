"""既存のleads.csv + ig_qualified.jsonをSQLiteに流し込むワンショットスクリプト"""
import csv
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import init_db, get_conn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEADS_CSV = os.path.join(ROOT, "data", "leads.csv")
QUALIFIED_JSON = os.path.join(ROOT, "data", "ig_qualified.json")


def main():
    init_db()
    if not os.path.exists(LEADS_CSV):
        print("leads.csv が見つかりません")
        return
    qualified = {}
    if os.path.exists(QUALIFIED_JSON):
        with open(QUALIFIED_JSON, "r", encoding="utf-8") as f:
            qualified = json.load(f)

    migrated = 0
    with open(LEADS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    with get_conn() as conn:
        for r in rows:
            if r.get("platform") != "instagram":
                continue
            q = qualified.get(r["id"], {})
            passed = 1 if q.get("passed") else 0
            reasons = q.get("reasons", [])
            followers = q.get("followers") or (int(r["followers"]) if r.get("followers", "").isdigit() else None)
            following = q.get("following")

            existing = conn.execute("SELECT id FROM leads WHERE username = ?", (r["username"],)).fetchone()
            if existing:
                continue

            conn.execute(
                """
                INSERT INTO leads (id, username, name, bio, followers, following,
                                   source_tag, target_type, status, qualified,
                                   qualified_reasons, auto_qualified, found_date,
                                   dm_sent_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["id"],
                    r["username"],
                    r.get("name", ""),
                    r.get("bio", ""),
                    followers,
                    following,
                    "",  # source_tag
                    r.get("target_type", "beginner"),
                    r.get("status", "未接触"),
                    passed,
                    json.dumps(reasons, ensure_ascii=False),
                    1 if q.get("note") else 0,
                    r.get("found_date", datetime.now().strftime("%Y-%m-%d")),
                    r.get("dm_sent_date") or None,
                    r.get("notes", ""),
                ),
            )
            migrated += 1
        conn.commit()
    print(f"{migrated}件 のIGリードを SQLite に移行しました")


if __name__ == "__main__":
    main()
