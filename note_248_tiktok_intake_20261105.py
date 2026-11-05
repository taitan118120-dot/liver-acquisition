#!/usr/bin/env python3
"""#248 n8134760a6b5f に、TikTok LIVE が今も新規エージェンシーを受け付けている根拠を足して再公開する（2026-11-05）。

「TikTokは新しい一次店を受け付けていない」は公開情報と合わなかった（公式の登録ページ、
2026-11-02 の参入検討企業向けサミット告知、2026年の提携契約の公表）。#248 は「審査が厳しい」版で
公開済みだったが、根拠が2024〜2025年の情報だけだったので、2026年の公式情報を足す。
  ・冒頭の結論と要点の一文を「今も公式に申し込みを受け付けている」に
  ・「理由1」の節を原稿どおりに差し替え（受付の根拠／公式フォームの条件／狭き門の理由）
  ・FAQ「TikTok LIVEの一次店には今から申し込めますか？」の答えを差し替え

■ 差し込み方式（本文の作り直しはしない）
  公開本文には原稿に無いもの（自動の「あわせて読みたい」・末尾のフォロー依頼）があるので、
  変えた区間だけを原稿から切り出して公開HTMLの該当区間と入れ替える（note_236_geo_20261024.py と同じ）。

使い方:
  python3 note_248_tiktok_intake_20261105.py --dry-run   # 置換結果を出す（GETのみ）
  python3 note_248_tiktok_intake_20261105.py --publish
  python3 note_248_tiktok_intake_20261105.py --verify    # ログアウト公開APIで検証
"""
import os
import re
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from facts_patterns import common_violations  # noqa: E402

KEY = "n8134760a6b5f"
MD_FILE = os.path.join(
    BASE_DIR, "blog", "articles_note",
    "248_ライバー事務所の一次店設立はなぜ厳しいTikTokの新規受付と税金給料支払いの壁.md")
# 新本文に入っていて旧本文には無い文字列（冪等判定と反映確認の両方に使う）
NEW_MARKS = ["申し込みは今も受け付けている", "参入を検討している企業・事業者も招く",
             "申し込めます。TikTok LIVEの公式ページに「エージェンシー登録」があり",
             "TikTok LIVEは今も公式に申し込みを受け付けていますが"]
# 直したあとに残っていてはいけない旧文
OLD_MARKS = ["TikTok LIVEには公式のエントリーフォームがありますが", "申し込み窓口は公式にあるが",
             "申し込む窓口そのものは、公式に案内されています", "実際に受け付けられるかどうかを含め",
             "新しい一次店を受け付けていない", "新規受付なし"]

TEXT_SWAPS = [
    ("TikTok LIVEには公式のエントリーフォームがありますが、", "TikTok LIVEは今も公式に申し込みを受け付けていますが、"),
    ("TikTok LIVEの申し込み窓口は公式にあるが、", "TikTok LIVEは今も公式に申し込みを受け付けているが、"),
]

# 入れ替える区間（公開HTML側）。note は保存のたびに name/id を振り直すので属性は読み飛ばす
_H2_REASON1 = re.compile(r"<h2[^>]*>理由1：")
_H3_NO_SCREENING = re.compile(r"<h3[^>]*>「審査なしで事務所を設立」")
_H3_FAQ_APPLY = re.compile(r"<h3[^>]*>TikTok LIVEの一次店には今から申し込めますか？</h3>")
_H3_FAQ_NEXT = re.compile(r"<h3[^>]*>一次店の設立が厳しいのはなぜですか？</h3>")
_GAP = "<p><br></p>"

PUBLIC_API = "https://note.com/api/v3/notes/{key}"
PUBLIC_HEADERS = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache",
                  "Pragma": "no-cache"}


def _md_section(start, stop):
    """原稿の start 行〜 stop 行の手前を note 用HTMLにする（フォロー依頼は付けない）。"""
    from note_auto_poster import markdown_to_html
    from note_publisher import convert_table_to_list, format_for_note
    lines = open(MD_FILE, encoding="utf-8").read().split("\n")
    i, j = lines.index(start), lines.index(stop)
    md = "\n".join(lines[i:j]).strip("\n")
    return markdown_to_html(format_for_note(convert_table_to_list(md)))


def _swap(html, start_re, stop_re, new_html):
    m1, m2 = start_re.search(html), stop_re.search(html)
    if not (m1 and m2 and m1.start() < m2.start()):
        raise ValueError(f"入れ替え区間が見つからない: {start_re.pattern}")
    return html[:m1.start()] + new_html + _GAP + html[m2.start():]


def transform(key, html):
    if NEW_MARKS[0] in html:
        return None
    for old, new in TEXT_SWAPS:
        if html.count(old) != 1:
            raise ValueError(f"置換元が1か所でない: {old}")
        html = html.replace(old, new)
    html = _swap(html, _H2_REASON1, _H3_NO_SCREENING,
                 _md_section("## 理由1：TikTok LIVEの審査を通るのが難しい",
                             "### 「審査なしで事務所を設立」という案内を見たら"))
    html = _swap(html, _H3_FAQ_APPLY, _H3_FAQ_NEXT,
                 _md_section("### TikTok LIVEの一次店には今から申し込めますか？",
                             "### 一次店の設立が厳しいのはなぜですか？"))
    return html


def problems(d):
    """公開側に足りないもの・あってはいけないもの。空なら合格。"""
    text = d.get("name", "") + "\n" + d.get("body", "")
    out = [f"未反映: {m}" for m in NEW_MARKS if m not in text]
    out += [f"旧文が残存: {m}" for m in OLD_MARKS if m in text]
    out += [f"{r}: {h}" for r, h in common_violations(text)]
    for once in ["ここまで読んでくれたあなたへ", "あわせて読みたい", "noteのフォロー",
                 "理由1：", "「審査なしで事務所を設立」という案内を見たら",
                 "TikTok LIVEの一次店には今から申し込めますか？"]:
        if text.count(once) != 1:
            out.append(f"重複または欠落: {once}")
    return out


def fetch_public(key):
    r = requests.get(PUBLIC_API.format(key=key), headers=PUBLIC_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()["data"]


def dry_run():
    d = fetch_public(KEY)
    nb = transform(KEY, d["body"])
    print(f"{KEY} {d['name'][:40]}")
    if nb is None:
        print("  変更なし（反映済み）")
        return
    print(f"  [BODY] {len(d['body'])} -> {len(nb)}")
    print("  直したあとの問題:", problems({"name": d["name"], "body": nb}) or "なし")
    i = nb.index("理由1：")
    print(nb[i - 120:nb.index("「審査なしで事務所を設立」") + 40])
    i = nb.index("今から申し込めますか？")
    print(nb[i - 120:nb.index("一次店の設立が厳しいのはなぜですか？") + 30])


def publish():
    from note_leadmagnet_publish import publish_one
    publish_one(KEY, transform, expect_marker=None)


def verify():
    for _ in range(4):
        d = fetch_public(KEY)
        left = problems(d)
        if not left:
            break
        time.sleep(6)  # CDN反映ラグ
    tags = len(d.get("hashtag_notes", []))
    ok = not left and tags > 0 and d.get("eyecatch")
    print(f"{'OK' if ok else 'NG'} {KEY} tags={tags} "
          f"eyecatch={'OK' if d.get('eyecatch') else 'MISSING'} {d['name'][:40]}")
    for p in left:
        print(f"   {p}")
    return bool(ok)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--dry-run":
        dry_run()
    elif arg == "--publish":
        publish()
    elif arg == "--verify":
        raise SystemExit(0 if verify() else 1)
    else:
        print(__doc__)
        raise SystemExit(1)
