#!/usr/bin/env python3
"""公開Note 112本の全数突合監査（2026-07-30）で見つかった確定ファクト違反を、公開側から除去する。

監査でわかったこと:
  ・ローカルmdが存在しない公開記事が2本あり、一括ファクト更新から漏れ続けていた
    （nd29c18b06dcc 新人期間完全攻略 / ne28bee508ca1 代理店とは）。
    後者には禁止表現「いつでも契約解除OK」が生き残っていた。[[feedback_no_free_exit_claim]]
  ・#05 は 2026-07-22 の b47ac86 で修正したはずが、公開側は旧版のまま
    （業界収入分布% と トップ層「月50万〜600万円以上」が残存）。
  ・2026-07-21 の「還元率100%+α」統一が、8本の本文で取りこぼされていた
    （TAITAN PRO紹介表だけ +α に更新され、本文が「還元率100%」のまま）。
  ・2026-07-15 の特典PDF改名（Pococha新人期→ライバー新人期）が5記事で取りこぼし。[[project_lead_magnet]]
  ・出典なし業界統計（#13/#14/#15/#22）、月収100万円の内訳具体数字（#76）、
    挫折率表現（#44）、断定表現（#2/#39/#48）、月10万の看板コピー（#1/#34/#53）、
    TikTok還元率の具体数字（#50）が残存。

機構は note_facts_fix_20260722.py と同じ（Chrome cookie + Playwright + reCAPTCHA + PUT + tag復元）。
ただし base の「リスナー→リスナーさん」一括置換は**使わない**（対象が広く
「リスナー層」「リスナー定着率」まで壊すため）。呼称は個別の置換文の中で直す。

使い方:
  python3 note_facts_fix_20260730.py --dry-run          # 全件ドライラン
  python3 note_facts_fix_20260730.py --dry-run <key>…   # 個別
  python3 note_facts_fix_20260730.py                     # 本番
"""
import re
import sys

import note_facts_fix_20260722 as base

NEW_PDF = "『ライバー新人期スタートダッシュガイド』"
OLD_PDF = "『Pococha新人期スタートダッシュガイド』"

# 還元率は「100%+α」で統一（+α の中身は断定しない）
RATE_RE = (r"還元率100%(?!\+α)", "還元率100%+α")


# key: {"num", "body":[(old,new)], "paras":{id:new|None}, "title":(old,new),
#       "regex":[(pat,repl)], "forbidden":[…], "forbidden_re":[…]}
FIXES = {
    # ── ローカルmdが無く一括更新から漏れていた2本 ───────────────
    "ne28bee508ca1": {
        "num": "md無", "label": "代理店とは",
        "body": [("<br>・いつでも契約解除OK", "")],
        "forbidden": ["いつでも契約解除", "Pococha新人期スタートダッシュガイド"],
    },
    "nd29c18b06dcc": {
        "num": "md無", "label": "新人期間完全攻略",
        "body": [
            ("失敗事例の8割は「<strong>孤独な試行錯誤</strong>」と「<strong>戦略の不在</strong>」が原因です。",
             "失敗事例に共通するのは「<strong>孤独な試行錯誤</strong>」と「<strong>戦略の不在</strong>」です。"),
        ],
        "forbidden": ["失敗事例の8割", "Pococha新人期スタートダッシュガイド"],
    },

    # 特典PDF改名の取りこぼし（#35/#63/#71）と #14 の「約60%」、#44 のタイトル・「そのうち8割」は
    # 2026-07-30 21〜22時台に別セッションが先に修正済み。ここでは対象から外す。

    # ── 還元率100% → 100%+α（本文の取りこぼし）─────────────
    "nb8a19480a23f": {"num": 98, "label": "会社員×代理店", "regex": [RATE_RE]},
    "n6b70b66ac397": {"num": 102, "label": "やめとけ", "regex": [RATE_RE]},
    "n76a0da65a0b3": {"num": 103, "label": "副業・在宅", "regex": [RATE_RE]},
    "n233d025744ba": {"num": 104, "label": "主婦・ママ", "regex": [RATE_RE]},
    "n673be1bcfcb8": {"num": 105, "label": "大学生", "regex": [RATE_RE]},
    "n6e53765e2224": {"num": 106, "label": "顔出しなし", "regex": [RATE_RE]},
    "n64aeaeb8876b": {"num": 107, "label": "事務所とフリー", "regex": [RATE_RE]},
    "nee22f1a16df4": {"num": 109, "label": "土日だけ副業", "regex": [RATE_RE]},

    # ── #05 業界収入分布%（出典なし統計）＋トップ層の月収レンジ ──
    "n80a29386b5a8": {
        "num": 5, "label": "収入の現実",
        "blocks": [
            ("■ ライバー全体の収入分布（推定）", "■ ライバー全体の収入イメージ"),
            ("・層: トップ層 ／ 月収目安: <strong>月50万</strong>〜600万円以上 ／ 割合: 約3%",
             "収入は<strong>「活動量 × 継続期間」</strong>で大きく変わります。"
             "始めたばかりの時期は小さな金額からのスタートですが、"
             "続けるほど積み上がっていくのが基本の形です。"
             "専業として大きく稼いでいる層もいますが、そこは特別な才能ではなく「続けた先」にあります。"),
            ("・層: 上位層 ／ 月収目安: <strong>月15万</strong>〜50万円 ／ 割合: 約7%", None),
            ("・層: 中間層 ／ 月収目安: <strong>月5万</strong>〜15万円 ／ 割合: 約15%", None),
            ("・層: 初心者〜中堅 ／ 月収目安: <strong>月1万</strong>〜5万円 ／ 割合: 約25%", None),
            ("・層: 始めたばかり ／ 月収目安: <strong>月0〜1万円</strong> ／ 割合: 約50%", None),
            ("見ての通り、<strong>月5万円以上稼いでいる人は全体の25%程度</strong>です。",
             "つまり、<strong>収入には大きな幅があります</strong>。"),
            ("ただし重要なのは、「稼げていない50%の多くは、配信を継続していない人」ということ。"
             "3ヶ月以上継続して週3回以上配信している人に限ると、<strong>月5万円</strong>以上の割合はぐっと上がります。",
             "ただし重要なのは、「伸びていない人の多くは、配信を継続していない人」ということ。"
             "3ヶ月以上継続して週3回以上配信している人ほど、手応えを感じられるラインに届きやすくなります。"),
        ],
        "forbidden": ["割合: 約3%", "割合: 約50%", "月50万</strong>〜600万円以上",
                      "全体の25%程度", "稼げていない50%"],
    },

    # ── #50 TikTok還元率の具体数字（確定ファクトで禁止）＋S帯月収＋倍率表現 ──
    "nadf7bf475ea9": {
        "num": 50, "label": "TikTokLIVE収益化",
        "blocks": [
            ("ライバーが受け取るのは<strong>ダイヤモンド</strong>で、"
             "<strong>1ダイヤモンド = 約0.5コイン相当</strong>の価値で還元されます。"
             "<strong>つまりギフト購入額の概ね50％がライバー側のダイヤモンド額面</strong>になります。",
             "ライバーが受け取るのは<strong>ダイヤモンド</strong>です。"
             "リスナーさんが支払った金額がそのまま渡るわけではなく、"
             "<strong>プラットフォーム手数料を差し引いた分</strong>がダイヤモンドとして還元されます。"),
            ("ダイヤモンドは<strong>1ダイヤモンド ≒ 0.005ドル前後（約0.7〜0.8円）</strong>で換金されます。"
             "為替・地域・TikTokの内部レート変動で前後するため、"
             "<strong>「概ねギフト購入額の30〜50％がライバーの最終的な手取り感」</strong>"
             "として認識しておくのが安全です。",
             "ダイヤモンドは日本円に換金しますが、為替・地域・TikTokの内部レート変動の影響を受けます。"
             "<strong>額面と最終的な手取りは一致しない</strong>と認識しておくのが安全です。"),
            ("・ステージ: リスナー購入額 ／ 金額（10,000円のギフトを贈られた場合の例）: "
             "<strong>10,000円</strong>",
             "・ステージ: リスナーさんのギフト購入 ／ 内容: "
             "<strong>支払われた金額の全額がライバーに渡るわけではありません</strong>"),
            ("・ステージ: TikTok手数料（プラットフォーム取り分・約50％） ／ "
             "金額（10,000円のギフトを贈られた場合の例）: -5,000円",
             "・ステージ: TikTok手数料（プラットフォーム取り分） ／ 内容: ここで差し引かれます"),
            ("・ステージ: ライバーのダイヤモンド額面 ／ 金額（10,000円のギフトを贈られた場合の例）: "
             "<strong>約5,000円相当</strong>",
             "・ステージ: ライバーのダイヤモンド額面 ／ 内容: 手数料を引いた残りがダイヤモンドになります"),
            ("・ステージ: 換金時のレート差・振込手数料 ／ 金額（10,000円のギフトを贈られた場合の例）: "
             "-数百〜千円程度",
             "・ステージ: 換金時のレート差・振込手数料 ／ 内容: さらにここでも目減りします"),
            ("・ステージ: <strong>ライバー実質手取り</strong> ／ "
             "金額（10,000円のギフトを贈られた場合の例）: <strong>約3,500〜4,500円</strong>",
             "・ステージ: <strong>ライバー実質手取り</strong> ／ 内容: "
             "<strong>額面より少なくなるのが普通です</strong>"),
            ("&gt; <strong>現役マネージャーの本音</strong>：「TikTokLIVEは50％バック」という記事を"
             "よく見かけますが、<strong>実態は「30〜45％の手取り」</strong>だと思っておいた方が安全です。"
             "為替・換金タイミング・最低換金額未満の繰越などで、"
             "<strong>額面通り入ってきたケースを見たことがありません</strong>。",
             "&gt; <strong>現役マネージャーの本音</strong>：ネット上には「TikTokLIVEは◯％バック」と"
             "断定する記事が多いのですが、<strong>額面どおりに入ってくると考えない方が安全</strong>です。"
             "為替・換金タイミング・最低換金額未満の繰越などで、"
             "<strong>額面通り入ってきたケースを見たことがありません</strong>。"),
            ("・項目: <strong>ギフト還元率（ライバー手取り目安）</strong> ／ "
             "<strong>TikTokLIVE</strong>: 約 <strong>30〜45％</strong> ／ "
             "<strong>Pococha</strong>: 約 <strong>40〜50％</strong> ／ "
             "<strong>17LIVE</strong>: 約 <strong>30〜40％</strong> ／ "
             "<strong>IRIAM</strong>: 約 <strong>40〜50％</strong>",
             "・項目: <strong>ギフトの手取り</strong> ／ <strong>TikTokLIVE</strong>: "
             "額面と手取りに差が出る ／ <strong>Pococha</strong>: 時間ダイヤがあるぶん収入が読みやすい ／ "
             "<strong>17LIVE</strong>: イベント次第で変動 ／ <strong>IRIAM</strong>: ギフトが中心"),
            ("■ 失敗2. <strong>ギフトの還元率を「50％」と勘違い</strong>",
             "■ 失敗2. <strong>ギフトの額面を、そのまま手取りだと勘違いする</strong>"),
            ("&gt; <strong>現役マネージャーの本音</strong>：当事務所のトップ層の多くは、"
             "<strong>TikTokショートでブランディング → プロフィールから「Pocochaやってます」と誘導 → "
             "Pocochaで月50万〜200万円</strong>、というモデルを回しています。"
             "<strong>「TikTokだけ」「Pocochaだけ」より、両輪で回した方が、収益も安全度も2〜3倍上がります</strong>。",
             "&gt; <strong>現役マネージャーの本音</strong>：当事務所のトップ層の多くは、"
             "<strong>TikTokショートでブランディング → プロフィールから「Pocochaやってます」と誘導 → "
             "Pocochaで伸ばす</strong>、というモデルを回しています。"
             "<strong>「TikTokだけ」「Pocochaだけ」より、両輪で回した方が、収益も安定度も上がります</strong>。"),
            ("■ Q2. ギフトの還元率は本当に50％ですか？",
             "■ Q2. ギフトの額面は、そのまま手取りになりますか？"),
            ("A. <strong>額面上は約50％</strong>ですが、<strong>為替・手数料・換金タイミング</strong>を"
             "加味した<strong>実質手取りは30〜45％</strong>です。"
             "「10万円分ギフトをもらった→3.5〜4.5万円が手元に残る」と理解してください。",
             "A. なりません。<strong>為替・手数料・換金タイミング</strong>の影響を受けるため、"
             "額面と実際に手元へ残る金額には差が出ます。"
             "<strong>ギフトの額面をそのまま収入として計算しない</strong>でください。"),
            ("・ギフトの<strong>実質手取りは30〜45％</strong>（額面50％ではない）",
             "・ギフトは<strong>額面と実質手取りが一致しない</strong>"
             "（為替・手数料・換金タイミングの影響を受ける）"),
        ],
        "forbidden": ["30〜45％", "概ね50％", "30〜50％がライバー", "還元率は本当に50％",
                      "月50万〜200万円", "2〜3倍上がります", "還元率（ライバー手取り目安）"],
    },

    # ── 出典なし業界統計 ─────────────────────────────
    "n75af519474d1": {
        "num": 13, "label": "イベント攻略",
        "body": [("実は、Pocochaでイベント入賞を経験したライバーの<strong>約70%が「初心者の頃に初入賞した」</strong>"
                  "と回答しています。",
                  "実は、Pocochaのイベントで初入賞を果たすライバーの多くは、"
                  "<strong>まだ初心者と呼ばれる時期</strong>に最初の入賞を経験しています。")],
        "forbidden": ["約70%が"],
    },
    "n03be7c901596": {
        "num": 15, "label": "男性ライバー",
        "body": [
            ("<strong>月収30万円以上の男性ライバーは全体の約15%</strong>と言われており、"
             "適切な戦略で十分に到達可能な数字です。",
             "男性ライバーでも<strong>月収30万円以上に届いている人</strong>は実際にいて、"
             "適切な戦略なら十分に狙えるラインです。"),
            ("データ上でも、男性ライバーの<strong>リスナー定着率は女性ライバーより約20%高い</strong>"
             "と言われています。",
             "実際、男性ライバーは<strong>一度ついたファンが離れにくい</strong>傾向があります。"),
        ],
        "forbidden": ["約15%", "約20%高い"],
    },
    "na08ce1921eb6": {
        "num": 22, "label": "30代ライバー",
        "body": [
            ("・Pocochaの利用者の<strong>約40%が25〜35歳</strong>",
             "・Pocochaの利用者は<strong>25〜35歳が大きな塊</strong>になっている"),
            ("・30代ライバーの月収中央値は20代より<strong>約20%高い</strong>",
             "・30代ライバーは<strong>収入が安定しやすい</strong>傾向がある"),
        ],
        "forbidden": ["約40%が25", "約20%高い"],
    },

    # ── 月収100万円の内訳具体数字（帰属ありでも禁止リスト該当）──
    "nf4cc6b26f530": {
        "num": 76, "label": "月収100万円の共通点",
        "body": [
            ("所属ライバー200名のうち、月収100万円超えライバー15名のリアルな共通点を、本音で全公開します。",
             "所属ライバー200名を見てきた中で、月収100万円を超えたメンバーに共通していたことを、本音で全公開します。"),
            ("15名のトップ層に共通する特徴を、出現頻度順に整理します。",
             "トップ層に共通する特徴を、出現頻度順に整理します。"),
            ("15名全員が、<strong>毎日同じ時間に最低3時間</strong>配信していました。",
             "例外なく、<strong>毎日同じ時間に最低3時間</strong>配信していました。"),
            ("15名全員、コアファン20〜50名の名前・特徴・職業・誕生日を完璧に記憶。",
             "全員が、コアファンの名前・特徴・職業・誕生日を完璧に記憶。"),
            ("15名のうち14名が、<strong>配信前に最低30分の準備</strong>をしていました。",
             "ほぼ全員が、<strong>配信前に最低30分の準備</strong>をしていました。"),
            ("15名全員が、<strong>「全リスナーを大切にする」のではなく、「コアファンを大切にする」</strong>"
             "スタンスを徹底。",
             "全員が、<strong>「リスナーさん全員を大切にする」のではなく、「コアファンを大切にする」</strong>"
             "スタンスを徹底。"),
            ("15名全員、<strong>月10〜30万円を自己投資</strong>に使っています。",
             "全員が、<strong>収入の一部を自己投資</strong>に回しています。"),
            ("15名全員、<strong>ふんわりではなく具体的な計画</strong>を立てています。",
             "全員が、<strong>ふんわりではなく具体的な計画</strong>を立てています。"),
            ("15名全員、<strong>マネージャー・先輩ライバー・コーチ</strong>など、相談相手を持っています。",
             "全員が、<strong>マネージャー・先輩ライバー・コーチ</strong>など、相談相手を持っています。"),
            ("15名全員、<strong>配信のために健康管理を最優先</strong>。",
             "全員が、<strong>配信のために健康管理を最優先</strong>にしています。"),
            ("15名の到達期間データ：", "到達までにかかった期間の傾向："),
        ],
        "forbidden": ["15名", "月10〜30万円を自己投資"],
    },

    # ── 挫折率表現（第4弾で除去と確定）──
    # タイトルと「そのうち8割は」は別セッションが先に修正済み。残った「残り7割は」だけを処理する。
    "n421fb46eb9a0": {
        "num": 44, "label": "初配信のコツ",
        "body": [
            ("<strong>初配信でリスナーが10人以上来た人は、私の200名中だいたい4人に1人</strong>でした。"
             "残り7割はリスナー0〜3人です。",
             "<strong>初配信でリスナーさんが10人以上来た人は、私の200名中でもごく一部</strong>でした。"
             "ほとんどの人はリスナーさん0〜3人からのスタートです。"),
        ],
        "forbidden": ["8割が翌日消える", "そのうち8割は", "残り7割は"],
    },

    # ── 断定的な誇大表現 ────────────────────────────
    "n2dc730f02053": {
        "num": 2, "label": "Pocochaは稼げる？",
        "body": [("Pocochaは時間ダイヤ制度があるおかげで、初心者でも確実に収入が得られる数少ないアプリです。",
                  "Pocochaは時間ダイヤ制度があるおかげで、"
                  "初心者でも配信した時間が収入につながる数少ないアプリです。")],
        "forbidden": ["確実に収入が得られる"],
    },
    "n9b5e9d5abc25": {
        "num": 39, "label": "代理店は稼げる？",
        "body": [
            ("ライバー代理店は<strong>正しくやれば確実に稼げるビジネスモデル</strong>です。",
             "ライバー代理店は<strong>正しくやれば収入を積み上げられるビジネスモデル</strong>です。"),
            ("まとめ｜ライバー代理店は「正しい努力」をすれば確実に稼げる",
             "まとめ｜ライバー代理店は「正しい努力」が積み上がるビジネス"),
        ],
        "forbidden": ["確実に稼げる"],
    },
    "n6194f89cb2aa": {
        "num": 48, "label": "Pococha始め方",
        "body": [("<strong>ランクに応じて時給が上がる設計</strong>なので、継続することで確実に収入が積み上がります。",
                  "<strong>ランクに応じて時給が上がる設計</strong>なので、"
                  "継続するほど収入が積み上がりやすくなります。")],
        "forbidden": ["確実に収入が積み上がります"],
    },

    # ── 月10万の看板コピー（収入目安は3ヶ月15〜20万／6ヶ月30〜40万で統一）──
    "n56e9a993492d": {
        "num": 1, "label": "ライバーの始め方",
        "body": [("顔出しなしで<strong>月10万円</strong>以上稼いでいる方もいます。",
                  "顔出しなしで<strong>月20万円</strong>以上稼いでいる方もいます。")],
        "forbidden": ["月10万円</strong>以上稼いでいる"],
    },
    "n6b2f4704cdcc": {
        "num": 34, "label": "容姿は関係ない",
        "body": [("・<strong>月収10万円以上のライバー</strong>の共通点は「継続力」と「コミュニケーション力」であり、"
                  "容姿との相関は低い",
                  "・<strong>安定して稼げているライバー</strong>の共通点は「継続力」と「コミュニケーション力」であり、"
                  "容姿との相関は低い")],
        "forbidden": ["月収10万円以上のライバー"],
    },
    "ne8d3dbf2befc": {
        "num": 53, "label": "IRIAM始め方",
        "body": [("<strong>月10万円以上を本気で目指す</strong>なら事務所所属を強く推奨します。",
                  "<strong>本気で収入を伸ばしたい</strong>なら事務所所属を強く推奨します。")],
        "forbidden": ["月10万円以上を本気で目指す"],
    },

    # ── 確定レンジとのズレ ───────────────────────────
    "n490e9578f165": {
        "num": 6, "label": "在宅副業7選",
        "body": [("・項目: 収入目安 ／ 内容: <strong>月15万</strong>〜40万円（3ヶ月目以降）",
                  "・項目: 収入目安 ／ 内容: <strong>3ヶ月目 月15〜20万円 / 6ヶ月目 月30〜40万円</strong>が目安"
                  "（伸び方は人によって大きく変わります）")],
        "forbidden": ["月15万</strong>〜40万円"],
    },
    "n091ee2617062": {
        "num": 11, "label": "主婦ライバー",
        "body": [("<strong>月25日で</strong>月18万<strong>〜25万円</strong>が目安です。",
                  "<strong>月25日</strong>続けた場合の目安です"
                  "（B帯の月収目安は20〜30万円。伸び方は人によって大きく変わります）。")],
        "forbidden": ["月18万<strong>〜25万円"],
    },
}

ORDER = list(FIXES.keys())


def replace_block(html, old_inner, new_inner):
    """<p|h2|h3 name="X" id="X">old_inner</p> をブロックごと差し替える／削除する。

    note.com は保存のたびにブロックidを振り直すため、idではなく**中身のHTMLで引き当てる**。
    （#50 は監査時のキャッシュとidが総取っ替えになっていた）
    """
    pat = re.compile(r'<(p|h2|h3)\s+name="([^"]+)"\s+id="\2"[^>]*>'
                     + re.escape(old_inner) + r'</\1>')
    m = pat.search(html)
    if not m:
        raise ValueError(f"ブロックが見つからない: {old_inner[:50]}…")
    if new_inner is None:
        return html[:m.start()] + html[m.end():]
    tag, bid = m.group(1), m.group(2)
    return html[:m.start()] + f'<{tag} name="{bid}" id="{bid}">{new_inner}</{tag}>' + html[m.end():]


def transform(key, html):
    """base.transform の差し替え。リスナー呼称の一括置換は行わない。"""
    spec = FIXES[key]
    out = html
    for old, new in spec.get("body", []):
        if old not in out:
            raise ValueError(f"置換対象が見つからない (key={key}): {old[:50]}…")
        out = out.replace(old, new)
    for old_inner, new_inner in spec.get("blocks", []):
        out = replace_block(out, old_inner, new_inner)
    for para_id, new_inner in spec.get("paras", {}).items():
        out = base.replace_para(out, para_id, new_inner)
    for pat, repl in spec.get("regex", []):
        out2 = re.sub(pat, repl, out)
        if out2 == out:
            raise ValueError(f"正規表現が1件も当たらない (key={key}): {pat}")
        out = out2
    return out


def apply_spec(key):
    """publish_one が参照する base 側のグローバルを、この key 用に差し替える。"""
    spec = FIXES[key]
    base.transform = transform
    base.TITLE_RULES = {key: spec["title"]} if "title" in spec else {}
    base.FORBIDDEN = list(spec.get("forbidden", []))


def verify_regex(key):
    """forbidden_re / 還元率パターンの事後検証（base の FORBIDDEN は literal のみ）。"""
    spec = FIXES[key]
    pats = list(spec.get("forbidden_re", []))
    if any(p == RATE_RE[0] for p, _ in spec.get("regex", [])):
        pats.append(r"還元率100%(?!\+α)")
    if not pats:
        return
    d = base.get_note(base.req_session(), key, draft=False)
    left = [p for p in pats if re.search(p, d["body"])]
    if left:
        raise RuntimeError(f"verify失敗（正規表現）: {left}")
    print("  --- verify(re) --- OK")


if __name__ == "__main__":
    args = sys.argv[1:]
    dry = "--dry-run" in args
    keys = [a for a in args if not a.startswith("--")] or ORDER
    results = {}
    for k in keys:
        spec = FIXES[k]
        print(f"[fix {k}] #{spec['num']} {spec['label']}")
        apply_spec(k)
        try:
            results[k] = base.publish_one(k, dry_run=dry)
            if not dry:
                verify_regex(k)
        except Exception as e:
            results[k] = f"ERROR: {e}"
            print(f"  !! {e}")
    print("\n=== 結果 ===")
    for k, v in results.items():
        print(f"  {k} #{FIXES[k]['num']:>4}  {v}")
    ng = [k for k, v in results.items() if str(v).startswith("ERROR")]
    if ng:
        print(f"\n失敗 {len(ng)} 件: {ng}")
        sys.exit(1)
