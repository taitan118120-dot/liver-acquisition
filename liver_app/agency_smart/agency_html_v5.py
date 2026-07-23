"""v5: HTMLスクレイプ版 (rate limit回避)
   bioは取れないが follower/following/full_name で agency 精査は十分通る。
   名前フィルタpre-pass→230人くらい→HTMLでfl/fw取得→Fly /api/ingest"""
import sys, os, time, json, re
sys.path.insert(0, '/Users/mitataisei/ライバー獲得/liver_app')
import ig_api
import httpx

PW = open('/Users/mitataisei/ライバー獲得/liver_app/.app_password').read().strip()
BASE = "https://taitan-pro-dm.fly.dev"
DELAY = 0.7
USERS_FILE = "/Users/mitataisei/ライバー獲得/liver_app/agency_smart/agency_users.json"
PROFS_FILE = "/Users/mitataisei/ライバー獲得/liver_app/agency_smart/agency_html_profs.json"

# 名前フィルタ
AGENCY_NAME_RE = re.compile(
    r"(経営|オーナー|owner|代表|社長|店長|founder|ceo|"
    r"サロン|エステ|ネイル|美容師|美容室|カフェ|コンカフェ|治療院|"
    r"運用代行|代行|集客|コンサル|販売|転売|"
    r"嬢|キャバ|ホステス|ラウンジ|歌舞伎|ナイトワーク|夜職|"
    r"配信者|ライバー|インフルエンサー|"
    r"副業|起業|フリーランス|個人事業|在宅|ママ社長)",
    re.IGNORECASE,
)

# Fly login
client = httpx.Client(timeout=60.0, follow_redirects=True)
client.post(f"{BASE}/login", data={"password": PW})
print("✓ Fly login", flush=True)

# 1. 候補load + 名前フィルタ
all934 = json.load(open(USERS_FILE, encoding="utf-8"))
filtered = {}
for uname, info in all934.items():
    text = (info.get("full_name", "") + " " + uname)
    if AGENCY_NAME_RE.search(text):
        filtered[uname] = info
print(f"raw 934 → name filter後 {len(filtered)}", flush=True)

# Fly既存除外
queue = client.get(f"{BASE}/api/queue").json().get("leads", [])
existing = {l.get("username") for l in queue}
to_fetch = [info for un, info in filtered.items() if un not in existing]
print(f"未登録 {len(to_fetch)} 件をHTMLスクレイプ", flush=True)

# 2. HTML scrape
profiles = []
errors = 0
for j, info in enumerate(to_fetch, 1):
    uname = info["username"]
    p = None
    try:
        p = ig_api.fetch_profile_html(uname)
    except Exception as e:
        errors += 1
    if not p or not p.get("followers"):
        time.sleep(DELAY)
        continue
    if p.get("is_private"):
        time.sleep(DELAY)
        continue
    profiles.append({
        "u": uname,
        "n": p.get("full_name") or info.get("full_name") or "",
        "b": "",  # HTMLでは取れない
        "fl": p.get("followers"),
        "fw": p.get("following"),
        "pv": False,
        "vf": p.get("is_verified"),
        "bz": False,
        "c": None,
        "tag": info.get("from_tag", ""),
        "target_type_hint": "agency",
    })
    if j % 30 == 0:
        print(f"  進捗 {j}/{len(to_fetch)} fetched={len(profiles)} err={errors}", flush=True)
        json.dump(profiles, open(PROFS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    time.sleep(DELAY)

json.dump(profiles, open(PROFS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
print(f"\n=== {len(profiles)} profiles fetched ===\n", flush=True)

# 3. push
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
            print(f"  batch {k//BATCH+1}: added={d.get('added')} updated={d.get('updated')}", flush=True)
    except Exception as e:
        print(f"  batch err: {e}", flush=True)

# 4. 確認
client.post(f"{BASE}/api/requalify")  # bio空でもagencyなら数値ベースで qualify=1
r = client.get(f"{BASE}/api/queue")
agency = [l for l in r.json().get("leads", []) if l.get("target_type") == "agency"]
print(f"\n✅ DONE: added={total_added} updated={total_updated}", flush=True)
print(f"📊 代理店キュー: {len(agency)} 件", flush=True)
