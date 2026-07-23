"""現状DB(data.sqlite)の status='未接触' リードを最新qualifyルールで再判定する。
app.py の /api/requalify と同じロジックをスタンドアロンで実行。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
from qualify import (
    detect_target_type, qualify_profile,
    _guess_foreign, NAIL_SALON_RE, ESTABLISHED_AGENCY_RE, FOREIGN_PERSON_RE,
    BEAUTY_PRO_RE, NAME_BUSINESS_RE,
    _is_pet_account, _is_food_guide,
)


def revive_oshikatsu(dry_run=False):
    """推し活/ファン専用 を理由に弾かれたリードを再判定して復活させる。
    qualified_reasons に '推し活' を含むレコードを対象に qualify_profile を再実行。"""
    cfg = db.all_settings()
    revived = 0
    still_ng = 0
    examples = []
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, username, name, bio, followers, following, post_count, target_type, qualified_reasons "
            "FROM leads WHERE status='未接触' AND qualified=0 AND qualified_reasons LIKE '%推し活%'"
        ).fetchall()
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
                if not dry_run:
                    conn.execute(
                        "UPDATE leads SET qualified=1, qualified_reasons='[]' WHERE id=?",
                        (r["id"],),
                    )
                revived += 1
                if len(examples) < 30:
                    examples.append((r["username"], r["name"], "✓ 復活"))
            else:
                if not dry_run:
                    conn.execute(
                        "UPDATE leads SET qualified_reasons=? WHERE id=?",
                        (json.dumps(reasons, ensure_ascii=False), r["id"]),
                    )
                still_ng += 1
                if len(examples) < 30:
                    examples.append((r["username"], r["name"], f"× {','.join(reasons[:2])}"))
        if not dry_run:
            conn.commit()
    print(f"=== revive_oshikatsu {'DRY-RUN' if dry_run else 'APPLIED'} ===")
    print(f"対象（推し活理由含む qualified=0）: {len(rows)}")
    print(f"  → 復活(qualified=1): {revived}")
    print(f"  → 他理由でまだNG: {still_ng}")
    print()
    print("--- 例（最大30件） ---")
    for u, n, why in examples:
        print(f"  {u} | {(n or '')[:40]} | {why}")

# app.py と同じ。bio空でも source_tag から強推定
EL_TAGS = ('17LIVE','イチナナライブ','IRIAM','イリアム','ふわっち','BIGOLIVE',
           'ミクチャ','ツイキャス','SHOWROOM','ライブ配信','配信者','ライバーさんと繋がりたい')

STRONG_AGENCY_TAGS = frozenset({
    "ネイルサロン経営","美容室経営","エステサロン経営","コンカフェオーナー","治療院経営","カフェ経営",
    "SNS運用代行","コンテンツ販売初心者","物販","ネット副業",
    "銀座ホステス","六本木ラウンジ","ラウンジ嬢","キャバクラ嬢",
    "配信者好きと繋がりたい","推し活",
})


def main(dry_run=False, mode="B"):
    """mode=A: source_tag→agency昇格あり（app.py /api/requalify と同等）
    mode=B: 既存 target_type を保持し、新フィルタの除外だけ適用"""
    cfg = db.all_settings()
    with db.get_conn() as conn:
        # source_tag → target_type 補正（mode=A のみ）
        if mode == "A" and not dry_run:
            conn.execute(
                f"UPDATE leads SET target_type='existing_liver' WHERE source_tag IN ({','.join(['?']*len(EL_TAGS))}) AND target_type='beginner' AND status='未接触'",
                EL_TAGS,
            )
            sa_tags = tuple(STRONG_AGENCY_TAGS)
            conn.execute(
                f"UPDATE leads SET target_type='agency' WHERE source_tag IN ({','.join(['?']*len(sa_tags))}) AND target_type='beginner' AND status='未接触'",
                sa_tags,
            )
            conn.commit()

        # mode=B では現在qualified=1のリードだけ再判定（弾く方向のみ。qualified=0の保留中を蘇らせない）
        if mode == "B":
            rows = conn.execute(
                "SELECT id, username, name, bio, followers, following, post_count, target_type, source_tag, qualified "
                "FROM leads WHERE status='未接触' AND qualified=1"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, username, name, bio, followers, following, post_count, target_type, source_tag, qualified "
                "FROM leads WHERE status='未接触'"
            ).fetchall()
        total = len(rows)
        passed = 0
        disqualified = 0
        before_qualified = sum(1 for r in rows if r["qualified"])
        new_disq_examples = []
        new_disq_examples_all = []

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
            current = r["target_type"]
            src_tag = r["source_tag"] or ""
            if mode == "A":
                detected = detect_target_type(profile)
                if detected in ("agency", "existing_liver"):
                    ttype = detected
                elif current == "existing_liver":
                    ttype = "existing_liver"
                elif src_tag in STRONG_AGENCY_TAGS:
                    ttype = "agency"
                else:
                    ttype = "beginner"
            else:
                # mode=B: 既存 target_type を保持
                ttype = current or "beginner"

            if not profile["biography"] or len(profile["biography"]) < 5:
                _fn = profile.get("full_name", "") or ""
                _un = profile.get("username", "") or ""
                _name_text = _fn + " " + _un
                name_ng_reason = None
                if _guess_foreign("", _fn) or FOREIGN_PERSON_RE.search(_fn):
                    name_ng_reason = "外国籍疑い（bio未取得）"
                elif NAIL_SALON_RE.search(_name_text):
                    name_ng_reason = "ネイル系（bio未取得）"
                elif BEAUTY_PRO_RE.search(_name_text):
                    name_ng_reason = "美容師系（bio未取得）"
                elif ESTABLISHED_AGENCY_RE.search(_name_text):
                    name_ng_reason = "既存代理店疑い（bio未取得）"
                elif _is_pet_account(profile):
                    name_ng_reason = "ペット/犬猫アカ（bio未取得）"
                elif _is_food_guide(profile):
                    name_ng_reason = "グルメ/カフェ紹介アカ（bio未取得）"
                elif _is_oshikatsu(profile):
                    name_ng_reason = "推し活/ファン専用（bio未取得）"
                elif ttype == "beginner" and NAME_BUSINESS_RE.search(_fn):
                    name_ng_reason = "事業者肩書（bio未取得）"

                if name_ng_reason:
                    if r["qualified"]:
                        new_disq_examples_all.append((r["username"], r["name"], name_ng_reason))
                        if len(new_disq_examples) < 50:
                            new_disq_examples.append((r["username"], r["name"], name_ng_reason))
                    if not dry_run:
                        conn.execute(
                            "UPDATE leads SET qualified=0, qualified_reasons=?, target_type=? WHERE id=?",
                            (json.dumps([name_ng_reason], ensure_ascii=False), ttype, r["id"]),
                        )
                    disqualified += 1
                    continue

                ok, reasons = qualify_profile(profile, cfg, target_type=ttype)
                if not ok and r["qualified"]:
                    new_disq_examples_all.append((r["username"], r["name"], ",".join(reasons[:2])))
                    if len(new_disq_examples) < 50:
                        new_disq_examples.append((r["username"], r["name"], ",".join(reasons[:2])))
                if not dry_run:
                    conn.execute(
                        "UPDATE leads SET qualified=?, qualified_reasons=?, target_type=? WHERE id=?",
                        (1 if ok else 0, json.dumps(reasons, ensure_ascii=False), ttype, r["id"]),
                    )
                if ok:
                    passed += 1
                else:
                    disqualified += 1
                continue

            ok, reasons = qualify_profile(profile, cfg, target_type=ttype)
            if not ok and r["qualified"]:
                new_disq_examples_all.append((r["username"], r["name"], ",".join(reasons[:2])))
                if len(new_disq_examples) < 50:
                    new_disq_examples.append((r["username"], r["name"], ",".join(reasons[:2])))
            if not dry_run:
                conn.execute(
                    "UPDATE leads SET qualified=?, qualified_reasons=?, target_type=? WHERE id=?",
                    (1 if ok else 0, json.dumps(reasons, ensure_ascii=False), ttype, r["id"]),
                )
            if ok:
                passed += 1
            else:
                disqualified += 1

        if not dry_run:
            conn.commit()

    print(f"=== requalify {'DRY-RUN' if dry_run else 'APPLIED'} ===")
    print(f"total 未接触: {total}")
    print(f"before qualified=1: {before_qualified}")
    print(f"after  qualified=1: {passed}")
    print(f"after  qualified=0: {disqualified}")
    print(f"※ before=1 → after=0 になった人数: {len(new_disq_examples_all)}")
    print()
    print("--- 新たに弾かれた候補（最大50件） ---")
    for u, n, why in new_disq_examples[:50]:
        print(f"  {u} | {(n or '')[:40]} | {why}")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    if "--revive-oshikatsu" in sys.argv:
        revive_oshikatsu(dry_run=dry)
    else:
        mode = "A" if "--mode-a" in sys.argv else "B"
        main(dry_run=dry, mode=mode)
