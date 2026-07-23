"""ライバー事務所アカウントがフォローしている先から代理店候補をリサーチ。

戦略:
  事務所はスカウト対象をフォローする習性がある。
  DB内の「ライバー/配信事務所（競合）」「既存代理店/同業者」タグ付きアカウントをシードとし、
  それらの following リストを取得 → agency qualify → DB ingest。

実行: cd liver_app && python3 agency_following_research.py
オプション:
  SEEDS=10        シード事務所の最大数 (default 15)
  MAX_FW=150      1事務所あたり取得するフォロー先の上限 (default 150)
  DRY_RUN=1       ingest せずログのみ
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import ig_api
from qualify import detect_target_type, qualify_profile

# ── 設定 ──────────────────────────────────────────────
API_BASE  = os.environ.get("LIVER_API", "https://taitan-pro-dm.fly.dev")
PASSWORD  = os.environ.get("APP_PASSWORD") or open(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".app_password")
).read().strip()

MAX_SEEDS      = int(os.environ.get("SEEDS", "15"))
MAX_FOLLOWING  = int(os.environ.get("MAX_FW", "150"))
DRY_RUN        = os.environ.get("DRY_RUN", "0") == "1"

# rate limit 対策。一人のフォロー先リスト取得後に休む
DELAY_FOLLOWING = 5.0   # 事務所1件ごとのインターバル
DELAY_PROFILE   = 2.5   # プロフィール取得ごとのインターバル
# プロフィール取得サブチャンク（40件→60秒休憩）
PROFILE_SUB     = int(os.environ.get("PROFILE_SUB", "40"))
PROFILE_SUB_SLEEP = int(os.environ.get("PROFILE_SUB_SLEEP", "60"))

INGEST_BATCH = 30
SOURCE_TAG   = "agency_following"


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ── Fly API ヘルパー ───────────────────────────────────
def fly_login() -> str:
    req = urllib.request.Request(
        f"{API_BASE}/login", method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"password": PASSWORD}).encode(),
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        sc = r.headers.get("Set-Cookie", "")
    return sc.split("liver_auth=")[1].split(";")[0]


def fetch_existing_usernames(auth: str) -> set[str]:
    req = urllib.request.Request(
        f"{API_BASE}/api/queue",
        headers={"Cookie": f"liver_auth={auth}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        return {l["username"] for l in data.get("leads", [])}
    except Exception:
        return set()


def ingest(auth: str, profiles: list[dict]) -> tuple[int, int]:
    if not profiles:
        return 0, 0
    req = urllib.request.Request(
        f"{API_BASE}/api/ingest", method="POST",
        headers={"Content-Type": "application/json", "Cookie": f"liver_auth={auth}"},
        data=json.dumps({"profiles": profiles}).encode(),
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
    return d.get("added", 0), d.get("updated", 0)


# ── シード取得（DB から事務所アカウントを抽出） ──────────
def load_seed_agencies() -> list[str]:
    """DB 内の事務所タグ付きアカウントを followers 降順で返す"""
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT username, followers FROM leads
               WHERE qualified_reasons LIKE '%ライバー/配信事務所%'
                  OR qualified_reasons LIKE '%既存代理店/同業者%'
                  OR qualified_reasons LIKE '%ライバースカウト%'
               ORDER BY COALESCE(followers, 0) DESC
            """
        ).fetchall()
    # 同一法人の別アカウント（アルファ/清水など）は重複が多いので先頭だけ使う
    seen_bases: set[str] = set()
    seeds: list[str] = []
    for username, _ in rows:
        base = username.split(".")[0].split("_")[0][:8]
        if base not in seen_bases:
            seen_bases.add(base)
            seeds.append(username)
        if len(seeds) >= MAX_SEEDS:
            break
    return seeds


# ── メイン ───────────────────────────────────────────
def main():
    log("=== agency_following_research 開始 ===")
    if DRY_RUN:
        log("DRY_RUN モード: ingest をスキップ")

    log("Fly login")
    auth = fly_login()

    log("既存リード取得（重複スキップ用）")
    existing = fetch_existing_usernames(auth)
    log(f"既存 {len(existing)}件")

    log("Chrome Cookie 取得")
    cookie = ig_api._load_cookies_from_chrome()
    if not cookie:
        log("ERROR: Chrome から IG Cookie 取得失敗")
        return
    log(f"Cookie OK ({len(cookie)} chars)")

    cfg = db.all_settings()

    # シード事務所リスト
    seeds = load_seed_agencies()
    log(f"シード事務所: {len(seeds)}件")
    for s in seeds:
        log(f"  @{s}")

    # ── フェーズ1: following リスト収集 ──
    candidates: dict[str, dict] = {}  # username -> {username, full_name, from_seed}

    for i, seed in enumerate(seeds, 1):
        log(f"\n[{i}/{len(seeds)}] @{seed} のフォロー先取得 (max {MAX_FOLLOWING}件)")
        try:
            users = ig_api.fetch_following(seed, max_count=MAX_FOLLOWING, manual_cookie=cookie)
            added = 0
            for u in users:
                uname = u["username"]
                if uname in existing or uname in candidates:
                    continue
                if u.get("is_private"):
                    continue
                candidates[uname] = {
                    "username": uname,
                    "full_name": u.get("full_name", ""),
                    "from_seed": seed,
                }
                added += 1
            log(f"  取得 {len(users)}件 → 新規候補 +{added}件 (合計 {len(candidates)}件)")
        except Exception as e:
            log(f"  ERROR: {e}")
        time.sleep(DELAY_FOLLOWING)

    log(f"\n=== フォロー先収集完了: 候補 {len(candidates)}件 ===")

    # ── フェーズ2: 名前フィルタ → プロフィール取得 → qualify → ingest ──
    from qualify import _guess_foreign, NAIL_SALON_RE, LIVER_AGENCY_RE, ESTABLISHED_AGENCY_RE, detect_target_type as _detect
    import json as _json

    batch_full: list[dict] = []   # プロフィール取得成功 → qualify 通過
    batch_pending: list[dict] = []  # プロフィール取得失敗 → 保留登録
    total_sent = qualified_count = skipped = name_ng = pending_reg = profile_sub_count = 0
    ng_reasons: dict[str, int] = {}

    items = list(candidates.items())
    for i, (uname, c) in enumerate(items, 1):
        full_name = c.get("full_name", "")

        # ── 名前ベースの事前 NG フィルタ（API 不要）──
        name_text = full_name + " " + uname
        if (_guess_foreign("", full_name) or
                NAIL_SALON_RE.search(name_text) or
                LIVER_AGENCY_RE.search(name_text) or
                ESTABLISHED_AGENCY_RE.search(name_text)):
            name_ng += 1
            continue

        # ── サブチャンク sleep（バースト防止）──
        if profile_sub_count >= PROFILE_SUB:
            log(f"  サブチャンク {PROFILE_SUB}件完了 → {PROFILE_SUB_SLEEP}s sleep")
            time.sleep(PROFILE_SUB_SLEEP)
            profile_sub_count = 0
        profile_sub_count += 1

        # ── プロフィール取得 ──
        profile = None
        try:
            profile = ig_api.fetch_profile(uname, manual_cookie=cookie)
        except Exception as e:
            ng_reasons[f"exc:{type(e).__name__}"] = ng_reasons.get(f"exc:{type(e).__name__}", 0) + 1

        if not profile:
            # API 失敗 → 保留登録（overnight_enrich が後で bio 取得）
            ng_reasons["profile_none"] = ng_reasons.get("profile_none", 0) + 1
            batch_pending.append({
                "u": uname,
                "n": full_name,
                "b": "",
                "fl": None,
                "fw": None,
                "pv": False,
                "vf": False,
                "bz": False,
                "c": None,
                "tag": SOURCE_TAG,
                "target_type_hint": "agency",
            })
            if len(batch_pending) >= INGEST_BATCH:
                if not DRY_RUN:
                    try:
                        a, u2 = ingest(auth, batch_pending)
                        pending_reg += a
                        log(f"  [{i}/{len(items)}] 保留 ingest +{a}, 累計保留 {pending_reg}")
                    except Exception as e:
                        log(f"  保留 ingest ERROR: {e}")
                batch_pending = []
            time.sleep(DELAY_PROFILE)
            continue

        # ── qualify（プロフィール取得成功） ──
        ttype = detect_target_type(profile)
        if ttype == "beginner":
            ttype = "agency"

        passed, reasons = qualify_profile(profile, cfg, target_type=ttype)

        if not passed:
            skipped += 1
            if i % 100 == 0:
                log(f"  {i}/{len(items)} passed={qualified_count} pending={pending_reg} skipped={skipped} ng_name={name_ng} api_ng={dict(list(ng_reasons.items())[:3])}")
            time.sleep(DELAY_PROFILE)
            continue

        qualified_count += 1
        batch_full.append({
            "u": uname,
            "n": profile.get("full_name") or full_name,
            "b": profile.get("biography", ""),
            "fl": profile.get("followers"),
            "fw": profile.get("following"),
            "pc": profile.get("post_count"),
            "pv": profile.get("is_private", False),
            "vf": profile.get("is_verified", False),
            "bz": profile.get("is_business", False),
            "c": profile.get("category"),
            "tag": SOURCE_TAG,
            "target_type_hint": ttype,
        })

        if len(batch_full) >= INGEST_BATCH:
            if not DRY_RUN:
                try:
                    a, u2 = ingest(auth, batch_full)
                    total_sent += a
                    log(f"  [{i}/{len(items)}] qualify済 ingest +{a}, 累計 {total_sent}")
                except Exception as e:
                    log(f"  ingest ERROR: {e}")
            batch_full = []

        time.sleep(DELAY_PROFILE)

    # 残り flush
    if not DRY_RUN:
        for batch_name, batch_data, counter_name in [
            ("qualify済", batch_full, "total_sent"),
            ("保留", batch_pending, "pending_reg"),
        ]:
            if batch_data:
                try:
                    a, u2 = ingest(auth, batch_data)
                    if counter_name == "total_sent":
                        total_sent += a
                    else:
                        pending_reg += a
                    log(f"  final {batch_name} ingest +{a}")
                except Exception as e:
                    log(f"  final {batch_name} ingest ERROR: {e}")

    log(
        f"\n=== 完了 ==="
        f"\n  フォロー先候補: {len(candidates)}件"
        f"\n  名前NG除外: {name_ng}件"
        f"\n  qualify通過（即時登録）: {qualified_count}件 → Fly送信 {total_sent}件"
        f"\n  プロフィール未取得（保留登録）: {pending_reg}件"
        f"\n  qualify失敗スキップ: {skipped}件"
        f"\n  API NG内訳: {ng_reasons}"
    )


if __name__ == "__main__":
    main()
