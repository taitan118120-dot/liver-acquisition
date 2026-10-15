"""導線番犬 Issue #61 の4本を直す（一度きり。2026-10-15）。

■ 内部リンクが2本しかない（4本とも）
  「あわせて読みたい」が2本しか無かった。3本目は 2026-09-20 に削除した 17LIVE 単体記事
  （#116/#117/#119）へのリンクだったとみられる。ブロックを外して pick_related で3本選び直す。
  リンク文言は公開一覧の**現在の**タイトルで作り直す（#41 のブロックには
  「20代からライバーを始めても遅くない？」と、実在しないタイトルが入っていた）。

■ n4857a2f79084（#41 40代・50代）の公開本文だけ「3」が「2」に化けていた
  原稿 41_40代50代ライバー始め方.md と突き合わせると、本文中の 3 がほぼ全部 2 になっている:
  「3ヶ月目で月15〜20万円、6ヶ月目で月30〜40万円」→「2ヶ月目で…月20〜40万円」（確定レンジ違反）、
  「B帯で月20〜30万」→「月20〜20万」、「理由3」→「理由2」が2つ、「最初の30日」→「20日」など。
  原稿で丸ごと上書きはしない。公開側にしか無い正しい手当て（収入表の確定レンジ化・
  17LIVE撤去後の「配信アプリ2選」・本文構造の変換）まで巻き戻るため。
  化けた箇所だけを、期待回数どおりに当たったときだけ置き換える。

■ 「ノルマなし・退所自由」（#97 n0ea2fd9bfb9d / #101 n9ae8b6546ea5）
  2年契約があるので「退所自由」は書かない（いつでも退所OK と同じ完成形）。
  番犬の正規表現から漏れていたので facts_patterns.py にも足した。原稿も同じ文言に直してある。

使い方:
  python3 note_funnel_fix_20261015.py --plan   # 置換と関連記事の選定を表示するだけ
  python3 note_funnel_fix_20261015.py          # 公開本文を書き換える
"""
import re
import sys

from note_boost_publish import insert_related
from note_cta_publish import get_note, req_session
from note_internal_links_publish import (RELATED_MARK, add_entry, build_catalog_light,
                                         pick_related)

# 関連記事ブロックを3本で組み直す記事
RELINK_KEYS = ["nd2d06917a050", "n0e8aef46383f", "n4857a2f79084", "na08ce1921eb6"]
KEYS = RELINK_KEYS + ["n0ea2fd9bfb9d", "n9ae8b6546ea5"]

REL_BLOCK_FULL_RE = re.compile(
    r"<h[1-6][^>]*>\s*(?:📖\s*)?" + re.escape(RELATED_MARK) + r"\s*</h[1-6]>\s*<ul[^>]*>.*?</ul>",
    re.S)

# (化けた文字列, 正しい文字列, 公開本文に現れる回数)。正しい側は原稿41の文言。
TEXT_FIXES = {
    "n4857a2f79084": [
        ("20代以上", "30代以上", 4),
        ("最初の20日", "最初の30日", 2),
        ("2ヶ月目で月15〜20万円、6ヶ月目で月20〜40万円",
         "3ヶ月目で月15〜20万円、6ヶ月目で月30〜40万円", 2),
        (">月20〜40万円<", ">月30〜40万円<", 1),
        (">月20〜40万円以上<", ">月30〜40万円以上<", 1),
        ("B帯で月20〜20万", "B帯で月20〜30万", 1),
        ("2ヶ月以上活動している方", "3ヶ月以上活動している方", 1),
        ("活動期間: 〜2ヶ月 ／", "活動期間: 〜3ヶ月 ／", 1),
        ("活動期間: 2〜6ヶ月 ／", "活動期間: 3〜6ヶ月 ／", 1),
        ("週5〜6日・2〜2時間", "週5〜6日・2〜3時間", 1),
        ("> ／ 配信頻度: 週5〜6日・2時間<", "> ／ 配信頻度: 週5〜6日・3時間<", 1),
        ("理由2：ライバルが少ない", "理由3：ライバルが少ない", 1),
        ("思い込み2：「何を話せば", "思い込み3：「何を話せば", 1),
        ("ステップ2：アプリをインストール＆アカウント作成（20分）",
         "ステップ3：アプリをインストール＆アカウント作成（30分）", 1),
        ("初配信（15〜20分でOK）", "初配信（15〜30分でOK）", 1),
        ("成功パターン2選", "成功パターン3選", 1),
        ("パターン2：「ラジオパーソナリティ型」", "パターン3：「ラジオパーソナリティ型」", 1),
        ("Q2. 1日何時間配信", "Q3. 1日何時間配信", 1),
        ("一人でやるより2倍速い", "一人でやるより3倍速い", 1),
        ("常連リスナーさんが2〜2人", "常連リスナーさんが2〜3人", 1),
        ("ターゲットリスナーさん：20〜50代", "ターゲットリスナーさん：30〜50代", 1),
        ("最初は1日20分〜1時間で十分", "最初は1日30分〜1時間で十分", 1),
    ],
    "n0ea2fd9bfb9d": [
        ("<strong>ノルマなし・退所自由</strong>の事務所なら",
         "<strong>ノルマのない</strong>事務所なら", 1),
    ],
    "n9ae8b6546ea5": [
        ("<strong>ノルマなし・退所自由</strong>を必ず確認。",
         "<strong>ノルマの有無</strong>を必ず確認。", 1),
    ],
}


def fix_text(key, html):
    for old, new, n in TEXT_FIXES.get(key, []):
        got = html.count(old)
        if got != n:
            raise RuntimeError(f"{key}: 『{old}』が {got} 回（期待 {n} 回）。本文が想定と違うので中断")
        html = html.replace(old, new)
    return html


def make_transform(catalog):
    def _t(key, html):
        html = fix_text(key, html)
        if key not in RELINK_KEYS:
            return html
        stripped, n = REL_BLOCK_FULL_RE.subn("", html, count=1)
        if n != 1:
            raise RuntimeError(f"{key}: あわせて読みたいブロックを外せなかった")
        # 外したあとの本文で選ぶ（本文中に既にある内部リンク先は候補から外れる）
        add_entry(catalog, catalog[key]["title"], stripped, key)
        rel = pick_related(key, catalog)
        if len(rel) < 3:
            raise RuntimeError(f"{key}: 関連記事が {len(rel)} 本しか選べない")
        out = insert_related(rel, catalog, key, stripped)
        if out is None:
            raise RuntimeError(f"{key}: 関連記事ブロックを入れる位置が見つからない")
        return out
    return _t


def main():
    plan = "--plan" in sys.argv
    s = req_session()
    catalog = build_catalog_light(s)
    t = make_transform(catalog)
    for key in KEYS:
        if key not in catalog:
            print(f"!! {key} が公開一覧に無い。skip")
            continue
        print(f"\n=== {key} {catalog[key]['title'][:40]}")
        if plan:
            body = get_note(s, key, draft=False)["body"]
            new = t(key, body)
            block = REL_BLOCK_FULL_RE.search(new) if key in RELINK_KEYS else None
            for k in re.findall(r"note\.com/taitan_118/n/(n[0-9a-f]+)",
                                block.group(0) if block else ""):
                print(f"   → {catalog[k]['title'][:50]}")
            print(f"   本文 {len(body)} → {len(new)}  文言の置換 {len(TEXT_FIXES.get(key, []))} 種")
            continue
        from note_leadmagnet_publish import publish_one
        marker = RELATED_MARK if key in RELINK_KEYS else TEXT_FIXES[key][-1][1]
        print("  結果:", publish_one(key, t, expect_marker=marker))


if __name__ == "__main__":
    main()
