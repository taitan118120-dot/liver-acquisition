"""現状qualified=0 だが新ルールで qualified=1 になる例と、その差分理由を出力"""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
from qualify import qualify_profile

cfg = db.all_settings()
print("=== cfg ===")
for k in ("min_followers", "max_followers", "min_posts", "max_ratio", "age_min", "age_max",
         "max_followers_agency", "min_followers_agency", "max_followers_existing"):
    print(f"  {k} = {cfg.get(k)}")
print()

with db.get_conn() as conn:
    rows = conn.execute(
        "SELECT id, username, name, bio, followers, following, post_count, target_type, qualified, qualified_reasons "
        "FROM leads WHERE status='未接触' AND qualified=0"
    ).fetchall()

flips = []
for r in rows:
    profile = {
        "username": r["username"],
        "full_name": r["name"] or "",
        "biography": r["bio"] or "",
        "followers": r["followers"],
        "following": r["following"],
        "post_count": r["post_count"],
        "is_private": False,
        "is_verified": False,
        "is_business": False,
        "category": None,
    }
    ttype = r["target_type"] or "beginner"
    ok, reasons = qualify_profile(profile, cfg, target_type=ttype)
    if ok:
        flips.append((r["username"], r["name"], r["target_type"], r["qualified_reasons"]))

print(f"qualified=0 → after=1 になる件数: {len(flips)}")
print()
print("--- 例（最大30件、現在のreasons） ---")
for u, n, t, reasons in flips[:30]:
    print(f"  [{t}] {u} | {(n or '')[:30]} | old reasons: {reasons}")
