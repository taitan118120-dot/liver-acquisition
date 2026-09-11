"""
Instagram 投稿インサイト取得＋勝ち型分析

Instagram Graph API から自分の投稿一覧とメディア単位のインサイト
(reach / views / saved / likes / comments / shares / profile_visits / follows)
を取得して data/ig_insights.csv に保存し、「どの型が伸びたか」を集計する。

112本投稿しても効果測定データが1件も無い状態を解消するための計測スクリプト。
公式 Graph API の読み取り専用（GET）のみ。スクレイピングも書き込みも一切しない。

使い方:
  python instagram/ig_insights.py                  # 取得＋CSV更新＋レポート表示
  python instagram/ig_insights.py --limit 200      # 取得件数
  python instagram/ig_insights.py --report-only    # 既存CSVから分析だけ
  python instagram/ig_insights.py --slots-only     # 既存CSVから着弾時刻(JST)別だけ
  python instagram/ig_insights.py --no-link-queue  # ig_posts.json への media_id 書き戻しをしない

必要な環境変数:
  INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ID
"""

import argparse
import ast
import csv
import json
import os
import re
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CSV_PATH = os.path.join(PROJECT_ROOT, "data", "ig_insights.csv")
POSTS_FILE = os.path.join(SCRIPT_DIR, "ig_posts.json")
VIRAL_FILE = os.path.join(SCRIPT_DIR, "ig_viral_generator.py")

# 新しい順に試す。Meta は約2年で旧バージョンを落とすので、固定せず生きている
# 最新版を実行時に選ぶ（views は v22.0 以降でしか取れない）
API_VERSIONS = ["v25.0", "v24.0", "v23.0", "v22.0", "v21.0"]

# 取りたい指標の最大集合。media_type ごとに対応状況が違うので、
# エラー内容から自動で落として「実際に取れる集合」を確定させる
WANT_METRICS = [
    "reach", "views", "saved", "likes", "comments", "shares",
    "total_interactions", "profile_visits", "follows",
]

FIELDS = [
    "media_id", "posted_at", "permalink", "media_type", "format",
    "reach", "views", "saved", "likes", "comments", "shares",
    "total_interactions", "profile_visits", "follows",
    "save_rate", "eng_rate",
    "queue_id", "source_type", "viral_type", "theme", "slides", "caption_head",
]

NUMERIC = [
    "reach", "views", "saved", "likes", "comments", "shares",
    "total_interactions", "profile_visits", "follows", "slides",
]

JST = timezone(timedelta(hours=9))

# フォロワー数。--report-only ではAPIを叩かないので記録値を使う。
# 正本は marketing/social_profiles.md（@taitan_pro7 / 2026-08-08 時点で15人）。
# リーチはフォロワー数を天井にするので、この数字を並べずに「平均リーチ21 vs 10」
# だけを見ると必ず読み違える（2026-09-11 のフォーマット誤判定の原因がこれ）。
FOLLOWERS_FALLBACK = 15
_FOLLOWERS = None  # ライブ取得できたらこちらが入る

# media_type -> 実際に取れた指標リスト（1メディア目で確定させて以降使い回す）
_SUPPORTED_CACHE = {}


# =====================================================================
# API 呼び出し
# =====================================================================

def _env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        print(f"[ERROR] {name} が未設定です。")
        sys.exit(2)
    return v


def _get(url, params):
    try:
        r = requests.get(url, params=params, timeout=60)
    except requests.exceptions.RequestException as e:
        return {"error": {"message": f"request failed: {e}"}}
    try:
        return r.json()
    except ValueError:
        return {"error": {"message": f"non-json response {r.status_code}"}}


def _err(data):
    return (data.get("error") or {}).get("message", "") or json.dumps(data, ensure_ascii=False)[:300]


class PermissionAbort(Exception):
    """権限不足・トークン失効。全メディアで同じ結果になるので即中断する。"""


# 権限・トークン系のエラーコード。指標の対応/非対応とは無関係で、
# メディアを変えても絶対に直らないため1件目で打ち切る
FATAL_CODES = {10, 190, 200, 803}


def _raise_if_fatal(data, media_id=""):
    err = data.get("error") or {}
    code = err.get("code")
    if code in FATAL_CODES:
        msg = err.get("message", "")
        if f"(#{code})" not in msg:
            msg = f"(#{code}) {msg}"
        raise PermissionAbort(msg + (f" [media {media_id}]" if media_id else ""))


def report_scopes(token):
    """トークンに付いている権限を出す。insights が取れない時の原因特定用。"""
    data = _get("https://graph.facebook.com/v21.0/debug_token",
                {"input_token": token, "access_token": token})
    info = data.get("data") or {}
    if not info:
        print(f"[WARN] トークン情報を取得できませんでした: {_err(data)[:160]}")
        return []
    scopes = info.get("scopes", [])
    print(f"[INFO] トークン権限: {', '.join(scopes) or '（なし）'}")
    if "instagram_manage_insights" not in scopes:
        print("[WARN] instagram_manage_insights がありません。"
              "インサイトAPIは権限不足で失敗します")
    return scopes


def pick_api_version(token, user_id):
    """生きている最新の API バージョンを選ぶ。ついでにフォロワー数も取る。

    フォロワー数は追加リクエストではなく、このバージョン判定の GET に
    fields で相乗りさせている（リーチの天井を出すのに必須なので、
    取れるタイミングで一緒に取ってしまう）。
    """
    global _FOLLOWERS
    override = os.environ.get("IG_GRAPH_API_VERSION", "").strip()
    if override:
        print(f"[INFO] APIバージョン {override}（環境変数指定）")
        return override
    for v in API_VERSIONS:
        data = _get(f"https://graph.facebook.com/{v}/{user_id}",
                    {"fields": "id,username,followers_count", "access_token": token})
        if data.get("id"):
            if isinstance(data.get("followers_count"), int):
                _FOLLOWERS = data["followers_count"]
            print(f"[INFO] APIバージョン {v} / アカウント @{data.get('username', '?')}"
                  f" / フォロワー {_FOLLOWERS if _FOLLOWERS is not None else '取得できず'}")
            return v
        time.sleep(1.0)
    print("[ERROR] どのAPIバージョンでもアカウント情報を取得できませんでした。"
          "トークン/ビジネスIDを確認してください。")
    sys.exit(1)


def fetch_media(base, token, user_id, limit, page_delay):
    """自分の投稿を新しい順に取得する（ページングごとに間隔を空ける）。"""
    out = []
    url = f"{base}/{user_id}/media"
    params = {
        "fields": "id,caption,timestamp,permalink,media_type,media_product_type",
        "limit": min(50, limit),
        "access_token": token,
    }
    page = 0
    while url and len(out) < limit:
        data = _get(url, params)
        if "data" not in data:
            print(f"[ERROR] 投稿一覧取得失敗: {_err(data)[:400]}")
            break
        out.extend(data["data"])
        page += 1
        nxt = (data.get("paging") or {}).get("next")
        if not nxt:
            break
        url, params = nxt, {}
        print(f"  ...{len(out)}件取得（{page}ページ目）。{page_delay}秒待機")
        time.sleep(page_delay)
    return out[:limit]


def _parse_values(data, metrics):
    vals = {m: 0 for m in metrics}
    for row in data.get("data", []):
        name = row.get("name")
        if name not in vals:
            continue
        v = row.get("values") or []
        if v:
            vals[name] = v[0].get("value", 0) or 0
        elif row.get("total_value"):
            vals[name] = row["total_value"].get("value", 0) or 0
    return vals


def _narrow_metrics(msg, metrics):
    """エラー文から「このメディアで使える指標」を絞り込む。

    Meta のエラーは2系統ある:
      - "must be one of the following values: reach, saved, ..." → 許可リスト型
      - "metric[0] ... views is not supported ..."               → 不許可指名型
    どちらでもない場合は None を返して1指標ずつのプローブに落とす。
    """
    low = msg.lower()
    for marker in ("must be one of the following values:", "supported metrics are:",
                   "following metrics:"):
        if marker in low:
            tail = low.split(marker, 1)[1]
            allowed = set(re.findall(r"[a-z_]+", tail))
            narrowed = [m for m in metrics if m in allowed]
            if narrowed and len(narrowed) < len(metrics):
                return narrowed
    offending = [m for m in metrics if re.search(rf"\b{m}\b", low)]
    if offending and len(offending) < len(metrics):
        return [m for m in metrics if m not in offending]
    return None


def resolve_metrics(base, token, media_id, media_type, delay):
    """この media_type で実際に取れる指標セットを確定させる（初回のみ）。"""
    if media_type in _SUPPORTED_CACHE:
        return _SUPPORTED_CACHE[media_type]

    url = f"{base}/{media_id}/insights"
    metrics = list(WANT_METRICS)
    for _ in range(4):
        data = _get(url, {"metric": ",".join(metrics), "access_token": token})
        if "data" in data:
            _SUPPORTED_CACHE[media_type] = metrics
            print(f"[INFO] {media_type} で取得できる指標: {', '.join(metrics)}")
            return metrics
        _raise_if_fatal(data, media_id)
        narrowed = _narrow_metrics(_err(data), metrics)
        if not narrowed:
            break
        metrics = narrowed
        time.sleep(delay)

    # 一括で無理なら1指標ずつ確認する（この media_type につき1回だけ）
    print(f"[INFO] {media_type}: 指標を1つずつ確認します")
    ok, last = [], ""
    for m in WANT_METRICS:
        data = _get(url, {"metric": m, "access_token": token})
        if "data" in data:
            ok.append(m)
        else:
            _raise_if_fatal(data, media_id)
            last = _err(data)
        time.sleep(delay)
    if not ok:
        # 全滅はレート制限やトークン失効の可能性が高い。ここで空集合を固定すると
        # 以降の全メディアが0のまま記録されてしまうのでキャッシュしない
        print(f"  [WARN] {media_type}: 指標を1つも取得できず（{last[:160]}）。"
              "次のメディアで再確認します")
        return []
    _SUPPORTED_CACHE[media_type] = ok
    print(f"[INFO] {media_type} で取得できる指標: {', '.join(ok)}")
    return ok


def fetch_insights(base, token, media_id, media_type, delay):
    metrics = resolve_metrics(base, token, media_id, media_type, delay)
    vals = {m: 0 for m in WANT_METRICS}
    if not metrics:
        return vals
    data = _get(f"{base}/{media_id}/insights",
                {"metric": ",".join(metrics), "access_token": token})
    if "data" not in data:
        print(f"  [WARN] insights取得失敗 {media_id}: {_err(data)[:180]}")
        return vals
    vals.update(_parse_values(data, metrics))
    return vals


# =====================================================================
# 投稿キューとの突き合わせ（型ラベル付け）
# =====================================================================

def load_viral_types():
    """ig_viral_generator.py の VIRAL_THEMES から theme_id -> type を読む。

    生成側は Pillow / google-genai を import するので、モジュールを読み込まず
    AST でリテラルだけ取り出す。
    """
    idx = {}
    if not os.path.exists(VIRAL_FILE):
        return idx
    try:
        with open(VIRAL_FILE, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "VIRAL_THEMES" not in names:
                continue
            for theme in ast.literal_eval(node.value):
                if theme.get("id"):
                    idx[theme["id"]] = theme.get("type", "")
    except Exception as e:
        print(f"[WARN] VIRAL_THEMES の読み取りに失敗: {e}")
    return idx


def _norm(text):
    """キャプション先頭を空白除去して照合キーにする。"""
    return re.sub(r"\s+", "", text or "")[:60]


def load_queue():
    """ig_posts.json を media_id / キャプション先頭の両方から引けるようにする。"""
    by_media, by_caption, raw = {}, {}, []
    if not os.path.exists(POSTS_FILE):
        return by_media, by_caption, raw
    try:
        with open(POSTS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        print(f"[WARN] ig_posts.json の読み取りに失敗: {e}")
        return by_media, by_caption, raw

    viral_types = load_viral_types()
    for p in raw:
        sf = p.get("source_file", "")
        theme_id = sf[len("viral_"):] if sf.startswith("viral_") else ""
        p["_viral_type"] = viral_types.get(theme_id, "")
        if p.get("media_id"):
            by_media[str(p["media_id"])] = p
        key = _norm(p.get("caption", ""))
        if key:
            by_caption.setdefault(key, p)
    return by_media, by_caption, raw


def match_queue(media, by_media, by_caption):
    p = by_media.get(str(media.get("id")))
    if p:
        return p, False
    p = by_caption.get(_norm(media.get("caption", "")))
    return (p, True) if p else (None, False)


def _fmt_label(media_type):
    return {
        "CAROUSEL_ALBUM": "カルーセル",
        "IMAGE": "単画像",
        "VIDEO": "動画",
        "REELS": "リール",
    }.get(media_type or "", media_type or "")


def _to_jst(ts):
    """API の "2026-08-07T11:45:00+0000" を JST ISO に直す。"""
    if not ts:
        return ""
    try:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return ts
    return dt.astimezone(JST).isoformat()


def build_rows(base, token, user_id, limit, delay, page_delay):
    by_media, by_caption, raw = load_queue()
    media = fetch_media(base, token, user_id, limit, page_delay)
    print(f"[INFO] 投稿 {len(media)} 件を取得。インサイトを {delay} 秒間隔で取得します")

    rows, newly_linked = [], 0
    for i, m in enumerate(media, 1):
        mid = str(m.get("id"))
        caption = (m.get("caption") or "").strip()
        media_type = m.get("media_type", "")
        ins = fetch_insights(base, token, mid, media_type, delay)

        p, by_text = match_queue(m, by_media, by_caption)
        if p and by_text and not p.get("media_id"):
            p["media_id"] = mid
            newly_linked += 1

        reach = ins.get("reach") or 0
        interactions = ins.get("total_interactions") or (
            ins.get("likes", 0) + ins.get("comments", 0)
            + ins.get("saved", 0) + ins.get("shares", 0)
        )
        rows.append({
            "media_id": mid,
            "posted_at": _to_jst(m.get("timestamp", "")),
            "permalink": m.get("permalink", ""),
            "media_type": media_type,
            "format": _fmt_label(media_type),
            **{k: ins.get(k, 0) for k in WANT_METRICS},
            "total_interactions": interactions,
            "save_rate": round((ins.get("saved") or 0) / reach, 4) if reach else 0,
            "eng_rate": round(interactions / reach, 4) if reach else 0,
            "queue_id": (p or {}).get("id", ""),
            "source_type": (p or {}).get("source_type", ""),
            "viral_type": (p or {}).get("_viral_type", ""),
            "theme": (p or {}).get("title", ""),
            "slides": len((p or {}).get("image_paths") or []) or (
                1 if media_type == "IMAGE" else ""),
            "caption_head": caption.split("\n")[0][:80],
        })
        if i % 10 == 0:
            print(f"  ...{i}/{len(media)}")
        time.sleep(delay)

    if newly_linked:
        print(f"[INFO] キャプション照合で {newly_linked} 件に media_id を新規紐付け")
    return rows, raw, newly_linked


def save_queue(raw):
    for p in raw:
        p.pop("_viral_type", None)
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    print(f"[OK] {POSTS_FILE} に media_id を書き戻し")


# =====================================================================
# CSV
# =====================================================================

def save_csv(rows):
    """既存CSVとの和集合をmedia_idキーでマージして書き戻す。

    mode="w"で単純上書きすると、--limitを既定より小さくして実行した回だけ
    古い投稿の行が消えて二度と復元できない（APIは直近の投稿しか返さないため）。
    それを防ぐため、必ず既存行を読み込んでから今回分で更新し、和集合を書く。
    """
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    merged = {}
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("media_id"):
                    merged[r["media_id"]] = r
    for r in rows:
        merged[r["media_id"]] = r
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in sorted(merged.values(), key=lambda x: x.get("posted_at", ""), reverse=True):
            w.writerow({k: r.get(k, "") for k in FIELDS})
    print(f"[OK] {CSV_PATH} に今回 {len(rows)} 件取得 / 累計 {len(merged)} 件保存")


def load_csv():
    if not os.path.exists(CSV_PATH):
        print(f"[ERROR] {CSV_PATH} がありません。先に取得してください。")
        sys.exit(2)
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in NUMERIC:
            try:
                r[k] = int(float(r.get(k) or 0))
            except (TypeError, ValueError):
                r[k] = 0
    return rows


# =====================================================================
# レポート
# =====================================================================

def _avg(rows, key):
    return round(sum(r.get(key, 0) for r in rows) / len(rows), 1) if rows else 0


def _bucket_report(rows, label, key, order=None, min_n=10):
    """区分別の比較表。**中央値で並べる**（平均は参考に併記するだけ）。

    平均で並べてはいけない: 2026-09-11 に「単画像 平均21.3 / カルーセル 平均10.1」
    から「カルーセルは単画像の半分」と結論したが、実体は67本中3本
    （リーチ171/187/173・いずれも views < reach のデータ異常行）が平均を
    持ち上げていただけで、中央値は 11.5 vs 10.0 とほぼ差が無かった。
    リーチ二桁のアカウントでは外れ値1本で平均が倍になるので、平均は使えない。

    期間が重なっていない区分を並べても「フォーマットの差」にはならない点にも注意。
    （単画像=4〜7月 / カルーセル=7月以降 で、重なりは1本しかなかった）
    """
    buckets = defaultdict(list)
    for r in rows:
        buckets[r.get(key) or "(不明)"].append(r)
    print(f"\n■ {label}別 ※中央値で並べる（平均は外れ値1本で倍になるので順位に使わない）")
    items = sorted(buckets.items(), key=lambda kv: -_med([r.get("reach", 0) for r in kv[1]]))
    if order:
        items = sorted(items, key=lambda kv: order.index(kv[0]) if kv[0] in order else 99)
    for k, v in items:
        span = _span(v)
        thin = "  ※n少・参考値" if len(v) < min_n else ""
        print(f"  {str(k):<14} n={len(v):>3}  中央リーチ {_med([r.get('reach',0) for r in v]):>6}  "
              f"(平均 {_avg(v,'reach'):>6})  保存計 {sum(r.get('saved',0) for r in v):>3}  "
              f"いいね計 {sum(r.get('likes',0) for r in v):>4}  "
              f"フォロー計 {sum(r.get('follows',0) for r in v):>3}  {span}{thin}")


def _span(rows):
    """その区分が投稿された期間。区分どうしが別の時期なら比較として成立しない。"""
    days = sorted((r.get("posted_at") or "")[:10] for r in rows if r.get("posted_at"))
    if not days:
        return ""
    return f"[{days[0]}〜{days[-1]}]"


def integrity_report(rows):
    """比較に使ってはいけない行を弾く。

    reach（ユニーク到達）は定義上 views（延べ表示）を超えられない。
    views < reach の行は2つの指標の計測期間がズレている疑いがあり、
    リーチの値をそのまま content の良し悪しに使えない。
    """
    bad = [r for r in rows if 0 < r.get("views", 0) < r.get("reach", 0)]
    if bad:
        print(f"\n[WARN] views < reach の行が {len(bad)}本あります"
              "（reachはviewsを超えられないので計測ズレ。比較からは除外します）")
        for r in sorted(bad, key=lambda x: -x["reach"])[:6]:
            print(f"    {(r.get('posted_at') or '')[:10]}  reach {r['reach']:>4} / views {r['views']:>4}  "
                  f"{(r.get('theme') or r.get('caption_head',''))[:34]}")
    return [r for r in rows if r not in bad]


def _med(values):
    """中央値。奇数長だとintが返って桁がガタつくので必ずfloatに揃える。"""
    return round(float(statistics.median(values)), 1) if values else 0.0


def _posted_hour(row):
    """CSVの posted_at（JST ISO）からJSTの時（0-23）を取る。取れなければ None。"""
    s = str(row.get("posted_at") or "").strip().replace("Z", "+00:00")
    s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        # 保存時は必ずJSTに直しているので、tzなしの古い行はJSTとみなす
        return dt.hour
    return dt.astimezone(JST).hour


def _load_window():
    """ig_slot.py の WINDOW を正本として読む（なければ None）。"""
    try:
        from ig_slot import WINDOW, in_window
    except ImportError:
        return None, None
    return WINDOW, in_window


def slot_report(rows, min_n=3):
    """着弾時刻(JST)別のリーチ中央値。ig_slot.WINDOW を決め直す根拠になる表。

    投稿1本ごとの reach / views は「その投稿の生涯値」なので、週を待たなくても
    過去の投稿だけで時刻別の比較ができる。GitHub Actions の schedule 遅延で
    着弾時刻が 20時台〜翌6時台までバラけているぶんが、そのままサンプルになる。
    Threads 側で同じ表から窓を決めた前例が threads/threads_slot.py の冒頭にある。

    平均でなく中央値を見るのは、1本のバズ（リーチ数千）で平均が持っていかれて
    「その時刻が強い」と誤読するのを避けるため。
    """
    live = [r for r in rows if r.get("reach", 0) > 0]
    if not live:
        print("[WARN] リーチが取れた投稿がありません（権限不足のままだと全部0になる）")
        return

    buckets = defaultdict(list)
    for r in live:
        h = _posted_hour(r)
        if h is not None:
            buckets[h].append(r)
    if not buckets:
        print("[WARN] posted_at を読めた投稿がありません")
        return

    window, in_window = _load_window()

    print("\n■ 着弾時刻(JST)別 ※ig_slot.WINDOW を決め直す根拠はここ")
    print("  （中央値で見る。1本のバズで平均が動くため）")
    for h in sorted(buckets):
        v = buckets[h]
        reach = [r.get("reach", 0) for r in v]
        views = [r.get("views", 0) for r in v]
        mark = ""
        if in_window:
            # その時刻の30分地点が窓に入るかで「現WINDOW内」を判定する
            probe = datetime(2000, 1, 1, h, 30, tzinfo=JST)
            mark = " ←現WINDOW内" if in_window(probe) else ""
        thin = "  ※n少" if len(v) < min_n else ""
        print(f"  {h:>2}時  n={len(v):>3}  中央リーチ {_med(reach):>7}  "
              f"中央views {_med(views):>7}  平均リーチ {_avg(v,'reach'):>7}{mark}{thin}")

    if not in_window:
        print("  [WARN] ig_slot.py を読めなかったので現WINDOWとの突き合わせは省略")
        return

    inside, outside = [], []
    for h, v in buckets.items():
        probe = datetime(2000, 1, 1, h, 30, tzinfo=JST)
        (inside if in_window(probe) else outside).extend(v)
    print(f"\n  現WINDOW: {window[0]}-{window[1]}（instagram/ig_slot.py が正本）")
    print(f"    窓内 n={len(inside):>3}  中央リーチ {_med([r.get('reach',0) for r in inside]):>7}")
    print(f"    窓外 n={len(outside):>3}  中央リーチ {_med([r.get('reach',0) for r in outside]):>7}")

    ranked = sorted(
        ((h, v) for h, v in buckets.items() if len(v) >= min_n),
        key=lambda kv: -_med([r.get("reach", 0) for r in kv[1]]),
    )
    if not ranked:
        print(f"    → n>={min_n} の時刻がまだ無い。窓は動かさず、投稿を貯めてから判断する")
        return
    best = ", ".join(f"{h}時({_med([r.get('reach',0) for r in v])})" for h, v in ranked[:4])
    print(f"    → 中央リーチが高い時刻(n>={min_n}): {best}")
    if len(live) < 20:
        print(f"    ※ 母数 {len(live)}本。窓を動かす判断には少なすぎるので参考値扱い")


def report(rows):
    live = [r for r in rows if r.get("reach", 0) > 0]
    if not live:
        print("[WARN] リーチが取れた投稿がありません")
        return
    print("\n" + "=" * 72)
    followers = _FOLLOWERS if _FOLLOWERS is not None else FOLLOWERS_FALLBACK
    src = "API" if _FOLLOWERS is not None else "記録値 marketing/social_profiles.md"
    print(f"投稿数 {len(live)} / 中央リーチ {_med([r['reach'] for r in live])} "
          f"(平均 {_avg(live,'reach')}) / 保存計 {sum(r['saved'] for r in live)} / "
          f"いいね計 {sum(r['likes'] for r in live)} / "
          f"フォロー計 {sum(r['follows'] for r in live)}")

    # リーチの天井＝フォロワー数。ここを超えた本数が「外（非フォロワー）に
    # 出た本数」で、フォーマット論より先に見るべき数字。
    out = [r for r in live if r["reach"] > followers]
    print(f"フォロワー {followers}人（{src}） → "
          f"リーチがフォロワー数を超えた投稿 {len(out)}/{len(live)}本 "
          f"({len(out)/len(live)*100:.0f}%)")
    if len(out) / len(live) < 0.3:
        print("  ※ 大半の投稿がフォロワーの外に出ていない。この状態では"
              "フォーマット/テーマの差は測れない（母数が足りない）")

    live = integrity_report(live)

    print("\n■ 伸びた投稿 TOP10（リーチ順）")
    for r in sorted(live, key=lambda x: -x["reach"])[:10]:
        print(f"  {r['reach']:>6}リーチ 💾{r['saved']:>4} 👍{r['likes']:>4} "
              f"[{r.get('format','')}/{r.get('viral_type') or r.get('source_type','')}] "
              f"{(r.get('theme') or r.get('caption_head',''))[:34]}")

    print("\n■ 沈んだ投稿 WORST5（リーチ順）")
    for r in sorted(live, key=lambda x: x["reach"])[:5]:
        print(f"  {r['reach']:>6}リーチ 💾{r['saved']:>4} 👍{r['likes']:>4} "
              f"[{r.get('format','')}/{r.get('viral_type') or r.get('source_type','')}] "
              f"{(r.get('theme') or r.get('caption_head',''))[:34]}")

    _bucket_report(live, "投稿フォーマット", "format")
    _bucket_report(live, "生成ソース（blog/twitter/viral）", "source_type")

    viral = [r for r in live if r.get("viral_type")]
    if viral:
        _bucket_report(viral, "バズ型（viralのみ）", "viral_type")

    slot_report(live)

    print("\n■ 月別")
    months = defaultdict(list)
    for r in live:
        months[(r.get("posted_at") or "")[:7]].append(r)
    for k in sorted(months):
        v = months[k]
        print(f"  {k:<14} n={len(v):>3}  中央リーチ {_med([r['reach'] for r in v]):>6}  "
              f"(平均 {_avg(v,'reach'):>6})  保存計 {sum(r['saved'] for r in v):>3}  "
              f"いいね計 {sum(r['likes'] for r in v):>4}")

    # 閾値を50固定にすると、リーチ二桁しか無い時期に表が丸ごと空になって
    # 「保存が取れていない」事実そのものが見えなくなる。上位1/4を母数にする。
    reaches = sorted((r["reach"] for r in live), reverse=True)
    floor = reaches[max(0, len(reaches) // 4 - 1)] if reaches else 0
    print(f"\n■ 保存率TOP5（リーチ上位1/4＝{floor}以上）")
    cand = [r for r in live if r["reach"] >= floor]
    if not any(r.get("saved") for r in cand):
        print(f"  上位{len(cand)}本すべて保存0。"
              "保存CTA（📌保存して〜）は現状まったく効いていない")
    for r in sorted(cand, key=lambda x: -(float(x.get("save_rate") or 0)))[:5]:
        print(f"  保存率 {float(r.get('save_rate') or 0):.1%}  "
              f"({r['saved']}/{r['reach']})  "
              f"{(r.get('theme') or r.get('caption_head',''))[:38]}")
    print("=" * 72)


def main():
    ap = argparse.ArgumentParser(description="Instagram インサイト取得・分析（読み取り専用）")
    ap.add_argument("--limit", type=int, default=200, help="取得する投稿数")
    ap.add_argument("--delay", type=float, default=2.0,
                    help="メディア1件ごとの待機秒（バースト防止）")
    ap.add_argument("--page-delay", type=float, default=3.0, help="ページング間の待機秒")
    ap.add_argument("--report-only", action="store_true", help="取得せずCSVから分析のみ")
    ap.add_argument("--slots-only", action="store_true",
                    help="着弾時刻(JST)別の表だけ出す（WINDOWを決め直すとき用）")
    ap.add_argument("--no-link-queue", action="store_true",
                    help="ig_posts.json への media_id 書き戻しをしない")
    args = ap.parse_args()

    if args.slots_only:
        slot_report(load_csv())
        return

    if args.report_only:
        report(load_csv())
        return

    token = _env("INSTAGRAM_ACCESS_TOKEN")
    user_id = _env("INSTAGRAM_BUSINESS_ID")
    report_scopes(token)
    version = pick_api_version(token, user_id)
    base = f"https://graph.facebook.com/{version}"

    try:
        rows, raw, linked = build_rows(base, token, user_id, args.limit,
                                       args.delay, args.page_delay)
    except PermissionAbort as e:
        print(f"\n[ERROR] インサイトAPIが権限不足で拒否されました: {e}")
        print("  Metaアプリに instagram_manage_insights（＋対象IGアカウントの")
        print("  ビジネス連携）を付けてトークンを取り直す必要があります。")
        print("  権限のないまま回しても全指標0のCSVを上書きするだけなので中断します。")
        sys.exit(3)
    if not rows:
        print("[ERROR] 取得0件")
        sys.exit(1)
    save_csv(rows)
    if linked and not args.no_link_queue:
        save_queue(raw)
    report(rows)


if __name__ == "__main__":
    main()
