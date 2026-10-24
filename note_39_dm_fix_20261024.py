#!/usr/bin/env python3
"""#39 n9b5e9d5abc25 のスカウトDM推奨を代理店LPの方針（3つの入口）に揃える（2026-10-24）。

代理店LP（lp/agency）の FAQ は「どうやって興味のある人を見つけるんですか？」に
①SNSで役に立つ話を発信して相談される側に回る ②すでにつながっている人に近況として話す
③無所属のライバーの配信をリスナーさんとして見に行き、関係ができてから話す
「面識のない相手への一斉DMは推奨していません——届かないうえにアカウントを危険にさらす」
と答え、特典ガイドの方針欄でも「面識のない人へ一斉にDMを送るやり方」をNGとしている。
一方 #39 は「平日21時 スカウトDM送信（5〜10通）」「スカウトDM数・返信率を毎週記録」
「Q4. スカウトDMは迷惑がられませんか？→パーソナライズすれば返信率は格段に上がる」と、
一斉DMを前提にした書き方だった。

ユーザー確認（2026-10-24）:
  ・DM前提の記述は **LPの3つの入口に書き換える**（Q4 は LP の FAQ どおりに答える）
  ・「最低でも週3回は発信」「最低3ヶ月のコミット」は **根拠なし→数字を外す**

使い方:
  python3 note_39_dm_fix_20261024.py --dry-run | --md | --publish | --verify
"""
import glob
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from facts_patterns import common_violations  # noqa: E402
from note_agency_income_fix_20261024 import _html_rule, fetch_public  # noqa: E402

KEY = "n9b5e9d5abc25"
MD_GLOB = os.path.join(BASE_DIR, "blog", "articles_note", "39_*.md")

# (原稿mdの旧, 新)。公開本文には ** を <strong> に読み替えて当てる
RULES = [
    ("「誰でもいいからスカウトする」では**刺さるメッセージが書けません**。",
     "「誰にでも同じ話をする」では**相手に刺さりません**。"),
    ("代理店ビジネスは**最低3ヶ月のコミット**が必要です。最初の1ヶ月は種まきの期間。",
     "代理店ビジネスは**関係づくりから始まるので、時間がかかります**。最初のうちは種まきの期間。"),
    ("投稿が止まっているアカウントにDMを送っても、**信頼されません**。最低でも週3回は発信を続けましょう。",
     "発信が止まっているアカウントには、**相談してもらえません**。無理のないペースで、発信を止めないことが大切です。"),
    ("共通点1：毎日30分のスカウト活動を継続している",
     "共通点1：毎日30分の発信と関係づくりを続けている"),
    ("大量に一気にやるより、**毎日コツコツ**のほうが圧倒的に結果が出ます。",
     "SNSでの発信や、無所属のライバーの配信をリスナーさんとして見に行くことを**毎日コツコツ**続けると、"
     "相談してもらえる関係が少しずつ増えていきます。"),
    ("これがスカウト時の**信頼の基盤**になります。",
     "これが「この人に相談したい」と思ってもらえる**信頼の基盤**になります。"),
    ("DMで「稼げますよ！」と売り込むのではなく、**「今どんなこと悩んでますか？」と相手の話を聞く**。"
     "この姿勢が返信率を劇的に上げます。",
     "「稼げますよ！」と売り込むのではなく、**「今どんなこと悩んでますか？」と相手の話を聞く**。"
     "相談してくれた人にも、すでにつながっている人にも、この姿勢は同じです。"),
    ("スカウトDM数・返信率・面談数・契約数・継続率を**毎週記録**しています。"
     "**改善ポイントが見える人は、必ず伸びます**。",
     "相談の数・面談数・所属数・配信を続けているライバーの数を**毎週記録**しています。"
     "**改善ポイントが見えるので、打ち手を変えられます**。"),
    # 1日の例（原稿は表、公開本文は「時間: … ／ 活動内容: …」の箇条書き。セルの文言だけ当てる）
    ("スカウト候補のリサーチ", "相談をくれた人・つながりのある人への返信"),
    ("**スカウトDM送信（5〜10通）**", "**無所属のライバーの配信をリスナーさんとして見に行く**"),
    ("ライバーの配信を見に行く・フォロー連絡", "所属したライバーの配信を見に行く・フォロー連絡"),
    ("Q4. スカウトDMは迷惑がられませんか？", "Q4. 知らない人にDMを送らないといけませんか？"),
    ("**A. 送り方次第です。** テンプレ丸出しのDMは嫌われます。**相手のプロフィールを読んで、"
     "パーソナライズしたメッセージ**を送れば、返信率は格段に上がります。",
     "**A. いいえ。** TAITAN PROでは、**面識のない相手への一斉DMは推奨していません**。"
     "届かないうえに、アカウントを危険にさらすためです。入口は主に3つです。"
     "①SNSで配信にまつわる役に立つ話を発信して、相談される側に回る "
     "②すでにつながっている人に近況として話す "
     "③無所属のライバーの配信をリスナーさんとして見に行き、関係ができてから話す。"
     "具体的な進め方は研修とトークの型でお伝えします。"),
]

GONE = ["スカウトDM", "返信率", "5〜10通", "パーソナライズ", "週3回", "最低3ヶ月",
        "スカウト候補のリサーチ", "必ず伸びます", "圧倒的に結果"]
NEW_MARK = "面識のない相手への一斉DMは推奨していません"


def transform_html(key, html):
    out = html
    for old, new in RULES:
        pat, rep = _html_rule(old, new)
        out = pat.sub(lambda m: rep, out)
    return None if out == html else out


def problems(d):
    # 「あわせて読みたい」の他記事タイトル（「…DM返信率を上げる…」）は本文ではないので除いて見る
    body = d.get("body", "")
    cut = body.find("あわせて読みたい")
    own = body[:cut] if cut != -1 else body
    out = [f"残存: {g}" for g in GONE if g in own]
    if NEW_MARK not in body:
        out.append("新しい文言が反映されていない")
    out += [f"{r}: {h}" for r, h in common_violations(d.get("name", "") + "\n" + body)]
    return out


def dry_run():
    d = fetch_public(KEY)
    nb = transform_html(KEY, d["body"])
    if nb is None:
        print("変更なし")
        return
    n = sum(1 for old, _ in RULES if _html_rule(old, "")[0].search(d["body"]))
    print(f"[BODY] {len(d['body'])} -> {len(nb)}  当たったルール {n}/{len(RULES)}")
    print("直したあとの問題:", problems({"name": d["name"], "body": nb}) or "なし")


def fix_md():
    p = glob.glob(MD_GLOB)[0]
    src = open(p, encoding="utf-8").read()
    new = src
    for old, new_s in RULES:
        if old not in new:
            print(f"  ⚠ 原稿に無い: {old[:30]}")
        new = new.replace(old, new_s)
    if new != src:
        open(p, "w", encoding="utf-8").write(new)
    left = [g for g in GONE if g in new] + [r for r, _ in common_violations(new)]
    print(f"  updated {os.path.relpath(p, BASE_DIR)}  残={left or 'なし'}")


def publish():
    from note_leadmagnet_publish import publish_one
    publish_one(KEY, transform_html, expect_marker=NEW_MARK)


def verify():
    for attempt in range(4):
        d = fetch_public(KEY)
        left = problems(d)
        if not left:
            break
        time.sleep(6)  # CDN反映ラグ
    tags = len(d.get("hashtag_notes", []))
    ok = not left and tags > 0 and d.get("eyecatch")
    print(f"{'OK' if ok else 'NG'} #39 {KEY} tags={tags} "
          f"eyecatch={'OK' if d.get('eyecatch') else 'MISSING'}")
    for p in left:
        print(f"   {p}")
    return ok


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--dry-run":
        dry_run()
    elif arg == "--md":
        fix_md()
    elif arg == "--publish":
        publish()
    elif arg == "--verify":
        raise SystemExit(0 if verify() else 1)
    else:
        print(__doc__)
        raise SystemExit(1)
