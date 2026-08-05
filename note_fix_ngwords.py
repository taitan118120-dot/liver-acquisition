#!/usr/bin/env python3
"""NGワード残存記事の外科的修正。
① 「還元率100%（手数料なし）」→「還元率100%」  … 手数料なし/0円/ゼロは全媒体NG
② 「15分のオンライン無料相談から(で)大丈夫です。」→「まずはLINEで気軽にご相談ください。」

使い方:
  python3 note_fix_ngwords.py --fee <key> ...      # ①
  python3 note_fix_ngwords.py --consult <key> ...  # ②
"""
import re
import sys
import time

from note_leadmagnet_publish import publish_one

FEE_PAT = re.compile(r"[（(]手数料(なし|0円|ゼロ|無料)[)）]")


def transform_fee(key, html):
    if not FEE_PAT.search(html):
        return None
    out = FEE_PAT.sub("", html)
    if re.search(r"手数料(なし|0円|ゼロ|無料)", out):
        raise ValueError(f"括弧書き以外の手数料表現が残存 (key={key})")
    return out


CTA_OLD_A = "<strong>15分のオンライン無料相談</strong>から大丈夫です。"
CTA_OLD_B = "<strong>15分のオンライン無料相談</strong>からで大丈夫です。"
CTA_NEW = "<strong>まずはLINEで気軽に</strong>ご相談ください。"


def transform_consult(key, html):
    if "オンライン無料相談" not in html:
        return None
    out = html.replace(CTA_OLD_A, CTA_NEW).replace(CTA_OLD_B, CTA_NEW)
    if "オンライン無料相談" in out:
        # strongタグ無し等の変則パターンに対応
        out = re.sub(r"15分のオンライン無料相談から(で)?大丈夫です。",
                     "まずはLINEで気軽にご相談ください。", out)
    if "オンライン無料相談" in out:
        raise ValueError(f"オンライン無料相談が残存 (key={key})")
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2 or args[0] not in ("--fee", "--consult"):
        print(__doc__)
        raise SystemExit(1)
    fn = transform_fee if args[0] == "--fee" else transform_consult
    results = {}
    for i, k in enumerate(args[1:], 1):
        print(f"[{i}/{len(args)-1}] {k}")
        try:
            results[k] = publish_one(k, fn)
        except Exception as e:
            results[k] = f"fail: {e}"
            print(f"  [FAIL] {e}")
        time.sleep(8)
    print("\n=== 結果 ===")
    for k, v in results.items():
        print(f"  {k}: {v}")
