"""ローカル(Mac)でリサーチを実行し、本番Fly DBに ingest API 経由でpush。
Fly側はIG rate limit (429) で詰まるので、家庭IPで実行する用途。

実行: cd liver_app && python3 local_research.py
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ig_api

API_BASE = os.environ.get("LIVER_API", "https://taitan-pro-dm.fly.dev")
PASSWORD = os.environ.get("APP_PASSWORD") or open(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".app_password")).read().strip()

# フォールバック用ハードコードタグ（API 失敗時のみ使用）。
# 通常は Fly /api/settings から動的取得（dashboard UI でカスタマイズ済の値が反映される）。
HASHTAGS_FALLBACK = {
    "beginner": [
        "UNIQLOコーデ", "プチプラコーデ", "ママコーデ",
        "お洒落さんと繋がりたい", "カフェ好きさんと繋がりたい",
        "カフェ巡り", "カフェ活", "映えスイーツ",
        "渋谷カフェ", "新宿カフェ", "原宿カフェ", "表参道カフェ",
        "下北沢カフェ", "横浜カフェ", "みなとみらいカフェ",
        "福岡カフェ", "大阪カフェ", "京都カフェ", "名古屋カフェ",
        "低身長コーデ", "古着女子", "古着男子", "淡色女子",
        "nikoand", "LOWRYSFARM", "GLOBALWORK", "ROPEPICNIC", "LEPSIM",
        "earthmusicandecology", "INGNI", "WEGO", "Lilybrown", "dazzlin",
        "渋谷スカイ", "赤レンガ倉庫",
    ],
    "existing_liver": [
        "17LIVE", "イチナナライブ", "IRIAM", "イリアム",
        "ふわっち", "BIGOLIVE", "ミクチャ", "ツイキャス",
        "SHOWROOM", "ライブ配信", "配信者", "ライバーさんと繋がりたい",
    ],
    "agency": [
        "ネイルサロン経営", "美容室経営", "コンカフェオーナー",
        "エステサロン経営", "カフェ経営", "治療院経営",
        "SNS運用代行", "コンテンツ販売初心者", "無在庫転売",
        "物販", "ネット副業", "インスタ運用代行",
        "ラウンジ嬢", "キャバクラ嬢", "銀座ホステス", "六本木ラウンジ",
        "ライバーになりたい", "配信者好きと繋がりたい", "推し活",
        # 🆕 代理店希望/副業希望（直接シグナル 2026-04-30）
        "代理店希望", "代理店募集", "スカウト副業",
        "ライバースカウト", "業務委託募集", "業務委託希望",
        "副業希望", "副業始めたい", "副業探してます",
        "在宅副業", "週末副業", "ママ副業",
        "完全在宅ワーク", "業務委託ママ", "スマホ副業",
    ],
}

# IG checkpoint回避のため delay は十分大きく (2026-04-30 ユーザ指摘で増)
DELAY_TAG = 4.0
DELAY_PROFILE = 2.5
INGEST_BATCH = 30
# チャンク分割: N タグ取得→5分待機 を繰り返す
CHUNK_TAGS = int(os.environ.get("CHUNK_TAGS", "15"))
CHUNK_SLEEP = int(os.environ.get("CHUNK_SLEEP", "300"))  # 5分
# プロフィール取得側もサブチャンク化: M件→1分待機
PROFILE_SUB_CHUNK = int(os.environ.get("PROFILE_SUB_CHUNK", "40"))
PROFILE_SUB_SLEEP = int(os.environ.get("PROFILE_SUB_SLEEP", "60"))


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def login():
    req = urllib.request.Request(
        f"{API_BASE}/login", method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"password": PASSWORD}).encode(),
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        sc = r.headers.get("Set-Cookie", "")
    return sc.split("liver_auth=")[1].split(";")[0]


def fetch_existing_usernames(auth):
    """本番のキューに既にあるusernameを取得（重複スキップ用）"""
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


def fetch_hashtags(auth):
    """Fly /api/settings から hashtags_by_type を取得。失敗時は None。"""
    req = urllib.request.Request(
        f"{API_BASE}/api/settings",
        headers={"Cookie": f"liver_auth={auth}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        hbt = data.get("hashtags_by_type")
        if isinstance(hbt, dict) and all(isinstance(v, list) for v in hbt.values()):
            return hbt
    except Exception as e:
        log(f"hashtags 取得失敗: {e} → fallback使用")
    return None


def ingest(auth, profiles):
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


def main():
    log("ログイン")
    auth = login()
    log(f"auth取得 ({len(auth)} chars)")

    log("既存リード取得（重複スキップ用）")
    existing = fetch_existing_usernames(auth)
    log(f"既存 {len(existing)}件")

    log("hashtags 取得（Fly /api/settings から動的取得）")
    HASHTAGS = fetch_hashtags(auth) or HASHTAGS_FALLBACK
    for ttype, tags in HASHTAGS.items():
        log(f"  {ttype}: {len(tags)}タグ")

    log("Cookie 取得")
    cookie = ig_api._load_cookies_from_chrome()
    if not cookie:
        log("ERROR: Chromeから IG Cookie 取得失敗")
        return
    log(f"Cookie OK ({len(cookie)} chars)")

    # 全タグをフラット化してチャンク分割
    all_tags = []
    for ttype, tags in HASHTAGS.items():
        for tag in tags:
            all_tags.append((ttype, tag))
    log(f"全{len(all_tags)}タグを {CHUNK_TAGS}件ずつ分割（間に{CHUNK_SLEEP}秒sleep）")

    candidates: dict[str, dict] = {}
    chunk_count = (len(all_tags) + CHUNK_TAGS - 1) // CHUNK_TAGS
    for chunk_idx in range(chunk_count):
        chunk = all_tags[chunk_idx*CHUNK_TAGS:(chunk_idx+1)*CHUNK_TAGS]
        log(f"--- チャンク {chunk_idx+1}/{chunk_count} ({len(chunk)}タグ) ---")
        for ttype, tag in chunk:
            try:
                users = ig_api.fetch_hashtag_users(tag, manual_cookie=cookie)
                for u in users:
                    uname = u["username"]
                    if uname in existing or uname in candidates:
                        continue
                    if u.get("is_private"):
                        continue
                    candidates[uname] = {
                        "username": uname,
                        "full_name": u.get("full_name", ""),
                        "tag": tag,
                        "target_type_hint": ttype,
                    }
                log(f"#{tag} ({ttype}): +{len(users)}, total candidates={len(candidates)}")
            except Exception as e:
                log(f"#{tag} ERROR: {e}")
            time.sleep(DELAY_TAG)
        if chunk_idx + 1 < chunk_count:
            log(f"=== チャンク終わり, {CHUNK_SLEEP}s sleep ===")
            time.sleep(CHUNK_SLEEP)

    log(f"=== 全タグ完了 候補 {len(candidates)}件 プロフィール取得開始 ===")

    batch = []
    total_sent = 0
    ng_reasons: dict[str, int] = {}
    profile_sub_count = 0
    for i, (uname, c) in enumerate(candidates.items(), 1):
        # サブチャンク sleep（バースト防止）
        if profile_sub_count >= PROFILE_SUB_CHUNK:
            log(f"  profile sub-chunk {PROFILE_SUB_CHUNK}件処理→{PROFILE_SUB_SLEEP}s sleep")
            time.sleep(PROFILE_SUB_SLEEP)
            profile_sub_count = 0
        profile_sub_count += 1
        # HTML mode (Googlebot UA, Cookie不要) を採用。
        # api mode は Cookieごとレート制限される (429) ため。
        try:
            profile = ig_api.fetch_profile_html(uname)
        except Exception as e:
            log(f"  {i}/{len(candidates)} {uname} ERROR: {e}")
            ng_reasons[f"exc:{type(e).__name__}"] = ng_reasons.get(f"exc:{type(e).__name__}", 0) + 1
            time.sleep(DELAY_PROFILE * 2)
            continue
        if not profile:
            reason = ig_api._html_last_error.get("reason") or "unknown"
            ng_reasons[reason] = ng_reasons.get(reason, 0) + 1
            if i % 50 == 0:
                log(f"  {i}/{len(candidates)} ng_reasons so far: {dict(list(ng_reasons.items())[:5])}")
            time.sleep(DELAY_PROFILE)
            continue
        batch.append({
            "u": uname,
            "n": profile.get("full_name") or c.get("full_name", ""),
            "b": profile.get("biography", ""),
            "fl": profile.get("followers"),
            "fw": profile.get("following"),
            "pc": profile.get("post_count"),
            "pv": profile.get("is_private", False),
            "vf": profile.get("is_verified", False),
            "bz": profile.get("is_business", False),
            "c": profile.get("category"),
            "tag": c["tag"],
            "target_type_hint": c["target_type_hint"],
        })
        if len(batch) >= INGEST_BATCH:
            try:
                a, u = ingest(auth, batch)
                total_sent += len(batch)
                log(f"  {i}/{len(candidates)} ingest +{a} (updated {u}), 累計送信 {total_sent}")
            except Exception as e:
                log(f"  ingest ERROR: {e}")
            batch = []
        time.sleep(DELAY_PROFILE)

    if batch:
        try:
            a, u = ingest(auth, batch)
            total_sent += len(batch)
            log(f"final ingest +{a} (updated {u}), 累計 {total_sent}")
        except Exception as e:
            log(f"final ingest ERROR: {e}")

    log(f"=== 完了: {total_sent}プロフィールをFlyに送信 ng_reasons={ng_reasons} ===")


if __name__ == "__main__":
    main()
