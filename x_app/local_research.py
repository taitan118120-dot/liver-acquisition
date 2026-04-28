"""ローカル(Mac)で X リサーチを実行し、本番Fly DBに ingest API 経由でpush。

X API Free 枠は月100reads と実用にならないため、Chrome の auth_token + ct0 Cookie を
使って x.com 内部 GraphQL を叩いてリサーチする (=「無料」運用)。

実行: cd x_app && python3 local_research.py
オプション:
  --target  beginner / existing_liver / agency  対象種別を限定
  --keyword "ライバー始めたい"                  単発キーワード
  --per-query 30                                 1クエリあたりの最大候補数
  --dry-run                                      ingest せず標準出力に出すだけ
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

DELAY_QUERY = 1.5  # クエリ間ディレイ
INGEST_BATCH = 30


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------- 本番 API ----------
def login() -> str:
    """APP_PASSWORD で /login → Set-Cookie: x_dm_auth=...; を抽出"""
    if not PASSWORD:
        raise RuntimeError("APP_PASSWORD 未設定。x_app/.app_password か環境変数で渡してください。")
    req = urllib.request.Request(
        f"{API_BASE}/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"password": PASSWORD}).encode(),
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        sc = r.headers.get("Set-Cookie", "")
    if f"{AUTH_COOKIE}=" not in sc:
        raise RuntimeError(f"auth cookie 取得失敗: {sc[:200]}")
    return sc.split(f"{AUTH_COOKIE}=")[1].split(";")[0]


def fetch_settings(auth: str) -> dict:
    req = urllib.request.Request(
        f"{API_BASE}/api/settings",
        headers={"Cookie": f"{AUTH_COOKIE}={auth}"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def fetch_existing_usernames(auth: str) -> set[str]:
    req = urllib.request.Request(
        f"{API_BASE}/api/queue",
        headers={"Cookie": f"{AUTH_COOKIE}={auth}"},
    )
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


# ---------- リサーチ本体 ----------
def build_query_specs(settings: dict, target_types: list[str], explicit_keywords: list[str]) -> list[dict]:
    if explicit_keywords:
        return [{"query": q, "target_type_hint": "beginner"} for q in explicit_keywords]
    kbt = settings.get("keywords_by_type") or {}
    specs = []
    for tt in target_types:
        for q in kbt.get(tt, []):
            specs.append({"query": q, "target_type_hint": tt})
    return specs


def run(target_types: list[str], explicit_keywords: list[str], per_query: int, dry_run: bool):
    log("Cookie 取得 (Chrome → x.com)")
    cookies = x_internal._load_cookies_from_chrome()
    if not cookies or "auth_token" not in cookies or "ct0" not in cookies:
        log("ERROR: Chrome から x.com の Cookie 取得失敗。Chrome で x.com にログインしてください。")
        return 1
    log(f"Cookie OK (auth_token={cookies['auth_token'][:8]}…, ct0={cookies['ct0'][:8]}…)")

    auth = ""
    settings: dict = {}
    existing: set[str] = set()
    if not dry_run:
        log("Fly ログイン")
        auth = login()
        log(f"auth 取得 ({len(auth)} chars)")
        settings = fetch_settings(auth)
        existing = fetch_existing_usernames(auth)
        log(f"既存リード {len(existing)}件 / settings keys={list(settings.keys())[:8]}…")
    else:
        # dry-run: ローカル DB から settings をそのまま読む
        try:
            import db as _db
            settings = _db.all_settings()
        except Exception:
            settings = {}

    query_ids = settings.get("x_graphql_query_ids") or None

    specs = build_query_specs(settings, target_types, explicit_keywords)
    if not specs:
        log("ERROR: 検索クエリが空。settings.keywords_by_type を確認")
        return 1
    log(f"=== {len(specs)} クエリで検索開始（per_query={per_query}）===")

    all_candidates: dict[str, dict] = {}
    for i, spec in enumerate(specs, 1):
        q = spec["query"]
        tt = spec["target_type_hint"]
        try:
            users = x_internal.fetch_search_users(
                q, max_users=per_query, manual_cookies=cookies, query_ids=query_ids
            )
        except x_internal.XAuthError as e:
            log(f"  [{i}/{len(specs)}] '{q}' AUTH ERROR: {e}")
            return 2
        except Exception as e:
            log(f"  [{i}/{len(specs)}] '{q}' ERROR: {e}")
            time.sleep(DELAY_QUERY * 2)
            continue
        new = 0
        for u in users:
            uname = u["username"]
            if uname in existing or uname in all_candidates:
                continue
            if u.get("is_private"):
                continue
            u["target_type_hint"] = tt
            u["source_tag"] = q
            all_candidates[uname] = u
            new += 1
        log(f"  [{i}/{len(specs)}] '{q}' ({tt}): +{new} (取得{len(users)}, total候補={len(all_candidates)})")
        time.sleep(DELAY_QUERY)

    log(f"=== 全クエリ完了: {len(all_candidates)} 件の新候補 ===")
    if not all_candidates:
        return 0

    # SearchTimeline には bio/followers が含まれるので追加 fetch_profile は不要
    profiles = []
    for u in all_candidates.values():
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
    ap = argparse.ArgumentParser(description="X リサーチ（Cookie 経由・無料）→ /api/ingest")
    ap.add_argument("--target", action="append", choices=["beginner", "existing_liver", "agency"],
                    help="対象種別。複数指定可（省略時=全種別）")
    ap.add_argument("--keyword", action="append", help="単発キーワード（settings 無視）")
    ap.add_argument("--per-query", type=int, default=30, help="1クエリあたりの最大候補数 (default 30)")
    ap.add_argument("--dry-run", action="store_true", help="ingest せず標準出力のみ")
    args = ap.parse_args()

    target_types = args.target or ["beginner", "existing_liver", "agency"]
    explicit = args.keyword or []
    rc = run(target_types, explicit, args.per_query, args.dry_run)
    sys.exit(rc)


if __name__ == "__main__":
    main()
