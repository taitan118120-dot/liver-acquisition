#!/usr/bin/env python3
"""#09「顔出しなしライバー」の公開記事から、収入目安の旧表記と旧特典PDF名を除去する（2026-07-29）。

#09（n79d526cf01a9）は**公開本文とローカルmdが別物**（公開側は短い箇条書き版、
ローカル `blog/articles_note/09_顔出しなしライバー.md` は長文版）。タイトルも一致しないため
`note_auto_poster.py --update 9` は候補ありスキップになり、`--accept-fuzzy` を付けると
記事が丸ごと別物に差し替わる。ユーザー判断で「公開側だけ外科的に修正」を選択したため、
note_facts_fix_20260722.py と同じ機構（Chrome cookie + Playwright + reCAPTCHA + PUT + tag復元）で
該当箇所だけ差し替える。

違反内容:
  ・「顔出しなしで月10万円以上」          → 看板コピーは月20万に統一 [[feedback_income_figures]]
  ・「初月: 月5〜10万円」「3ヶ月目: 月10〜20万円」→ 初月は数字を書かない／3ヶ月目は月15〜20万
  ・「事務所サポートで初月から月10万円も目指せる」→ 3ヶ月目の目安に置換
  ・特典PDF名『Pococha新人期スタートダッシュガイド』→『ライバー新人期スタートダッシュガイド』
    （2026-07-15の全アプリ対応改訂の取りこぼし。[[project_lead_magnet]]）
  ※「個人の場合 初月 月1〜2万円 / 3ヶ月目 月3〜5万円」はフリー対比の少額として意図的に維持する

使い方:
  python3 note_facts_fix_20260729.py --dry-run
  python3 note_facts_fix_20260729.py
"""
import sys

import note_facts_fix_20260722 as base

KEY = "n79d526cf01a9"

base.BODY_RULES[KEY] = [
    ("顔出しなしで月10万円以上稼いでいるライバーもたくさんいます。",
     "顔出しなしで月20万円以上稼いでいるライバーもたくさんいます。"),
    ("・初月: 月5〜10万円（Pocochaラジオ配信）<br>・3ヶ月目: 月10〜20万円",
     "・初月: 配信に慣れる時期（初日から収益が発生します）<br>"
     "・3ヶ月目: 月15〜20万円（Pocochaラジオ配信）<br>・6ヶ月目: 月30〜40万円"),
    ("・事務所サポートで初月から月10万円も目指せる",
     "・事務所サポートで3ヶ月目に月15〜20万円が目安"),
    ("『Pococha新人期スタートダッシュガイド』", "『ライバー新人期スタートダッシュガイド』"),
]
base.PARA_RULES.pop(KEY, None)
base.TITLE_RULES.pop(KEY, None)

# 公開後の自己検証。ここに引っかかる文字列が残っていたら失敗扱い
base.FORBIDDEN = [
    "初月: 月5〜10万円",
    "3ヶ月目: 月10〜20万円",
    "初月から月10万円",
    "顔出しなしで月10万円以上",
    "Pococha新人期スタートダッシュガイド",
]

if __name__ == "__main__":
    dry = "--dry-run" in sys.argv[1:]
    print(f"[fix {KEY}]")
    base.publish_one(KEY, dry_run=dry)
