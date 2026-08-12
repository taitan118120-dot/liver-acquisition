#!/usr/bin/env python3
"""公開済みnote記事から「何千（人）」の実績誇張を外科的に除去する（2026-08-12）。

きっかけ: facts_patterns.py の「根拠なしの実績誇張」パターンは
`数百人|何百人|数千` だけを見ていて、**桁の大きい「何千人」が素通りしていた**。
パターンに「何千」を足した結果、公開中の2記事が新たにヒットした。

  ・#57 n576132a999ab 「何千人ものライバーを見てきた」
      → 所属200名 [[project_taitan_pro_note_facts]]・実稼働は一部という実態と桁が合わない。
        数字を出さず、確定ファクト（Pococha歴4年・事務所運営）だけで言い換える。
  ・#91 n06891851e621 「世界中の何千もの会社にまとめて少額から投資できる」
      → 全世界株インデックスの一般解説であって TAITAN PRO の実績主張ではない＝誤爆。
        ただし語そのものが検品に引っかかり続けるので、意味を変えずに言い換える。

機構は note_exitclaim_fix.py と同じ（Chrome cookie + Playwright + reCAPTCHA + PUT）。
PUTでタグが消えるため、publish_one 側で ensure_tags による復元が走る。

使い方:
  python3 note_kazensen_fix_20260812.py --dry-run
  python3 note_kazensen_fix_20260812.py
"""
import re
import sys

from note_cta_publish import get_note, req_session
from note_leadmagnet_publish import publish_one

# key -> [(旧, 新), ...]
RULES = {
    # #57 ライバーデビュー準備
    "n576132a999ab": [
        ("そして何千人ものライバーを見てきた中で気づいた",
         "そしてPococha歴4年と事務所運営を通じて見てきたライバーたちの姿から気づいた"),
    ],
    # #91 ライバーNISA全世界株資産運用
    "n06891851e621": [
        ("世界中の何千もの会社にまとめて少額から投資できる",
         "世界中の幅広い企業にまとめて少額から投資できる"),
    ],
}

# 変換後に残っていたら異常とみなすパターン（facts_patterns の実績誇張と同じ語）
BANNED = re.compile(r"何千|数千人|何百人|数百人")


def transform(key, html):
    new = html
    for old, rep in RULES.get(key, []):
        new = new.replace(old, rep)
    if new == html:
        return None  # 変更なし＝済み
    left = BANNED.findall(re.sub(r"<[^>]+>", "", new))
    if left:
        raise ValueError(f"未処理の禁止表現が残存 (key={key}): {sorted(set(left))}")
    return new


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    keys = [a for a in args if not a.startswith("--")] or list(RULES)
    s = req_session()
    fails = []
    for i, key in enumerate(keys, 1):
        d = get_note(s, key, draft=False)
        print(f"[{i}/{len(keys)}] {key} {d['name'][:44]}")
        try:
            new = transform(key, d["body"])
        except ValueError as e:
            print(f"  !! {e}")
            fails.append(key)
            continue
        if new is None:
            print("  skip（該当表現なし＝対応済み）")
            continue
        print(f"  変換OK: {len(d['body'])} -> {len(new)} bytes")
        if dry:
            continue
        try:
            publish_one(key, transform_fn=transform,
                        expect_marker=RULES[key][0][1][:24])
        except Exception as e:
            print(f"  !! PUT失敗: {e}")
            fails.append(key)
    if fails:
        print(f"\n要対応: {fails}")
        return 1
    print("\n全件OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
