#!/usr/bin/env python3
"""note_funnel_guard.py
公開中のNote記事の「導線」が剥がれていないかを毎日見る番犬。

■ なぜ必要か（2026-08-28 に実測して分かったこと）
公開140本を全件走査したところ、**「あわせて読みたい」ブロックが40本で消えていた**
（合計2,541PV＝全PVの29%）。内訳は

  ・17本 … `data/note_boost_log.json` 上は「実施済み(ok)」なのに本文から消えている＝**回帰**。
    8/8以降にPUTを打つ一括修正スクリプト（オンライン面談削除など）が本文を書き戻した際に落ちた。
  ・23本 … 8/8のboost以降に `note_auto_poster.py` が公開した新記事。
    poster は内部リンクを入れないので、新記事は必ずリンク0で世に出る。

どちらも **PUTは成功していてログも緑**なので、ログを見ても永久に気づけない。
実際、全期間PV1位（TikTokLIVE収益化・468PV）と代理店1位（スカウト術・209PV）が
どこにも繋がらない行き止まりのまま数ヶ月放置されていた。

■ 見るもの（すべて非ログインの公開APIで確認できる）
  1. 冒頭CTA（🎁 先に特典だけ受け取るのもOK）があるか
  2. 「あわせて読みたい」が**見出しとして**あるか（地の文の引用は数えない）
  3. 公式LINEリンクがあるか
  4. 代理店（＝事務所を"作る側"）記事が、代理店の導線を指しているか
     — `/agency/` LP と『ライバー代理店パートナー スタートガイド』。
       ライバー向け特典を出していたら違反（2026-08-28まで14本全部がそうだった）

使い方:
  python3 note_funnel_guard.py                 # 全件確認。違反があれば exit 1
  python3 note_funnel_guard.py --json          # data/note_funnel_guard_report.json も出力
  python3 note_funnel_guard.py --max-missing 5 # 許容本数（既定0）
"""
import argparse
import json
import os
import re
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_PATH = os.path.join(BASE_DIR, "data", "note_funnel_guard_report.json")
URLNAME = "taitan_118"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

EARLY_MARK = "先に特典だけ受け取るのもOK"
LINE_URL = "lin.ee/xchCfdn"
AGENCY_LP = "taitan-pro-lp.netlify.app/agency/"
AGENCY_GIFT = "ライバー代理店パートナー スタートガイド"
LIVER_GIFT = "ライバー新人期スタートダッシュガイド"

# 見出しとしての「あわせて読みたい」だけを数える。地の文の
# 「> 📖 あわせて読みたい：…」を数えると、リンク0の記事を緑と誤判定する
# （note_boost_publish が実際に踏んだ罠）。noteは保存時に見出しへ name/id を
# 振り直すので、固定文字列ではなく属性を許す正規表現でしか当たらない。
RELATED_RE = re.compile(r"<h[1-6][^>]*>\s*(?:📖\s*)?あわせて読みたい")
INTERNAL_RE = re.compile(r"note\.com/" + URLNAME + r"/n/n[0-9a-f]+")

# 位置のしきい値。冒頭CTAはこれより前、関連ブロックはこれより後ろに無いとおかしい。
# 2026-08-29 の全141本の実測は 冒頭CTA 2〜10% / 関連ブロック 60〜99% で、
# どちらも余裕をもってこの内側にある。
POS_MAX_PCT = 40   # 冒頭CTAの上限
POS_MIN_PCT = 40   # 関連ブロックの下限

# 代理店（＝作る側）記事の判定。note_agency_cta_publish と同じ規則。
AGENCY_WORDS = ["代理店", "開業", "スカウト術", "スカウトDM", "マネージャーとは", "スカウト"]
AGENCY_EXCLUDE = ["選び方", "口コミ", "評判", "入るべき", "やめとけ", "見分け方"]


def is_agency(title):
    if any(w in title for w in AGENCY_EXCLUDE):
        return False
    return any(w in title for w in AGENCY_WORDS)


def fetch_published(session):
    """公開中の記事を [(key, title)] で返す。非ログインの公開APIのみ。"""
    out, page = [], 1
    while page <= 25:
        r = session.get(
            f"https://note.com/api/v2/creators/{URLNAME}/contents"
            f"?kind=note&page={page}", timeout=25)
        r.raise_for_status()
        d = r.json()["data"]
        notes = d.get("contents", [])
        for n in notes:
            out.append((n["key"], n.get("name", "")))
        if d.get("isLastPage") or d.get("last_page") or not notes:
            break
        page += 1
        time.sleep(0.6)
    return out


def check(session, key, title):
    r = session.get(f"https://note.com/api/v3/notes/{key}",
                    headers={"Cache-Control": "no-cache"}, timeout=25)
    r.raise_for_status()
    d = r.json()["data"]
    if d.get("status") != "published":
        return None
    body = d.get("body", "") or ""
    n = max(1, len(body))
    problems = []

    # 「有る」だけでなく「正しい場所に有る」まで見る。どちらも実測で外れた:
    #  ・冒頭CTAが74〜83%地点＝ほぼ末尾（見出しの無い記事に関連ブロックを先に入れると、
    #    その <h3> が「最初の見出し」になりCTAがその直前に入る）
    #  ・関連ブロックが6%地点＝導入直後（find_insert_pos の最後の手当てが
    #    rfind("lin.ee/…") で、末尾に特典段落を持たない記事では冒頭CTAを掴む。
    #    実測 n8e088d985eab は27,127文字の記事で pos=1634 が返っていた）
    i = body.find(EARLY_MARK)
    if i < 0:
        problems.append("冒頭CTAなし")
    elif i / n * 100 > POS_MAX_PCT:
        problems.append(f"冒頭CTAが末尾寄り（{i / n * 100:.0f}%地点）")

    m = RELATED_RE.search(body)
    if not m:
        problems.append("あわせて読みたいブロックなし")
    else:
        if len(set(INTERNAL_RE.findall(body))) < 3:
            problems.append("内部リンクが3本未満")
        if m.start() / n * 100 < POS_MIN_PCT:
            problems.append(f"あわせて読みたいが前半（{m.start() / n * 100:.0f}%地点）")

    if LINE_URL not in body:
        problems.append("公式LINEリンクなし")
    if is_agency(title):
        if AGENCY_LP not in body:
            problems.append("代理店記事なのに代理店LPを指していない")
        if AGENCY_GIFT not in body:
            problems.append("代理店記事なのに代理店向け特典を出していない")
        if LIVER_GIFT in body:
            problems.append("代理店記事にライバー向け特典が残っている")
    return {"key": key, "title": title, "agency": is_agency(title),
            "problems": problems}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-missing", type=int, default=0,
                    help="違反を許容する本数（既定0）")
    args = ap.parse_args()

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})

    pub = fetch_published(s)
    print(f"公開記事 {len(pub)}本を確認中…", file=sys.stderr)

    rows = []
    for i, (key, title) in enumerate(pub, 1):
        try:
            r = check(s, key, title)
        except Exception as e:
            print(f"  取得失敗 {key}: {e}", file=sys.stderr)
            continue
        if r:
            rows.append(r)
        time.sleep(0.3)

    bad = [r for r in rows if r["problems"]]
    ag_bad = [r for r in bad if r["agency"]]

    print(f"\n■ 公開 {len(rows)}本 / 導線に欠けがある記事 {len(bad)}本"
          f"（うち代理店記事 {len(ag_bad)}本）")
    for r in bad:
        print(f"  - {r['title'][:50]}")
        print(f"      {' / '.join(r['problems'])}   https://note.com/{URLNAME}/n/{r['key']}")

    report = {"checked": len(rows), "bad": len(bad), "agency_bad": len(ag_bad),
              "max_missing": args.max_missing, "items": bad}
    if args.json:
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        json.dump(report, open(REPORT_PATH, "w"), ensure_ascii=False, indent=1)
        print(f"\n保存: {REPORT_PATH}")

    if len(bad) > args.max_missing:
        sys.exit(1)
    print("\nOK")


if __name__ == "__main__":
    main()
