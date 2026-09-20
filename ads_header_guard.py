#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ads/google_ads_設計書.md の冒頭「最終更新」ヘッダーが、本文の最新節に追いついているかを見る番犬。

背景（2026-09-20）:
  本書3行目の `作成日：… / **最終更新：…** / 前回：… / 前回：…` は
  「冒頭だけ読めば最新状況が分かる」ことを意図した要約で、その先の5,000行は履歴として読む前提。
  ところがヘッダーは **§0-37（2026-09-06）で止まったまま §0-38〜§0-47 の10節ぶん更新されず**、
  「ポリシー制限は A1・A2・A5 の3本＝キャンペーンAだけ」と言い続けていた。
  実測（§0-46）は **広告9本・摘発アセット31件・3キャンペーン全部** で、
  冒頭だけ読んだ人／セッションは規模を1/3以下に見誤る。日予算も同様に
  §0-17 の ¥5,200/日 のままで、実値（§0-45）の ¥3,120/日 とズレていた。

動作:
  - 本文の `## 0-NN` の最大値（`## 0-A` は操作リファレンスなので対象外）
  - ヘッダーの `最終更新：` ブロック（先頭から最初の ` / 前回：` まで）が言及する `§0-NN` の最大値
  この2つが一致しなければ赤。通信は一切しない（ローカルのファイルを読むだけ）。

⚠️ 見ているのは**番号だけ**。番号だけ書き換えて中身を更新しなければ素通りする。
   中身の責任は設計書 §0-A A-10 の表のほう。ここは「更新し忘れ」だけを捕まえる。

使い方:
  python3 ads_header_guard.py             # 人が読む形で出力
  python3 ads_header_guard.py --json      # data/ads_header_guard_report.json を書く（CI用）
  python3 ads_header_guard.py --self-test # 通信なしで検知器そのものを自己診断
終了コード: 0=一致 / 1=ズレている・読めない
"""

import argparse
import io
import json
import os
import re
import sys

DOC = "ads/google_ads_設計書.md"
REPORT = "data/ads_header_guard_report.json"

# 本文の節見出し。`## 0-A.`（操作リファレンス）は番号でないので拾わない。
RE_SECTION = re.compile(r"^##\s*0-(\d+)\.", re.M)
# ヘッダー内の節参照。`§0-46 ⑦` のような後続文字は見ない。
RE_REF = re.compile(r"§\s*0-(\d+)")
# ヘッダー行の見つけ方と、「最終更新」ブロックの終端。
RE_HEADER_LINE = re.compile(r"^作成日：.*最終更新：", re.M)
RE_LATEST_END = re.compile(r"\s/\s*前回：")


def analyze(text):
    """設計書の本文から {ok, body_max, header_max, ...} を返す。例外は投げない。"""
    out = {
        "ok": False,
        "body_max": None,
        "header_max": None,
        "header_refs": [],
        "missing": [],
        "unknown": [],
        "error": None,
    }

    sections = sorted({int(n) for n in RE_SECTION.findall(text)})
    if not sections:
        out["error"] = "本文に `## 0-NN` の節が1つも見つからない（見出しの書式が変わった可能性）"
        return out
    out["body_max"] = sections[-1]

    m = RE_HEADER_LINE.search(text)
    if not m:
        out["error"] = "`作成日：… 最終更新：…` のヘッダー行が見つからない（3行目の書式が変わった可能性）"
        return out

    line = text[m.start():].split("\n", 1)[0]
    # 「最終更新」ブロック＝ヘッダー行の先頭から、最初の ` / 前回：` の手前まで。
    # `前回：` が無い（チェーンがまだ1件）場合は行末までを見る。
    end = RE_LATEST_END.search(line, m.end() - m.start())
    latest = line[: end.start()] if end else line

    refs = sorted({int(n) for n in RE_REF.findall(latest)})
    out["header_refs"] = refs
    if not refs:
        out["error"] = "「最終更新」ブロックに `§0-NN` の節参照が1つも無い（末尾に更新した節番号を書くこと）"
        return out
    out["header_max"] = refs[-1]

    # ヘッダーが実在しない節を指している（採番ミス・タイポ）。
    out["unknown"] = [n for n in refs if n not in sections]
    # ヘッダーが触れていない新しい節。
    out["missing"] = [n for n in sections if n > out["header_max"]]

    out["ok"] = (out["header_max"] == out["body_max"]) and not out["unknown"]
    return out


def _self_test():
    """検知器が「何も見つけられないまま緑」になっていないことを、通信なしで確かめる。"""
    head = "# t\n\n作成日：2026-07-20 / **最終更新：2026-09-20（要約。§0-45〜§0-47**）** / 前回：2026-09-06（古い要約。§0-37**）**\n\n"
    body = "".join("## 0-%d. dummy\n\n本文で §0-99 に言及しても本文側は見ない。\n\n" % i for i in range(1, 48))

    cases = [
        ("一致すれば緑", head + body, True, None),
        (
            "本文が先に進んだら赤",
            head + body + "## 0-48. new\n",
            False,
            lambda r: r["missing"] == [48] and r["body_max"] == 48 and r["header_max"] == 47,
        ),
        (
            "ヘッダーが古いまま（実際に起きた形）",
            "# t\n\n作成日：x / **最終更新：2026-09-06（§0-37**）**\n\n" + body,
            False,
            lambda r: r["header_max"] == 37 and r["missing"] == list(range(38, 48)),
        ),
        (
            "前回：チェーンの古い番号は最新扱いしない",
            "# t\n\n作成日：x / **最終更新：2026-09-06（§0-37**）** / 前回：z（§0-47**）**\n\n" + body,
            False,
            lambda r: r["header_max"] == 37,
        ),
        (
            "実在しない節を指したら赤",
            "# t\n\n作成日：x / **最終更新：t（§0-48**）**\n\n" + body,
            False,
            lambda r: r["unknown"] == [48],
        ),
        ("ヘッダー行が無ければ赤", body, False, lambda r: "ヘッダー行" in (r["error"] or "")),
        (
            "節が無ければ赤",
            head,
            False,
            lambda r: "節が1つも" in (r["error"] or ""),
        ),
        (
            "節参照が無ければ赤",
            "# t\n\n作成日：x / **最終更新：2026-09-20（番号を書き忘れた要約）**\n\n" + body,
            False,
            lambda r: "節参照が1つも" in (r["error"] or ""),
        ),
    ]

    failed = 0
    for name, text, want_ok, extra in cases:
        got = analyze(text)
        bad = got["ok"] != want_ok or (extra is not None and not extra(got))
        print("%s %s" % ("NG" if bad else "ok", name))
        if bad:
            print("   -> %s" % json.dumps(got, ensure_ascii=False))
            failed += 1

    # 本物の設計書でも例外なく走り切ること（結果の合否は問わない）。
    if os.path.exists(DOC):
        real = analyze(io.open(DOC, encoding="utf-8").read())
        if real["body_max"] is None:
            print("NG 実ファイルで節を1つも拾えなかった")
            failed += 1
        else:
            print("ok 実ファイルを解析できた（本文最大 §0-%s）" % real["body_max"])

    print("\n自己診断: %d件失敗" % failed)
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="data/ に JSON レポートを書く（CI用）")
    ap.add_argument("--self-test", action="store_true", help="通信なしで検知器を自己診断する")
    args = ap.parse_args()

    if args.self_test:
        return _self_test()

    if not os.path.exists(DOC):
        print("NG %s が無い" % DOC)
        return 1

    r = analyze(io.open(DOC, encoding="utf-8").read())

    if args.json:
        os.makedirs(os.path.dirname(REPORT), exist_ok=True)
        io.open(REPORT, "w", encoding="utf-8").write(
            json.dumps(r, ensure_ascii=False, indent=2) + "\n"
        )

    if r["error"]:
        print("NG %s" % r["error"])
        return 1

    if r["ok"]:
        print("ok ヘッダーは本文の最新節 §0-%d に追いついています（ヘッダー参照: %s）"
              % (r["body_max"], ", ".join("§0-%d" % n for n in r["header_refs"])))
        return 0

    if r["unknown"]:
        print("NG ヘッダーが実在しない節を指しています: %s（本文の最大は §0-%d）"
              % (", ".join("§0-%d" % n for n in r["unknown"]), r["body_max"]))
    if r["missing"]:
        print("NG ヘッダーは §0-%d 止まりで、本文の §0-%d まで %d節ぶん反映されていません: %s"
              % (r["header_max"], r["body_max"], len(r["missing"]),
                 ", ".join("§0-%d" % n for n in r["missing"])))
    return 1


if __name__ == "__main__":
    sys.exit(main())
