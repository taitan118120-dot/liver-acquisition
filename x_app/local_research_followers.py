"""ライブ配信プラットフォーム公式アカウント等のフォロワーを刈り取って /api/ingest にpush。

キーワード検索より精度が高い。例えば @17liveJP のフォロワーは
「17LIVE のリスナー or 配信者」が大半なので existing_liver/beginner として有望。

実行: cd x_app && python3 local_research_followers.py [--target @17liveJP] [--max 200]

target_accounts は引数 or settings.x_target_accounts から取得。
settings.x_target_accounts のフォーマット:
  {"@17liveJP": "existing_liver", "@iriam_official": "existing_liver", ...}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import x_internal

API_BASE = os.environ.get("X_API_BASE", "https://taitan-pro-x-dm.fly.dev")
PASSWORD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".app_password")
PASSWORD = os.environ.get("APP_PASSWORD") or (
    open(PASSWORD_FILE).read().strip() if os.path.exists(PASSWORD_FILE) else ""
)
AUTH_COOKIE = "x_dm_auth"

# デフォルト ターゲット（settings 未設定時のフォールバック）
DEFAULT_TARGETS = {
    # ライブ配信プラットフォーム公式
    "17liveJP":         "existing_liver",
    "iriam_official":   "existing_liver",
    "MIRRATIV_jp":      "existing_liver",
    "showroom_jp":      "existing_liver",
    "fuwacchi_jp":      "existing_liver",
    "BIGOLIVEofficial": "existing_liver",
    "TwitCasting_jp":   "existing_liver",
    "PocochaJapan":     "existing_liver",
    # ライバー事務所
    "live_pro_taitan":  "agency",
}

INGEST_BATCH = 30
DELAY_BETWEEN_TARGETS = 3.0


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def login() -> str:
    if not PASSWORD:
        raise RuntimeError("APP_PASSWORD 未設定")
    req = urllib.request.Request(
        f"{API_BASE}/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"password": PASSWORD}).encode(),
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        sc = r.headers.get("Set-Cookie", "")
    return sc.split(f"{AUTH_COOKIE}=")[1].split(";")[0]


def fetch_settings(auth: str) -> dict:
    req = urllib.request.Request(f"{API_BASE}/api/settings", headers={"Cookie": f"{AUTH_COOKIE}={auth}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def fetch_existing_usernames(auth: str) -> set[str]:
    req = urllib.request.Request(f"{API_BASE}/api/queue", headers={"Cookie": f"{AUTH_COOKIE}={auth}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        return {l["username"] for l in data.get("leads", [])}
    except Exception as e:
        log(f"既存リード取得失敗（続行）: {e}")
        return set()


def ingest(auth: str, profiles: list[dict]) -> tuple[int, int]:
    if not profiles:
        return 0, 0
    req = urllib.request.Request(
        f"{API_BASE}/api/ingest",
        method="POST",
        headers={"Content-Type": "application/json", "Cookie": f"{AUTH_COOKIE}={auth}"},
        data=json.dumps({"profiles": profiles}).encode(),
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
    return d.get("added", 0), d.get("updated", 0)


def normalize_target(s: str) -> str:
    return s.lstrip("@").strip()


def run(targets: dict[str, str], max_per_target: int, dry_run: bool) -> int:
    log("Cookie 取得 (Chrome → x.com)")
    cookies = x_internal._load_cookies_from_chrome()
    if not cookies or "auth_token" not in cookies or "ct0" not in cookies:
        log("ERROR: Chrome から x.com Cookie 取得失敗")
        return 1
    log(f"Cookie OK")

    auth = ""
    existing: set[str] = set()
    if not dry_run:
        log("Fly ログイン")
        auth = login()
        existing = fetch_existing_usernames(auth)
        log(f"既存リード {len(existing)}件")

    log(f"=== {len(targets)} ターゲットからフォロワー刈り取り（最大{max_per_target}/target）===")

    all_collected: dict[str, dict] = {}
    for target, ttype_hint in targets.items():
        target = normalize_target(target)
        try:
            users = x_internal.fetch_followers(
                target, max_count=max_per_target, manual_cookies=cookies
            )
        except x_internal.XAuthError as e:
            log(f"  @{target} AUTH ERROR: {e}")
            return 2
        except Exception as e:
            log(f"  @{target} ERROR: {e}")
            time.sleep(DELAY_BETWEEN_TARGETS)
            continue
        new = 0
        for u in users:
            uname = u["username"]
            if uname in existing or uname in all_collected:
                continue
            if u.get("is_private"):
                continue
            u["target_type_hint"] = ttype_hint
            u["source_tag"] = f"followers:@{target}"
            all_collected[uname] = u
            new += 1
        log(f"  @{target} ({ttype_hint}): +{new} (取得{len(users)}, total={len(all_collected)})")
        time.sleep(DELAY_BETWEEN_TARGETS)

    if not all_collected:
        log("候補ゼロ。終了")
        return 0

    profiles = []
    for u in all_collected.values():
        profiles.append({
            "u": u["username"],
            "n": u.get("full_name", ""),
            "b": u.get("biography", ""),
            "fl": u.get("followers"),
            "fw": u.get("following"),
            "pv": u.get("is_private", False),
            "vf": u.get("is_verified", False),
            "bz": u.get("is_business", False),
            "c": u.get("category"),
            "tag": u.get("source_tag", ""),
            "target_type_hint": u.get("target_type_hint", "beginner"),
        })

    if dry_run:
        log(f"[dry-run] {len(profiles)}件 のサンプル先頭5件:")
        for p in profiles[:5]:
            print(json.dumps(p, ensure_ascii=False))
        return 0

    log(f"=== ingest 開始 ({len(profiles)}件) ===")
    total_added, total_updated = 0, 0
    for s in range(0, len(profiles), INGEST_BATCH):
        batch = profiles[s:s + INGEST_BATCH]
        try:
            a, u = ingest(auth, batch)
            total_added += a
            total_updated += u
            log(f"  ingest {s + len(batch)}/{len(profiles)}: +{a} updated={u}")
        except Exception as e:
            log(f"  ingest ERROR (batch {s}): {e}")
        time.sleep(0.3)

    log(f"=== 完了: 新規 {total_added} / 更新 {total_updated} / 候補 {len(profiles)} ===")
    return 0


def main():
    ap = argparse.ArgumentParser(description="X 公式アカウント等のフォロワー刈り取り → /api/ingest")
    ap.add_argument("--target", action="append",
                    help="ターゲット username（@省略可）。複数指定可。settings.x_target_accounts を上書き")
    ap.add_argument("--type", default="beginner",
                    choices=["beginner", "existing_liver", "agency"],
                    help="--target 指定時の target_type_hint (default beginner)")
    ap.add_argument("--max", type=int, default=200, help="1ターゲットあたりの最大取得数")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.target:
        targets = {normalize_target(t): args.type for t in args.target}
    else:
        # settings から取得 (login が必要)
        try:
            auth = login()
            cfg = fetch_settings(auth)
            t_cfg = cfg.get("x_target_accounts") or {}
            targets = {normalize_target(k): v for k, v in t_cfg.items()} if t_cfg else dict(DEFAULT_TARGETS)
            if not t_cfg:
                log("settings.x_target_accounts 未設定 → DEFAULT_TARGETS 使用")
        except Exception as e:
            log(f"settings 取得失敗 → DEFAULT_TARGETS 使用: {e}")
            targets = dict(DEFAULT_TARGETS)

    rc = run(targets, args.max, args.dry_run)
    sys.exit(rc)


if __name__ == "__main__":
    main()
