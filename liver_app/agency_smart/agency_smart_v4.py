"""v4: 効率化版
   1. 既存934候補を名前(full_name)でpre-filter → 高品質な~150件
   2. DM送信済agencyシード13人のfollowers/followingからagencyっぽい人抽出 → ~300件
   3. 重複除外して全プロフ取得→Fly push

   IG rate limit対策で起動時にprofile API動作確認、毎50件毎に5分休憩。
"""
import sys, os, time, json, re
sys.path.insert(0, '/Users/mitataisei/ライバー獲得/liver_app')
import ig_api
import httpx

PW = open('/Users/mitataisei/ライバー獲得/liver_app/.app_password').read().strip()
BASE = "https://taitan-pro-dm.fly.dev"
PROF_DELAY = 3.0
TIMEOUT = 25.0
HEAVY_REST_EVERY = 50  # この件数ごとに5分休憩
HEAVY_REST_SECS = 300

# ===== 名前フィルタ =====
AGENCY_NAME_RE = re.compile(
    r"(経営|オーナー|owner|代表|社長|店長|founder|ceo|"
    r"サロン|エステ|ネイル|美容師|美容室|カフェ|コンカフェ|治療院|"
    r"運用代行|代行|集客|コンサル|販売|転売|"
    r"嬢|キャバ|ホステス|ラウンジ|歌舞伎|ナイトワーク|夜職|"
    r"配信者|ライバー|インフルエンサー|"
    r"副業|起業|フリーランス|個人事業|在宅|ママ社長)",
    re.IGNORECASE,
)

def name_passes(full_name, username):
    text = (full_name or "") + " " + (username or "")
    return bool(AGENCY_NAME_RE.search(text))

# ===== Fly login =====
client = httpx.Client(timeout=60.0, follow_redirects=True)
client.post(f"{BASE}/login", data={"password": PW})
print("✓ Fly login", flush=True)

# ===== 1. profile API動作確認 =====
def check_rate_limit():
    """profile APIが200返せるか確認"""
    try:
        r = httpx.get("https://www.instagram.com/api/v1/users/web_profile_info/?username=instagram",
                      headers=ig_api._headers(), timeout=TIMEOUT, follow_redirects=False)
        return r.status_code == 200
    except: return False

print("\n=== rate limit check ===", flush=True)
if not check_rate_limit():
    print("⚠️ profile API still 429. waiting 10min...", flush=True)
    time.sleep(600)
    if not check_rate_limit():
        print("❌ still blocked. stop. retry tomorrow.", flush=True)
        sys.exit(0)
print("✓ rate limit clear", flush=True)

# ===== 2. シード13人を取得 =====
SEED_USERNAMES = [
    "__mayuko1001__nail", "amuse.toshi", "ayaka.happy_cat", "fp_shin.n",
    "ishikawa_ryo_", "japppn_love", "maeshima_businessperson",
    "maguchika.nailsalon.sales", "nakase.design.laboratory", "neo.ryusan",
    "reeei.34", "rhino.9079154", "tomoe_meili",
]

# ===== 3. 既存934候補をload + name filter =====
print("\n=== name filter on 934候補 ===", flush=True)
all934 = json.load(open("/Users/mitataisei/ライバー獲得/liver_app/agency_smart/agency_users.json", encoding="utf-8"))
print(f"raw: {len(all934)}", flush=True)
name_passed = {}
for uname, info in all934.items():
    if name_passes(info.get("full_name", ""), uname):
        name_passed[uname] = info
print(f"after name filter: {len(name_passed)}", flush=True)

# ===== 4. シードのfollowers/followingを取得して拡散 =====
print("\n=== seed expansion (13人 × followers+following) ===", flush=True)
seed_pool = {}  # username → info

def fetch_user_id(username):
    try:
        r = httpx.get(f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}",
                      headers=ig_api._headers(), timeout=TIMEOUT, follow_redirects=False)
        if r.status_code != 200: return None
        return ((r.json().get("data") or {}).get("user") or {}).get("id")
    except: return None

def fetch_friendship_list(user_id, kind, max_count=100):
    """kind = 'followers' or 'following'. 最大100件取得"""
    url = f"https://www.instagram.com/api/v1/friendships/{user_id}/{kind}/?count={max_count}"
    try:
        r = httpx.get(url, headers=ig_api._headers(), timeout=TIMEOUT, follow_redirects=False)
        if r.status_code != 200:
            print(f"    {kind} HTTP {r.status_code}", flush=True)
            return []
        users = r.json().get("users") or []
        return users
    except Exception as e:
        print(f"    {kind} err: {e}", flush=True)
        return []

for i, seed_un in enumerate(SEED_USERNAMES, 1):
    print(f"  [{i}/13] @{seed_un}", flush=True)
    uid = fetch_user_id(seed_un)
    if not uid:
        print(f"    user_id取得失敗", flush=True)
        time.sleep(PROF_DELAY)
        continue
    time.sleep(PROF_DELAY)

    # followers
    flw = fetch_friendship_list(uid, "followers", 100)
    for u in flw:
        un = u.get("username")
        if un and un not in seed_pool and un not in SEED_USERNAMES:
            if name_passes(u.get("full_name",""), un):
                seed_pool[un] = {"username": un, "full_name": u.get("full_name",""), "from_tag": f"seed_followers_{seed_un}"}
    time.sleep(PROF_DELAY)

    # following
    fwg = fetch_friendship_list(uid, "following", 100)
    for u in fwg:
        un = u.get("username")
        if un and un not in seed_pool and un not in SEED_USERNAMES:
            if name_passes(u.get("full_name",""), un):
                seed_pool[un] = {"username": un, "full_name": u.get("full_name",""), "from_tag": f"seed_following_{seed_un}"}
    time.sleep(PROF_DELAY)
    print(f"    +{len(flw)+len(fwg)} raw → seed_pool total: {len(seed_pool)}", flush=True)

print(f"\nseed expansion total: {len(seed_pool)}", flush=True)

# ===== 5. 統合: name_passed + seed_pool, 既存重複除外 =====
print("\n=== merge & dedupe ===", flush=True)
combined = {}
combined.update(name_passed)
for un, info in seed_pool.items():
    if un not in combined:
        combined[un] = info
print(f"combined: {len(combined)}", flush=True)

# Fly側既存 ingest済を除外（重複push避ける）
sett_resp = client.get(f"{BASE}/api/queue")
existing_in_fly = {l.get("username") for l in sett_resp.json().get("leads", [])}
# 全リード取得API無いので queue だけで OK（未送信のみ）
to_fetch = [info for un, info in combined.items() if un not in existing_in_fly]
print(f"to fetch (Fly未登録): {len(to_fetch)}", flush=True)

# ===== 6. 各プロフィール取得 =====
print(f"\n=== profile fetch ({len(to_fetch)}件, delay={PROF_DELAY}s) ===", flush=True)
profiles = []
errors = 0
rate_429 = 0

for j, info in enumerate(to_fetch, 1):
    uname = info["username"]
    try:
        r = httpx.get(f"https://www.instagram.com/api/v1/users/web_profile_info/?username={uname}",
                      headers=ig_api._headers(), timeout=TIMEOUT, follow_redirects=False)
        if r.status_code == 429:
            rate_429 += 1
            print(f"  [{j}] @{uname} 429 → wait 5min", flush=True)
            time.sleep(300)
            if rate_429 >= 3:
                print("  ❌ 429連発、中断", flush=True)
                break
            continue
        rate_429 = 0
        if r.status_code != 200:
            errors += 1; time.sleep(PROF_DELAY); continue
        u = ((r.json().get("data") or {}).get("user")) or {}
        if not u: time.sleep(PROF_DELAY); continue
        profiles.append({
            "u": uname, "n": u.get("full_name") or "",
            "b": (u.get("biography") or "")[:500],
            "fl": (u.get("edge_followed_by") or {}).get("count"),
            "fw": (u.get("edge_follow") or {}).get("count"),
            "pv": u.get("is_private"), "vf": u.get("is_verified"),
            "bz": u.get("is_business_account"), "c": u.get("category_name"),
            "tag": info["from_tag"], "target_type_hint": "agency",
        })
    except Exception as e:
        errors += 1
        print(f"  err @{uname} {type(e).__name__}", flush=True)

    # 50件毎に5分休憩
    if j > 0 and j % HEAVY_REST_EVERY == 0:
        print(f"  進捗 {j}/{len(to_fetch)} fetched={len(profiles)} → 5min休憩", flush=True)
        # checkpoint
        json.dump(profiles, open("/Users/mitataisei/ライバー獲得/liver_app/agency_smart/agency_smart_profs.json", "w", encoding="utf-8"), ensure_ascii=False)
        time.sleep(HEAVY_REST_SECS)
    else:
        time.sleep(PROF_DELAY)

# 最終checkpoint
json.dump(profiles, open("/Users/mitataisei/ライバー獲得/liver_app/agency_smart/agency_smart_profs.json", "w", encoding="utf-8"), ensure_ascii=False)
print(f"\n=== {len(profiles)} profiles fetched ===\n", flush=True)

# ===== 7. push to Fly =====
BATCH = 50
total_added = total_updated = 0
for k in range(0, len(profiles), BATCH):
    batch = profiles[k:k+BATCH]
    try:
        r = client.post(f"{BASE}/api/ingest", json={"profiles": batch})
        if r.status_code == 200:
            d = r.json()
            total_added += d.get("added", 0)
            total_updated += d.get("updated", 0)
            print(f"  batch {k//BATCH+1}: +added={d.get('added')} updated={d.get('updated')}", flush=True)
    except Exception as e:
        print(f"  batch err: {e}", flush=True)

# ===== 8. queue確認 =====
r = client.get(f"{BASE}/api/queue")
agency = [l for l in r.json().get("leads",[]) if l.get("target_type")=="agency"]
print(f"\n✅ DONE: ingested={total_added} updated={total_updated}", flush=True)
print(f"📊 代理店キュー: {len(agency)} 件", flush=True)
