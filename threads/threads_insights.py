"""
Threads 投稿インサイト取得＋勝ち型分析

Threads Graph API から自分の投稿一覧とメディア単位のインサイト
(views / likes / replies / reposts / quotes / shares) を取得して
data/threads_insights.csv に保存し、「どの型が伸びたか」を集計する。

投稿を増やす前に「何が読まれたか」を確定させるための計測スクリプト。
書き込み系APIは一切呼ばない（読み取りのみ）。

使い方:
  python threads/threads_insights.py                 # 取得＋CSV更新＋レポート表示
  python threads/threads_insights.py --limit 100     # 取得件数
  python threads/threads_insights.py --report-only   # 既存CSVから分析だけ

必要な環境変数:
  THREADS_USER_ID / THREADS_ACCESS_TOKEN
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict

import requests

GRAPH_BASE = "https://graph.threads.net/v1.0"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CSV_PATH = os.path.join(PROJECT_ROOT, "data", "threads_insights.csv")
POSTS_FILE = os.path.join(SCRIPT_DIR, "threads_posts.json")

METRICS = ["views", "likes", "replies", "reposts", "quotes", "shares"]

FIELDS = [
    "media_id", "timestamp", "permalink",
    "views", "likes", "replies", "reposts", "quotes", "shares",
    "engagements", "eng_rate",
    "angle", "style", "has_link", "text_len", "hook", "text",
]

# 本文からの型判定（生成プロンプト側の型に対応）
HOOK_PATTERNS = [
    ("告白型", r"^(正直|ぶっちゃけ|これ言うと|本音を言うと|言いにくいんだけど)"),
    ("常識壊し型", r"(は嘘|は嘘です|もう古い|って思ってません|は間違|信じてる人)"),
    ("具体シーン型", r"^(先月|先週|昨日|この前|うちに来た|今日).{0,20}(子|ライバー|人)"),
    ("数字チラ見せ型", r"^[^\n]{0,30}[0-9０-９]"),
    ("問いかけ型", r"[?？]\s*$|^[^\n]{0,40}[?？]"),
]


def _env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        print(f"[ERROR] {name} が未設定です。")
        sys.exit(2)
    return v


def _get(url, params):
    r = requests.get(url, params=params, timeout=60)
    try:
        return r.json()
    except ValueError:
        return {"error": {"message": f"non-json response {r.status_code}"}}


def fetch_media(token, user_id, limit):
    """自分の投稿を新しい順に取得する（ページング対応）。"""
    out = []
    url = f"{GRAPH_BASE}/{user_id}/threads"
    params = {
        "fields": "id,text,timestamp,permalink,media_type,is_quote_post",
        "limit": min(100, limit),
        "access_token": token,
    }
    while url and len(out) < limit:
        data = _get(url, params)
        if "data" not in data:
            print(f"[ERROR] 投稿一覧取得失敗: {json.dumps(data, ensure_ascii=False)[:400]}")
            break
        out.extend(data["data"])
        nxt = (data.get("paging") or {}).get("next")
        if not nxt:
            break
        url, params = nxt, {}
    return out[:limit]


def fetch_insights(token, media_id):
    data = _get(
        f"{GRAPH_BASE}/{media_id}/insights",
        {"metric": ",".join(METRICS), "access_token": token},
    )
    vals = {m: 0 for m in METRICS}
    for row in data.get("data", []):
        name = row.get("name")
        if name not in vals:
            continue
        v = row.get("values") or []
        if v:
            vals[name] = v[0].get("value", 0) or 0
        elif row.get("total_value"):
            vals[name] = row["total_value"].get("value", 0) or 0
    if "data" not in data:
        msg = json.dumps(data, ensure_ascii=False)[:200]
        print(f"  [WARN] insights取得失敗 {media_id}: {msg}")
    return vals


def _queue_index():
    """キューJSONから media_id -> angle を引けるようにする。"""
    idx = {}
    if not os.path.exists(POSTS_FILE):
        return idx
    try:
        with open(POSTS_FILE, encoding="utf-8") as f:
            for p in json.load(f):
                if p.get("media_id"):
                    idx[str(p["media_id"])] = {
                        "angle": p.get("angle", ""),
                        "has_link": bool(p.get("link")),
                    }
    except Exception:
        pass
    return idx


def classify_style(text):
    """宣伝色で分類する。事務所名や誘導が本文にあるほど『宣伝型』。"""
    promo = 0
    if "TAITAN PRO" in text:
        promo += 1
    if re.search(r"還元率|所属\s*200|提携|マネージャー|サポート体制", text):
        promo += 1
    if re.search(r"友だち追加|LINE|リンク|プロフ", text):
        promo += 1
    if promo >= 2:
        return "宣伝型"
    if promo == 1:
        return "混在型"
    return "本音型"


def classify_hook(text):
    first = (text or "").strip().split("\n")[0]
    for name, pat in HOOK_PATTERNS:
        if re.search(pat, first):
            return name
    return "その他"


def build_rows(token, user_id, limit):
    qidx = _queue_index()
    rows = []
    media = fetch_media(token, user_id, limit)
    print(f"[INFO] 投稿 {len(media)} 件を取得")
    for i, m in enumerate(media, 1):
        mid = str(m.get("id"))
        text = (m.get("text") or "").strip()
        ins = fetch_insights(token, mid)
        views = ins["views"] or 0
        eng = ins["likes"] + ins["replies"] + ins["reposts"] + ins["quotes"] + ins["shares"]
        q = qidx.get(mid, {})
        rows.append({
            "media_id": mid,
            "timestamp": m.get("timestamp", ""),
            "permalink": m.get("permalink", ""),
            **ins,
            "engagements": eng,
            "eng_rate": round(eng / views, 4) if views else 0,
            "angle": q.get("angle", ""),
            "style": classify_style(text),
            "has_link": int(q.get("has_link", False)),
            "text_len": len(text),
            "hook": classify_hook(text),
            "text": text.replace("\n", "\\n"),
        })
        if i % 20 == 0:
            print(f"  ...{i}/{len(media)}")
    return rows


def save_csv(rows):
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in sorted(rows, key=lambda x: x["timestamp"], reverse=True):
            w.writerow({k: r.get(k, "") for k in FIELDS})
    print(f"[OK] {CSV_PATH} に {len(rows)} 件保存")


def load_csv():
    if not os.path.exists(CSV_PATH):
        print(f"[ERROR] {CSV_PATH} がありません。先に取得してください。")
        sys.exit(2)
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in METRICS + ["engagements", "text_len", "has_link"]:
            try:
                r[k] = int(float(r.get(k) or 0))
            except ValueError:
                r[k] = 0
    return rows


def _avg(rows, key):
    return round(sum(r[key] for r in rows) / len(rows), 1) if rows else 0


def report(rows):
    rows = [r for r in rows if r["views"] > 0]
    if not rows:
        print("[WARN] viewsが取れた投稿がありません")
        return
    print("\n" + "=" * 60)
    print(f"投稿数 {len(rows)} / 平均views {_avg(rows,'views')} / 平均反応 {_avg(rows,'engagements')}")

    print("\n■ 伸びた投稿 TOP10（views順）")
    for r in sorted(rows, key=lambda x: -x["views"])[:10]:
        head = r["text"].split("\\n")[0][:38]
        print(f"  {r['views']:>6} views / 👍{r['likes']:>3} 💬{r['replies']:>2} "
              f"[{r['style']}/{r['hook']}] {head}")

    print("\n■ 沈んだ投稿 WORST5（views順）")
    for r in sorted(rows, key=lambda x: x["views"])[:5]:
        head = r["text"].split("\\n")[0][:38]
        print(f"  {r['views']:>6} views / 👍{r['likes']:>3} 💬{r['replies']:>2} "
              f"[{r['style']}/{r['hook']}] {head}")

    for label, key in (("宣伝色", "style"), ("フック型", "hook"), ("angle", "angle")):
        buckets = defaultdict(list)
        for r in rows:
            buckets[r.get(key) or "(不明)"].append(r)
        print(f"\n■ {label}別")
        for k, v in sorted(buckets.items(), key=lambda kv: -_avg(kv[1], "views")):
            print(f"  {k:<10} n={len(v):>3}  平均views {_avg(v,'views'):>7}  "
                  f"平均👍{_avg(v,'likes'):>5}  平均💬{_avg(v,'replies'):>4}")

    print("\n■ 本文の長さ別")
    def bucket(n):
        return "〜80字" if n <= 80 else "81〜180字" if n <= 180 else "181〜300字" if n <= 300 else "301字〜"
    buckets = defaultdict(list)
    for r in rows:
        buckets[bucket(r["text_len"])].append(r)
    for k in ["〜80字", "81〜180字", "181〜300字", "301字〜"]:
        v = buckets.get(k)
        if v:
            print(f"  {k:<10} n={len(v):>3}  平均views {_avg(v,'views'):>7}  平均👍{_avg(v,'likes'):>5}")

    print("\n■ リンク有無別（キューに記録があるものだけ）")
    known = [r for r in rows if r.get("angle")]
    for flag, label in ((1, "リンクあり"), (0, "リンクなし")):
        v = [r for r in known if r["has_link"] == flag]
        if v:
            print(f"  {label:<10} n={len(v):>3}  平均views {_avg(v,'views'):>7}  平均👍{_avg(v,'likes'):>5}")
    print("=" * 60)


def main():
    ap = argparse.ArgumentParser(description="Threads インサイト取得・分析")
    ap.add_argument("--limit", type=int, default=200, help="取得する投稿数")
    ap.add_argument("--report-only", action="store_true", help="取得せずCSVから分析のみ")
    args = ap.parse_args()

    if args.report_only:
        report(load_csv())
        return

    token = _env("THREADS_ACCESS_TOKEN")
    user_id = _env("THREADS_USER_ID")
    rows = build_rows(token, user_id, args.limit)
    if not rows:
        print("[ERROR] 取得0件")
        sys.exit(1)
    save_csv(rows)
    report(rows)


if __name__ == "__main__":
    main()
