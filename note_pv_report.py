#!/usr/bin/env python3
"""公開Note記事のPVを実測し、テーマ別の勝ち負けを経過日数で正規化して出す。

使い方:
  python3 note_pv_report.py                     # 取得 → data/note_pv_YYYYMMDD.csv → 分析
  python3 note_pv_report.py --fetch-only        # 取得とCSV出力だけ
  python3 note_pv_report.py --analyze data/note_pv_20260810.csv   # 既存CSVを分析し直す

cookie は note_cookies.json（リポジトリ直下）か環境変数 NOTE_COOKIES_JSON。
API は連打しない（ページ間 1.2秒）。

■ 使うAPI
  /api/v1/stats/pv?filter=all|monthly|weekly&page=N&sort=pv   … PV・スキ（要ログイン）
  /api/v2/creators/{urlname}/contents?kind=note&page=N        … 公開日・タグ

■ 注意
  stats/pv には下書き・削除済みノートが混ざる。公開記事の実体は contents 側で決める。
  分類は**タイトルのみ**で行う。ハッシュタグは全記事に #副業 #ライバー 等が一律で
  付いているので、混ぜると全記事が同じクラスタに落ちて集計が無意味になる。
"""
import argparse
import csv
import datetime
import json
import os
import statistics
import sys
import time
from collections import defaultdict

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
COOKIE_FILE = os.path.join(BASE_DIR, "note_cookies.json")
URLNAME = "taitan_118"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "application/json",
           "X-Requested-With": "XMLHttpRequest"}
JST = datetime.timezone(datetime.timedelta(hours=9))

# 公開直後はnoteのタイムライン露出でPV/日が跳ねるので、集計からは外して別枠で見る
MIN_AGE_DAYS = 21


# ─── 分類ルール ────────────────────────────────────────────

# note_article_generator.py の SEO_KEYWORDS 10カテゴリに寄せた単一ラベル。
# 上から順に評価し最初に当たったものを採用する（＝上ほど優先）。
# 「誰向けか」をアプリ名や事務所より優先する（「大学生におすすめの事務所」は大学生記事）。
CATEGORY_RULES = [
    ("lifestyle",       ["主婦", "ママ", "大学生", "高校生", "シングルマザー", "シンママ",
                         "フリーター", "看護師", "社会人", "地方", "10代", "20代", "30代",
                         "40代", "50代", "男性", "子育て", "学生", "会社員"]),
    ("troubleshooting", ["伸びない", "辞めたい", "やめとけ", "アンチ", "メンタル", "来ない",
                         "マンネリ", "辛い", "しんどい", "モチベ", "過疎", "下がった",
                         "疲れ", "挫折", "続かない", "重い枠", "壁", "失敗", "後悔",
                         "トラブル", "荒らし", "緊張", "不安"]),
    ("income",          ["月収", "年収", "収入", "稼げ", "稼ぐ", "稼ぎ方", "時給", "いくら",
                         "投げ銭", "収益化", "換金", "ダイヤ", "報酬", "ギフト", "万円",
                         "経費", "確定申告", "税金", "扶養", "節税", "共済", "NISA", "老後"]),
    ("comparison",      ["違い", "比較", "どっち", "ランキング", "選び方", "おすすめ", "10選"]),
    ("agency",          ["事務所", "マネージャー", "代理店", "還元率", "面談", "スカウト", "所属"]),
    ("advanced",        ["イベント", "S帯", "Sランク", "ブランディング", "SNS運用", "専業",
                         "グッズ", "コラボ", "海外", "開業", "独立", "出口戦略"]),
    ("skills",          ["トーク", "リスナー", "ファン", "盛り上げ", "サムネ", "機材", "照明",
                         "マイク", "リングライト", "背景", "テクニック", "枠タイトル",
                         "時間帯", "ゴールデンタイム", "配信時間", "何時に", "距離感", "コメント"]),
    ("beginner",        ["始め方", "始める", "初心者", "初配信", "デビュー", "未経験",
                         "なるには", "なる条件", "準備", "1日目", "新人", "最初", "何話す",
                         "向いてる", "1ヶ月目", "チェックリスト", "知るべき", "ロードマップ",
                         "30日", "3ヶ月"]),
    ("platform",        ["Pococha", "ポコチャ", "17LIVE", "イチナナ", "TikTok", "IRIAM",
                         "SHOWROOM", "ふわっち", "ミクチャ", "ツイキャス", "BIGO",
                         "配信アプリ", "ライブ配信"]),
    ("sidejob",         ["副業", "在宅", "両立", "バレ", "本業", "スキマ"]),
]

# テーマクラスタ（多ラベル）。1記事が複数に入る。勝ち負けを見るのはこちらが主。
CLUSTER_RULES = {
    "40-50代":      ["40代", "50代", "アラフォー", "アラフィフ", "大人の配信者"],
    "TikTokLIVE":   ["TikTok", "ティックトック"],
    "Pococha":      ["Pococha", "ポコチャ"],
    "17LIVE":       ["17LIVE", "イチナナ"],
    "対象外アプリ":   ["IRIAM", "SHOWROOM", "ふわっち", "ツイキャス", "BIGO"],
    "新人期間":      ["新人期間", "新人", "デビュー", "初配信", "1日目", "31日", "最初の",
                    "1ヶ月目", "30日", "始め方", "始める前", "初心者"],
    "収入・お金":     ["月収", "年収", "収入", "稼げ", "稼ぐ", "稼ぎ", "時給", "いくら",
                    "収益化", "換金", "ダイヤ", "報酬", "投げ銭", "ギフト", "万円"],
    "税金・制度":     ["確定申告", "経費", "税金", "扶養", "節税", "共済", "NISA", "老後",
                    "年金", "開業届", "インボイス"],
    "事務所":        ["事務所", "マネージャー", "還元率", "所属", "面談", "代理店", "スカウト"],
    "主婦・ママ":     ["主婦", "ママ", "子育て", "シングルマザー", "シンママ"],
    "メンタル・継続":  ["メンタル", "辞めたい", "やめとけ", "辛い", "しんどい", "モチベ",
                    "続か", "重い枠", "疲れ", "壁", "アンチ", "伸びない", "緊張",
                    "不安", "後悔", "来ない", "荒らし"],
    "顔出しなし":     ["顔出し", "顔バレ", "身バレ", "Vtuber", "アバター", "声だけ", "ラジオ配信"],
    "配信テク":      ["トーク", "枠タイトル", "時間帯", "ゴールデンタイム", "盛り上げ",
                    "コメント", "リスナー", "ファン", "常連", "何時に", "距離感"],
    "機材・環境":     ["機材", "照明", "マイク", "リングライト", "背景", "サムネ"],
    "副業・両立":     ["副業", "在宅", "会社員", "両立", "バレ", "本業", "スキマ"],
    "比較・選び方":   ["比較", "どっち", "違い", "選び方", "ランキング", "おすすめ", "10選"],
}


def classify(title):
    cat = "other"
    for name, words in CATEGORY_RULES:
        if any(w in title for w in words):
            cat = name
            break
    clusters = [c for c, words in CLUSTER_RULES.items() if any(w in title for w in words)]
    return cat, clusters


# ─── 取得 ─────────────────────────────────────────────────

def load_cookies():
    raw = os.environ.get("NOTE_COOKIES_JSON")
    if raw:
        data = json.loads(raw)
    elif os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    else:
        sys.exit(f"cookieが無い: {COOKIE_FILE} も NOTE_COOKIES_JSON も見つからない")
    return {c["name"]: c["value"] for c in data}


def get_json(url, cookies):
    r = requests.get(url, cookies=cookies, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {url}")
    return r.json()


def fetch_stats(filt, cookies, max_page=30):
    rows, meta = [], {}
    for page in range(1, max_page + 1):
        d = get_json(f"https://note.com/api/v1/stats/pv"
                     f"?filter={filt}&page={page}&sort=pv", cookies)["data"]
        if page == 1:
            meta = {k: d.get(k) for k in ("start_date_str", "end_date_str", "total_pv",
                                          "total_like", "last_calculate_at")}
        rows += d.get("note_stats", [])
        if d.get("last_page"):
            break
        time.sleep(1.2)
    print(f"  [{filt}] {len(rows)}件", file=sys.stderr)
    return meta, rows


def fetch_contents(cookies, max_page=60):
    out = []
    for page in range(1, max_page + 1):
        d = get_json(f"https://note.com/api/v2/creators/{URLNAME}/contents"
                     f"?kind=note&page={page}", cookies)["data"]
        items = d.get("contents", [])
        out += items
        if d.get("isLastPage") or not items:
            break
        time.sleep(1.2)
    print(f"  [contents] 公開{len(out)}本", file=sys.stderr)
    return out


def build_rows(stats, contents):
    today = datetime.datetime.now(JST)
    pv = {}
    for filt in ("all", "monthly", "weekly"):
        for r in stats[filt]:
            pv.setdefault(r["key"], {})[filt] = r.get("read_count", 0)

    rows = []
    for c in contents:
        p = pv.get(c["key"], {})
        pub = datetime.datetime.fromisoformat(c["publishAt"])
        days = max(1, (today - pub).days)
        pv_all, pv_m, pv_w = p.get("all", 0), p.get("monthly", 0), p.get("weekly", 0)
        cat, clusters = classify(c["name"])
        rows.append({
            "key": c["key"],
            "title": c["name"],
            "published_at": pub.strftime("%Y-%m-%d"),
            "days_since": days,
            "pv_all": pv_all,
            "pv_monthly": pv_m,
            "pv_weekly": pv_w,
            "likes": c.get("likeCount", 0),
            "comments": c.get("commentCount", 0),
            "pv_per_day_all": round(pv_all / days, 3),
            "pv_per_day_monthly": round(pv_m / min(30, days), 3),
            "category": cat,
            "clusters": "|".join(clusters),
            "tag_count": len(c.get("hashtags", [])),
            "eyecatch": int(bool(c.get("eyecatch"))),
        })
    rows.sort(key=lambda r: -r["pv_all"])
    return rows


def write_csv(rows, path):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"保存: {path}（{len(rows)}本）")


# ─── 分析 ─────────────────────────────────────────────────

def load_csv(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    for r in rows:
        for k in ("days_since", "pv_all", "pv_monthly", "pv_weekly", "likes", "tag_count"):
            r[k] = int(r[k])
        for k in ("pv_per_day_all", "pv_per_day_monthly"):
            r[k] = float(r[k])
        r["clusters"] = [c for c in r["clusters"].split("|") if c]
    return rows


def agg_table(label, groups, min_n=2):
    print(f"\n── {label} " + "─" * 44)
    print(f"  {'グループ':14s} {'本数':>4s} {'PV/日中央':>9s} {'PV/日平均':>9s} "
          f"{'月間平均':>8s} {'週間平均':>8s} {'全期間計':>8s} {'♡平均':>6s}")
    out = []
    for g, rs in groups.items():
        if len(rs) < min_n:
            continue
        out.append((g, len(rs),
                    statistics.median(r["pv_per_day_all"] for r in rs),
                    statistics.mean(r["pv_per_day_all"] for r in rs),
                    statistics.mean(r["pv_monthly"] for r in rs),
                    statistics.mean(r["pv_weekly"] for r in rs),
                    sum(r["pv_all"] for r in rs),
                    statistics.mean(r["likes"] for r in rs)))
    for g, n, med, mean, mm, mw, tot, lk in sorted(out, key=lambda x: -x[2]):
        print(f"  {g:14s} {n:4d} {med:9.2f} {mean:9.2f} {mm:8.1f} {mw:8.1f} {tot:8d} {lk:6.1f}")


def analyze(rows):
    # build_rows は clusters を "A|B" の文字列で持つ（CSV用）。そのまま渡されると
    # 多ラベル集計が1文字ずつのグループになるので、ここで必ずリストに揃える。
    for r in rows:
        if isinstance(r["clusters"], str):
            r["clusters"] = [c for c in r["clusters"].split("|") if c]

    mature = [r for r in rows if r["days_since"] >= MIN_AGE_DAYS]
    young = [r for r in rows if r["days_since"] < MIN_AGE_DAYS]

    print(f"■ 公開 {len(rows)}本（集計対象 {len(mature)}本 / "
          f"経過{MIN_AGE_DAYS}日未満の観測中 {len(young)}本）")
    print(f"  全期間PV {sum(r['pv_all'] for r in rows)} / "
          f"月間 {sum(r['pv_monthly'] for r in rows)} / 週間 {sum(r['pv_weekly'] for r in rows)}")
    print(f"  PV/日(全期間) 中央値 {statistics.median(r['pv_per_day_all'] for r in mature):.3f}"
          f" / 平均 {statistics.mean(r['pv_per_day_all'] for r in mature):.3f}")

    def dump(title, rs, key, n=20):
        print(f"\n── {title} " + "─" * 30)
        for r in rs[:n]:
            print(f"  {r['pv_per_day_all']:5.2f}/日 全{r['pv_all']:4d} 月{r['pv_monthly']:3d} "
                  f"週{r['pv_weekly']:3d} ♡{r['likes']:2d} {r['days_since']:3d}日 "
                  f"[{r['category']:15s}] {r['title'][:42]}")

    dump(f"全期間PV/日 上位20（経過{MIN_AGE_DAYS}日以上）",
         sorted(mature, key=lambda r: -r["pv_per_day_all"]), "pv_per_day_all")
    dump(f"全期間PV/日 下位20（経過{MIN_AGE_DAYS}日以上）",
         sorted(mature, key=lambda r: r["pv_per_day_all"]), "pv_per_day_all")

    print("\n── いま伸びている（週間PV）上位15 " + "─" * 25)
    for r in sorted(rows, key=lambda r: -r["pv_weekly"])[:15]:
        print(f"  週{r['pv_weekly']:3d} 月{r['pv_monthly']:4d} 全{r['pv_all']:4d} "
              f"{r['days_since']:3d}日 [{r['category']:15s}] {r['title'][:46]}")

    bycat = defaultdict(list)
    for r in mature:
        bycat[r["category"]].append(r)
    agg_table("カテゴリ別（generatorの10カテゴリ・単一ラベル）", bycat)

    byclu = defaultdict(list)
    for r in mature:
        for c in r["clusters"]:
            byclu[c].append(r)
    agg_table("テーマクラスタ別（多ラベル）", byclu)

    print("\n── 公開月別 " + "─" * 44)
    bym = defaultdict(list)
    for r in rows:
        bym[r["published_at"][:7]].append(r)
    for m in sorted(bym):
        rs = bym[m]
        print(f"  {m}  {len(rs):3d}本  PV/日中央 "
              f"{statistics.median(r['pv_per_day_all'] for r in rs):6.2f}"
              f"  月間平均 {statistics.mean(r['pv_monthly'] for r in rs):6.1f}")

    srt = sorted(rows, key=lambda r: -r["pv_all"])
    tot = sum(r["pv_all"] for r in rows)
    print()
    for n in (5, 10, 20, 30):
        s = sum(r["pv_all"] for r in srt[:n])
        print(f"  上位{n:2d}本で全期間PVの {s / tot * 100:.1f}%（{s}/{tot}）")
    zero = [r for r in mature if r["pv_monthly"] == 0]
    print(f"  月間PV 0 の記事: {len(zero)}本 / {len(mature)}本")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--analyze", metavar="CSV", help="既存CSVを分析するだけ")
    ap.add_argument("--fetch-only", action="store_true", help="取得とCSV出力だけ")
    ap.add_argument("--out", help="出力CSVパス（既定: data/note_pv_YYYYMMDD.csv）")
    args = ap.parse_args()

    if args.analyze:
        analyze(load_csv(args.analyze))
        return

    cookies = load_cookies()
    stats = {}
    print("取得中...", file=sys.stderr)
    for filt in ("all", "monthly", "weekly"):
        _, stats[filt] = fetch_stats(filt, cookies)
        time.sleep(1.5)
    contents = fetch_contents(cookies)

    rows = build_rows(stats, contents)
    out = args.out or os.path.join(
        DATA_DIR, f"note_pv_{datetime.datetime.now(JST):%Y%m%d}.csv")
    os.makedirs(DATA_DIR, exist_ok=True)
    write_csv(rows, out)
    if not args.fetch_only:
        print()
        analyze(rows)


if __name__ == "__main__":
    main()
