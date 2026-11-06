#!/usr/bin/env python3
"""#43 n01815f0e5285 を「独立ロードマップ」から「開業せずに代理店で続ける」へ組み直す（2026-11-06）。

ユーザー指示「代理店契約を長くしてほしいので事務所開業はおすすめしてない」。
旧 #43 は「代理店で実績を積んで → 法人設立 → 事務所契約 → 独立」を最強ルートとして勧め、
CTAでも「将来の事務所開業を目指す方にも最適」「開業に向けた事業計画の相談にも対応」
「独立後も連携パートナーとして関係を継続可能」「代理店時代のライバーを自社事務所に移管」
と、代理店パートナーの独立を事務所自身が後押ししていた。

■ 新しい骨格（原稿 blog/articles_note/43_*.md が正本）
  開業で背負う4つの仕事（審査・支払い・税金・ルール管理）→ 事務所の仕事の中心は
  代理店でも同じ → 代理店で続ける3つの理由（代理店LP #vs-direct の3訴求）→
  「いつか独立」の前に知っておくこと → FAQ「独立したほうがいい？→おすすめしていない」。
  代理店側の金額は書かない（2026-10-24 確定）。旧版の初期費用50〜300万円・法人設立費用・
  審査基準「所属10〜30人」・「マネージャー1人につきライバー30人」は出所が無いので落とした。

■ タイトルとタグ
  タイトルは検索語「ライバー事務所 開業 方法」を残して結論を変える。
  タグは公開中の #独立 #起業 #事務所設立 #法人化 #ロードマップ が独立志望の読者を呼ぶので
  NEW_TAGS に入れ替える（publish_one は live のタグを復元するので get_note を差し替える）。

■ リンク元27本（2026-11-06 にログアウト公開APIで全208本を走査）
  related_html が旧タイトル「…独立ロードマップ【2026年完全版】」をリンク文言としてコピーしている。
  リンク文言を新タイトルへ。地の文で「独立までの道のり」「開業までの手順」と紹介していた
  3本（#149/#210/#244）は文ごと言い換える。

■ #43 本文の差し替え範囲
  冒頭〜「あわせて読みたい」の直前を原稿から作り直す。それより後ろ（あわせて読みたい・
  特典・LINEボタン・フォロー依頼）は公開側にしか無い追加物なので残す。

使い方:
  python3 note_43_no_independence_20261106.py --dry-run   # 置換結果を出す（GETのみ）
  python3 note_43_no_independence_20261106.py --md        # ローカル原稿（リンク元）と key_map を直す
  python3 note_43_no_independence_20261106.py --publish   # #43 → リンク元の順に公開
  python3 note_43_no_independence_20261106.py --verify    # ログアウト公開APIで検証
"""
import glob
import json
import os
import re
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from facts_patterns import common_violations  # noqa: E402

KEY = "n01815f0e5285"
MD_FILE = glob.glob(os.path.join(BASE_DIR, "blog", "articles_note", "43_*.md"))[0]
KEYMAP_FILE = os.path.join(BASE_DIR, "data", "note_key_map.json")

OLD_TITLE = "ライバー事務所を開業する方法｜代理店との違いと独立ロードマップ【2026年完全版】"
OLD_SHORT = "ライバー事務所を開業する方法｜代理店との違いと独立ロードマップ"
NEW_TITLE = ("ライバー事務所の開業方法を調べている人へ｜直営と代理店の違いと、"
             "開業せずに代理店で続けるという選択【2026年版】")
NEW_SHORT = NEW_TITLE.replace("【2026年版】", "")

NEW_TAGS = ["ライバー事務所", "開業", "ライバー代理店", "代理店", "代理店パートナー",
            "ライバー", "副業", "事務所運営", "スカウト", "ビジネス"]

# 2026-11-06 にログアウト公開APIで全208本を走査して見つけたリンク元
INBOUND = [
    "n8134760a6b5f", "n662ec65efdeb", "n0fa2207bcf94", "n911b8e4fc304", "nbc3438aa9c55",
    "n525f904caf13", "ndea5f40953da", "n788c3f2ac198", "n757225e527ab", "n0c5ab0c57d58",
    "nc724ae8b1bfe", "nb56931d43385", "ne10b7646b37f", "nc932709431a0", "n8acd2b1825e0",
    "n696837722cd3", "n0e8aef46383f", "n6b70b66ac397", "n6006676b8d6e", "nfde7bf8ebf40",
    "n2a16d2f925ce", "n699ef655effb", "na737000db46a", "ne7911c5b9ce9", "ne28bee508ca1",
    "na36a4968c3bc", "nddb6b019f91f",
]

# 地の文の言い換え（公開HTML・ローカル原稿の両方に当てる）。リンクは間に挟まるので前後で分ける
CONTEXT_SWAPS = [
    # #244 n662ec65efdeb
    ("立ち上げの考え方は、", "事務所を自分で開業する場合との違いは、"),
    # #210 nbc3438aa9c55
    ("2つの違いと、どちらから始めるかの考え方は", "2つの違いと、開業せずに代理店で続けるという考え方は"),
    # #149 n696837722cd3
    ("には、開業までの手順を書きました。", "には、開業で背負う仕事と、代理店との違いを書きました。"),
    # #250（未公開の在庫。原稿だけ）
    ("独立までの道のりは", "事務所を開業する場合との違いは"),
]

# 新本文に入っていて旧本文には無い文字列（冪等判定と反映確認の両方に使う）
NEW_MARK = "開業せずに代理店で続けるという選択"
# #43 の公開本文・タイトル・リンク元のどこにも残っていてはいけない旧文言
GONE = ["独立ロードマップ", "将来の事務所開業を目指す", "開業に向けた事業計画",
        "独立後も連携パートナー", "自社事務所に移管", "将来は自分の事務所を持ちたい",
        "「代理店→独立」", "自分が本部になる", "独立までの道のり", "開業までの手順を書きました",
        "どちらから始めるかの考え方", "立ち上げの考え方は、"]

_ANCHOR = re.compile(r'(<a [^>]*n01815f0e5285[^>]*>)([^<]*)(</a>)')
# 公開本文の末尾（施策の追加物）の起点。note は保存のたびに name/id を振り直すので属性は読み飛ばす
_TAIL = re.compile(r"(?:<p[^>]*><br></p>)?<h3[^>]*>あわせて読みたい</h3>")

PUBLIC_API = "https://note.com/api/v3/notes/{key}"
PUBLIC_HEADERS = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache",
                  "Pragma": "no-cache"}


def new_head_html():
    """原稿のタイトル行の次〜末尾の特典段落の手前を note 用HTMLにする。"""
    from note_auto_poster import markdown_to_html
    from note_publisher import convert_table_to_list, format_for_note
    lines = open(MD_FILE, encoding="utf-8").read().split("\n")
    assert lines[0] == "# " + NEW_TITLE, "原稿のタイトルが NEW_TITLE と一致しない"
    end = next(i for i, l in enumerate(lines) if l.startswith("🎁 **友だち追加特典**"))
    md = "\n".join(lines[1:end]).strip("\n")
    return markdown_to_html(format_for_note(convert_table_to_list(md)))


def transform_43(key, html):
    if NEW_MARK in html:
        return None
    m = _TAIL.search(html)
    if not m:
        raise ValueError("「あわせて読みたい」が見つからない")
    return new_head_html() + html[m.start():]


def _anchor_text(m):
    text = m.group(2)
    new = NEW_TITLE if text.endswith("】") else NEW_SHORT
    return m.group(1) + new + m.group(3)


def transform_inbound(key, html):
    out = _ANCHOR.sub(_anchor_text, html)
    for old, new in CONTEXT_SWAPS:
        out = out.replace(old, new)
    return None if out == html else out


def transform(key, html):
    return transform_43(key, html) if key == KEY else transform_inbound(key, html)


def transform_title(key, title):
    return NEW_TITLE if key == KEY and title != NEW_TITLE else None


def problems(key, d):
    """公開側に残っていてはいけないもの。空なら合格。"""
    title, body = d.get("name", ""), d.get("body", "")
    text = title + "\n" + body
    out = [f"残存: {g}" for g in GONE if g in text]
    if key == KEY:
        if title != NEW_TITLE:
            out.append(f"タイトルが旧いまま: {title}")
        if "これから始める人にライバー事務所の開業をおすすめしていません" not in re.sub(r"<[^>]+>", "", body):
            out.append("新本文が反映されていない")
        out += [f"{r}: {h}" for r, h in common_violations(text)]
    else:
        for m in _ANCHOR.finditer(body):
            if m.group(2) not in (NEW_TITLE, NEW_SHORT):
                out.append(f"リンク文言が新タイトルでない: {m.group(2)}")
    return out


def fetch_public(key):
    r = requests.get(PUBLIC_API.format(key=key), headers=PUBLIC_HEADERS, timeout=30,
                     params={"_": str(time.time())})
    r.raise_for_status()
    return r.json()["data"]


def dry_run():
    for key in [KEY] + INBOUND:
        d = fetch_public(key)
        nb = transform(key, d["body"])
        nt = transform_title(key, d["name"])
        print(f"\n{key} {d['name'][:40]}")
        if nt:
            print(f"  [TITLE] -> {nt}")
        if nb is None:
            print("  変更なし")
            continue
        print(f"  [BODY] {len(d['body'])} -> {len(nb)}")
        if key != KEY:
            for m in _ANCHOR.finditer(nb):
                s = re.sub(r"<[^>]+>", "", nb[max(0, m.start() - 160):m.end() + 60])
                print(f"    …{s[-230:]}")
        left = problems(key, {"name": nt or d["name"], "body": nb})
        print("  直したあとの問題:", left or "なし")
        time.sleep(0.3)


def fix_md():
    """リンク元のローカル原稿と key_map を直す（#43 の原稿そのものは手で書き直し済み）。"""
    link = re.compile(r"\[([^\]]*)\]\(https://note\.com/taitan_118/n/n01815f0e5285\)")

    def sub_link(m):
        new = NEW_TITLE if m.group(1).endswith("】") else NEW_SHORT
        return f"[{new}](https://note.com/taitan_118/n/n01815f0e5285)"

    for path in sorted(glob.glob(os.path.join(BASE_DIR, "blog", "articles_note", "*.md"))):
        if path == MD_FILE:
            continue
        src = open(path, encoding="utf-8").read()
        if "n01815f0e5285" not in src:
            continue
        out = link.sub(sub_link, src)
        for old, new in CONTEXT_SWAPS:
            out = out.replace(old, new)
        if out != src:
            open(path, "w", encoding="utf-8").write(out)
            print(f"  updated {os.path.relpath(path, BASE_DIR)}")
    km = json.load(open(KEYMAP_FILE, encoding="utf-8"))
    if km["43"]["title"] != NEW_TITLE:
        km["43"]["title"] = NEW_TITLE
        with open(KEYMAP_FILE, "w", encoding="utf-8") as f:
            json.dump(km, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("  updated data/note_key_map.json #43 title")


def _install_new_tags():
    """publish_one は live のタグを控えて復元する。#43 だけ NEW_TAGS を控えさせる。"""
    import note_leadmagnet_publish as lp
    orig = lp.get_note

    def get_note(s, key, draft=True):
        d = orig(s, key, draft=draft)
        if key == KEY:
            d["hashtag_notes"] = [{"hashtag": {"name": "#" + t}} for t in NEW_TAGS]
        return d
    lp.get_note = get_note


def publish_all(only=None):
    from note_leadmagnet_publish import publish_one
    _install_new_tags()
    keys = [KEY] + INBOUND if not only else only
    fail = 0
    # #43 を先に。タイトルが変わってからリンク元を直す
    for i, key in enumerate(keys, 1):
        print(f"\n[{i}/{len(keys)}] {key}", flush=True)
        try:
            publish_one(key, transform, expect_marker=None, title_fn=transform_title)
        except Exception as e:  # noqa: BLE001 — 1本落ちても残りは処理する
            print(f"  !! 失敗: {type(e).__name__}: {e}", flush=True)
            fail += 1
        time.sleep(8)
    return fail


def verify():
    bad = 0
    for key in [KEY] + INBOUND:
        for attempt in range(4):
            d = fetch_public(key)
            left = problems(key, d)
            if not left:
                break
            time.sleep(6)  # CDN反映ラグ
        tags = [h["hashtag"]["name"].lstrip("#") for h in d.get("hashtag_notes", [])]
        if key == KEY and sorted(tags) != sorted(NEW_TAGS):
            left.append(f"タグが入れ替わっていない: {tags}")
        ok = not left and tags and d.get("eyecatch")
        bad += not ok
        print(f"{'OK' if ok else 'NG'} {key} tags={len(tags)} "
              f"eyecatch={'OK' if d.get('eyecatch') else 'MISSING'} {d['name'][:40]}")
        for p in left:
            print(f"   {p}")
        time.sleep(0.3)
    print(f"\n検証 {1 + len(INBOUND)} 本 / 問題 {bad} 本")
    return bad == 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--dry-run":
        dry_run()
    elif arg == "--md":
        fix_md()
    elif arg == "--publish":
        raise SystemExit(1 if publish_all(sys.argv[2:] or None) else 0)
    elif arg == "--verify":
        raise SystemExit(0 if verify() else 1)
    else:
        print(__doc__)
        raise SystemExit(1)
