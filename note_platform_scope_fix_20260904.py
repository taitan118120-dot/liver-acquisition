#!/usr/bin/env python3
"""公開中のnote記事から「取扱外プラットフォームへの誘導」を消す（2026-09-04）。

[[feedback_note_target_platforms]] で取扱は Pococha・TikTok LIVE・17LIVE の3つに
決まっている。ところが 2026-09-04 に note_live_facts_guard で全148本を実測すると、
**25本の公開本文**に IRIAM / ふわっち / SHOWROOM / REALITY が残っていた。
WARN 扱いなので番犬は緑のままで、誰も気づいていなかった。

ただし25本が全部同じ害ではない。文脈を1本ずつ読むと2種類に割れる:

  (a) 読者を取扱外アプリへ**推奨・誘導している** … 16本。これが問題。
      いちばん重いのが n2b77c40294ef #73（顔バレ・身バレ）の FAQ で、
        「IRIAMやPocochaラジオなら、顔出しなしでもコアファンが付きやすく、
          月収50万円以上稼ぐライバーもいます」
      と書いたうえで、記事末では公式LINE登録に誘っている。**自社で受けられない
      需要を自分で作っている**形で、[[project_ai_geo_channel]] の通り Note は
      AI経由の実入会が出ている入口なので、そのまま取り逃がしになる。
      n6006676b8d6e #65 に至っては「IRIAMやPocochaのラジオ配信専門の**事務所**を
      選ぶのがおすすめです」で、他社事務所へ送っていた。

  (b) 比較表・一般論で名前が出るだけ … 9本。触らない。
      うち7本（#61 #53 #50 #48 #33 #23 #9）は既に
      「TAITAN PROが取り扱っているのは Pococha・TikTok LIVE・17LIVE の3つ／
        それ以外は自力運用が前提」の但し書きが入っていて、立て付けとして正しい。
      残り2本（#60 スカウトDM運用論＝代理店向けの実務、#40 事務所の仕組み＝
      「配信プラットフォーム（Pococha、17LIVE、IRIAMなど）」という登場人物の例示）は
      読者をアプリへ送る文脈ではない。

顔出しなしの受け皿は **Pococha のラジオ配信** に寄せる。n79d526cf01a9 #9
「顔出しなしでライバーはできる？」が既にその立て付けで、そこが正本。
プラットフォーム紹介の枠そのものを埋め直す必要がある記事（#41 #5 #1）は、
IRIAM の枠を 17LIVE / TikTok LIVE に差し替えて取扱3つで閉じる。

やっていること（note_income_floor_fix_20260904.py と同じ作法）:
  - 公開本文（HTML）とローカル原稿（Markdown）の**両方**に当てる。片方だけ直すと
    乖離する（[[project_note_pv_stats]]）。原稿は次の一括スクリプトで公開側へ
    戻ってくるので、放置すると復活する。
  - 置換はすべて**完全一致・出現1回**。0回でも2回以上でも止める。
  - 要素ごと消す場合だけは例外で、note が保存のたびに name/id を振り直すため
    タグ属性を含む完全一致が書けない。そこで cut_element / cut_span を使い、
    「アンカー文字列が1回だけ」を確認したうえで前後のタグ境界まで削る。
    削った塊は --plan で必ず表示する（目視できない削除はしない）。
  - PUT の前に元の本文を data/note_body_backup/<key>.json に退避する。
  - 反映確認は**ログアウト状態の公開API**（Cache-Control: no-cache）。
    PUT:200 は反映の証拠にならない。

意図的に直していないもの:
  - (b) の9本すべて（上記）
  - パターン外の取扱外アプリ（TwitCasting/ツイキャス・Bigo Live・ミラティブ・
    Hakuna・Mildom）。facts_patterns の取扱外パターンが見ていないので今回の
    実測25件に入っていない。#1 の「4. TwitCasting … おすすめ度★★★☆☆」など
    同じ害の形が残る。パターン側を広げる話なので別件にする。

使い方:
  python3 note_platform_scope_fix_20260904.py --plan          # 差分を出すだけ（GETのみ）
  python3 note_platform_scope_fix_20260904.py --local         # ローカル原稿だけ直す
  python3 note_platform_scope_fix_20260904.py --apply         # 公開本文を直す（PUT）
  python3 note_platform_scope_fix_20260904.py --apply <key>…  # 記事を絞って直す
  python3 note_platform_scope_fix_20260904.py --verify        # 公開APIで再検品
"""
import json
import os
import re
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

BACKUP_DIR = os.path.join(BASE_DIR, "data", "note_body_backup")
LOG_FILE = os.path.join(BASE_DIR, "data", "note_platform_scope_log.json")
ARTICLE_DIR = os.path.join(BASE_DIR, "blog", "articles_note")

PUBLIC_API = "https://note.com/api/v3/notes/{key}"
PUBLIC_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "application/json",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

BATCH = 8
BATCH_SLEEP = 25

# ── 差し替え表 ─────────────────────────────────────────────
# key: {"md": 原稿ファイル名, "html": [(旧, 新), …], "cut": [op, …], "text": [(旧, 新), …]}
#   html … 公開本文に当てる (旧, 新)。**タグ属性を含まない**部分文字列で書く
#          （note は保存のたびに name/id を振り直すので属性込みの一致は必ず腐る）
#   cut  … 要素ごと削る。("elem", アンカー文字列, タグ名) / ("span", 先頭文字列, 終端文字列)
#   text … ローカル原稿（Markdown）に当てる。表は | 区切りなのでHTMLとは別物
FIXES = {
    # ── #76 月収100万円ライバーの共通点 ────────────────────────
    # FAQ「月収100万円ライバーはどのプラットフォームが多い？」の答えに、
    # 取扱3つ＋IRIAM を並べていた。取扱の枠そのものが崩れる形なので IRIAM を落とす。
    "nf4cc6b26f530": {
        "md": "76_月収100万円ライバー共通点.md",
        "html": [("<strong>Pococha・TikTok LIVE・17LIVE・IRIAM</strong>が多いです。",
                  "<strong>Pococha・TikTok LIVE・17LIVE</strong>が多いです。")],
        "text": [("**Pococha・TikTok LIVE・17LIVE・IRIAM**が多いです。",
                  "**Pococha・TikTok LIVE・17LIVE**が多いです。")],
    },
    # ── #74 配信ゴールデンタイム ──────────────────────────────
    # 「プラットフォーム別 最適配信時間」に IRIAM の節があった。
    # 平日22:00〜深夜2:00 まで書いてあり、取扱外アプリの**運用ガイド**になっている。
    # 節ごと落とすと Pococha / TikTok LIVE / 17LIVE の3つで閉じる。
    "ne31d02263e2f": {
        "md": "74_配信ゴールデンタイム完全ガイド.md",
        "html": [],
        "cut": [("span", "■ IRIAM", "</ul>")],
        "text": [("### IRIAM\n\n- **平日**：22:00〜深夜2:00（リスナーさんが定着しやすい）\n"
                  "- **土日**：14:00〜17:00 or 21:00〜深夜\n\n", "")],
    },
    # ── #73 顔バレ・身バレ対策 ────────────────────────────────
    # 今回いちばん重い1本。比較表で IRIAM を「◎ 完全顔出し不要」の最上位に置き、
    # 「顔出しNGなら、IRIAMかPocochaラジオ一択」と断定し、FAQ で
    # 「IRIAMやPocochaラジオなら…月収50万円以上稼ぐライバーもいます」まで書いて、
    # そのうえで記事末は公式LINE登録。顔出しなしを探している読者を丸ごと外へ流していた。
    # 取扱外3行（IRIAM・ふわっち・SHOWROOM）を表から落として、Pococha ラジオに寄せる。
    "n2b77c40294ef": {
        "md": "73_顔バレ身バレ対策完全ガイド.md",
        "html": [
            ("<strong>顔出しNGなら、IRIAMかPocochaラジオ一択</strong>。",
             "<strong>顔出しNGなら、Pocochaのラジオ配信が第一候補</strong>。"),
            # 「月収50万円以上稼ぐライバーもいます」は取扱外アプリの実績なので一緒に落とす。
            ("IRIAMやPocochaラジオなら、顔出しなしでもコアファンが付きやすく、"
             "月収50万円以上稼ぐライバーもいます。",
             "Pocochaのラジオ配信なら、顔出しなしでもコアファンが付きやすく、"
             "時間ダイヤで土台をつくれます。"),
        ],
        "cut": [
            ("elem", "プラットフォーム: IRIAM（Vアバター） ／ 顔出しなしの難易度: ◎ 完全顔出し不要", "li"),
            ("elem", "プラットフォーム: ふわっち ／ 顔出しなしの難易度: ○ ラジオOK", "li"),
            ("elem", "プラットフォーム: SHOWROOM ／ 顔出しなしの難易度: △ 一部可能", "li"),
        ],
        "text": [
            ("| IRIAM（Vアバター） | ◎ 完全顔出し不要 |\n", ""),
            ("| ふわっち | ○ ラジオOK |\n", ""),
            ("| SHOWROOM | △ 一部可能 |\n", ""),
            ("**顔出しNGなら、IRIAMかPocochaラジオ一択**。",
             "**顔出しNGなら、Pocochaのラジオ配信が第一候補**。"),
            ("IRIAMやPocochaラジオなら、顔出しなしでもコアファンが付きやすく、"
             "月収50万円以上稼ぐライバーもいます。",
             "Pocochaのラジオ配信なら、顔出しなしでもコアファンが付きやすく、"
             "時間ダイヤで土台をつくれます。"),
        ],
    },
    # ── #65 TikTokライバー事務所の選び方 ──────────────────────
    # 「顔出しNGならIRIAMやPocochaのラジオ配信専門の**事務所**を選ぶのがおすすめ」。
    # 事務所選びの記事で、他社事務所へ名指しで送っていた最悪の形。
    "n6006676b8d6e": {
        "md": "65_TikTokライバー事務所選び方.md",
        "html": [("顔出しNGならIRIAMやPocochaのラジオ配信専門の事務所を選ぶのがおすすめです。",
                  "顔出しNGなら、Pocochaのラジオ配信で始めたうえで、"
                  "ラジオ配信のサポート実績がある事務所を選ぶのがおすすめです。")],
        "text": [("顔出しNGならIRIAMやPocochaのラジオ配信専門の事務所を選ぶのがおすすめです。",
                  "顔出しNGなら、Pocochaのラジオ配信で始めたうえで、"
                  "ラジオ配信のサポート実績がある事務所を選ぶのがおすすめです。")],
    },
    # ── #62 TikTok LIVE 始め方 ────────────────────────────────
    # FAQ が「顔出しNGなら、IRIAMやPocochaのラジオ配信を検討してください」。
    # 冒頭の対比（PocochaやIRIAMと違い）も取扱3つの中で言い直せる。
    "nf70121f2fda2": {
        "md": "62_TikTokLIVE始め方完全ガイド.md",
        "html": [
            ("PocochaやIRIAMと違い、TikTok LIVEには", "Pococha や 17LIVE と違い、TikTok LIVEには"),
            ("顔出しNGなら、IRIAMやPocochaのラジオ配信を検討してください。",
             "顔出しNGなら、Pocochaのラジオ配信を検討してください。"),
        ],
        "text": [
            ("PocochaやIRIAMと違い、TikTok LIVEには", "Pococha や 17LIVE と違い、TikTok LIVEには"),
            ("顔出しNGなら、IRIAMやPocochaのラジオ配信を検討してください。",
             "顔出しNGなら、Pocochaのラジオ配信を検討してください。"),
        ],
    },
    # ── #57 ライバーデビュー準備 ──────────────────────────────
    # 「IRIAMは声だけの配信がメインなので、顔出しに抵抗がある人にはおすすめです」。
    # 明示的な推奨。同じ需要を Pococha のラジオ配信で受ける。
    "n576132a999ab": {
        "md": "57_ライバーデビュー準備.md",
        "html": [("IRIAMは声だけの配信がメインなので、顔出しに抵抗がある人にはおすすめです。",
                  "顔出しに抵抗がある人は、Pocochaで申請すればラジオ配信（音声のみ）も選べます。")],
        "text": [("IRIAMは声だけの配信がメインなので、顔出しに抵抗がある人にはおすすめです。",
                  "顔出しに抵抗がある人は、Pocochaで申請すればラジオ配信（音声のみ）も選べます。")],
    },
    # ── #56 副業ライバーおすすめ ──────────────────────────────
    # 4箇所で IRIAM を推している（一覧・箇条書き・「〜ならIRIAM」・FAQ）。
    # 箇条書きの枠は 17LIVE で埋めて取扱3つに寄せ、顔出しなしは Pococha ラジオへ。
    # FAQ の「自分の комфортゾーン」は生成時に混入したロシア語で、ついでに直る。
    "ndce8a9117fa4": {
        "md": "56_副業ライバーおすすめ.md",
        "html": [
            ("ライブ配信プラットフォームは、Pococha、Bigo Live、IRIAM、TikTok Liveなど、"
             "星の数ほど存在します。",
             "ライブ配信プラットフォームは、Pococha、TikTok LIVE、17LIVEをはじめ、"
             "星の数ほど存在します。"),
            ("<strong>IRIAM</strong>: イラスト1枚でVライバーになれる。顔出しなしで始めたい人に最適。",
             "<strong>17LIVE</strong>: イベント文化が強く、短期集中で盛り上がりを作りやすい。"
             "そのぶん収入の波は大きめ。"),
            ("たとえば、「顔出しは抵抗があるけど、声でリスナーさんと交流したい」ならIRIAM。"
             "「毎日コツコツ配信して、安定して稼ぎたい」ならPocochaがおすすめです。",
             "たとえば、「顔出しは抵抗があるけど、声でリスナーさんと交流したい」なら"
             "Pocochaのラジオ配信。「イベントで短期集中して結果を出したい」なら"
             "17LIVEが候補になります。"),
            ("顔出しせずに配信できるプラットフォームもありますし、"
             "IRIAMのようにイラスト1枚でVライバーとして活動する選択肢もあります。"
             "自分の комфортゾーンに合わせて選べますよ。",
             "Pocochaは申請すればラジオ配信（音声のみ）ができるので、"
             "顔を映さずに声だけで活動できます。自分に合うスタイルで選べますよ。"),
        ],
        "text": [
            ("ライブ配信プラットフォームは、Pococha、Bigo Live、IRIAM、TikTok Liveなど、"
             "星の数ほど存在します。",
             "ライブ配信プラットフォームは、Pococha、TikTok LIVE、17LIVEをはじめ、"
             "星の数ほど存在します。"),
            ("*   **IRIAM**: イラスト1枚でVライバーになれる。顔出しなしで始めたい人に最適。",
             "*   **17LIVE**: イベント文化が強く、短期集中で盛り上がりを作りやすい。"
             "そのぶん収入の波は大きめ。"),
            ("たとえば、「顔出しは抵抗があるけど、声でリスナーさんと交流したい」ならIRIAM。"
             "「毎日コツコツ配信して、安定して稼ぎたい」ならPocochaがおすすめです。",
             "たとえば、「顔出しは抵抗があるけど、声でリスナーさんと交流したい」なら"
             "Pocochaのラジオ配信。「イベントで短期集中して結果を出したい」なら"
             "17LIVEが候補になります。"),
            ("顔出しせずに配信できるプラットフォームもありますし、"
             "IRIAMのようにイラスト1枚でVライバーとして活動する選択肢もあります。"
             "自分の комфортゾーンに合わせて選べますよ。",
             "Pocochaは申請すればラジオ配信（音声のみ）ができるので、"
             "顔を映さずに声だけで活動できます。自分に合うスタイルで選べますよ。"),
        ],
    },
    # ── #45 ライバーの時給 ────────────────────────────────────
    # FAQ「顔出しなしだと時給は下がりますか？」の答えが IRIAM 頼み。
    "n72ac7218ef26": {
        "md": "45_ライバー時給.md",
        "html": [("ただしIRIAMなど音声アプリは固定リスナーさんが付きやすく、",
                  "ただしPocochaのラジオ配信は固定リスナーさんが付きやすく、")],
        "text": [("ただしIRIAMなど音声アプリは固定リスナーさんが付きやすく、",
                  "ただしPocochaのラジオ配信は固定リスナーさんが付きやすく、")],
    },
    # ── #44 初配信のコツ ──────────────────────────────────────
    # FAQ「顔出ししないと緊張しない？」の答えで IRIAM を入口に据えていた。
    "n421fb46eb9a0": {
        "md": "44_初配信コツ.md",
        "html": [("IRIAMなど声だけのアプリで慣れてから顔出しに移行する人も多いです。",
                  "Pocochaのラジオ配信で慣れてから顔出しに移行する人も多いです。")],
        "text": [("IRIAMなど声だけのアプリで慣れてから顔出しに移行する人も多いです。",
                  "Pocochaのラジオ配信で慣れてから顔出しに移行する人も多いです。")],
    },
    # ── #41 40代・50代からライバー ────────────────────────────
    # おすすめアプリのランキング第2位に IRIAM を据えていた（第1位 Pococha・第3位 ツイキャス）。
    # 枠を 17LIVE に差し替える。「安定収入が見込める」「完全匿名で活動可能」は
    # 取扱外アプリについての断定でもあるので、17LIVE 側では書かない。
    "n4857a2f79084": {
        "md": "41_40代50代ライバー始め方.md",
        "html": [
            ("■ 第2位：IRIAM（イリアム）| 顔出しNGならこちら",
             "■ 第2位：17LIVE（イチナナ）| イベントで勝負したい方向け"),
            ("<strong>顔出しに抵抗がある方</strong>にはIRIAMが最適。",
             "<strong>イベントで短期集中して結果を出したい方</strong>には17LIVEが向いています。"),
            ("<strong>アバター（Vtuber）配信</strong>なので顔出し不要",
             "<strong>イベント文化が強く</strong>、盛り上がりを作りやすい"),
            ("<strong>声の魅力</strong>で勝負できる（大人の声は大きな武器）",
             "<strong>ギフト単価</strong>が比較的高い"),
            ("コアファンがつきやすく、<strong>安定収入</strong>が見込める",
             "顔出しに抵抗がある方は、<strong>Pocochaのラジオ配信</strong>という選択肢もある"),
            ("<strong>在宅で完全匿名</strong>のまま活動可能",
             "そのぶん<strong>収入の振れ幅は大きめ</strong>"),
            ("<strong>A. 顔出しなし（IRIAM・ラジオ配信）なら完全匿名で活動可能</strong>です。",
             "<strong>A. 顔出しなし（Pocochaのラジオ配信）なら匿名のまま活動できます</strong>。"),
        ],
        "text": [
            ("### 第2位：IRIAM（イリアム）| 顔出しNGならこちら",
             "### 第2位：17LIVE（イチナナ）| イベントで勝負したい方向け"),
            ("**顔出しに抵抗がある方**にはIRIAMが最適。",
             "**イベントで短期集中して結果を出したい方**には17LIVEが向いています。"),
            ("- **アバター（Vtuber）配信**なので顔出し不要",
             "- **イベント文化が強く**、盛り上がりを作りやすい"),
            ("- **声の魅力**で勝負できる（大人の声は大きな武器）",
             "- **ギフト単価**が比較的高い"),
            ("- コアファンがつきやすく、**安定収入**が見込める",
             "- 顔出しに抵抗がある方は、**Pocochaのラジオ配信**という選択肢もある"),
            ("- **在宅で完全匿名**のまま活動可能", "- そのぶん**収入の振れ幅は大きめ**"),
            ("**A. 顔出しなし（IRIAM・ラジオ配信）なら完全匿名で活動可能**です。",
             "**A. 顔出しなし（Pocochaのラジオ配信）なら匿名のまま活動できます**。"),
        ],
    },
    # ── #34 ライバーに容姿は関係ない ──────────────────────────
    # 「戦略2: Vtuber（アバター）配信に挑戦する」が丸ごと IRIAM/REALITY 推奨。
    # 戦略1 が既に Pococha ラジオなので、戦略2 は TikTok LIVE の
    #「顔を映さない構図」に差し替える（#53 #9 のルート②と同じ立て付け）。
    "n6b2f4704cdcc": {
        "md": "34_ライバー容姿関係ない.md",
        "html": [
            ("■ 戦略2: Vtuber（アバター）配信に挑戦する", "■ 戦略2: 顔を映さない構図で配信する"),
            ("IRIAMやREALITYなら、アバターを使って配信できます。自分の顔を出さずに、"
             "キャラクターとして活動できるので、容姿を一切気にする必要がありません。",
             "TikTok LIVEなら、手元の作業・イラスト・BGMなど「見せる素材」を主役にして、"
             "顔を映さない構図で配信できます。見せられるものが決まっている人ほど向いています。"),
        ],
        "text": [
            ("### 戦略2: Vtuber（アバター）配信に挑戦する", "### 戦略2: 顔を映さない構図で配信する"),
            ("IRIAMやREALITYなら、アバターを使って配信できます。自分の顔を出さずに、"
             "キャラクターとして活動できるので、容姿を一切気にする必要がありません。",
             "TikTok LIVEなら、手元の作業・イラスト・BGMなど「見せる素材」を主役にして、"
             "顔を映さない構図で配信できます。見せられるものが決まっている人ほど向いています。"),
        ],
    },
    # ── #26 ライバーの副業は会社にバレる？ ────────────────────
    # 「対策3: 顔出しを避ける」の手段として IRIAM を案内していた。
    # IRIAM を落とすと箇条書きの「Vtuber配信（アバター使用）」だけが宙に浮く
    # （取扱外の配信形式を勧めたまま名前だけ消える）ので、その行も一緒に落とす。
    "n9197ae57ed8a": {
        "md": "26_ライバー副業バレない.md",
        "html": [("Pocochaではラジオ配信も可能。IRIAMならイラスト1枚でVtuber配信ができます。",
                  "Pocochaでは申請すればラジオ配信（音声のみ）が可能です。"
                  "顔を映さずに声だけで活動できます。")],
        "cut": [("elem", "<strong>Vtuber配信</strong>（アバター使用）", "li")],
        "text": [
            ("- **Vtuber配信**（アバター使用）\n", ""),
            ("Pocochaではラジオ配信も可能。IRIAMならイラスト1枚でVtuber配信ができます。",
             "Pocochaでは申請すればラジオ配信（音声のみ）が可能です。"
             "顔を映さずに声だけで活動できます。"),
        ],
    },
    # ── #11 主婦がライバーで月20万円 ──────────────────────────
    # 「顔出しなしでもOK」の受け皿を Pococha と IRIAM の2択で出していた。
    # IRIAM の行を落とすと Pococha ラジオだけが残り、直後の
    # 「ラジオ配信なら部屋を映す必要もなく」と自然につながる。
    "n091ee2617062": {
        "md": "11_主婦ライバー.md",
        "html": [],
        "cut": [("elem", "<strong>IRIAM</strong>: イラストを使ったVtuber配信", "li")],
        "text": [("- **IRIAM**: イラストを使ったVtuber配信\n", "")],
    },
    # ── #10 大学生がライバーで月20万円 ────────────────────────
    "n3e1a72579743": {
        "md": "10_大学生ライバー.md",
        "html": [("A: Pocochaでは申請すればラジオ配信（音声のみ）も可能。"
                  "IRIAMならVtuber形式で配信できます。",
                  "A: Pocochaでは申請すればラジオ配信（音声のみ）も可能です。"
                  "顔を映さずに声だけで活動できます。")],
        "text": [("A: Pocochaでは申請すればラジオ配信（音声のみ）も可能。"
                  "IRIAMならVtuber形式で配信できます。",
                  "A: Pocochaでは申請すればラジオ配信（音声のみ）も可能です。"
                  "顔を映さずに声だけで活動できます。")],
    },
    # ── #5 ライバーの収入はぶっちゃけいくら？ ──────────────────
    # アプリ別の収入解説が Pococha / 17LIVE / IRIAM の3節構成で、IRIAM の節が
    # 「まだ参入者が少ないため穴場です」まで書いた完全な推薦文だった。
    # 枠を TikTok LIVE に差し替えると、そのまま取扱3つの解説になる。
    "n80a29386b5a8": {
        "md": "05_ライバー収入現実.md",
        "html": [
            ("■ IRIAM（イリアム）", "■ TikTok LIVE"),
            ("<strong>顔出しなしで稼げるのが最大の魅力。</strong>",
             "<strong>TikTok本体からの拡散力が最大の魅力。</strong>"),
            ("Vtuber形式のため、顔を出したくない方に人気。市場は成長中で、"
             "まだ参入者が少ないため穴場です。",
             "ショート動画からLIVEへ人を流せるため、アプリの外から新しいリスナーさんが"
             "入ってきます。ただし配信の開始にはフォロワー1,000人などの条件があります。"),
            ("逆に固定ファンが定着すれば、顔出しなしでも収入は積み上がっていきます。",
             "逆に固定ファンが定着すれば、収入は積み上がっていきます。"),
        ],
        "text": [
            ("### IRIAM（イリアム）", "### TikTok LIVE"),
            ("**顔出しなしで稼げるのが最大の魅力。**",
             "**TikTok本体からの拡散力が最大の魅力。**"),
            ("Vtuber形式のため、顔を出したくない方に人気。市場は成長中で、"
             "まだ参入者が少ないため穴場です。",
             "ショート動画からLIVEへ人を流せるため、アプリの外から新しいリスナーさんが"
             "入ってきます。ただし配信の開始にはフォロワー1,000人などの条件があります。"),
            ("逆に固定ファンが定着すれば、顔出しなしでも収入は積み上がっていきます。",
             "逆に固定ファンが定着すれば、収入は積み上がっていきます。"),
        ],
    },
    # ── #1 ライバーの始め方 ───────────────────────────────────
    # アプリ紹介の3番目に「IRIAM — 顔出しナシで始めたい人向け おすすめ度★★★★☆」。
    # おすすめ度つきで取扱外を推していた。枠を TikTok LIVE に差し替える。
    # ※ 4番目の TwitCasting（★★★☆☆）も取扱外だが、facts_patterns の
    #   取扱外パターンが見ていないため今回の実測に入っていない。別件で扱う。
    "n56e9a993492d": {
        "md": "01_ライバー始め方.md",
        "html": [
            ("■ 3. IRIAM（イリアム）— 顔出しナシで始めたい人向け",
             "■ 3. TikTok LIVE — 拡散力で新しいリスナーさんを集めたい人向け"),
            ("Vtuber特化のアプリ。自分のイラスト（Live2D）を使って配信できるので、"
             "顔出し不要。イラストは外注で3000円〜作れます。",
             "ショート動画からLIVEへ人を流せるのが最大の強み。配信の開始には"
             "フォロワー1,000人などの条件があるため、まずは動画投稿から入るのが定石です。"),
            ("またIRIAMならVtuber形式で配信できますし、ツイキャスなら声だけの配信も人気です。",
             "顔を映さずに声だけで活動できます。"),
        ],
        "text": [
            ("### 3. IRIAM（イリアム）— 顔出しナシで始めたい人向け",
             "### 3. TikTok LIVE — 拡散力で新しいリスナーさんを集めたい人向け"),
            ("Vtuber特化のアプリ。自分のイラスト（Live2D）を使って配信できるので、"
             "顔出し不要。イラストは外注で3000円〜作れます。",
             "ショート動画からLIVEへ人を流せるのが最大の強み。配信の開始には"
             "フォロワー1,000人などの条件があるため、まずは動画投稿から入るのが定石です。"),
            ("またIRIAMならVtuber形式で配信できますし、ツイキャスなら声だけの配信も人気です。",
             "顔を映さずに声だけで活動できます。"),
        ],
    },
}

# 触らないと決めた9本。--verify がここを鳴らしても正常。理由は冒頭の docstring。
KEEP_AS_IS = {
    "n5fa353fd8dd4": "#61 代表の経歴（渡り歩いた媒体）＋取扱3つの但し書きあり",
    "ne8d3dbf2befc": "#53 ルート③に「TAITAN PROが取り扱うのは3つ／自力運用が前提」明記",
    "nadf7bf475ea9": "#50 4プラットフォーム比較表＋取扱3つの但し書きあり",
    "n6194f89cb2aa": "#48 Pocochaとの比較表＋取扱3つの但し書きあり",
    "ne57e6ea14042": "#33 アプリ比較10選（記事の主題）＋取扱3つの但し書きあり",
    "ncb75e31303b6": "#23 メタバース配信のトレンド例示＋取扱3つの但し書きあり",
    "n79d526cf01a9": "#9 顔出しなしルート③に「サポートしていないので自力運用」明記（正本）",
    "nfde7bf8ebf40": "#60 代理店向けスカウトDM実務。媒体別の文体表でライバー誘導ではない",
    "n9bf9cb3baed8": "#40 「配信プラットフォーム（Pococha、17LIVE、IRIAMなど）」＝登場人物の例示",
}

PLATFORM_RE = re.compile(r"IRIAM|イリアム|SHOWROOM|ショールーム|ふわっち|REALITY")
# note が保存のたびに振り直す name/id。目視用に落とすだけで、判定には使わない。
ATTR_RE = re.compile(r' (?:name|id)="[0-9a-f-]+"')


def public_note(key, session=None):
    s = session or requests
    r = None
    for attempt in range(3):
        r = s.get(PUBLIC_API.format(key=key), headers=PUBLIC_HEADERS, timeout=30)
        if r.status_code == 200:
            return r.json()["data"]
        time.sleep(1 + attempt)
    raise RuntimeError(f"{key}: HTTP {r.status_code if r else '?'}")


def _already(new, text):
    """new が（見た目は変わらない形で）既に text に入っているか。

    そのまま `new in text` で見てはいけない。反映後の本文は note 側で形が変わる
    （note_geo_structure が「・」段落を <ul><li> に畳み、保存のたびに name/id を
    振り直し、<br> を段落に割る）ので、タグと行頭記号を落として照合する。
    """
    probe = re.sub(r"<[^>]+>", "", new).lstrip("・*-  　").strip()
    return bool(probe) and probe in re.sub(r"<[^>]+>", "", text)


def apply_pairs(text, pairs, where):
    """(旧, 新) を完全一致・出現1回で当てる。旧が0回でも新が既にあれば反映済みとして飛ばす。"""
    out = text
    for old, new in pairs:
        n = out.count(old)
        if n == 0 and (new == "" or _already(new, out)):
            continue
        if n != 1:
            raise RuntimeError(f"{where}: 『{old[:44]}』の出現が {n} 回（1回のはず）")
        out = out.replace(old, new)
    return out


def cut_element(html, anchor, tag, where):
    """anchor を含む <tag>…</tag> を丸ごと削る。(新html, 削った塊) を返す。

    note は保存のたびに name/id を振り直すので、タグ属性込みの完全一致は書けない。
    そこで「アンカーが本文に1回だけ」を確認してからタグ境界まで広げる。
    入れ子の同名タグを巻き込んでいないかも確認する（表の1行だけ消すつもりで
    リスト全体を消す事故を防ぐ）。
    """
    n = html.count(anchor)
    if n == 0:
        return html, None  # 反映済み
    if n != 1:
        raise RuntimeError(f"{where}: アンカー『{anchor[:40]}』の出現が {n} 回（1回のはず）")
    i = html.index(anchor)
    start = html.rfind(f"<{tag}", 0, i)
    if start < 0:
        raise RuntimeError(f"{where}: <{tag}> の開始タグが見つからない")
    close = f"</{tag}>"
    j = html.find(close, i)
    if j < 0:
        raise RuntimeError(f"{where}: {close} が見つからない")
    end = j + len(close)
    removed = html[start:end]
    if removed.count(f"<{tag}") != 1:
        raise RuntimeError(f"{where}: <{tag}> が入れ子で、意図より広い塊を消そうとしている")
    return html[:start] + html[end:], removed


def cut_span(html, head, tail, where):
    """head を含む要素の開始タグから、その後の tail の直後までを丸ごと削る。"""
    n = html.count(head)
    if n == 0:
        return html, None  # 反映済み
    if n != 1:
        raise RuntimeError(f"{where}: アンカー『{head[:40]}』の出現が {n} 回（1回のはず）")
    i = html.index(head)
    start = html.rfind("<", 0, i)
    if start < 0:
        raise RuntimeError(f"{where}: 開始タグが見つからない")
    j = html.find(tail, i)
    if j < 0:
        raise RuntimeError(f"{where}: 終端『{tail}』が見つからない")
    end = j + len(tail)
    return html[:start] + html[end:], html[start:end]


def apply_cuts(html, cuts, where, show=False):
    out = html
    for op in cuts:
        kind = op[0]
        if kind == "elem":
            out, removed = cut_element(out, op[1], op[2], where)
        elif kind == "span":
            out, removed = cut_span(out, op[1], op[2], where)
        else:
            raise RuntimeError(f"{where}: 未知の cut 種別 {kind}")
        if show and removed:
            print("     ✂ 削除: " + ATTR_RE.sub("", removed)[:240])
    return out


def fix_html(key, body, show=False):
    spec = FIXES[key]
    out = apply_pairs(body, spec.get("html", []), f"{key}(html)")
    out = apply_cuts(out, spec.get("cut", []), f"{key}(cut)", show=show)
    return re.sub(r"<p[^>]*></p>", "", out)


def md_path(key):
    return os.path.join(ARTICLE_DIR, FIXES[key]["md"])


def fix_local(keys):
    changed = 0
    for key in keys:
        path = md_path(key)
        if not os.path.exists(path):
            print(f"  ✗ 原稿なし {os.path.basename(path)}")
            continue
        src = open(path, encoding="utf-8").read()
        new = apply_pairs(src, FIXES[key]["text"], f"{key}(md)")
        if new == src:
            print(f"  変更なし {os.path.basename(path)}")
            continue
        open(path, "w", encoding="utf-8").write(new)
        print(f"  ✓ {os.path.basename(path)}  {len(src)} -> {len(new)}字")
        changed += 1
    print(f"\nローカル原稿: {changed} 本を更新")
    return changed


def backup(key, note):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"{key}.json")
    if os.path.exists(path):
        return path  # 最初の1回だけ残す（変換後で上書きしない）
    json.dump({"key": key, "title": note["name"], "body": note["body"],
               "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")},
              open(path, "w"), ensure_ascii=False, indent=1)
    return path


def plan(keys, session, show=True):
    ok = []
    for key in keys:
        d = public_note(key, session)
        try:
            new = fix_html(key, d["body"], show=show)
        except RuntimeError as e:
            print(f"  ✗ {key} {d['name'][:30]}\n     {e}")
            continue
        spec = FIXES[key]
        n = len(spec.get("html", [])) + len(spec.get("cut", []))
        left = len(PLATFORM_RE.findall(re.sub(r"<[^>]+>", "", new)))
        print(f"  ✓ {key} {d['name'][:36]}  body {len(d['body'])} -> {len(new)}字 "
              f"（{n}箇所／残り取扱外 {left}）")
        ok.append(key)
        time.sleep(0.4)
    print(f"\n変換可能: {len(ok)} / {len(keys)} 本")
    return ok


def apply(keys):
    from note_leadmagnet_publish import publish_one
    log = json.load(open(LOG_FILE)) if os.path.exists(LOG_FILE) else {}
    ok = skip = fail = 0
    for i, key in enumerate(keys, 1):
        d = public_note(key)
        print(f"\n[{i}/{len(keys)}] {key} {d['name'][:36]}", flush=True)
        print(f"  backup → {os.path.basename(backup(key, d))}")

        def _t(_key, live_html, _k=key):
            # publish_one は必ずライブ本文を取り直して渡してくる（並行セッション対策）。
            # plan 時点の差分を貼らず、ここでもう一度当て直す。
            new = fix_html(_k, live_html)
            return None if new == live_html else new  # 反映済みなら PUT しない

        try:
            r = publish_one(key, _t, expect_marker=None)
            log[key] = r
            ok += 1 if r == "ok" else 0
            skip += 1 if r == "skip" else 0
        except Exception as e:
            print(f"  !! 失敗: {e}", flush=True)
            log[key] = f"error: {e}"
            fail += 1
        json.dump(log, open(LOG_FILE, "w"), ensure_ascii=False, indent=1)
        time.sleep(BATCH_SLEEP if i % BATCH == 0 else 3)
    print(f"\n完了 ok={ok} skip={skip} fail={fail}")
    return fail


def verify(keys):
    """ログアウト状態の公開APIで実測する。PUT:200 は反映の証拠にならない。"""
    s = requests.Session()
    ng = 0
    for key in keys:
        d = public_note(key, s)
        text = re.sub(r"<[^>]+>", "", d["body"] or "")
        hits = sorted(set(PLATFORM_RE.findall(d["name"] + "\n" + text)))
        # 直した記事に残骸が無いかも見る（旧文字列がそのまま残っていたら反映漏れ）
        stale = [old[:30] for old, _ in FIXES[key].get("html", []) if old in d["body"]]
        stale += [op[1][:30] for op in FIXES[key].get("cut", []) if op[1] in d["body"]]
        bad = []
        if hits:
            bad.append("取扱外が残存 " + " / ".join(hits))
        if stale:
            bad.append("旧文字列が残存 " + " / ".join(stale))
        if not d.get("eyecatch"):
            bad.append("eyecatchなし")
        tags = len(d.get("hashtag_notes") or [])
        if tags < 10:
            bad.append(f"タグ{tags}")
        ng += 1 if bad else 0
        print(f"  {'NG ' + ' ／ '.join(bad) if bad else 'ok'}  {key} {d['name'][:34]}")
        time.sleep(0.8)
    print(f"\n検証: NG {ng} 本 / {len(keys)} 本")
    return ng


def main():
    args = sys.argv[1:]
    explicit = [a for a in args if a.startswith("n") and not a.startswith("--")]
    keys = explicit or list(FIXES)
    unknown = [k for k in keys if k not in FIXES]
    if unknown:
        raise SystemExit(f"差し替え表に無いキー: {unknown}")

    if "--verify" in args:
        sys.exit(1 if verify(keys) else 0)
    if "--local" in args:
        sys.exit(0 if fix_local(keys) is not None else 1)

    session = requests.Session()
    if "--plan" in args:
        plan(keys, session)
        return
    if "--apply" in args:
        ok = plan(keys, session, show=False)
        if len(ok) != len(keys):
            raise SystemExit("変換できない記事がある。先に差し替え表を直すこと")
        sys.exit(1 if apply(ok) else 0)
    raise SystemExit(__doc__.split("使い方:")[-1])


if __name__ == "__main__":
    main()
