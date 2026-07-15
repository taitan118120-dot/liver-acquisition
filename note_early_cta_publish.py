#!/usr/bin/env python3
"""PV上位の公開済みnote記事に「冒頭寄り」の特典PDF CTAを挿入する。

末尾CTA（note_leadmagnet_publish.py）は全記事適用済みだが、読了率を考えると
上位記事は最初の見出しの手前（＝導入の直後）にも軽いCTAを置いたほうが転換する。

- 挿入位置: 本文で最初に現れる <h1-4> 見出しの直前
- 冪等: 「先に特典だけ受け取る」が既にあればスキップ
- 機構は note_leadmagnet_publish.publish_one をそのまま使う（検証・タグ復元込み）

使い方:
  python3 note_early_cta_publish.py <key> [<key> ...]
"""
import re
import sys

from note_leadmagnet_publish import publish_one, verify

EARLY_MARK = "先に特典だけ受け取る"
EARLY_HTML = (
    "<p>🎁 <strong>先に特典だけ受け取るのもOK</strong>：配信の最初の30日でやることを"
    "全部まとめた非売品PDF『ライバー新人期スタートダッシュガイド』を、"
    '<a href="https://lin.ee/xchCfdn">公式LINEの友だち追加</a>で無料でお渡ししています。</p>'
)


def transform_early(key, html):
    if EARLY_MARK in html:
        return None  # 済み
    m = re.search(r"<h[1-4][\s>]", html)
    if not m:
        print(f"  skip（見出しが見つからない key={key}）")
        return None
    pos = m.start()
    return html[:pos] + EARLY_HTML + html[pos:]


def main():
    keys = [a for a in sys.argv[1:] if a.startswith("n")]
    if not keys:
        print(__doc__)
        return
    results = {}
    for key in keys:
        print(f"[early-cta {key}]")
        try:
            r = publish_one(key, transform_fn=transform_early)
            if r == "ok":
                dv = verify(key)
                if EARLY_MARK not in dv["body"]:
                    raise RuntimeError("冒頭CTAが本文に反映されていない")
            results[key] = r
        except Exception as e:
            print(f"  !!! ERROR: {e}")
            results[key] = f"error: {e}"
        print()
    print("── 結果 ──")
    for k, v in results.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
