#!/usr/bin/env python3
"""公開Noteに残っていた旧特典PDF名『Pococha新人期スタートダッシュガイド』を
『ライバー新人期スタートダッシュガイド』へ差し替える（2026-07-29）。

2026-07-15の全アプリ対応改訂（[[project_lead_magnet]]）の取りこぼし。
公開112本を走査した結果、旧名が残っていたのは7本。うち5本は
`blog/articles_note/{16,32,35,63,71}_*.md` があるので `--update` で反映済み。

本スクリプトが扱うのは **ローカルmdが存在しない2本**：
  nd29c18b06dcc 【2026年最新】Pococha新人期間 完全攻略        旧名2箇所
  ne28bee508ca1 ライバー事務所の代理店とは？                    旧名1箇所

`--update` は本文を丸ごとローカルmdで置き換えるため、対応するmdが無い記事には使えない
（#09 で判明した「ローカルと公開が別物」問題の再来を避ける）。そこで
note_facts_fix_20260722.py と同じ外科的置換（Chrome cookie + Playwright + PUT + tag復元）で
該当文字列だけを差し替える。

なお nd29c18b06dcc には「リスナー」呼び捨てが21箇所あるが、本件のスコープ外なので
base.fix_listener_honorific は無効化して**旧PDF名だけ**を触る。

使い方:
  python3 note_leadmagnet_rename_20260729.py --dry-run
  python3 note_leadmagnet_rename_20260729.py
"""
import sys

import note_facts_fix_20260722 as base

OLD = "『Pococha新人期スタートダッシュガイド』"
NEW = "『ライバー新人期スタートダッシュガイド』"

KEYS = ["nd29c18b06dcc", "ne28bee508ca1"]

for _k in KEYS:
    base.BODY_RULES[_k] = [(OLD, NEW)]
    base.PARA_RULES.pop(_k, None)
    base.TITLE_RULES.pop(_k, None)

# 今回は旧PDF名の差し替えだけが目的。呼び捨て修正は別件なので触らない
base.fix_listener_honorific = lambda html: html

# 公開後の自己検証
base.FORBIDDEN = ["Pococha新人期スタートダッシュガイド"]

if __name__ == "__main__":
    args = sys.argv[1:]
    dry = "--dry-run" in args
    keys = [a for a in args if not a.startswith("--")] or KEYS
    for k in keys:
        print(f"[rename {k}]")
        base.publish_one(k, dry_run=dry)
