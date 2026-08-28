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

from facts_patterns import common_violations
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

# 筆者の肩書き（本文の話題ではない）。クラスタ判定の前に落とす。
# 「〜を現役マネージャーが解説」で顔出しなし記事が b2b 判定され、
# BtoB記事の関連リンクにライバー向け記事が混ざっていた。
_BYLINE = ["現役マネージャー", "ライバー事務所代表", "現役代表"]


def clusters_of(title):
    for b in _BYLINE:
        title = title.replace(b, "")
    out = []
    for name, kws in CLUSTERS:
        if any(k in title for k in kws):
            out.append(name)
    return out


_WORD_RE = re.compile(r"[ぁ-んァ-ヶー一-龥A-Za-z0-9]+")
# 日本語のタイトルは語の区切りが無いので、単語ではなく文字bigramで重なりを測る。
# 定型句はbigram化の「前」に落とす（全記事に付く「2026年最新」「完全ガイド」が
# 無関係な記事同士を高スコアで結びつけてしまうため）。
_BOILER = ["2026年完全版", "2026年最新", "2026年公式データ", "2026年版", "2026",
           "元ミクチャNo.1", "元Sランク", "完全ガイド", "完全攻略", "完全比較", "完全解説",
           "完全図解", "完全版", "保存版", "全公開", "徹底解説", "実データ", "最新", "完全",
           "ガイド", "方法", "ライバー", "ライブ", "配信", "解説", "公開", "徹底", "理由",
           "現役", "note"]


def tokens_of(title):
    """タイトルの文字bigram集合。定型句を除いてから作る。"""
    for b in _BOILER:
        title = title.replace(b, "\n")
    out = set()
    for run in _WORD_RE.findall(title):
        if len(run) == 1:
            out.add(run)
        for i in range(len(run) - 1):
            out.add(run[i:i + 2])
    return out


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


def build_catalog_light(session):
    """本文を持たない軽量カタログ。pick_related / related_html はこれで足りる。

    build_catalog は公開判定のために記事1本ごとに GET するので、公開140本で2分以上
    かかる。毎日の自動投稿（note_auto_poster）から呼ぶには重すぎるうえ、公開直後の
    記事は PV API にまだ現れず catalog から丸ごと落ちることがある。こちらは
      ・公開判定 … creators/contents（＝公開中しか返さない公開API）
      ・PV      … stats/pv。取れなければ0扱いで続行（クラスタとタイトル類似だけで選ぶ）
    にして、本文はカタログに載せない。

    pick_related は catalog[key]["body"] を「対象記事が既にリンク済みの記事」の
    除外にしか使わないので、対象記事だけ add_entry で本文ごと入れれば足りる。
    """
    from note_tag_guard import list_published

    pv = {}
    try:
        pv = fetch_pv(session, "all")
    except Exception as e:
        print(f"  [links] PV取得に失敗（PVなしで関連記事を選ぶ）: {type(e).__name__}: {e}")

    catalog = {}
    for n in list_published(session):
        key, title = n.get("key"), n.get("name") or ""
        if not key:
            continue
        catalog[key] = {"title": title, "pv_all": pv.get(key, (0, ""))[0],
                        "pv_month": 0, "clusters": clusters_of(title), "body": ""}
    return catalog


# まだ key を持たない記事（＝これから新規公開する記事）を pick_related に渡すための仮key。
PENDING_KEY = "__pending__"


def add_entry(catalog, title, body, key=None):
    """記事1本をカタログへ載せて key を返す。

    新規公開の記事はまだ note 上に存在せず、公開直後の記事も公開一覧APIへの反映が
    遅れることがある。pick_related は catalog[key] を必ず引くので、対象記事は
    こちらで明示的に入れてから呼ぶ（自分自身は候補から外れる）。
    """
    key = key or PENDING_KEY
    catalog[key] = {"title": title, "pv_all": 0, "pv_month": 0,
                    "clusters": clusters_of(title), "body": body or ""}
    return key


# ─── 代理店ブリッジ ──────────────────────────────────────
# 2026-08-28 の実測: 全期間PV上位30本（＝全PVの63%）が持つ内部リンク67本のうち、
# 代理店（＝事務所を"作る側"）記事へのリンクは **4本** しかなかった。
# pick_related はクラスタの重なりとタイトル類似で選ぶので、ライバー向け記事から
# 代理店記事へは構造上ぜったいに繋がらない。月3,300PVの本体が代理店funnelに
# 一滴も流れていない状態だった（data/note_pv_analysis_20260828.md §3）。
#
# そこで「事務所そのものを調べている読者」の記事に限り、関連3本のうち1枠を
# 代理店記事に予約する。事務所の還元率・契約・仕組みを読んでいる人は
# "作る側" から最も近い層で、話題としても地続き。
# ライバーの配信テクや新人期間の記事には**入れない**（読者がまるで違う）。
# 「代理店」「開業」は"作る側"であることが単語だけで確定する強いしるし。
# 「事務所」「マネージャー」「スカウト」は弱く、"選ぶ側"の記事にも出るので
# 除外語と突き合わせて判定する（例:「事務所に入るメリット・デメリット」は選ぶ側）。
_AGENCY_STRONG = ["代理店", "開業"]
_AGENCY_WEAK = ["スカウト術", "スカウトDM", "マネージャーとは", "事務所を作"]
_AGENCY_WEAK_EXCLUDE = ["選び方", "口コミ", "評判", "入るべき", "やめとけ", "見分け方",
                        "メリット", "デメリット"]

# ブリッジを差し込む側＝「事務所という仕組みそのものを調べている読者」。
# 事務所という語が出るだけでは足りない（「事務所に入って変わったこと」のような
# ライバーの体験談まで拾ってしまう）ので、仕組み・条件を調べている語との
# 同時出現を条件にする。
_BRIDGE_TOPIC = ["仕組み", "還元率", "マージン", "契約", "移籍", "選び方", "フリー",
                 "メリット", "デメリット", "入るべき", "見分け方", "違約金", "マネージャー"]


def is_agency_article(title):
    for b in _BYLINE:
        title = title.replace(b, "")
    if any(w in title for w in _AGENCY_STRONG):
        return True
    if any(w in title for w in _AGENCY_WEAK_EXCLUDE):
        return False
    return any(w in title for w in _AGENCY_WEAK)


def wants_agency_bridge(title):
    # 「〜を現役マネージャーが解説」の肩書きで顔出しなし記事まで拾っていた。
    # clusters_of と同じく肩書きを先に落とす。
    for b in _BYLINE:
        title = title.replace(b, "")
    if is_agency_article(title):
        return False  # 代理店記事どうしは通常のスコアリングで十分近い
    if "事務所" not in title and "マネージャー" not in title:
        return False
    return any(w in title for w in _BRIDGE_TOPIC)


def pick_related(key, catalog, n=3):
    """同クラスタ優先＋タイトルbigramの近さで加点し、同点はPVの高い順。

    事務所まわりを読んでいる記事だけは、3本のうち1本を代理店記事に予約する
    （_AGENCY_BRIDGE_FROM 参照）。
    """
    me = catalog[key]
    my_cl = set(me["clusters"])
    my_tok = tokens_of(me["title"])
    already = set(re.findall(r"note\.com/taitan_118/n/(n[0-9a-f]+)", me["body"]))
    scored = []
    for k, m in catalog.items():
        if k == key or k in already:
            continue
        tok = tokens_of(m["title"])
        jaccard = len(my_tok & tok) / max(1, len(my_tok | tok))
        overlap = len(my_cl & set(m["clusters"]))
        scored.append((overlap * 10 + round(jaccard * 40), m["pv_all"], k))
    scored.sort(reverse=True)
    picked = [k for _, _, k in scored[:n]]

    if n >= 2 and wants_agency_bridge(me["title"]) \
            and not any(is_agency_article(catalog[k]["title"]) for k in picked):
        bridge = next((k for _, _, k in sorted(scored, key=lambda t: -t[1])
                       if is_agency_article(catalog[k]["title"])), None)
        if bridge:
            picked[-1] = bridge  # いちばん弱い1本を代理店記事に差し替える
    return picked


def related_html(keys, catalog):
    """関連記事ブロックのHTML。**他記事のタイトルを本文へコピーする**点に注意。

    タイトルが確定ファクト違反だと、この関数がそれを他記事の本文へ増殖させる。
    2026-08-29 に実際に起きた: 「初見リスナーを常連化する」等の呼び捨てタイトル3本が
    「あわせて読みたい」経由で他記事の本文に入っていた（実測 n3eef71e830e8）。
    本文だけ直しても、次にこのブロックを入れ直した時点で戻る。
    そこで、貼る前にタイトル自体を検品して鳴らす（貼るのは止めない。
    note_boost_publish の長時間バッチを1本のタイトルで落とすほうが害が大きい。
    公開後の検出は note_live_facts_guard が毎日やる）。
    """
    for k in keys:
        for reason, hit in common_violations(catalog[k].get("title", "")):
            print(f"  [WARN] リンク先タイトルが確定ファクト違反: {k} {reason}: {hit}\n"
                  f"         先にタイトルを直すこと（本文だけ直しても再発する）。"
                  f"note_listener_facts_fix_20260828.py の title_fn を参照")
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
            # 反映確認はこの施策が入れたマーカーで行う（既定の特典段落は
            # この施策の対象外の記事にも存在しないことがあるため）
            r = publish_one(key, make_transform(plans[key], catalog),
                            expect_marker=RELATED_MARK)
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
