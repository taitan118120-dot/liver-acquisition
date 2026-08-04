#!/usr/bin/env python3
"""公開済みnote記事の末尾CTA手前に「関連記事」ブロック（内部リンク3本）を挿入する。

背景（2026-08-04 実測）: 公開115本の相互内部リンクはほぼ0本だった。
PV上位20本を監査したところ、本文中に note.com/taitan_118 のリンクを持つ記事は3本だけ。
読者は1記事読んで離脱し、回遊がまったく起きていない。#130 以降の新規記事は
「関連記事」節を持っているので、既存の集客資産にも同じ構造を後付けする。

- 挿入位置: 「TAITAN PROについて」見出しの直前（無ければ特典段落 = 「友だち追加特典」の直前）
- 冪等: 本文に RELATED_MARK が既にあればスキップ
- 関連記事の選び方: タイトルからクラスタを判定し、同クラスタの高PV記事を上位3本
                    （自分自身と、すでに本文にリンク済みの記事は除外）
- 機構は note_leadmagnet_publish.publish_one をそのまま使う（reCAPTCHA・タグ復元・検証込み）

使い方:
  python3 note_internal_links_publish.py --plan            # 挿入内容を出すだけ（GETのみ）
  python3 note_internal_links_publish.py --top 30          # 月間PV上位30本に適用
  python3 note_internal_links_publish.py <key> [<key>...]  # 個別指定
"""
import json
import os
import re
import sys
import time

from note_cta_publish import get_note, req_session

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "data", "internal_links_log.json")
PV_API = "https://note.com/api/v1/stats/pv"

RELATED_MARK = "あわせて読みたい"

# タイトルのキーワード → クラスタ。上から順に当てて、当たったものを全部持つ。
CLUSTERS = [
    ("age",      ["40代", "50代", "30代", "大人世代"]),
    ("tiktok",   ["TikTok"]),
    ("newbie",   ["新人期間", "始めたばかり", "1ヶ月目", "初動", "始め方", "デビュー", "初配信", "未経験"]),
    ("rank",     ["B帯", "C帯", "S帯", "ランク", "時間ダイヤ", "ダイヤ換金", "同接", "イベント"]),
    ("listener", ["リスナー", "コアファン", "ファン", "コメント", "フォロワー", "御新規", "投げ銭", "枠"]),
    ("mental",   ["メンタル", "緊張", "病む", "辞めたい", "重い", "しんどい", "性格", "トラブル", "距離感"]),
    ("noface",   ["顔出し", "顔バレ", "身バレ", "親バレ", "容姿"]),
    ("money",    ["収入", "月収", "稼げ", "稼ぐ", "時給", "確定申告", "経費", "税金", "扶養", "NISA", "共済"]),
    # 事務所探し（ライバー向け）と、代理店・開業（BtoB側）は読者が別なのでクラスタを分ける
    ("agency",   ["事務所", "契約", "還元率", "移籍", "やめとけ", "怪しい"]),
    ("b2b",      ["代理店", "マネージャー", "開業", "スカウト", "DM"]),
    ("persona",  ["主婦", "ママ", "大学生", "会社員", "副業", "男性", "在宅"]),
    ("platform", ["17LIVE", "Pococha", "比較", "掛け持ち", "アプリ"]),
]

# クラスタが1つも当たらない記事のフォールバック先（PV上位から選ぶ）
FALLBACK_MIN = 2


def clusters_of(title):
    out = []
    for name, kws in CLUSTERS:
        if any(k in title for k in kws):
            out.append(name)
    return out


_TOKEN_RE = re.compile(r"[ぁ-んァ-ヶ一-龥A-Za-z0-9]{2,}")
_STOP = {"2026", "年版", "最新", "完全", "ガイド", "方法", "ライバー", "ライブ", "配信",
         "元Sランク", "解説", "公開", "全公開", "保存版", "徹底", "理由", "現役", "note"}


def tokens_of(title):
    return {t for t in _TOKEN_RE.findall(title) if t not in _STOP and len(t) >= 2}


def fetch_pv(session, filt="monthly"):
    """記事ごとの read_count を key -> (pv, title) で返す。"""
    out, page = {}, 1
    while page <= 25:
        r = session.get(f"{PV_API}?filter={filt}&page={page}&sort=pv&ts={int(time.time()*1000)}",
                        timeout=25)
        r.raise_for_status()
        d = r.json()["data"]
        notes = d.get("note_stats", [])
        for n in notes:
            out[n["key"]] = (n.get("read_count", 0), n.get("name", ""))
        if d.get("last_page") or not notes:
            break
        page += 1
        time.sleep(0.5)
    return out


def build_catalog(session):
    """公開記事だけの key -> dict(title, pv, clusters) を作る。"""
    monthly = fetch_pv(session, "monthly")
    alltime = fetch_pv(session, "all")
    merged = {}
    for key, (pv, title) in alltime.items():
        merged[key] = {"title": title, "pv_all": pv,
                       "pv_month": monthly.get(key, (0, ""))[0]}
    # 下書き・削除済みが stats に混ざるので status を確認して落とす
    catalog = {}
    for key, meta in merged.items():
        try:
            d = get_note(session, key, draft=False)
        except Exception:
            continue
        if d.get("status") != "published":
            continue
        meta["title"] = d["name"]
        meta["clusters"] = clusters_of(d["name"])
        meta["body"] = d["body"]
        catalog[key] = meta
        time.sleep(0.3)
    return catalog


def pick_related(key, catalog, n=3):
    """同クラスタ優先＋タイトル語の重なりで加点し、同点はPVの高い順。"""
    me = catalog[key]
    my_cl = set(me["clusters"])
    my_tok = tokens_of(me["title"])
    already = set(re.findall(r"note\.com/taitan_118/n/(n[0-9a-f]+)", me["body"]))
    scored = []
    for k, m in catalog.items():
        if k == key or k in already:
            continue
        overlap = len(my_cl & set(m["clusters"]))
        shared = len(my_tok & tokens_of(m["title"]))
        score = overlap * 10 + shared * 3
        scored.append((score, m["pv_all"], k))
    scored.sort(reverse=True)
    picked = [k for sc, _, k in scored[:n] if sc > 0]
    if len(picked) < n:  # クラスタも語も当たらない記事はPV上位で埋める
        for _, _, k in sorted(scored, key=lambda t: -t[1]):
            if k not in picked:
                picked.append(k)
            if len(picked) >= n:
                break
    return picked[:n]


def related_html(keys, catalog):
    items = "".join(
        f'<li><a href="https://note.com/taitan_118/n/{k}" target="_blank" rel="noopener">'
        f'{catalog[k]["title"]}</a></li>'
        for k in keys)
    return f"<h3>{RELATED_MARK}</h3><ul>{items}</ul>"


def find_insert_pos(html):
    """「TAITAN PROについて」見出しの直前 → 無ければ特典段落の直前。"""
    m = re.search(r"<h[1-4][^>]*>[^<]*TAITAN\s*PRO(について|とは)", html)
    if m:
        return m.start()
    pos = html.rfind("友だち追加特典")
    if pos == -1:
        pos = html.rfind("lin.ee/xchCfdn")
    if pos == -1:
        return None
    p_start = html.rfind("<p", 0, pos)
    return p_start if p_start != -1 else None


def make_transform(keys, catalog):
    block = related_html(keys, catalog)

    def _t(key, html):
        if RELATED_MARK in html:
            return None
        pos = find_insert_pos(html)
        if pos is None:
            print(f"  skip（挿入位置が見つからない key={key}）")
            return None
        return html[:pos] + block + html[pos:]
    return _t


def _load_log():
    if os.path.exists(LOG_FILE):
        return json.load(open(LOG_FILE))
    return {}


def main():
    args = sys.argv[1:]
    plan_only = "--plan" in args
    top = 30
    if "--top" in args:
        top = int(args[args.index("--top") + 1])
    explicit = [a for a in args if a.startswith("n") and not a.startswith("--")]

    s = req_session()
    print("公開記事カタログを構築中…（PV取得 + status確認）")
    catalog = build_catalog(s)
    print(f"  公開記事 {len(catalog)} 本")

    if explicit:
        targets = [k for k in explicit if k in catalog]
    else:
        targets = sorted(catalog, key=lambda k: -catalog[k]["pv_month"])[:top]

    log = _load_log()
    plans = {}
    for key in targets:
        rel = pick_related(key, catalog)
        plans[key] = rel
        done = RELATED_MARK in catalog[key]["body"]
        print(f"\n[{catalog[key]['pv_month']:>3}PV/月] {catalog[key]['title'][:38]}  "
              f"{'（済）' if done else ''}")
        for k in rel:
            print(f"    → {catalog[k]['title'][:46]}")

    if plan_only:
        print(f"\n--plan のため書き込みなし。対象 {len(targets)} 本。")
        return

    from note_leadmagnet_publish import publish_one
    ok = skip = fail = 0
    for i, key in enumerate(targets, 1):
        if log.get(key) == "ok":
            print(f"[{i}/{len(targets)}] {key} 既に完了。skip")
            skip += 1
            continue
        print(f"\n[{i}/{len(targets)}] {key} {catalog[key]['title'][:30]}")
        try:
            r = publish_one(key, make_transform(plans[key], catalog))
            log[key] = r
            ok += 1 if r == "ok" else 0
            skip += 1 if r == "skip" else 0
        except Exception as e:
            print(f"  !! 失敗: {e}")
            log[key] = f"error: {e}"
            fail += 1
        json.dump(log, open(LOG_FILE, "w"), ensure_ascii=False, indent=1)
        time.sleep(3)
    print(f"\n完了 ok={ok} skip={skip} fail={fail}")


if __name__ == "__main__":
    main()
