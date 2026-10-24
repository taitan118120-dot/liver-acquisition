#!/usr/bin/env python3
"""Note #25/#39/#43 の代理店パートナー収入を「金額を書かない」に揃える（2026-10-24）。

代理店LP（lp/agency）の収入目安は 2026-08-02 に
「1ヶ月目 月5万円〜／1〜3ヶ月 月10〜20万円（副業で取り組む方の平均レンジ）…」へ
変わったが、Note は旧LPの「副業レンジ 月3〜10万」のまま残っていて食い違っていた。
ユーザー確認（2026-10-24）:
  ・寄せ先 → **金額は書かない**（「人数と活動状況で変わる、目安は個別に案内」。LPは触らない）
  ・#39 の月収分布表（約30/35/25/10%）と「70%以上が月3万円以上」→ **実データではない**
    （2026-08-02 に「帰属ありなので維持」としていた判断を撤回）
  ・#39「月50万円以上を稼いでいるパートナーもいる」→ 事実なので残す
  ・#39「北海道から沖縄まで全国にいます」→ 根拠なし
#39 は同じ節に月3人ペースのシミュレーション表・「月5万円到達期間 3〜6ヶ月」・
「半年後に月10万円」「月10万円は現実的なゴール」もあり、LPの数字とも分布表とも
噛み合っていなかったので、収入の節を「何で決まるか」に組み直す（#37型）。
既定ルール [[feedback_dont_make_up_numbers]] で確認なしに定性化したもの（同じ記事の
事務所内部データを装った数字）: 「継続率が2倍以上変わるというデータ」
「パートナーの約半数はライバー未経験者」「副業パートナーの平均的な1日」。

公開の3段は note_publish_core（note_leadmagnet_publish.publish_one 経由）が正本。

使い方:
  python3 note_agency_income_fix_20261024.py --dry-run   # 置換結果を出す（GETのみ）
  python3 note_agency_income_fix_20261024.py --md        # ローカル原稿を直す
  python3 note_agency_income_fix_20261024.py --publish   # 3本を公開
  python3 note_agency_income_fix_20261024.py --verify    # ログアウト公開APIで検証
"""
import glob
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
NUM = {"ne7911c5b9ce9": "25", "n9b5e9d5abc25": "39", "n01815f0e5285": "43"}

# #39 の収入の節（「実績データをもとに…」〜「稼げない代理店パートナー」の手前）の差し替え後
BLOCK_39 = """この記事では、出所のわからない収入表やシミュレーションは使いません。かわりに、**代理店の収入が何で決まるのか**を、仕組みから説明します。

---

## 代理店パートナーの収入は「何で決まるか」

代理店パートナーの報酬は、紹介したライバーの活動に連動します。収入の大きさを決めるのは、次の3つです。

- **サポートしているライバーの人数**：所属までサポートしたライバーが何人いるか
- **そのライバーが配信を続けているか**：報酬が積み上がるのは、活動が続いている間だけ
- **そのライバーがどれだけ伸びるか**：配信の頻度や時間によって変わる

同じ人数を紹介していても、収入は人によって大きく変わります。金額の目安は条件によって違うので、個別にご案内しています。

### なぜ積み上がるのか

理由は**ビジネスモデルの構造**にあります。

1. **ストック型収益**：一度紹介したライバーが活動を続ける限り、報酬が毎月入り続ける
2. **積み上げ効果**：配信を続けているライバーの分に、新しく所属したライバーの分が上乗せされていく
3. **始めるお金がかからない**：加盟金・保証金・月会費が0円なので、うまくいかなくても始めるときに払ったお金が無駄になることはない

---

## 代理店の収入が積み上がる仕組み

代理店ビジネスの特徴は**ストック型収益**です。月ごとに見ると、収入はこう動きます。

- 新しく所属したライバーの分が、報酬に加わる
- 配信を続けているライバーの分は、毎月続く
- 配信をやめたライバーの分は、そこで止まる

つまり収入は「これまでに何人紹介したか」ではなく、**「今も配信を続けている人が何人いて、どれだけ活動しているか」**で決まります。だからこそ、紹介したあとのサポートが収入を左右します。

**ポイントは「紹介して終わり」ではなく「育てる」意識**。ライバーが稼げるようになれば、あなたの報酬も連動して上がります。**Win-Winの関係**が自然に成立するのです。
"""
BLOCK_39_MD_START = "TAITAN PROと提携している代理店パートナーの実績データをもとに"
BLOCK_39_MD_END = "**Win-Winの関係**が自然に成立するのです。\n"
BLOCK_39_HTML = re.compile(
    r"<p[^>]*>TAITAN PROと提携している代理店パートナーの実績データ.*?(?=<h2[^>]*>稼げない代理店パートナー)",
    re.S)

# (原稿mdの旧, 新)。公開本文には ** を <strong> に読み替えて当てる（_html_rule）
RULES = {
    "ne7911c5b9ce9": [  # #25
        ("副業（ライバー5〜10人担当）: **月3〜10万円**",
         "副業で取り組む場合: 担当ライバーの人数と活動状況で変わるので、目安は個別にご案内しています"),
    ],
    "n01815f0e5285": [  # #43
        ("**月3〜10万円**（TAITAN PROの代理店パートナーの副業レンジ）の継続報酬を安定させる",
         "継続報酬が毎月安定して入る状態をつくる"),
    ],
    "n9b5e9d5abc25": [  # #39
        ("一方、月10万円以上を安定して稼いでいるパートナーには**明確な共通点**があります。",
         "一方、収入を積み上げているパートナーには**共通点**があります。"),
        ("些細なことですが、**ライバーの継続率が2倍以上変わる**というデータがあります。",
         "些細なことですが、これだけで**ライバーが配信を続けやすくなります**。"),
        ("副業パートナーの平均的な1日を紹介します。", "副業で取り組む場合の1日の例です。"),
        ("これだけの稼働で、半年後に**月10万円の継続収入**が見えてくるのは、他の副業にはない魅力です。",
         "決まったシフトはないので、**本業の空き時間に合わせて組める**のが副業として続けやすいところです。"),
        ("TAITAN PROのパートナーの約半数はライバー未経験者です。",
         "TAITAN PROの代理店パートナーは未経験OKです。"),
        ("紹介するライバーの数が増えれば増えるほど、**青天井で収入は伸びていきます**。"
         "実際に月50万円以上を稼いでいるパートナーも存在します。",
         "サポートするライバーが増え、その活動が続くほど、**報酬は積み上がっていきます**。"
         "実際に月50万円以上を稼いでいるパートナーもいます。"),
        ("実際にTAITAN PROのパートナーは北海道から沖縄まで全国にいます。",
         "地方にお住まいでも、全国どこからでも活動できます。"),
        ("**70%以上のパートナーが月3万円以上**を達成",
         "収入は**サポートするライバーの人数と、その活動が続くか**で決まる"),
        ("正しい方法で、正しい量をこなせば、**月10万円は現実的なゴール**です。",
         "紹介したあとのフォローを続けられるかどうかが、**収入の差**になります。伸び方は人によって大きく変わります。"),
    ],
}

# 比較表の1行。原稿は表、公開本文は note_geo_structure が箇条書きにした形
ROW_39_MD = "| **月5万円到達期間** | **3〜6ヶ月** | 1〜3ヶ月 | 3〜6ヶ月 | 6〜12ヶ月 |\n"
ROW_39_HTML = re.compile(r"<li[^>]*><p[^>]*>項目: <strong>月5万円到達期間</strong>.*?</li>", re.S)

# 消したはずのもの。公開本文のどこにも残っていてはいけない
GONE = {
    "ne7911c5b9ce9": ["3〜10万"],
    "n01815f0e5285": ["3〜10万"],
    "n9b5e9d5abc25": ["約30%", "約35%", "約25%", "約10%", "70%以上", "成功率", "2026年4月時点",
                      "月3人ペース", "1〜2万円", "5〜8万円", "20〜40万円", "月5万円到達期間",
                      "半年後に", "月10万円", "2倍以上", "約半数", "平均的な1日", "青天井",
                      "北海道から沖縄", "実績データ"],
}
NEW_MARK = {
    "ne7911c5b9ce9": "目安は個別にご案内しています",
    "n01815f0e5285": "継続報酬が毎月安定して入る状態をつくる",
    "n9b5e9d5abc25": "代理店パートナーの収入は「何で決まるか」",
}

PUBLIC_API = "https://note.com/api/v3/notes/{key}"
PUBLIC_HEADERS = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache",
                  "Pragma": "no-cache"}


def _html_rule(old, new):
    from note_auto_poster import convert_inline_markdown
    pat = re.escape(old).replace(re.escape("**"), "</?strong>")
    return re.compile(pat), convert_inline_markdown(new)


def _block_39_html():
    from note_auto_poster import markdown_to_html
    # 原稿の区切り線は公開本文では空行段落になっている（既存の見た目に合わせる）
    md = "\n".join("" if line == "---" else line for line in BLOCK_39.strip("\n").split("\n"))
    return markdown_to_html(md) + "<p><br><br></p>"


def transform_html(key, html):
    out = html
    if key == "n9b5e9d5abc25":
        out = BLOCK_39_HTML.sub(lambda m: _block_39_html(), out, count=1)
        out = ROW_39_HTML.sub("", out)
    for old, new in RULES[key]:
        pat, rep = _html_rule(old, new)
        out = pat.sub(lambda m: rep, out)
    return None if out == html else out


def transform_md(key, md):
    out = md
    if key == "n9b5e9d5abc25" and BLOCK_39_MD_START in out:
        s = out.index(BLOCK_39_MD_START)
        e = out.index(BLOCK_39_MD_END, s) + len(BLOCK_39_MD_END)
        out = out[:s] + BLOCK_39 + out[e:]
        out = out.replace(ROW_39_MD, "")
    for old, new in RULES[key]:
        out = out.replace(old, new)
    return None if out == md else out


def problems(key, d):
    text = d.get("name", "") + "\n" + d.get("body", "")
    out = [f"残存: {g}" for g in GONE[key] if g in text]
    if NEW_MARK[key] not in text:
        out.append("新しい文言が反映されていない")
    out += [f"{r}: {h}" for r, h in common_violations(text)]
    return out


def fetch_public(key):
    r = requests.get(PUBLIC_API.format(key=key), headers=PUBLIC_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()["data"]


def md_path(key):
    return glob.glob(os.path.join(ARTICLE_DIR, f"{NUM[key]}_*.md"))[0]


def dry_run():
    for key in NUM:
        d = fetch_public(key)
        nb = transform_html(key, d["body"])
        print(f"\n#{NUM[key]} {key} {d['name'][:40]}")
        if nb is None:
            print("  変更なし")
            continue
        print(f"  [BODY] {len(d['body'])} -> {len(nb)}")
        print("  直したあとの問題:", problems(key, {"name": d["name"], "body": nb}) or "なし")
        time.sleep(0.3)


def fix_md():
    for key in NUM:
        p = md_path(key)
        src = open(p, encoding="utf-8").read()
        new = transform_md(key, src)
        if new is None:
            continue
        open(p, "w", encoding="utf-8").write(new)
        left = [g for g in GONE[key] if g in new] + [r for r, _ in common_violations(new)]
        print(f"  updated {os.path.relpath(p, BASE_DIR)}  残={left or 'なし'}")


def publish_all():
    from note_leadmagnet_publish import publish_one
    fail = 0
    for i, key in enumerate(NUM, 1):
        print(f"\n[{i}/{len(NUM)}] #{NUM[key]} {key}", flush=True)
        try:
            publish_one(key, transform_html, expect_marker=NEW_MARK[key])
        except Exception as e:  # noqa: BLE001 — 1本落ちても残りは処理する
            print(f"  !! 失敗: {type(e).__name__}: {e}", flush=True)
            fail += 1
        time.sleep(8)
    return fail


def verify():
    bad = 0
    for key in NUM:
        for attempt in range(4):
            d = fetch_public(key)
            left = problems(key, d)
            if not left:
                break
            time.sleep(6)  # CDN反映ラグ
        tags = len(d.get("hashtag_notes", []))
        ok = not left and tags > 0 and d.get("eyecatch")
        bad += not ok
        print(f"{'OK' if ok else 'NG'} #{NUM[key]} {key} tags={tags} "
              f"eyecatch={'OK' if d.get('eyecatch') else 'MISSING'} {d['name'][:36]}")
        for p in left:
            print(f"   {p}")
    print(f"\n検証 {len(NUM)} 本 / 問題 {bad} 本")
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
