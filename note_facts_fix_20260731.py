#!/usr/bin/env python3
"""#05「ライバーの収入はぶっちゃけいくら？」に残っていた出典なし収入レンジを定性表現に置換する（2026-07-31）。

2026-07-30 の全数監査（note_facts_fix_20260730.py）では、業界全体の収入分布%と
トップ層「月50万〜600万円以上」だけを除去し、プラットフォーム別レンジは
ユーザー判断待ちとして保留していた。2026-07-31 にユーザーが「定性表現に置換」を選択。

対象（公開・ローカルmd 両方）:
  ・17LIVE節  初心者 月0〜3万円 / 中堅 月5〜20万円 / 上位 月30万〜100万円以上
              ＋「トップライバーの中には年収1000万円を超える人もいます」
  ・IRIAM節   初心者 月0〜2万円 / 中堅 月3〜10万円 / 上位 月15万〜50万円
  ・要因1     週1〜2回 月0〜1万円 / 週3〜4回 月1〜5万円 / 週5〜6回 月5〜15万円
              （「毎日配信: 月20万円以上」は確定ファクトのB帯20〜30万と整合するため数字を残す）

いずれも出典・帰属のない数字で、かつ少額表記が [[feedback_income_figures]] に抵触する。
17LIVE は確定ファクトが未確立のため、置換文でも収入実績を一切書かない。

機構は note_facts_fix_20260730.py と同じ（本文HTMLで引き当てるブロック置換）。

使い方:
  python3 note_facts_fix_20260731.py --dry-run
  python3 note_facts_fix_20260731.py
"""
import sys

import note_facts_fix_20260722 as base
from note_facts_fix_20260730 import replace_block

KEY = "n80a29386b5a8"

# (旧inner, 新inner)  新inner が None ならブロックごと削除
BLOCKS = [
    # ── 17LIVE：階層別レンジ3行 → 定性2文 ──
    ("・初心者: <strong>月0〜3万円</strong>",
     "そのぶん<strong>収入の振れ幅が大きい</strong>のが実情です。"
     "始めたばかりの時期はほとんど伸びないことも珍しくない一方、"
     "イベントで結果を出せたときの跳ね方は大きくなります。"),
    ("・中堅: <strong>月5〜20万円</strong>", None),
    ("・上位: <strong>月30万</strong>〜100万円以上", None),
    ("トップライバーの中には年収1000万円を超える人もいます。",
     "裏を返すと、<strong>イベントの結果に収入が左右されやすい</strong>ということ。"
     "月ごとの波を小さくしたいなら、時間ダイヤで土台をつくれるPocochaと"
     "組み合わせるのが現実的です。"),

    # ── IRIAM：階層別レンジ3行 → 定性1文 ──
    ("・初心者: <strong>月0〜2万円</strong>",
     "ギフトが収入の中心になるため、<strong>ファンがつくまでは時間がかかりやすい</strong>のが実情です。"
     "逆に固定ファンが定着すれば、顔出しなしでも収入は積み上がっていきます。"),
    ("・中堅: <strong>月3〜10万円</strong>", None),
    ("・上位: <strong>月15万</strong>〜50万円", None),

    # ── 要因1 配信頻度：少額レンジ → 定性（最終行の月20万円は確定ファクト側と整合するため維持）──
    ("・週1〜2回の配信: <strong>月0〜1万円</strong>",
     "・週1〜2回の配信: 収入として実感できるところまでは届きにくい"),
    ("・週3〜4回の配信: <strong>月1〜5万円</strong>",
     "・週3〜4回の配信: 少しずつ手応えが出てくる"),
    ("・週5〜6回の配信: <strong>月5〜15万円</strong>",
     "・週5〜6回の配信: <strong>収入が積み上がり始める</strong>"),
    ("・毎日配信: <strong>月20万円</strong>以上を目指せる",
     "・毎日配信: <strong>月20万円</strong>以上が射程に入ってくる"),
]

FORBIDDEN = [
    "月0〜3万円", "月5〜20万円", "月30万</strong>〜100万円以上", "年収1000万円",
    "月0〜2万円", "月3〜10万円", "月15万</strong>〜50万円",
    "月0〜1万円", "月1〜5万円", "月5〜15万円", "以上を目指せる",
]


def transform(key, html):
    out = html
    for old_inner, new_inner in BLOCKS:
        out = replace_block(out, old_inner, new_inner)
    return out


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv[1:]
    base.transform = transform
    base.TITLE_RULES = {}
    base.FORBIDDEN = FORBIDDEN
    print(f"[fix {KEY}] #5 収入の現実（プラットフォーム別レンジ→定性表現）")
    print(base.publish_one(KEY, dry_run=dry))
