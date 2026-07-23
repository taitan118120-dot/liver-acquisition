"""寝てる間に raw_candidates_2026-04-25.json を slow-rate で enrich → 数値フィルタ → ingest。
   429 レートリミット中は5分間隔でリトライ。"""
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import ig_api
from qualify import qualify_profile, detect_target_type

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw_candidates_2026-04-25.json")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auto_enrich_log.txt")
DELAY = 2.0  # 安全マージン
RETRY_WAIT = 300  # 5分


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def wait_for_rate_limit_clear():
    """instagramユーザのプロフを叩いて200が返るまで待つ"""
    while True:
        try:
            p = ig_api.fetch_profile("instagram")
            if p and p.get("followers"):
                log("rate limit clear")
                return
        except ig_api.IGAuthError as e:
            log(f"認証エラー: {e}")
            sys.exit(1)
        except Exception as e:
            pass
        log(f"still 429, sleep {RETRY_WAIT}s")
        time.sleep(RETRY_WAIT)


def main():
    if not os.path.exists(RAW):
        log(f"no raw: {RAW}")
        return
    with open(RAW, "r", encoding="utf-8") as f:
        cands = json.load(f)
    log(f"start: {len(cands)} candidates, delay={DELAY}s")

    cfg = db.all_settings()
    fetched = 0
    qualified = 0
    skipped_existing = 0
    errors = 0
    rate_hits = 0

    for i, c in enumerate(cands, 1):
        username = c["username"]
        # skip if already in dashboard
        if db.get_lead(f"ig_{__slug(username)}"):
            skipped_existing += 1
            continue
        try:
            profile = ig_api.fetch_profile(username)
        except Exception as e:
            log(f"[{i}] @{username} err: {e}")
            errors += 1
            time.sleep(DELAY)
            continue
        if profile is None:
            # could be 429 or not_found
            rate_hits += 1
            if rate_hits >= 5:
                log(f"連続5回 None → rate limit疑い、5分待機 (i={i})")
                wait_for_rate_limit_clear()
                rate_hits = 0
            time.sleep(DELAY)
            continue
        rate_hits = 0
        fetched += 1

        followers = profile.get("followers") or 0
        following = profile.get("following") or 0
        if not followers or not following:
            time.sleep(DELAY)
            continue
        if followers < 1 or following < 1:
            time.sleep(DELAY)
            continue

        # target_type をbioから推定（agency/existing_liver/beginner）
        ttype = detect_target_type(profile)
        # tag-hint: existing_liver は信頼。agency は誤検知が多いのでbio優先
        tag_hint = c.get("target_type_hint")
        if ttype == "beginner" and tag_hint == "existing_liver":
            ttype = "existing_liver"

        # numeric filter (target_type別)
        if ttype == "agency":
            max_fl = cfg.get("max_followers_agency", 30000)
            if followers >= max_fl:
                time.sleep(DELAY)
                continue
            # agencyはratio制限なし（経営者は数千フォロー数千フォロワーが普通）
        elif ttype == "existing_liver":
            max_fl = cfg.get("max_followers_existing", 1000)
            if followers >= max_fl:
                time.sleep(DELAY)
                continue
        else:  # beginner
            if followers >= cfg.get("max_followers", 10000):
                time.sleep(DELAY)
                continue
            ratio = max(followers, following) / min(followers, following)
            if ratio > cfg.get("max_ratio", 5.0):
                time.sleep(DELAY)
                continue

        # qualify_profile (target_type別ルール)
        passed, reasons = qualify_profile(profile, cfg, target_type=ttype)

        # ingest to dashboard SQLite
        lead_id = f"ig_{__slug(username)}"
        with db.get_conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO leads (id, username, name, bio, followers, following,
                                                 source_tag, target_type, status, qualified,
                                                 qualified_reasons, auto_qualified, found_date, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, '未接触', ?, ?, 1, ?, ?)""",
                (lead_id, username, profile.get("full_name") or "", (profile.get("biography") or "")[:500],
                 followers, following, c.get("from_tag", ""), ttype, 1 if passed else 0,
                 json.dumps(reasons, ensure_ascii=False), datetime.now().strftime("%Y-%m-%d"),
                 f"ハッシュタグ: #{c.get('from_tag','')} (slow auto-enrich 2026-04-25)"),
            )
            conn.commit()
        if passed:
            qualified += 1

        if i % 20 == 0:
            log(f"進捗 {i}/{len(cands)} fetched={fetched} qualified={qualified} errors={errors}")
        time.sleep(DELAY)

    log(f"完了: fetched={fetched} qualified={qualified} skipped_existing={skipped_existing} errors={errors}")


import re
def __slug(u):
    s = re.sub(r"[^A-Za-z0-9_]", "_", u).strip("_")[:40]
    return s


if __name__ == "__main__":
    # 起動時にまずrate limit確認
    log("=== auto_enrich_ingest start ===")
    wait_for_rate_limit_clear()
    main()
