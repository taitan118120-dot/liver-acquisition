#!/usr/bin/env python3
"""公開中のnote記事から「出典のない市場規模の金額」を落とす（2026-09-04）。

■ 何が起きていたか
  #23「ライブ配信市場の将来性」（全期間PV 240＝8位）が、同じ記事の中で

    ネット上には「アプリ別の平均月収」を並べた表が多く出回っていますが、
    **集計元も対象人数も書かれていないものがほとんど**です。

  と書きながら、自分の市場規模だけは出典なしで断定していた:
    - 国内は2026年に約1,500億円／2020年の約500億円から3倍
    - グローバルは約7兆円／日本は世界で3番目
  ユーザーに確認したところ **裏取りの出典は無い**（2026-09-04）。
  [[feedback_dont_make_up_numbers]] に照らして金額の断定をやめ、
  「なぜ伸びているか」（5G・投げ銭文化・企業のライブコマース参入）という
  構造の説明だけを残す。

■ 直す範囲は1本ではない
  同じ数字を grep で追うと、公開記事3本に散っていた:
    #23 ncb75e31303b6  本文2箇所 ＋ **GEOブロック3箇所**
    #22 na08ce1921eb6  本文1箇所（「日本国内だけで約1,500億円規模」）
    #69 n1b4784640d76  FAQ 1箇所（「2030年に2,000億円規模になると言われており」）

  #23 の3箇所は 2026-09-04 の note_geo_retrofit.py が後付けした
  「📌 この記事の要点」「❓ よくある質問」。あれは**本文にある数字しか使わない**
  作りなので、本文の捏造をそのまま3箇所に増幅していた。本文だけ直すと
  要点とFAQに古い数字が残る（＝AIに読ませる用の要約だけが嘘になる）。

■ 番犬の穴も塞いだ
  facts_patterns の「根拠のない市場規模・成長率」は **%表記しか見ていなかった**
  （2026-08-11にXのキュー「市場規模は毎年130%以上成長」を潰した時の形のまま）。
  だから億円・兆円・世界N位は毎日の content_facts_guard を素通りしていた。
  同じコミットで金額・順位も見るようにしている。

使い方:
  python3 note_marketsize_fix_20260904.py --dry-run   # 置換結果を出す（GETのみ）
  python3 note_marketsize_fix_20260904.py --bodies    # 公開本文を直す
  python3 note_marketsize_fix_20260904.py --verify    # 公開API（非ログイン）で確認
"""
import json
import os
import re
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

BACKUP_DIR = os.path.join(BASE_DIR, "data", "note_body_backup")
LOG_FILE = os.path.join(BASE_DIR, "data", "note_marketsize_fix_log.json")

# 検証は**ログアウト状態の公開API**で見る（cookie付きGETは下書き側を混ぜて返す）。
PUBLIC_API = "https://note.com/api/v3/notes/{key}"
PUBLIC_HEADERS = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache",
                  "Pragma": "no-cache"}

# note は保存のたびに段落へ name/id を振り直し、強調は <strong> と ** で揺れる。
# 固定文字列で書くと必ず外れるので、強調タグの入りうる位置は TAG で吸収する。
TAG = r"(?:</?[a-zA-Z][^>]*>|\*\*)*"


def _rx(*parts):
    return re.compile("".join(parts))


RULES = {
    # ── #23 ライブ配信市場の将来性 ──────────────────────────
    "ncb75e31303b6": [
        # 本文: 国内市場規模（金額の断定 → 伸びの理由だけ）
        (_rx(r"日本のライブ配信市場は、", TAG, r"2026年に約1,500億円規模", TAG,
             r"に到達。2020年の約500億円から3倍に成長しています。"),
         "市場規模の金額はメディアによって数字がばらばらで、集計の範囲も書かれて"
         "いないものがほとんどです。ここでは金額ではなく、"
         "<strong>何が伸びを支えているのか</strong>を見ます。"),
        # 見出しは金額を出す前提の名前だったので合わせて変える
        (_rx(r"■ 国内市場規模"), "■ 国内市場が伸びている理由"),
        (_rx(r"■ 世界市場"), "■ 海外との違い"),
        (_rx(r"グローバルでは", TAG, r"約7兆円規模", TAG,
             r"。中国が最大市場ですが、日本市場は世界で3番目の規模を持ち、"
             r"成長余地はまだ大きいとされています。"),
         "ライブコマース（配信しながら商品を売る形）は海外で先に広がり、日本は"
         "これから本格化する段階です。市場規模の金額や国別の順位は、出所のはっきり"
         "した数字が見つからないため、この記事では扱いません。"),
        # GEOブロック①: 要点の定義文
        (_rx(r"ライブ配信市場の将来性とは、国内市場が2026年に約1,500億円規模へ拡大した"
             r"成長フェーズにあり、今から参入しても間に合う状況のことです。"),
         "ライブ配信市場の将来性とは、5G通信の普及・投げ銭文化の定着・企業の"
         "ライブコマース参入に支えられて市場が広がり、今から参入しても間に合う"
         "状況のことです。"),
        # GEOブロック②: 要点の1つめの箇条書き
        (_rx(r"国内市場は2020年の約500億円から2026年に約1,500億円へ。"
             r"世界では約7兆円規模で、日本は世界で3番目の市場です"),
         "伸びを支えているのは5G通信の普及・投げ銭文化の定着・企業の"
         "ライブコマース参入の3つです"),
        # GEOブロック③: FAQ の1問目
        (_rx(r"遅くありません。国内市場は2020年の約500億円から2026年に約1,500億円規模へ"
             r"拡大していて、市場の伸びにライバーの供給が追いついていない状態です。"),
         "遅くありません。5Gの普及や企業のライブコマース参入で市場が広がる一方、"
         "ライバーの供給が追いついていない状態です。"),
    ],
    # ── #22 30代からライバーを始めても遅くない？ ─────────────
    # この段落は節の枕でしかなく、次の「かつては10代〜20代前半が中心でしたが、
    # 今は状況が大きく変わっています。」が同じ話を数字なしで言っている。
    # 言い換えると新しい未検証の主張を足すことになるので段落ごと落とす。
    "na08ce1921eb6": [
        (_rx(r"<p[^>]*>ライブ配信市場は2026年現在、", TAG,
             r"日本国内だけで約1,500億円規模", TAG,
             r"に成長しています。</p>\s*<p[^>]*><br></p>"),
         ""),
    ],
    # ── #69 ライバーを始める前に知るべき10のこと ──────────────
    "n1b4784640d76": [
        (_rx(r"。ライブ配信市場は2030年に2,000億円規模になると言われており、"
             r"今がまさに成長期。"),
         "。ただし「市場規模◯◯億円」という数字はネット上に出所の書かれていない"
         "ものが多いので、ここでは金額は出しません。5Gの普及や企業のライブコマース"
         "参入で配信の裾野は広がっていて、"),
        # 上の置換後に残る「間違いなくあります」は断定が強すぎる（根拠を落としたので
        # なおさら）。強調タグの中身だけ差し替える。
        (_rx(r"間違いなくあります"), "あります"),
    ],
}

# 反映確認に使う「もう本文に出てはいけない」文字列。
LEFTOVERS = ["1,500億", "500億円", "7兆円", "世界で3番目", "2,000億円"]


def fetch_public(key):
    r = requests.get(PUBLIC_API.format(key=key), headers=PUBLIC_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()["data"]


def transform(key, html):
    """RULES を順に当てる。1つも当たらなければ None（＝publish_one が skip する）。"""
    if html is None:
        return None
    out, hit = html, 0
    for rx, repl in RULES[key]:
        out, n = rx.subn(repl, out)
        hit += n
    return out if hit else None


def rule_hits(key, html):
    return [(rx.pattern[:40], len(rx.findall(html))) for rx, _ in RULES[key]]


def leftovers(text):
    return [w for w in LEFTOVERS if w in text]


def _load(path):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except Exception:
            pass
    return {}


def backup(key, note, tag="pre_marketsize_20260904"):
    """PUT前の本文を退避する。

    note_geo_structure.backup は `<key>.json` を**最初の1回しか**書かない
    （変換後で上書きしないため）。#23 は既に GEO 後付け前のスナップショットで
    埋まっているので、今回の直前状態は別名で残す。
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"{key}.{tag}.json")
    if not os.path.exists(path):
        json.dump({"key": key, "title": note["name"], "body": note["body"],
                   "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                  open(path, "w"), ensure_ascii=False, indent=1)
    return path


def dry_run():
    for key in RULES:
        d = fetch_public(key)
        body = d["body"]
        new = transform(key, body)
        print(f"\n=== {key} {d['name'][:40]}")
        for pat, n in rule_hits(key, body):
            mark = "OK " if n else "MISS"
            print(f"  [{mark}] x{n}  {pat}")
        print(f"  body {len(body)} -> {len(new) if new else '(変更なし)'}")
        print(f"  残存: {leftovers(new if new else body) or 'なし'}")


def publish(key):
    from note_leadmagnet_publish import publish_one

    d = fetch_public(key)
    print(f"  backup: {os.path.relpath(backup(key, d), BASE_DIR)}")
    r = publish_one(key, transform, expect_marker=None)
    if r == "skip":
        print("  変更なし（既に修正済み）")
        return r
    # publish_one の verify は cookie 付きGET。読者が見るのはログアウト側。
    for attempt in range(4):
        time.sleep(6)
        dv = fetch_public(key)
        left = leftovers(dv["body"])
        tags = len(dv.get("hashtag_notes", []))
        print(f"  [公開API {attempt + 1}] 残存={left or 'なし'} tags={tags} "
              f"eyecatch={'OK' if dv.get('eyecatch') else 'MISSING!'}")
        if not left:
            if tags == 0:
                raise RuntimeError("タグが0のまま（note_tag_guard.ensure_tags 要確認）")
            return r
    raise RuntimeError(f"公開APIで確認できない（残={left}）")


def verify():
    bad = 0
    for key in RULES:
        d = fetch_public(key)
        left = leftovers(d["body"])
        tags = len(d.get("hashtag_notes", []))
        state = "OK" if not left else f"NG {left}"
        print(f"  {key} {state}  tags={tags} "
              f"eyecatch={'OK' if d.get('eyecatch') else 'MISSING!'} "
              f"{d['name'][:30]}")
        bad += bool(left)
    print(f"\n違反が残っている記事: {bad} 本")
    return bad


def main():
    args = sys.argv[1:]
    if "--verify" in args:
        sys.exit(1 if verify() else 0)
    if "--bodies" in args or [a for a in args if a.startswith("n")]:
        keys = [a for a in args if a.startswith("n") and not a.startswith("--")] \
            or list(RULES)
        log = _load(LOG_FILE)
        for i, key in enumerate(keys):
            print(f"\n=== [{i + 1}/{len(keys)}] {key}")
            try:
                log[key] = publish(key)
            except Exception as e:
                log[key] = f"error: {type(e).__name__}: {e}"
                print(f"  !! {log[key]}")
            json.dump(log, open(LOG_FILE, "w"), ensure_ascii=False, indent=1)
            time.sleep(3)
        print("\n", json.dumps(log, ensure_ascii=False, indent=1))
        return
    dry_run()


if __name__ == "__main__":
    main()
