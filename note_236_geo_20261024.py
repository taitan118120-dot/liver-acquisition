#!/usr/bin/env python3
"""#236 nd7bbfa439e8b に AI 検索向けの要点と FAQ を足して再公開する（2026-10-24）。

10月の公式LINE流入元で ChatGPT・AI が最多だったので、AI が「石川県 ライバー事務所」
「金沢 ライバー事務所」に答えるときに引ける文を #236 に置く
（data/geo_measurement_2026-10-15.md：石川の質問で TAITAN PRO が名前を出されていない）。
  ・冒頭の結論の直後に「この記事の要点」（金沢拠点の事務所としての一文を含む）
  ・FAQ の先頭に3問（石川県にライバー事務所はあるか／地元か全国対応か／金沢での始め方）
足した文は確定ファクト（拠点・対応アプリ・還元率100%+α・ノルマなし・オンライン完結）だけで書いた。

■ 差し込み方式（本文の作り直しはしない）
  公開本文には原稿に無いもの（自動で入った「あわせて読みたい」・末尾のフォロー依頼）があるので、
  原稿から本文を作り直すとそれが消えるか二重になる。足した2か所だけを原稿から切り出して
  公開HTMLの該当位置に差し込む。

公開の3段は note_publish_core（note_leadmagnet_publish.publish_one 経由）が正本。

使い方:
  python3 note_236_geo_20261024.py --dry-run   # 置換結果を出す（GETのみ）
  python3 note_236_geo_20261024.py --publish
  python3 note_236_geo_20261024.py --verify    # ログアウト公開APIで検証
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

KEY = "nd7bbfa439e8b"
MD_FILE = os.path.join(BASE_DIR, "blog", "articles_note", "236_石川金沢でライバー事務所を探している人へ.md")
# 新本文に入っていて旧本文には無い文字列（冪等判定と反映確認の両方に使う）
NEW_MARKS = ["この記事の要点", "Q. 石川県にライバー事務所はありますか？",
             "Q. 金沢でライバーを始めるには、何から始めればいいですか？"]

# 差し込み位置（公開HTML側）。note は保存のたびに name/id を振り直すので属性は読み飛ばす
_AFTER_INTRO = re.compile(r"<p[^>]*>先に結論を書きます。.*?この記事はその話です。</p>")
_BEFORE_FIRST_FAQ = re.compile(r"<h3[^>]*>Q\. 金沢の事務所に行く必要はありますか？</h3>")

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


def transform(key, html):
    if NEW_MARKS[0] in html:
        return None
    m1 = _AFTER_INTRO.search(html)
    m2 = _BEFORE_FIRST_FAQ.search(html)
    if not (m1 and m2 and m1.end() < m2.start()):
        raise ValueError("差し込み位置（冒頭の結論／最初のFAQ）が見つからない")
    summary = "<p><br></p>" + _md_section("**この記事の要点**", "🎁 **先に特典だけ受け取るのもOK**：配信の最初の30日でやることを全部まとめた非売品PDF『ライバー新人期スタートダッシュガイド』を、[公式LINEの友だち追加](https://lin.ee/xchCfdn)で無料でお渡ししています。")
    faqs = _md_section("### Q. 石川県にライバー事務所はありますか？", "### Q. 金沢の事務所に行く必要はありますか？") + "<p><br></p>"
    return (html[:m1.end()] + summary + html[m1.end():m2.start()]
            + faqs + html[m2.start():])


def problems(d):
    """公開側に足りないもの・あってはいけないもの。空なら合格。"""
    text = d.get("name", "") + "\n" + d.get("body", "")
    out = [f"未反映: {m}" for m in NEW_MARKS if m not in text]
    out += [f"{r}: {h}" for r, h in common_violations(text)]
    for once in ["ここまで読んでくれたあなたへ", "あわせて読みたい", "noteのフォロー"]:
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
