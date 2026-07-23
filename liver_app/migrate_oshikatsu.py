"""推し活タグでリサーチされた既存リードを agency → beginner に移行 (2026-05-06)
対象: source_tag が 推し活系 OR target_type=agency かつ qualified_reasons に「推し活」を含む。
beginner ルールで qualify_profile を再実行し、qualified を更新する。"""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
from qualify import qualify_profile

OSHIKATSU_TAGS = {
    "推し活", "推し活女子", "推し活アカ", "推し活仲間募集",
    "推し活初心者", "推しのいる生活", "推し事",
    "ジャニヲタ", "ジャニーズ担当", "アイドル好き",
    "Vtuber推し", "二次元推し", "担当", "単担", "箱推し",
    "ガチ恋", "現場参戦",
}


def main(dry_run=False):
    cfg = db.all_settings()
    moved = 0
    new_qualified = 0
    new_disq = 0
    examples = []
    with db.get_conn() as conn:
        # source_tag が推し活系のリード（target_type 関係なく拾う）
        rows = conn.execute(
            "SELECT id, username, name, bio, followers, following, post_count, target_type, source_tag, qualified, qualified_reasons "
            "FROM leads WHERE status='未接触' AND source_tag IN ({})".format(
                ",".join(["?"] * len(OSHIKATSU_TAGS))
            ),
            list(OSHIKATSU_TAGS),
        ).fetchall()

        for r in rows:
            old_ttype = r["target_type"] or "beginner"
            if old_ttype == "beginner":
                continue  # 既に beginner ならスキップ
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
            ok, reasons = qualify_profile(profile, cfg, target_type="beginner")
            old_q = r["qualified"]
            new_q = 1 if ok else 0
            if not dry_run:
                conn.execute(
                    "UPDATE leads SET target_type='beginner', qualified=?, qualified_reasons=? WHERE id=?",
                    (new_q, json.dumps(reasons, ensure_ascii=False), r["id"]),
                )
            moved += 1
            if old_q == 0 and new_q == 1:
                new_qualified += 1
                if len(examples) < 30:
                    examples.append((r["username"], r["name"], "✓ 復活(beginner)"))
            elif old_q == 1 and new_q == 0:
                new_disq += 1
                if len(examples) < 30:
                    examples.append((r["username"], r["name"], f"× {','.join(reasons[:2])}"))
        if not dry_run:
            conn.commit()
    print(f"=== migrate_oshikatsu {'DRY-RUN' if dry_run else 'APPLIED'} ===")
    print(f"対象（source_tag=推し活系 かつ target_type≠beginner）: {moved}")
    print(f"  → beginner化により新規qualified: {new_qualified}")
    print(f"  → beginner化により新規disqualified: {new_disq}")
    print()
    print("--- 例（最大30件） ---")
    for u, n, why in examples:
        print(f"  {u} | {(n or '')[:40]} | {why}")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    main(dry_run=dry)
