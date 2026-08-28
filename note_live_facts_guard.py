#!/usr/bin/env python3
"""note_live_facts_guard.py — 公開中のnote記事「本文そのもの」の確定ファクト番犬
==============================================================================
content_facts_guard.py との違いは、走査対象がローカル原稿ではなく
**note が実際に配信している本文**（公開API）だという1点だけ。判定の物差し
（禁止パターン＝facts_patterns.py、記事用WARN＝content_facts_guard）は共有する。

なぜ要るのか（2026-08-28 に実測した死角）:
  content_facts_guard は blog/articles_note/*.md しか読まない。ところが note 記事は
  **原稿を直しても note 側は変わらない**し、逆に **原稿を通さない書き換え**が
  日常的に走る:
    - note_cta_publish / note_leadmagnet_publish / note_boost_publish /
      note_internal_links_publish などが、公開本文を直接 fetch→PUT で書き換える
    - 過去の一括修正スクリプトも、公開側だけ直して原稿を放置したものがある
  結果、原稿と公開本文は両方向にズレる。実際 2026-08-28 に、代理店記事2本で
    - #25 ライバーマネージャー … 原稿は「リスナーさん」なのに公開本文は呼び捨てのまま
    - #42 スカウト術（代理店記事で最多PV）… 公開本文に「オンライン面談」「リスナー」
      「何百人」が残存
  が見つかった。どちらも content_facts_guard は**構造上ずっと緑**で、
  読者が読んでいる側だけが違反していた。

この番犬が見る3軸:
  1. 公開本文の禁止パターン — facts_patterns.common_violations を
     **タイトル＋本文**に当てる（タイトルも読者の目に触れる。実際
     「初見リスナーを常連化する」のような呼び捨てがタイトルに入っている）
  2. 原稿との乖離（drift） — 同じ違反がローカル原稿にも在るか。
     **公開側にだけ在る違反**が最重要で、これが content_facts_guard に映らない分。
     逆に「原稿にだけ在る」＝原稿を直したが note へ未反映、も報告する。
  3. 取得できない記事 — 公開キー台帳にあるのに公開APIが 4xx/5xx を返す、
     status が published でない、本文が空。台帳の腐りをここで拾う
     （キー台帳そのものの突合は note_keys_guard の担当。ここは配信側から見る）

判定ポリシー（content_facts_guard と同じ。番犬は鳴きやめるように作る）:
  - NG   = 記事用WARNに落ちない禁止パターン／取得失敗 → exit 1
  - WARN = AUDIT_WARN_LABELS | ARTICLE_WARN_LABELS。主語・文脈で可否が変わるので人が読む
  - 「自社と矛盾する判断軸」(CONTRACT_AXIS_LABEL) だけは記事でも赤のまま
    （content_facts_guard 側の assert と同じ理由。WARNの山に埋もれさせない）

認証は要らない。**ログアウト状態の公開API**を叩くので、読者に見えているものと
同じものを見る（cookie付きGETは下書き側を混ぜて返すことがあり、担保にならない）。
そのため CI でもそのまま動く。

使い方:
  python3 note_live_facts_guard.py                 # 全140本
  python3 note_live_facts_guard.py --limit 10      # 先頭10本だけ（動作確認用）
  python3 note_live_facts_guard.py <key> [<key>…]  # 個別指定
  python3 note_live_facts_guard.py --warn          # WARN を全件表示（既定は理由ごと3件）
  python3 note_live_facts_guard.py --drift-only    # 公開側にだけ在る違反だけ出す

レポートは data/note_live_facts_report.json に保存される。
"""

import glob
import json
import os
import re
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 物差しは共通正本から借りる。ここには禁止パターンのコピーを一切置かない
# （content_facts_guard の冒頭コメントと同じ理由。コピーは必ずどれかが古くなる）。
from content_facts_guard import ARTICLE_WARN_LABELS  # noqa: E402
from facts_patterns import (  # noqa: E402
    AUDIT_WARN_LABELS, CONTRACT_AXIS_LABEL, common_violations)

KEYS_FILE = os.path.join(BASE_DIR, "data", "published_note_keys.json")
KEYMAP_FILE = os.path.join(BASE_DIR, "data", "note_key_map.json")
REPORT_FILE = os.path.join(BASE_DIR, "data", "note_live_facts_report.json")
ARTICLE_DIR = os.path.join(BASE_DIR, "blog", "articles_note")

PUBLIC_API = "https://note.com/api/v3/notes/{key}"
# 公開APIはCDN越しなので、no-cache を付けないと直した直後でも旧本文が返る。
PUBLIC_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "application/json",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
SLEEP = 0.3          # note への負荷を作らない。140本で約1分
RETRY = 3

WARN_LABELS = AUDIT_WARN_LABELS | ARTICLE_WARN_LABELS
# content_facts_guard と同じ不変条件。判断軸の矛盾をWARNに落とすと、
# 「記事が自分を撃つ」形が数十件のWARNに埋もれて誰も気づけなくなる。
assert CONTRACT_AXIS_LABEL not in WARN_LABELS, (
    f"{CONTRACT_AXIS_LABEL} はWARNに落としてはいけない（赤のまま出す）")


def fetch(key):
    """ログアウト状態の公開API。(data, error) を返す。"""
    last = None
    for attempt in range(RETRY):
        try:
            r = requests.get(PUBLIC_API.format(key=key), headers=PUBLIC_HEADERS, timeout=30)
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"[:120]
        else:
            if r.status_code == 200:
                try:
                    return r.json()["data"], None
                except (ValueError, KeyError) as e:
                    last = f"JSONとして読めない: {type(e).__name__}: {e}"[:120]
            else:
                last = f"HTTP {r.status_code}"
                if r.status_code in (404, 410):
                    break  # 消えた記事にリトライしても意味がない
        time.sleep(1 + attempt)
    return None, last


def load_keys():
    with open(KEYS_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_keymap():
    """key -> {"num": 記事番号, "title": …, "md": ローカル原稿のパス or None}"""
    out = {}
    try:
        with open(KEYMAP_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return out
    for num, rec in raw.items():
        key = rec.get("key")
        if not key:
            continue
        hits = glob.glob(os.path.join(ARTICLE_DIR, f"{num}_*.md"))
        out[key] = {"num": num, "title": rec.get("title", ""),
                    "md": os.path.relpath(hits[0], BASE_DIR) if hits else None}
    return out


def local_labels(md_rel):
    """ローカル原稿で検出される違反ラベルの集合。drift 判定にだけ使う。"""
    if not md_rel:
        return None
    try:
        text = open(os.path.join(BASE_DIR, md_rel), encoding="utf-8").read()
    except OSError:
        return None
    return {reason for reason, _ in common_violations(text)}


def scan_one(key, meta):
    """1本ぶんの (violations, warns, error) を返す。"""
    d, err = fetch(key)
    label = f"{meta.get('num', '?')} {meta.get('title', '')[:34]}"
    where = f"note:{key}（#{label}）"
    if err:
        return [{"where": where, "reason": f"公開記事を取得できない（{err}）。"
                                           f"削除・非公開・キー台帳の腐りのいずれか",
                 "hit": PUBLIC_API.format(key=key), "drift": None}], [], err

    status = d.get("status")
    body = d.get("body") or ""
    title = d.get("name") or ""
    if status != "published":
        return [{"where": where, "reason": f"公開キー台帳にあるのに status={status}",
                 "hit": title[:60], "drift": None}], [], None
    if not body.strip():
        return [{"where": where, "reason": "公開本文が空",
                 "hit": title[:60], "drift": None}], [], None

    # タイトルも読者に見える文面なので一緒に当てる。
    text = title + "\n" + body
    local = local_labels(meta.get("md"))

    ng, warn = [], []
    for reason, hit in common_violations(text):
        # drift: True=公開側にだけ在る（原稿を直したが note 未反映 or 公開側だけ改変）
        #        False=原稿にも在る（content_facts_guard 側でも見えている）
        #        None=原稿が特定できず判定不能
        drift = None if local is None else (reason not in local)
        item = {"where": where, "reason": reason, "hit": hit[:80],
                "drift": drift, "md": meta.get("md")}
        (warn if reason in WARN_LABELS else ng).append(item)
    return ng, warn, None


def main():
    argv = sys.argv[1:]
    show_all_warns = "--warn" in argv
    drift_only = "--drift-only" in argv
    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    explicit = [a for a in argv if a.startswith("n") and not a.startswith("--")]

    keymap = load_keymap()
    keys = explicit or load_keys()
    if limit:
        keys = keys[:limit]

    violations, warns, failed = [], [], []
    for i, key in enumerate(keys, 1):
        ng, wn, err = scan_one(key, keymap.get(key, {}))
        violations += ng
        warns += wn
        if err:
            failed.append(key)
        if i % 20 == 0:
            print(f"  … {i}/{len(keys)} 走査")
        time.sleep(SLEEP)

    if drift_only:
        violations = [v for v in violations if v.get("drift")]
        warns = [w for w in warns if w.get("drift")]

    drift_ng = [v for v in violations if v.get("drift")]
    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump({"scanned": len(keys), "fetch_failed": failed,
                   "violations": violations, "warn": warns,
                   "drift_violations": drift_ng},
                  f, ensure_ascii=False, indent=1)

    print(f"\n[走査] 公開記事 {len(keys)} 本（ログアウト状態の公開API）")
    print(f"[結果] 違反={len(violations)}（うち公開側にだけ在る={len(drift_ng)}） "
          f"警告(判断保留)={len(warns)} → {os.path.relpath(REPORT_FILE, BASE_DIR)}")

    for v in violations:
        mark = {True: "【原稿には無い＝公開側だけ】", False: "", None: "【原稿不明】"}[v.get("drift")]
        print(f"  ❌ {v['where']}: {v['reason']} {mark}")
        if v["hit"]:
            print(f"     → {v['hit']}")

    by_reason = {}
    for w in warns:
        by_reason.setdefault(w["reason"], []).append(w)
    for reason, items in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        d = sum(1 for x in items if x.get("drift"))
        print(f"  ⚠️ [{len(items)}件{f'／うち公開側だけ {d}件' if d else ''}] {reason}")
        for w in (items if show_all_warns else items[:3]):
            print(f"       - {w['where']}: {w['hit']}")
        if not show_all_warns and len(items) > 3:
            print(f"       …ほか {len(items) - 3} 件（--warn で全件表示）")

    if violations:
        return 1
    print("\n公開中のnote記事本文に確定ファクト違反なし ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
