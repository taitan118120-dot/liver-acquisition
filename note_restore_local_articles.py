#!/usr/bin/env python3
"""公開中のnote記事から、ローカル原稿 blog/articles_note/NN_*.md を復元する。

ローカルmdが無い記事は note_auto_poster.py --update の突合対象外になり、
一括ファクト更新から永久に漏れ続ける。公開本文をmdに逆変換して管理下に戻す。

逆変換は note_auto_poster.markdown_to_html / note_publisher.format_for_note の
逆写像として書いてあり、書き出し後に「md → HTML に順変換して本文テキストが一致するか」
を必ず検証する（不一致ならファイルを書かずに落ちる）。

使い方:
  python3 note_restore_local_articles.py --dry-run
  python3 note_restore_local_articles.py
"""
import html as html_mod
import os
import re
import sys

from note_auto_poster import ARTICLES_DIR, format_body_for_note, markdown_to_html
from note_cta_publish import get_note, req_session

# key -> (記事番号, ファイル名スラッグ)
TARGETS = {
    "na36a4968c3bc": (16, "ライバー事務所還元率の真実"),
    "n84121e6b7eab": (32, "ライバー事務所移籍変更方法"),
    "n699ef655effb": (35, "ライバー事務所契約書チェック10項目"),
    "ndc2f493ebdde": (63, "TikTokLIVEフォロワー1000人集め方"),
    "n3e73861d21f5": (71, "コアファン作り方完全ガイド"),
}


def _inline_to_md(frag):
    """インラインHTML（a / strong / br 済み）をMarkdownに戻す"""
    frag = re.sub(r'<a [^>]*href="([^"]+)"[^>]*><strong>(.*?)</strong></a>', r"**[\2](\1)**", frag)
    frag = re.sub(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", frag)
    frag = re.sub(r"<strong>(.*?)</strong>", r"**\1**", frag)
    frag = re.sub(r"<em>(.*?)</em>", r"**\1**", frag)
    frag = re.sub(r"<[^>]+>", "", frag)
    return html_mod.unescape(frag).strip()


def html_to_markdown(body):
    """note本文HTML → 原稿Markdown

    figure(埋め込みカード)・ol/ul/table はMarkdownで表現できないので生HTMLの1行として残す。
    note_auto_poster.markdown_to_html 側に同じ形の passthrough がある。
    """
    out = []
    # ブロック単位に切る
    block = r"<(h2|h3|p|figure|ol|ul|table)\b[^>]*>(.*?)</\1>|<hr\s*/?>"
    for m in re.finditer(block, body, re.DOTALL):
        tag = m.group(1)
        inner = m.group(2) or ""
        if tag is None:
            out.append("---")
            continue
        if tag in ("figure", "ol", "ul", "table"):
            out.append(re.sub(r"\s*\n\s*", " ", m.group(0)).strip())
            continue
        # <br> は行区切り
        lines = [_inline_to_md(x) for x in re.split(r"<br\s*/?>", inner)]
        lines = [x for x in lines]
        if tag == "h2":
            out.append("## " + " ".join(x for x in lines if x))
            continue
        if tag == "h3":
            out.append("### " + " ".join(x for x in lines if x))
            continue
        for line in lines:
            if not line:
                out.append("")
            elif line.startswith("・"):
                out.append("- " + line[1:].strip())
            elif line.startswith("■ "):
                out.append("### " + line[2:].strip())
            else:
                out.append(line)
    md = "\n".join(out)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md


def _plain(text_html):
    """比較用：HTMLからタグを落として空白を潰した本文テキスト"""
    t = re.sub(r"<[^>]+>", "\n", text_html)
    t = html_mod.unescape(t)
    t = t.replace("・", "").replace("■", "")
    # 一部の公開記事は本文に生の ** が残っている（投稿時に太字変換されなかった）。
    # md復元時に正しい太字へ直るので、比較では * を無視する。
    t = t.replace("*", "")
    return re.sub(r"\s+", "", t)


def restore(key, dry_run=False):
    num, slug = TARGETS[key]
    d = get_note(req_session(), key, draft=False)
    title, body = d["name"], d["body"]
    md = html_to_markdown(body)

    # 検証: md を順変換して本文テキストが一致するか
    regen = markdown_to_html(format_body_for_note(md))
    ok = _plain(regen) == _plain(body)
    path = os.path.join(ARTICLES_DIR, f"{num:02d}_{slug}.md")
    print(f"  #{num} {title[:36]}")
    print(f"  html {len(body)} -> md {len(md)}  round-trip={'OK' if ok else 'MISMATCH'}")
    if not ok:
        a, b = _plain(body), _plain(regen)
        i = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
        print(f"  差分開始 {i}文字目:\n    live: …{a[max(0,i-60):i+60]}…\n    regen:…{b[max(0,i-60):i+60]}…")
        raise SystemExit(f"round-trip不一致のため書き出し中止 (key={key})")
    if dry_run:
        print(f"  [dry-run] {os.path.relpath(path)} は書かない")
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{md}\n")
    print(f"  wrote {os.path.relpath(path)}")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    keys = [a for a in sys.argv[1:] if not a.startswith("--")] or list(TARGETS)
    for k in keys:
        print(f"[restore {k}]")
        restore(k, dry_run=dry)
