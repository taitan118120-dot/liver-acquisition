#!/usr/bin/env python3
"""#37「ライバー月収平均」の公開記事から17LIVEの部分だけを外す（2026-10-02ユーザー指示）。

2026-09-20の17LIVE撤去（note_drop17live_20260920.py）では比較言及は残す線引きだったが、
この記事はタイトルに「・17LIVE」を冠し、「取り扱っている3つのアプリ」として17LIVEを
並べていたので、タイトル・節・言及をすべて外す。ローカル原稿
blog/articles_note/37_ライバー月収平均2026.md も同日に同じ内容へ修正済み。

  python3 note_drop17live_37_20261002.py [--dry-run]
"""
import re
import sys

KEY = "n17dbf76c743e"
OLD_TITLE_PART = "｜Pococha・TikTok LIVE・17LIVEの現実と"
NEW_TITLE_PART = "｜Pococha・TikTok LIVEの現実と"

REPLACEMENTS = [
    ("TAITAN PROが取り扱っている3つのアプリで", "TAITAN PROが取り扱っている2つのアプリで"),
    ("3つを並べると、", "2つを並べると、"),
    ("ギフトで跳ねる（TikTok LIVE・17LIVE）", "ギフトで跳ねる（TikTok LIVE）"),
    ("TikTok LIVE・17LIVE＝ギフトの爆発力", "TikTok LIVE＝ギフトの爆発力"),
]
# 17LIVEの節: 見出し段落から「熱量の高いファン…」段落の終わりまで
SECTION_RE = re.compile(r"<p[^>]*>[■\s]*17LIVE（イチナナ）.*?熱量の高いファン.*?</p>", re.S)


def transform(key, html):
    out = html
    out, n = SECTION_RE.subn("", out)
    for a, b in REPLACEMENTS:
        out = out.replace(a, b)
    if n != 1 or "17LIVE" in out or "イチナナ" in out:
        raise RuntimeError(f"想定外の本文（節の一致={n}, 17LIVE残={out.count('17LIVE')}）")
    return out if out != html else None


def title_fn(key, title):
    return title.replace(OLD_TITLE_PART, NEW_TITLE_PART)


def main():
    if "--dry-run" in sys.argv:
        from note_leadmagnet_publish import get_note, req_session
        d = get_note(req_session(), KEY, draft=False)
        new = transform(KEY, d["body"])
        print(title_fn(KEY, d["name"]))
        print(f"body {len(d['body'])} -> {len(new) if new else '変更なし'}")
        return
    from note_leadmagnet_publish import publish_one
    print(publish_one(KEY, transform_fn=transform, expect_marker=None, title_fn=title_fn))


if __name__ == "__main__":
    main()
