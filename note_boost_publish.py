#!/usr/bin/env python3
"""公開済みnote記事に「冒頭CTA」と「関連記事3本」をまとめて後付けする。

2026-08-04 に月間PV上位30本までは実施済みだが、公開118本のうち残り約90本は
どちらも入っていない。冒頭CTA（note_early_cta_publish）と内部リンク
（note_internal_links_publish）はどちらも「本文を書き換えて再公開」なので、
別々に回すと同じ記事へPUTが2回飛ぶ。1本あたり約1分かかるうえ、note側の
連投検知にも近づくので、この2施策は**1回のPUTにまとめる**のがこのスクリプト。

- 冒頭CTA: 最初の <h1-4> の直前（note_early_cta_publish.transform_early と同一）
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
import sys
import time

from note_early_cta_publish import EARLY_MARK, transform_early
from note_internal_links_publish import (RELATED_MARK, build_catalog,
                                         find_insert_pos, make_transform,
                                         pick_related)
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


def needs(body):
    """(冒頭CTAが要るか, 関連記事が要るか)"""
    need_early = EARLY_MARK not in body
    need_rel = RELATED_MARK not in body and find_insert_pos(body) is not None
    return need_early, need_rel


def make_combined(need_early, rel_keys, catalog):
    """冒頭CTAと関連記事を1回の書き換えで両方入れる transform。"""
    rel_t = make_transform(rel_keys, catalog) if rel_keys else None

    def _t(key, html):
        out = html
        if need_early:
            r = transform_early(key, out)
            if r is not None:
                out = r
        if rel_t is not None:
            r = rel_t(key, out)
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
        marker = RELATED_MARK if need_rel else EARLY_MARK
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
