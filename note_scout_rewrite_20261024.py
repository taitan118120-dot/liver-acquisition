#!/usr/bin/env python3
"""#42・#60 のスカウト記事を「一斉DM前提」から代理店LPの方針（3つの入口）へ組み直す（2026-10-24）。

代理店LP（lp/agency）の FAQ は「面識のない相手への一斉DMは推奨していません——届かない
うえにアカウントを危険にさらすため」とし、入口を①発信して相談される側に回る
②つながっている人に近況として話す ③無所属のライバーの配信をリスナーさんとして見に行く、
の3つに絞っている。ところが2本は記事の骨格そのものが一斉DMだった:
  #42 n2a16d2f925ce「スカウト術｜DM返信率を上げる実践テクニック」
      … Xで「在宅 副業 探してる」と検索してDM／週にDM 30〜50通が目標／1日5〜10通
  #60 nfde7bf8ebf40「「弊社ライバー事務所です」と書いた瞬間、返信率は半分になる」
      … 事務所として毎月数千〜数万通／「半分」「1/3」「9割の新人」「ほぼ100%ブロック」は根拠なし
      ／IRIAM・ふわっち・17LIVE の媒体別文体表（取り扱いは Pococha・TikTok LIVE のみ）
ユーザー確認（2026-10-24）: 2本とも組み直して改題／「以前は一斉DMも試したが入会につながらず
やめた」は**数字なしで**書いてよい（2026-06 のIGコールドDMの実体験）／#42 の支援内容
（DMテンプレ提供・返信率1on1コンサル・送信数の自動トラッキング・BAN回避ルール）は
LPの表現（研修とトークの型・管理ツール提供・専用の相談窓口）に置き換える。

■ 差し替え範囲
  記事の頭〜「あわせて読みたい」の手前を原稿から作り直す。それより後ろ（関連リンク・
  末尾CTA・フォロー依頼）は公開側にしか無い施策の追加物なので残す。

■ リンク元17本
  旧タイトルは他記事の「あわせて読みたい」にリンク文言としてコピーされ、一部は地の文
  （「DMの文面そのものの話は「…返信率は半分になる」にまとめてあります」）でも引かれていた。
  2026-10-24 にログアウト公開APIで全記事を走査して拾ったものを INBOUND に置く。

公開の3段は note_publish_core（note_leadmagnet_publish.publish_one 経由）が正本。

使い方:
  python3 note_scout_rewrite_20261024.py --dry-run | --md | --publish | --verify
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

ARTICLE_DIR = os.path.join(BASE_DIR, "blog", "articles_note")
KEYMAP_FILE = os.path.join(BASE_DIR, "data", "note_key_map.json")

OLD42 = "ライバー代理店のスカウト術｜DM返信率を上げる実践テクニック【2026年版】"
NEW42 = "ライバー代理店のスカウト術｜一斉DMに頼らない3つの入口と、最初の声のかけ方【2026年版】"
OLD60 = "「弊社ライバー事務所です」と書いた瞬間、返信率は半分になる｜スカウトDM運用論"
NEW60 = "ライバー事務所が一斉スカウトDMをやめた理由｜代わりに続けている3つの入口【運用論】"

TARGETS = {
    "n2a16d2f925ce": {"num": "42", "title": NEW42, "md": "42_ライバー代理店スカウト術DM返信率.md"},
    "nfde7bf8ebf40": {"num": "60", "title": NEW60, "md": "60_スカウトDM返信率.md"},
}
INBOUND = ["n01815f0e5285", "n9b5e9d5abc25", "ne7911c5b9ce9", "ne28bee508ca1", "n696837722cd3",
           "n8acd2b1825e0", "nc932709431a0", "nb56931d43385", "nc724ae8b1bfe", "n0c5ab0c57d58",
           "n757225e527ab", "n788c3f2ac198", "ndea5f40953da", "n525f904caf13", "n8fb330228428",
           "n6b4833be529b", "n0fa2207bcf94"]

# リンク文言・地の文の言い換え。順番に意味がある（長い綴りが先）。公開HTMLと原稿mdの両方に当てる
TEXT_RULES = [
    (OLD42, NEW42),
    ("ライバー代理店のスカウト術｜DM返信率を上げる実践テクニック", NEW42),
    (OLD60, NEW60),
    ("「弊社ライバー事務所です」と書いた瞬間、返信率は半分になる", NEW60),
    # 短いリンク文言（#213）。HTMLは >…</a>、md は […]( の形
    (">スカウトDM運用論</a>", ">一斉スカウトDMをやめた理由</a>"),
    ("[スカウトDM運用論](", "[一斉スカウトDMをやめた理由]("),
    # 地の文（#160 / #213）。リンク先が「文面の作り方」の記事ではなくなったので言い換える
    ("DMの文面そのものの話は", "一斉DMをやめた理由と、関係ができた相手への最初のメッセージの話は"),
    ("文面そのものの作り方は", "最初のメッセージの書き方は"),
]

# 消したはずのもの（本文側。関連リンクの他記事タイトルは除いて見る）
GONE_OWN = ["週30〜50通", "1日5〜10通", "数千〜数万通", "1/3", "9割", "ほぼ100%", "IRIAM", "ふわっち",
            "17LIVE", "返信率は半分", "DMテンプレートの提供", "返信率改善の1on1", "自動トラッキング",
            "BAN回避", "データ横断分析", "在宅 副業 探してる"]
# 消したはずのもの（どこにも残ってはいけない＝リンク文言も含む）
GONE_ALL = ["返信率は半分", "DM返信率を上げる実践テクニック"]

_RELATED = re.compile(r"<h3[^>]*>あわせて読みたい")
_GIFT = re.compile(r"<p[^>]*>🎁 <strong>友だち追加特典")

PUBLIC_API = "https://note.com/api/v3/notes/{key}"
PUBLIC_HEADERS = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache",
                  "Pragma": "no-cache"}


def apply_text_rules(text):
    for old, new in TEXT_RULES:
        text = text.replace(old, new)
    return text


def new_head_html(key):
    """原稿のタイトル行の次〜末尾CTA（友だち追加特典）の手前を note 用HTMLにする。"""
    from note_auto_poster import markdown_to_html
    t = TARGETS[key]
    lines = open(os.path.join(ARTICLE_DIR, t["md"]), encoding="utf-8").read().split("\n")
    assert lines[0] == "# " + t["title"], f"#{t['num']} 原稿のタイトルが新タイトルと一致しない"
    end = next(i for i, l in enumerate(lines) if l.startswith("🎁 **友だち追加特典**"))
    # 原稿の区切り線は公開本文では空行段落になっている（既存の見た目に合わせる）
    body = ["" if l == "---" else l for l in lines[1:end]]
    return markdown_to_html("\n".join(body).strip("\n")) + "<p><br></p>"


def transform(key, html):
    if key in TARGETS:
        if "面識のない相手への一斉DMは推奨していません" in html:
            return None
        m = _RELATED.search(html) or _GIFT.search(html)
        if not m:
            raise ValueError("末尾（あわせて読みたい／友だち追加特典）が見つからない")
        out = new_head_html(key) + apply_text_rules(html[m.start():])
    else:
        out = apply_text_rules(html)
    return None if out == html else out


def transform_title(key, title):
    t = TARGETS.get(key)
    return t["title"] if t and title != t["title"] else None


def problems(key, d):
    title, body = d.get("name", ""), d.get("body", "")
    cut = body.find("あわせて読みたい")
    own = body[:cut] if cut != -1 else body
    out = [f"残存: {g}" for g in GONE_ALL if g in title + body]
    if key in TARGETS:
        out += [f"残存: {g}" for g in GONE_OWN if g in own]
        if title != TARGETS[key]["title"]:
            out.append(f"タイトルが旧いまま: {title}")
        if "面識のない相手への一斉DMは推奨していません" not in own:
            out.append("新本文が反映されていない")
        out += [f"{r}: {h}" for r, h in common_violations(title + "\n" + body)]
    elif NEW42 not in body and NEW60 not in body:
        out.append("リンク文言が新タイトルになっていない")
    return out


def fetch_public(key):
    r = requests.get(PUBLIC_API.format(key=key), headers=PUBLIC_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()["data"]


def dry_run():
    from note_structure_guard import scan_body
    for key in list(TARGETS) + INBOUND:
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
        print("  直したあとの問題:", problems(key, {"name": nt or d["name"], "body": nb}) or "なし")
        if key in TARGETS:
            print("  本文構造:", scan_body(nb) or "なし")
        time.sleep(0.3)


def fix_md():
    # リンク元の原稿（公開されていない原稿も含めて、リンクを持つものは全部）
    for p in sorted(glob.glob(os.path.join(ARTICLE_DIR, "*.md"))):
        if os.path.basename(p) in {t["md"] for t in TARGETS.values()}:
            continue
        src = open(p, encoding="utf-8").read()
        new = apply_text_rules(src)
        if new != src:
            open(p, "w", encoding="utf-8").write(new)
            print(f"  updated {os.path.relpath(p, BASE_DIR)}")
    km = json.load(open(KEYMAP_FILE, encoding="utf-8"))
    for t in TARGETS.values():
        km[t["num"]]["title"] = t["title"]
    with open(KEYMAP_FILE, "w", encoding="utf-8") as f:
        json.dump(km, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("  updated data/note_key_map.json #42/#60 title")


def publish_all():
    from note_leadmagnet_publish import publish_one
    fail = 0
    # 本体2本を先に（タイトルが変わってからリンク元を直す）
    keys = list(TARGETS) + INBOUND
    for i, key in enumerate(keys, 1):
        print(f"\n[{i}/{len(keys)}] {key}", flush=True)
        try:
            publish_one(key, transform, expect_marker=None, title_fn=transform_title)
        except Exception as e:  # noqa: BLE001 — 1本落ちても残りは処理する
            print(f"  !! 失敗: {type(e).__name__}: {e}", flush=True)
            fail += 1
        time.sleep(25 if i % 8 == 0 else 8)  # note の連投検知を避ける（note_boost_publish と同じ刻み）
    return fail


def verify():
    bad = 0
    keys = list(TARGETS) + INBOUND
    for key in keys:
        for attempt in range(4):
            d = fetch_public(key)
            left = problems(key, d)
            if not left:
                break
            time.sleep(6)  # CDN反映ラグ
        tags = len(d.get("hashtag_notes", []))
        ok = not left and tags > 0 and d.get("eyecatch")
        bad += not ok
        print(f"{'OK' if ok else 'NG'} {key} tags={tags} "
              f"eyecatch={'OK' if d.get('eyecatch') else 'MISSING'} {d['name'][:40]}")
        for p in left:
            print(f"   {p}")
    print(f"\n検証 {len(keys)} 本 / 問題 {bad} 本")
    return bad == 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--dry-run":
        dry_run()
    elif arg == "--md":
        fix_md()
    elif arg == "--publish":
        raise SystemExit(1 if publish_all() else 0)
    elif arg == "--verify":
        raise SystemExit(0 if verify() else 1)
    else:
        print(__doc__)
        raise SystemExit(1)
