#!/usr/bin/env python3
"""公開済みnote記事に「冒頭CTA」と「関連記事3本」をまとめて後付けする。

2026-08-04 に月間PV上位30本までは実施済みだが、公開118本のうち残り約90本は
どちらも入っていない。冒頭CTA（note_early_cta_publish）と内部リンク
（note_internal_links_publish）はどちらも「本文を書き換えて再公開」なので、
別々に回すと同じ記事へPUTが2回飛ぶ。1本あたり約1分かかるうえ、note側の
連投検知にも近づくので、この2施策は**1回のPUTにまとめる**のがこのスクリプト。

- 冒頭CTA: 最初の <h1-4> の直前。見出しが無い/末尾寄りの記事は導入直後（early_or_fallback）
- 関連記事: 「TAITAN PROについて」見出し or 特典段落の直前（note_internal_links_publish と同一）
- 冪等: 既に入っているものは入れない。両方入っていればそのままskip
- 進捗は data/note_boost_log.json。既存の
  data/internal_links_log.json も読んで「内部リンク済み」を尊重する

使い方:
  python3 note_boost_publish.py --plan             # 対象と挿入内容を出すだけ（GETのみ）
  python3 note_boost_publish.py --limit 20         # 月間PV降順に20本処理
  python3 note_boost_publish.py <key> [<key> ...]  # 個別指定
"""
import json
import os
import re
import sys
import time

from note_early_cta_publish import EARLY_HTML, EARLY_MARK
from note_internal_links_publish import (RELATED_MARK, build_catalog,
                                         find_insert_pos, pick_related,
                                         related_html)
from note_cta_publish import req_session

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "data", "note_boost_log.json")
LINKS_LOG = os.path.join(BASE_DIR, "data", "internal_links_log.json")

# note側の連投検知を避けるため、BATCH本ごとに BATCH_SLEEP 秒あける
BATCH = 8
BATCH_SLEEP = 25


def _load(path):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except Exception:
            return {}
    return {}


# 冒頭CTAは本文のこの割合より前に入っていないと「冒頭」とは言えない
EARLY_MAX_PCT = 40

# 関連記事ブロックの検出は「見出しとしての あわせて読みたい」で見る。
# ① 素の「あわせて読みたい」だけで判定すると、本文中に「> 📖 あわせて読みたい：…」と
#    地の文で書いている記事を「もう入っている」と誤判定し、内部リンクを1本も入れずに
#    終わる（実測2本: n16405bbbfdff / n27ea6809b1ed）。
# ② かわりに "<h3>あわせて読みたい" のような固定文字列で見るのも駄目。note は保存時に
#    見出しへ name/id 属性を振り直すので、次に読むと <h3 name="…" id="…"> になって
#    マッチせず、同じブロックを二重に挿入してしまう。
# → 属性を許す正規表現で見るのが唯一正しい。
REL_BLOCK_RE = re.compile(r"<h[1-6][^>]*>\s*" + re.escape(RELATED_MARK) + r"\s*</h[1-6]>")


def has_related_block(html):
    return bool(REL_BLOCK_RE.search(html))


def _early_pct(html):
    """冒頭CTAが本文の何%地点にあるか。無ければ None。"""
    p = html.find(EARLY_MARK)
    return None if p < 0 else p / max(1, len(html)) * 100


def needs(body):
    """(冒頭CTAが要るか, 関連記事が要るか)"""
    pct = _early_pct(body)
    need_early = pct is None or pct > EARLY_MAX_PCT
    need_rel = not has_related_block(body) and find_insert_pos(body) is not None
    return need_early, need_rel


def _strip_early(html):
    """末尾寄りに入ってしまった冒頭CTAの <p> を丸ごと取り除く。"""
    i = html.find(EARLY_MARK)
    s = html.rfind("<p", 0, i)
    e = html.find("</p>", i)
    if s == -1 or e == -1:
        return html
    return html[:s] + html[e + 4:]


def early_or_fallback(key, html):
    """冒頭CTAを本文の冒頭に入れる（既に末尾寄りに入っていれば入れ直す）。

    note_early_cta_publish.transform_early は「最初の <h1-4> の直前」に入れるが、
    これは2通りに外れる。どちらも実測で踏んだ:
      ① 公開HTMLから復元した記事（#16 / #134）は見出しが1つも無く、None が
         返って黙ってスキップされる
      ② ①の記事に関連記事ブロックを先に入れると、その <h3> が「最初の見出し」に
         なり、CTAが本文の74〜83%地点＝ほぼ末尾に入る
    そこで、見出しが無い/末尾寄りのときは導入の直後（3つめの <p> の直前）に入れる。
    """
    pct = _early_pct(html)
    if pct is not None:
        if pct <= EARLY_MAX_PCT:
            return None  # 済み
        html = _strip_early(html)  # 位置が悪いので入れ直す

    m = re.search(r"<h[1-4][\s>]", html)
    pos = m.start() if m else None
    if pos is not None and pos / max(1, len(html)) * 100 > EARLY_MAX_PCT:
        pos = None  # 最初の見出しが末尾寄り（関連記事ブロックが唯一の見出し等）
    if pos is None:
        starts = [m2.start() for m2 in re.finditer(r"<p[\s>]", html)]
        if not starts:
            print(f"  skip（見出しも <p> も無い key={key}）")
            return None
        pos = starts[2] if len(starts) > 2 else starts[-1]
    return html[:pos] + EARLY_HTML + html[pos:]


def insert_related(rel_keys, catalog, key, html):
    """関連記事ブロックを挿入する。冪等判定は has_related_block で行う。

    note_internal_links_publish.make_transform は素の「あわせて読みたい」で
    冪等判定するため、地の文でその語を使っている記事をskipしてしまう。
    """
    if has_related_block(html):
        return None
    pos = find_insert_pos(html)
    if pos is None:
        print(f"  skip（関連記事の挿入位置が見つからない key={key}）")
        return None
    return html[:pos] + related_html(rel_keys, catalog) + html[pos:]


def make_combined(need_early, rel_keys, catalog):
    """冒頭CTAと関連記事を1回の書き換えで両方入れる transform。"""

    def _t(key, html):
        out = html
        if need_early:
            r = early_or_fallback(key, out)
            if r is not None:
                out = r
        if rel_keys:
            r = insert_related(rel_keys, catalog, key, out)
            if r is not None:
                out = r
        return None if out == html else out
    return _t


def main():
    args = sys.argv[1:]
    plan_only = "--plan" in args
    limit = None
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    explicit = [a for a in args if a.startswith("n") and not a.startswith("--")]

    s = req_session()
    print("公開記事カタログを構築中…（PV取得 + status確認）")
    catalog = build_catalog(s)
    print(f"  公開記事 {len(catalog)} 本")

    log = _load(LOG_FILE)
    links_done = {k for k, v in _load(LINKS_LOG).items() if v == "ok"}

    order = explicit or sorted(catalog, key=lambda k: -catalog[k]["pv_month"])
    todo = []
    for key in order:
        if key not in catalog:
            continue
        if log.get(key) == "ok":
            continue
        body = catalog[key]["body"]
        need_early, need_rel = needs(body)
        if key in links_done:
            need_rel = False
        if not (need_early or need_rel):
            continue
        todo.append((key, need_early, need_rel))
    if limit:
        todo = todo[:limit]

    print(f"\n対象 {len(todo)} 本"
          f"（冒頭CTA {sum(1 for _, e, _ in todo if e)} / 関連記事 {sum(1 for _, _, r in todo if r)}）")

    plans = {}
    for key, need_early, need_rel in todo:
        rel = pick_related(key, catalog) if need_rel else []
        plans[key] = rel
        mark = ("CTA" if need_early else "") + ("+links" if need_rel else "")
        print(f"\n[{catalog[key]['pv_month']:>3}PV/月] {mark:9} {catalog[key]['title'][:36]}")
        for k in rel:
            print(f"    → {catalog[k]['title'][:46]}")

    if plan_only:
        print(f"\n--plan のため書き込みなし。対象 {len(todo)} 本。")
        return

    from note_leadmagnet_publish import publish_one
    ok = skip = fail = 0
    for i, (key, need_early, need_rel) in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] {key} {catalog[key]['title'][:30]}", flush=True)
        # 検証は壊れやすい方（冒頭CTA）を優先して見る。関連記事の挿入位置は
        # needs() の find_insert_pos で先に存在を確認しているので確実に入るが、
        # 冒頭CTAは本文構造に依存する（見出しが無い記事があった）。
        marker = EARLY_MARK if need_early else RELATED_MARK
        try:
            r = publish_one(key, make_combined(need_early, plans[key], catalog),
                            expect_marker=marker)
            log[key] = r
            ok += 1 if r == "ok" else 0
            skip += 1 if r == "skip" else 0
        except Exception as e:
            print(f"  !! 失敗: {e}", flush=True)
            log[key] = f"error: {e}"
            fail += 1
        json.dump(log, open(LOG_FILE, "w"), ensure_ascii=False, indent=1)
        time.sleep(BATCH_SLEEP if i % BATCH == 0 else 3)
    print(f"\n完了 ok={ok} skip={skip} fail={fail}")


if __name__ == "__main__":
    main()
