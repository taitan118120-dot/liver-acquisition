#!/usr/bin/env python3
"""開業を勧めていた #169/#168/#149/#248 を「代理店で長く続ける」に揃える（2026-11-06）。

ユーザー指示「代理店契約を長くしてほしいので事務所開業はおすすめしてない」の続き。
#43 は note_43_no_independence_20261106.py で先に改稿済み。

■ #169 n0c5ab0c57d58 / #168 n8f217e546626（全面改稿・改題・タグ入れ替え）
  どちらも 2026-04 に Gemini が生成した記事で、読者に開業を勧めるうえ、裏付けのない体験談
  （「深夜2時に涙」「1日15時間以上」「1週間で辞めた夜」「1日8時間マイクの前」）や、
  出典としての所属数（「300名のライバーさんと関わってきた経験から」）、
  「+αは事務所独自のボーナス」（+αの中身の断定）、スカウトDMの作成・送信の推奨が入っていた。
  冒頭〜「ここまで読んでくださり」の直前を原稿から作り直す。末尾CTA・あわせて読みたい・
  フォロー依頼は公開側にしか無い追加物なので残す（note_47_rewrite_20261024.py と同じ方式）。
  タグの #独立 #ランクアップ #お金の勉強 等は外す（publish_one は live のタグを復元するので差し替える）。

■ #149 n696837722cd3（区間の差し替え。タイトルは代表の体験談なので維持）
  「これから開業する人へ、順番の提案」→「これから事務所の仕事を始める人へ」、
  「代理店という選択肢もある」（いきなり立ち上げるより代理店から＝あとで開業してよい含み）→
  「今から始めるなら、開業はしなくていい」、末尾の「代理店と事務所のどちらが向いているか」を外す。

■ #248 n8134760a6b5f（区間の差し替え）
  「既存の事務所の枠組みで、実務を経験する」（踏み台扱い）→「代理店として、長く続ける」、
  「3. 一次店を目指すなら、体制を先に作る」→「規模を大きくしたいなら、代理店のまま担当を増やす」、
  「代理店から先の事業をどう考えるかの個別相談」→「担当ライバーが増えてきたときの進め方」。

■ リンク元（2026-11-06 にログアウト公開APIで全208本を走査）
  #169 ← #210 nbc3438aa9c55・n8fb330228428 ／ #168 ← #210。リンク文言を新タイトルへ。

使い方:
  python3 note_agency_no_independence_20261106.py --dry-run
  python3 note_agency_no_independence_20261106.py --md        # リンク元のローカル原稿と key_map
  python3 note_agency_no_independence_20261106.py --publish [key ...]
  python3 note_agency_no_independence_20261106.py --verify
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

ART = os.path.join(BASE_DIR, "blog", "articles_note")
KEYMAP_FILE = os.path.join(BASE_DIR, "data", "note_key_map.json")


def _md(num):
    return glob.glob(os.path.join(ART, f"{num}_*.md"))[0]


K169, K168, K149, K248 = "n0c5ab0c57d58", "n8f217e546626", "n696837722cd3", "n8134760a6b5f"

REWRITE = {  # key: (記事番号, 新タイトル, 新タグ)
    K169: ("169",
           "ライバー事務所の開業準備は何から始める？｜手続きより先に考えたいことと、開業しないという選択肢【2026年版】",
           ["ライバー事務所", "開業", "準備", "ライバー代理店", "代理店", "代理店パートナー",
            "副業", "事務所運営", "スカウト", "ビジネス"]),
    K168: ("168",
           "ライバー事務所の立ち上げは集客でつまずく？｜人が集まって続く仕組みと、開業しなくてもできる集客【2026年版】",
           ["ライバー事務所", "立ち上げ", "集客", "開業", "ライバー代理店", "代理店",
            "代理店パートナー", "スカウト", "副業", "事務所運営"]),
}
INBOUND = ["nbc3438aa9c55", "n8fb330228428"]
ALL = [K169, K168, K149, K248] + INBOUND

# 地の文の言い換え（#210。公開HTML・ローカル原稿の両方）
CONTEXT_SWAPS = [("準備の順番は", "開業準備で先に考えたいことは")]

# 新本文に入っていて旧本文には無い文字列
NEW_MARK = {
    K169: "開業準備は、手続きの準備と仕事の準備の2つに分かれる",
    K168: "この集客は、開業しなくてもできる",
    K149: "今から始めるなら、開業はしなくていい",
    K248: "規模を大きくしたいなら、代理店のまま担当を増やす",
}
# どこにも残っていてはいけない旧文言
GONE = ["深夜2時", "1日15時間", "1週間で辞めてしまった夜", "1日8時間マイク", "300名のライバーさんと関わ",
        "300名のライバーさんをサポート", "300名の所属ライバーをサポートしてきた", "事務所独自のボーナス",
        "ライバー事務所を作りたい」という熱い気持ち", "あなただけの成功", "「あなただから」と選ばれる事務所",
        "これから開業する人へ", "代理店という選択肢もある", "代理店と事務所のどちらが向いているか",
        "実務を経験する", "一次店を目指すなら", "代理店から先の事業",
        "準備の順序を間違えると全てが無駄", "集客で結局つまずくの"]

_TAIL = re.compile(r"(?:<p[^>]*><br><br></p>)?<p[^>]*>ここまで読んでくださり")
_GAP = "<p><br></p>"
PUBLIC_API = "https://note.com/api/v3/notes/{key}"
PUBLIC_HEADERS = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache", "Pragma": "no-cache"}


def _to_html(md):
    from note_auto_poster import markdown_to_html
    from note_publisher import convert_table_to_list, format_for_note
    return markdown_to_html(format_for_note(convert_table_to_list(md)))


def _strong(s):
    """原稿の **x** を公開HTMLの <strong>x</strong> にする（置換元・先の照合用）。"""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)


# ── #169 / #168：冒頭〜末尾CTAの手前を作り直す ──
def _head_html(num, title):
    lines = open(_md(num), encoding="utf-8").read().split("\n")
    assert lines[0] == "# " + title, f"#{num} 原稿のタイトルが新タイトルと一致しない"
    cta = next(i for i, l in enumerate(lines) if l.startswith("ここまで読んでくださり"))
    end = max(i for i in range(cta) if lines[i] == "---")
    return _to_html("\n".join(lines[1:end]).strip("\n"))


def transform_rewrite(key, html):
    num, title, _ = REWRITE[key]
    if NEW_MARK[key] in re.sub(r"<[^>]+>", "", html):
        return None
    m = _TAIL.search(html)
    if not m:
        raise ValueError("末尾CTA（ここまで読んでくださり）が見つからない")
    return _head_html(num, title) + html[m.start():]


# ── #149 / #248：変えた区間だけ入れ替える ──
def _md_section(num, start, stop):
    lines = open(_md(num), encoding="utf-8").read().split("\n")
    i, j = lines.index(start), lines.index(stop)
    return _to_html("\n".join(lines[i:j]).strip("\n"))


def _swap(html, start_re, stop_re, new_html):
    m1 = re.search(start_re, html)
    m2 = re.search(stop_re, html[m1.end():]) if m1 else None
    if not (m1 and m2):
        raise ValueError(f"入れ替え区間が見つからない: {start_re}")
    return html[:m1.start()] + new_html + _GAP + html[m1.end() + m2.start():]


def _text(html, old, new):
    old, new = _strong(old), _strong(new)
    if html.count(old) != 1:
        raise ValueError(f"置換元が1か所でない（{html.count(old)}）: {old[:40]}")
    return html.replace(old, new)


def transform_149(key, html):
    if NEW_MARK[key] in html:
        return None
    html = _text(html, "には、開業で背負う仕事と、代理店との違いを書きました。ただ、開業した人が本当に困るのはその後です。",
                 "には、開業で背負う仕事と、代理店との違いを書きました。この記事は、私がTAITAN PROを立ち上げたときに"
                 "一番きつかった「最初の10人」の話です。人が集まるまでの壁は、事務所でも代理店でも変わりません。")
    html = _text(html, ">これから開業する人へ、順番の提案<", ">これから事務所の仕事を始める人へ、順番の提案<")
    html = _text(html, "私が今ゼロからやるなら、この順番でやります。",
                 "私が今ゼロからやるなら、この順番でやります。**どれも開業しなくても、代理店のままでできることです。**")
    html = _swap(html, r"<h2[^>]*>代理店という選択肢もある</h2>", r"<h2[^>]*>関連記事</h2>",
                 _md_section("149", "## 今から始めるなら、開業はしなくていい", "## 関連記事"))
    html = _text(html, "今の状況で代理店と事務所のどちらが向いているかも、正直にお伝えします。",
                 "今の状況に合った始め方も、正直にお伝えします。")
    return html


def transform_248(key, html):
    if NEW_MARK[key] in html:
        return None
    html = _text(html, "今から始めるなら、**既存の事務所の枠組みで実務を経験する**のが現実的",
                 "今から始めるなら、**既存の事務所の代理店として長く続ける**のが現実的")
    html = _text(html, ">1. 既存の事務所の枠組みで、実務を経験する<", ">1. 既存の事務所の代理店として、長く続ける<")
    html = _text(html, "**スカウトと育成という中心の仕事**から始められます。",
                 "**スカウトと育成という中心の仕事**だけに時間を使えます。代理店の報酬は担当ライバーが配信を続けている間"
                 "ずっと積み上がる仕組みなので、**同じ場所で長く続けるほど力になります。**")
    html = _swap(html, r"<h3[^>]*>3\. 一次店を目指すなら、体制を先に作る</h3>", r"<h2[^>]*>❓ よくある質問</h2>",
                 _md_section("248", "### 3. 規模を大きくしたいなら、代理店のまま担当を増やす", "## ❓ よくある質問"))
    html = _text(html, "**既存の事務所の代理店として実務を経験する**ほうが現実的です。",
                 "**既存の事務所の代理店として長く続ける**ほうが現実的です。")
    html = _text(html, "代理店から先の事業をどう考えるかの個別相談", "担当ライバーが増えてきたときの進め方の個別相談")
    return html


# ── リンク元：リンク文言を新タイトルへ ──
def _new_anchor(key, text):
    title = REWRITE[key][1]
    if text.endswith("】"):
        return title
    if "｜" in text:
        return title.replace("【2026年版】", "")
    return title.split("｜")[0]


def transform_inbound(key, html):
    out = html
    for k in REWRITE:
        out = re.sub(r'(<a [^>]*' + k + r'[^>]*>)([^<]*)(</a>)',
                     lambda m, k=k: m.group(1) + _new_anchor(k, m.group(2)) + m.group(3), out)
    for old, new in CONTEXT_SWAPS:
        out = out.replace(old, new)
    return None if out == html else out


TRANSFORMS = {K169: transform_rewrite, K168: transform_rewrite, K149: transform_149, K248: transform_248}


def transform(key, html):
    return TRANSFORMS.get(key, transform_inbound)(key, html)


def transform_title(key, title):
    if key in REWRITE and title != REWRITE[key][1]:
        return REWRITE[key][1]
    return None


def problems(key, d):
    title, body = d.get("name", ""), d.get("body", "")
    text = title + "\n" + body
    plain = re.sub(r"<[^>]+>", "", text)
    out = [f"残存: {g}" for g in GONE if g in plain]
    if key in NEW_MARK and NEW_MARK[key] not in plain:
        out.append("新本文が反映されていない")
    if key in REWRITE and title != REWRITE[key][1]:
        out.append(f"タイトルが旧いまま: {title}")
    if key in NEW_MARK:
        # リンク文言は他記事のタイトル（#168 のあわせて読みたいに「…｜違約金・契約条件…」がある）なので外す
        out += [f"{r}: {h}" for r, h in common_violations(re.sub(r"<a [^>]*>[^<]*</a>", "", text))]
        for once in ["あわせて読みたい", "noteのフォロー"]:
            if plain.count(once) != 1:
                out.append(f"重複または欠落: {once}")
    for k in REWRITE:
        for m in re.finditer(r'<a [^>]*' + k + r'[^>]*>([^<]*)</a>', body):
            if REWRITE[k][1].split("｜")[0] not in m.group(1):
                out.append(f"リンク文言が新タイトルでない: {m.group(1)}")
    return out


def fetch_public(key):
    r = requests.get(PUBLIC_API.format(key=key), headers=PUBLIC_HEADERS, timeout=30,
                     params={"_": str(time.time())})
    r.raise_for_status()
    return r.json()["data"]


def dry_run():
    for key in ALL:
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
        time.sleep(0.3)


def fix_md():
    for path in sorted(glob.glob(os.path.join(ART, "*.md"))):
        src = open(path, encoding="utf-8").read()
        out = src
        for k in REWRITE:
            out = re.sub(r"\[([^\]]*)\]\(https://note\.com/taitan_118/n/" + k + r"\)",
                         lambda m, k=k: f"[{_new_anchor(k, m.group(1))}](https://note.com/taitan_118/n/{k})", out)
        if out != src:
            for old, new in CONTEXT_SWAPS:
                out = out.replace(old, new)
            open(path, "w", encoding="utf-8").write(out)
            print(f"  updated {os.path.relpath(path, BASE_DIR)}")
    km = json.load(open(KEYMAP_FILE, encoding="utf-8"))
    for k, (num, title, _) in REWRITE.items():
        if km[num]["title"] != title:
            km[num]["title"] = title
            print(f"  updated key_map #{num}")
    with open(KEYMAP_FILE, "w", encoding="utf-8") as f:
        json.dump(km, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _install_new_tags():
    """publish_one は live のタグを控えて復元する。改稿する2本だけ新タグを控えさせる。"""
    import note_leadmagnet_publish as lp
    orig = lp.get_note

    def get_note(s, key, draft=True):
        d = orig(s, key, draft=draft)
        if key in REWRITE:
            d["hashtag_notes"] = [{"hashtag": {"name": "#" + t}} for t in REWRITE[key][2]]
        return d
    lp.get_note = get_note


def publish_all(only=None):
    from note_leadmagnet_publish import publish_one
    _install_new_tags()
    keys = only or ALL
    fail = 0
    for i, key in enumerate(keys, 1):  # 改稿記事を先に。タイトルが変わってからリンク元を直す
        print(f"\n[{i}/{len(keys)}] {key}", flush=True)
        try:
            publish_one(key, transform, expect_marker=None, title_fn=transform_title)
        except Exception as e:  # noqa: BLE001
            print(f"  !! 失敗: {type(e).__name__}: {e}", flush=True)
            fail += 1
        time.sleep(8)
    return fail


def verify():
    bad = 0
    for key in ALL:
        for _ in range(4):
            d = fetch_public(key)
            left = problems(key, d)
            if not left:
                break
            time.sleep(6)
        tags = [h["hashtag"]["name"].lstrip("#") for h in d.get("hashtag_notes", [])]
        if key in REWRITE and sorted(tags) != sorted(REWRITE[key][2]):
            left.append(f"タグが入れ替わっていない: {tags}")
        ok = not left and tags and d.get("eyecatch")
        bad += not ok
        print(f"{'OK' if ok else 'NG'} {key} tags={len(tags)} "
              f"eyecatch={'OK' if d.get('eyecatch') else 'MISSING'} {d['name'][:40]}")
        for p in left:
            print(f"   {p}")
        time.sleep(0.3)
    print(f"\n検証 {len(ALL)} 本 / 問題 {bad} 本")
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
