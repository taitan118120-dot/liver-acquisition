#!/usr/bin/env python3
"""
Note記事 自動生成（Gemini API）
================================
SEOキーワードリストからカテゴリローテーションで
毎日新しい記事を自動生成する。

使い方:
  python3 note_article_generator.py --generate       # 1記事生成
  python3 note_article_generator.py --generate -n 3   # 3記事生成
  python3 note_article_generator.py --dry-run         # 生成せず確認
  python3 note_article_generator.py --generate -n 6 --category agency  # 代理店だけ6本
  python3 note_article_generator.py --list-unused     # 未使用キーワード一覧
  python3 note_article_generator.py --stats           # 統計情報

必要:
  pip install google-genai
  export GEMINI_API_KEY="your-api-key"
"""

import os
import sys
import re
import json
import glob
import random
import argparse
from datetime import datetime

# ─── パス設定 ─────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTICLES_DIR = os.path.join(BASE_DIR, "blog", "articles_note")
DATA_DIR = os.path.join(BASE_DIR, "data")
TRACKER_FILE = os.path.join(DATA_DIR, "note_keyword_tracker.json")

# ─── CTA ブロック ─────────────────────────────────────
# 長すぎるCTAは離脱要因。特典（リードマグネット）を受け取り理由にしてLINE登録へ誘導する。
# 「オンライン無料相談」という文言は使わない（CTAはLINE誘導に統一）。
#
# 2026-08-28: CTAを**カテゴリ別に出し分ける**ようにした。それまでは単一のCTAが
# 全記事の末尾に付き、代理店（＝事務所を"作る側"）向けの記事にも
#   ・ライバー向けLP `/beginner/`
#   ・ライバー向け特典『ライバー新人期スタートダッシュガイド』
# が出ていた。「会社員をしながら代理店をやる1週間の組み方」を読んだ人に
# 「新人ライバーの最初の30日」PDFを差し出していたことになる。
# 公式LINEは welcome で希望の種別を聞き分け、代理店希望者には
# 『ライバー代理店パートナー スタートガイド』を配る作りになっている（line_bot/messages.py）
# ので、記事側の訴求もそこへ合わせる。
SIGNATURE = "_— たいたん（TAITAN PRO代表 / 元Pococha Sランク / ミスターコン1位）_"

CTA_BLOCK_LIVER = """

---

ここまで読んでくださり、ありがとうございます。

TAITAN PROの公式LINEでは、友だち追加特典として**『ライバー新人期スタートダッシュガイド』**（最初の30日でやることを全部まとめた非売品PDF）を無料でお渡ししています。「自分もやってみたい」「もう少し聞いてみたい」という方は、特典を受け取りつつ気軽に聞いてください。ノルマなし・初期費用0円です。

**[LINEで特典を受け取る →](https://lin.ee/xchCfdn)**　|　**[サイトを見る →](https://taitan-pro-lp.netlify.app/beginner/?utm_source=note&utm_medium=article&utm_campaign=note_cta)**

""" + SIGNATURE + "\n"

CTA_BLOCK_AGENCY = """

---

ここまで読んでくださり、ありがとうございます。

TAITAN PROでは、ライバーとして活動する人だけでなく、**紹介して育てる側（代理店パートナー）**も一緒に増やしています。公式LINEでは友だち追加特典として**『ライバー代理店パートナー スタートガイド』**（何から手をつけて、どこでつまずくのかをまとめた非売品PDF）を無料でお渡ししています。

登録後に「代理店」と送っていただければ、ライバー向けではなく代理店パートナー向けの案内をお届けします。話を聞くだけでも大丈夫です。勧誘はしません。

**[LINEで代理店ガイドを受け取る →](https://lin.ee/xchCfdn)**　|　**[代理店パートナーのページを見る →](https://taitan-pro-lp.netlify.app/agency/?utm_source=note&utm_medium=article&utm_campaign=note_cta_agency)**

""" + SIGNATURE + "\n"


def cta_block_for(category):
    """記事カテゴリに合ったCTAを返す。agency は"作る側"なので代理店導線へ流す。"""
    return CTA_BLOCK_AGENCY if category == "agency" else CTA_BLOCK_LIVER


# 後方互換（外部から参照されている場合に備える）
CTA_BLOCK = CTA_BLOCK_LIVER

# Note人気・母集団の大きい汎用ハッシュタグ（各記事にランダム混入）
GENERAL_NOTE_TAGS = [
    "副業", "お金の勉強", "仕事について話そう", "自己紹介", "今こんな気分",
    "最近の学び", "毎日note", "ビジネス", "働き方", "キャリア", "スキルアップ",
]

# タイトルの型。**記事ごとに1つだけ渡す**（プロンプトに4つ並べて「選べ」と書くと、
# モデルは毎回いちばん強く見える1つを選ぶ）。
# 2026-08-30、agency 6本を生成したら6本とも D型の例文
# 「○○を知らないまま始めると、最初の1ヶ月で心が折れます」を丸写しにしていた。
# 6日連続で同じ形のタイトルが並ぶのはCTRにも効かないし、明らかに機械が書いた顔になる。
# 例文は「そのまま使える完成文」ではなく**言い回しの説明**にして、模倣先を潰す。
# [[feedback-ai-prompt-teaches-violations]] と同じ構図（模倣される位置に置いたものは真似される）。
TITLE_PATTERNS = [
    "数量提示型: 読者がこれから踏む手順の数や期間を示す（「5つ」「最初の3日」など）。"
    "**自分の実績を数量で語らないこと**——送ったDMの通数、支えた人数、返信率、達成率は"
    "どれも裏が取れないので書かない。使ってよい数字は【確定ファクト】に載っているものだけ",
    "逆説・本音型: 世間で言われている常識を先に否定し、そのあとに本音を置く。"
    "「実は」「正直に言うと」で始めない（使い古されている）",
    "失敗談型: 主語を「私」または「担当したライバーさん」にして、"
    "うまくいかなかった事実から入り、そこで何を変えたかを副題に置く",
    "問いかけ型: 読者がいま抱えている迷いをそのまま疑問文にする。"
    "答えを副題で先に少しだけ見せる",
    "断言型: これから何が起きるかを言い切る。**割合や人数では断言しない**"
    "（「9割が」型は禁止）。起きる出来事そのもので言い切ること",
]


# ─── SEO キーワードリスト（10カテゴリ） ────────────────
# 各キーワードの "p" は優先度で、2026-08-10 の公開124本のPV実測に基づく
# （data/note_pv_20260810.csv / 分析は data/note_pv_analysis_20260810.md）。
#   p=3 … 実測の勝ちテーマ。40-50代 / TikTok LIVE / Pococha / 顔出しなし /
#          配信テク（時間帯・枠）/ 収入の具体額
#   p=2 … 中位。母数はあるが平均止まり
#   p=1 … 実測で負けている、または未検証。抽選には残すが当たりにくい
# 抽選確率は「カテゴリ重み × p」。SHOWROOM/IRIAM/ふわっち/ミクチャ/ツイキャス単体の
# キーワードは集客対象プラットフォーム外なので**プールから除外**した（Pococha・
# TikTok LIVE・17LIVE のみ扱う）。退役させたキーワードは
# data/note_keyword_tracker.json の "retired" に理由付きで記録している。
SEO_KEYWORDS = {
    "lifestyle": [
        # 実測トップクラスタ。40-50代は PV/日中央 1.33・月間平均48・スキ平均8.0で全クラスタ1位
        {"keyword": "40代 ライバー 始める", "slug": "40代ライバー始める", "p": 3, "hashtags": ["40代", "ライバー", "副業", "始め方"]},
        {"keyword": "50代 ライブ配信 始める", "slug": "50代ライブ配信", "p": 3, "hashtags": ["50代", "ライブ配信", "ライバー", "始め方"]},
        {"keyword": "40代 50代 ライバー 収入 リアル", "slug": "40代50代ライバー収入", "p": 3, "hashtags": ["40代", "50代", "ライバー", "収入"]},
        {"keyword": "40代 50代 TikTokLIVE 始め方", "slug": "40代50代TikTokLIVE", "p": 3, "hashtags": ["40代", "50代", "TikTokLIVE", "始め方"]},
        {"keyword": "50代 Pococha 続け方", "slug": "50代Pococha続け方", "p": 3, "hashtags": ["50代", "Pococha", "ライバー", "継続"]},
        {"keyword": "40代 50代 配信 話す内容", "slug": "40代50代配信話す内容", "p": 3, "hashtags": ["40代", "50代", "雑談", "ライブ配信"]},
        {"keyword": "男性ライバー コツ 稼ぐ", "slug": "男性ライバーコツ", "p": 2, "hashtags": ["男性ライバー", "コツ", "稼ぐ", "ライバー"]},
        {"keyword": "30代 ライバー 遅くない", "slug": "30代ライバー遅くない", "p": 2, "hashtags": ["30代", "ライバー", "副業", "ライブ配信"]},
        {"keyword": "社会人 ライバー 副業", "slug": "社会人ライバー副業", "p": 2, "hashtags": ["社会人", "ライバー", "副業", "両立"]},
        {"keyword": "地方 ライバー 稼げる", "slug": "地方ライバー稼げる", "p": 2, "hashtags": ["地方", "ライバー", "稼げる", "在宅"]},
        # 主婦・ママは実測 PV/日中央 0.23・月間6.0で下位。数は絞って残す
        {"keyword": "主婦 ライバー 在宅 始め方", "slug": "主婦ライバー始め方", "p": 1, "hashtags": ["主婦", "ライバー", "在宅", "副業"]},
        {"keyword": "シングルマザー 副業 ライバー", "slug": "シンママ副業ライバー", "p": 1, "hashtags": ["シングルマザー", "副業", "ライバー", "在宅"]},
        {"keyword": "大学生 ライバー 稼ぐ 方法", "slug": "大学生ライバー稼ぐ", "p": 1, "hashtags": ["大学生", "ライバー", "稼ぐ", "副業"]},
        {"keyword": "看護師 副業 ライバー", "slug": "看護師副業ライバー", "p": 1, "hashtags": ["看護師", "副業", "ライバー", "在宅"]},
        {"keyword": "フリーター ライバー 生活", "slug": "フリーターライバー", "p": 1, "hashtags": ["フリーター", "ライバー", "生活", "収入"]},
    ],
    # [[feedback_note_target_platforms]]: SHOWROOM/IRIAM/ふわっち の単体記事は書かない。
    # 2026-08-10: この3つの単体キーワードが残っていて、「ふわっち 稼げる 仕組み」は
    # 実際に記事#58として生成・公開まで到達していた（2026-04-26）。
    # プロンプト側に「IRIAM/SHOWROOMは出さない」と書いても、キーワードで
    # お題として渡していたら意味がないので、キーワード自体を外す。
    # 除外の範囲は x_post_guard の「取扱外プラットフォーム」と同じ
    # （IRIAM/SHOWROOM/ふわっち/REALITY）。ツイキャス・ミクチャはそこに入っていない。
    "platform": [
        # TikTokLIVEクラスタは週間PV平均12.9で全クラスタ1位。Pocochaが総PVの母体
        {"keyword": "TikTokLIVE 収益化 条件", "slug": "TikTokLIVE収益化", "p": 3, "hashtags": ["TikTokLIVE", "収益化", "条件", "ライバー"]},
        {"keyword": "TikTokLIVE フォロワー 増やし方", "slug": "TikTokLIVEフォロワー増やし方", "p": 3, "hashtags": ["TikTokLIVE", "フォロワー", "増やし方", "ライバー"]},
        {"keyword": "TikTokLIVE 配信時間 目安", "slug": "TikTokLIVE配信時間目安", "p": 3, "hashtags": ["TikTokLIVE", "配信時間", "目安", "ライバー"]},
        {"keyword": "TikTokLIVE 伸びない 原因", "slug": "TikTokLIVE伸びない原因", "p": 3, "hashtags": ["TikTokLIVE", "伸びない", "原因", "対策"]},
        {"keyword": "Pococha 稼ぎ方 攻略 2026", "slug": "Pococha稼ぎ方2026", "p": 3, "hashtags": ["Pococha", "稼ぎ方", "攻略", "ライバー"]},
        {"keyword": "Pococha 新人期間 過ごし方", "slug": "Pococha新人期間過ごし方", "p": 3, "hashtags": ["Pococha", "新人期間", "過ごし方", "ライバー"]},
        {"keyword": "Pococha ランク制度 仕組み", "slug": "Pocochaランク制度", "p": 2, "hashtags": ["Pococha", "ランク", "制度", "ライバー"]},
        {"keyword": "Pococha 時間ダイヤ 計算 2026", "slug": "Pococha時間ダイヤ計算", "p": 2, "hashtags": ["Pococha", "時間ダイヤ", "計算", "収入"]},
        {"keyword": "Pococha オフの日 使い方", "slug": "Pocochaオフの日使い方", "p": 2, "hashtags": ["Pococha", "オフの日", "配信", "ライバー"]},
        {"keyword": "17LIVE 始め方 初心者", "slug": "17LIVE始め方", "p": 2, "hashtags": ["17LIVE", "始め方", "初心者", "ライバー"]},
        {"keyword": "17LIVE イベント 攻略", "slug": "17LIVEイベント攻略", "p": 2, "hashtags": ["17LIVE", "イベント", "攻略", "ライバー"]},
        {"keyword": "Pococha TikTokLIVE 17LIVE 掛け持ち", "slug": "3アプリ掛け持ち", "p": 2, "hashtags": ["Pococha", "TikTokLIVE", "17LIVE", "掛け持ち"]},
        {"keyword": "Pococha 17LIVE どっち", "slug": "Pococha17LIVE比較", "p": 1, "hashtags": ["Pococha", "17LIVE", "比較", "ライバー"]},
    ],
    "income": [
        # 収入・お金クラスタは PV/日中央 0.58 で2位。ただし税金・制度系（確定申告・経費・
        # 共済・NISA・老後）は 0.18/月間5.9 で全クラスタ最下位のためプールから退役させた
        {"keyword": "ライバー 収入 現実 ぶっちゃけ", "slug": "ライバー収入ぶっちゃけ", "p": 3, "hashtags": ["ライバー", "収入", "現実", "副業"]},
        {"keyword": "ライバー 月収 平均 2026", "slug": "ライバー月収平均", "p": 3, "hashtags": ["ライバー", "月収", "収入", "ライブ配信"]},
        {"keyword": "TikTokLIVE ギフト 換金 仕組み", "slug": "TikTokLIVEギフト換金", "p": 3, "hashtags": ["TikTokLIVE", "ギフト", "換金", "収入"]},
        {"keyword": "ライバー ダイヤ 換金 方法", "slug": "ライバーダイヤ換金", "p": 3, "hashtags": ["ライバー", "ダイヤ", "換金", "Pococha"]},
        {"keyword": "ライバー 収入 3ヶ月 6ヶ月 推移", "slug": "ライバー収入推移", "p": 3, "hashtags": ["ライバー", "収入", "推移", "副業"]},
        {"keyword": "ライブ配信 稼ぎ方 コツ", "slug": "配信稼ぎ方コツ", "p": 2, "hashtags": ["ライブ配信", "稼ぎ方", "コツ", "ライバー"]},
        {"keyword": "ライバー 時給 いくら", "slug": "ライバー時給", "p": 2, "hashtags": ["ライバー", "時給", "収入", "副業"]},
        {"keyword": "配信 収益化 最短", "slug": "配信収益化最短", "p": 2, "hashtags": ["配信", "収益化", "ライバー", "稼ぐ"]},
        {"keyword": "ライバー 収入 ランキング アプリ別", "slug": "ライバー収入ランキング", "p": 2, "hashtags": ["ライバー", "収入", "ランキング", "アプリ"]},
        {"keyword": "ライブ配信 いくら稼げる 初心者", "slug": "配信いくら稼げる", "p": 2, "hashtags": ["ライブ配信", "稼げる", "初心者", "収入"]},
        {"keyword": "投げ銭 仕組み 配信", "slug": "投げ銭仕組み", "p": 1, "hashtags": ["投げ銭", "仕組み", "ライブ配信", "収入"]},
        {"keyword": "ライバー 年収 トップ", "slug": "ライバー年収トップ", "p": 1, "hashtags": ["ライバー", "年収", "トップ", "収入"]},
    ],
    "skills": [
        # 配信テククラスタは月間PV平均23.2。ゴールデンタイム記事が週間3位まで浮上した
        {"keyword": "ライブ配信 ゴールデンタイム 時間帯", "slug": "配信ゴールデンタイム", "p": 3, "hashtags": ["ライブ配信", "ゴールデンタイム", "時間帯", "ライバー"]},
        {"keyword": "配信 枠タイトル 付け方", "slug": "配信枠タイトル付け方", "p": 3, "hashtags": ["配信", "枠タイトル", "付け方", "ライバー"]},
        {"keyword": "ライブ配信 盛り上げ方 テクニック", "slug": "配信盛り上げ方", "p": 3, "hashtags": ["ライブ配信", "盛り上げ方", "テクニック", "ライバー"]},
        {"keyword": "配信 リスナーさん 常連 増やし方", "slug": "常連リスナー増やし方", "p": 3, "hashtags": ["リスナー", "常連", "増やし方", "ライバー"]},
        {"keyword": "配信 コメント 拾い方 コツ", "slug": "配信コメント拾い方", "p": 3, "hashtags": ["配信", "コメント", "拾い方", "トーク"]},
        {"keyword": "ライブ配信 トーク術 コツ", "slug": "配信トーク術コツ", "p": 2, "hashtags": ["トーク術", "ライブ配信", "コツ", "ライバー"]},
        {"keyword": "ライバー リスナー 増やし方", "slug": "リスナー増やし方", "p": 2, "hashtags": ["リスナー", "増やし方", "ライバー", "ファン"]},
        {"keyword": "配信 ファン 作り方", "slug": "配信ファン作り方", "p": 2, "hashtags": ["配信", "ファン", "作り方", "ライバー"]},
        {"keyword": "配信 サムネイル 作り方", "slug": "配信サムネ作り方", "p": 1, "hashtags": ["サムネイル", "作り方", "配信", "ライバー"]},
        {"keyword": "配信 機材 おすすめ 2026", "slug": "配信機材おすすめ2026", "p": 1, "hashtags": ["配信機材", "おすすめ", "リングライト", "マイク"]},
        {"keyword": "リングライト おすすめ 配信", "slug": "リングライトおすすめ", "p": 1, "hashtags": ["リングライト", "おすすめ", "配信", "機材"]},
        {"keyword": "ライブ配信 背景 おしゃれ", "slug": "配信背景おしゃれ", "p": 1, "hashtags": ["配信背景", "おしゃれ", "ライブ配信", "ライバー"]},
    ],
    "beginner": [
        # 新人期間クラスタ20本。Pococha新人期間 完全攻略が全期間3位（273PV）
        {"keyword": "Pococha 新人期間 スタートダッシュ", "slug": "Pococha新人期間スタートダッシュ", "p": 3, "hashtags": ["Pococha", "新人期間", "スタートダッシュ", "ライバー"]},
        {"keyword": "TikTokLIVE 最初の30日 やること", "slug": "TikTokLIVE最初の30日", "p": 3, "hashtags": ["TikTokLIVE", "30日", "初心者", "ロードマップ"]},
        {"keyword": "初配信 コツ 緊張", "slug": "初配信コツ", "p": 3, "hashtags": ["初配信", "コツ", "ライバー", "緊張"]},
        {"keyword": "ライバー 始め方 2026", "slug": "ライバー始め方2026", "p": 2, "hashtags": ["ライバー", "始め方", "ライブ配信", "副業", "2026"]},
        {"keyword": "ライブ配信 初心者 やり方", "slug": "配信初心者やり方", "p": 2, "hashtags": ["ライブ配信", "初心者", "配信", "副業"]},
        {"keyword": "配信アプリ おすすめ 初心者", "slug": "配信アプリおすすめ初心者", "p": 2, "hashtags": ["配信アプリ", "おすすめ", "ライバー", "初心者"]},
        {"keyword": "ライブ配信 何話す ネタ", "slug": "配信何話すネタ", "p": 2, "hashtags": ["ライブ配信", "ネタ", "トーク", "初心者"]},
        {"keyword": "ライバー 向いてる人 特徴", "slug": "ライバー向いてる人", "p": 2, "hashtags": ["ライバー", "向いてる人", "適性", "ライブ配信"]},
        {"keyword": "スマホ ライブ配信 始め方", "slug": "スマホ配信始め方", "p": 1, "hashtags": ["スマホ", "ライブ配信", "始め方", "ライバー"]},
        {"keyword": "ライバー 未経験 始める", "slug": "ライバー未経験", "p": 1, "hashtags": ["ライバー", "未経験", "始め方", "副業"]},
        {"keyword": "ライバー 必要なもの 機材", "slug": "ライバー必要なもの", "p": 1, "hashtags": ["ライバー", "必要なもの", "機材", "始め方"]},
        {"keyword": "ライバー デビュー 準備", "slug": "ライバーデビュー準備", "p": 1, "hashtags": ["ライバー", "デビュー", "準備", "初心者"]},
    ],
    "comparison": [
        # 顔出しなしクラスタは4本と少数だが月間24.0・週間9.2で効率が高い
        {"keyword": "顔出しなし 配信 方法 比較", "slug": "顔出しなし配信比較", "p": 3, "hashtags": ["顔出しなし", "配信", "比較", "Vtuber"]},
        {"keyword": "顔出しなし ライバー 稼げる", "slug": "顔出しなしライバー稼げる", "p": 3, "hashtags": ["顔出しなし", "ライバー", "稼げる", "声だけ"]},
        {"keyword": "Pococha TikTokLIVE どっち 稼げる", "slug": "PocochaTikTok比較", "p": 3, "hashtags": ["Pococha", "TikTokLIVE", "比較", "稼げる"]},
        {"keyword": "配信アプリ 比較 2026 一覧", "slug": "配信アプリ比較2026", "p": 2, "hashtags": ["配信アプリ", "比較", "2026", "おすすめ"]},
        {"keyword": "稼げる 配信アプリ ランキング", "slug": "稼げる配信アプリランキング", "p": 2, "hashtags": ["稼げる", "配信アプリ", "ランキング", "ライバー"]},
        {"keyword": "ライバー YouTuber 違い 比較", "slug": "ライバーYouTuber違い", "p": 1, "hashtags": ["ライバー", "YouTuber", "違い", "比較"]},
        {"keyword": "ライバー Vtuber どっち 向き", "slug": "ライバーVtuberどっち", "p": 1, "hashtags": ["ライバー", "Vtuber", "比較", "どっち"]},
        {"keyword": "ライバー インフルエンサー 違い", "slug": "ライバーインフルエンサー違い", "p": 1, "hashtags": ["ライバー", "インフルエンサー", "違い", "比較"]},
        {"keyword": "副業 比較 ライバー 他", "slug": "副業比較ライバー", "p": 1, "hashtags": ["副業", "比較", "ライバー", "おすすめ"]},
        {"keyword": "ライバー チャットレディ 違い", "slug": "ライバーチャトレ違い", "p": 1, "hashtags": ["ライバー", "チャットレディ", "違い", "比較"]},
    ],
    "agency": [
        # 2026-08-28 再測定。このカテゴリの中身は**実務型と募集型で9倍差**がある。
        #   実務型（すでにやる気のある人が「やり方」を検索する）… 月間PV合計 253
        #     スカウト術 106 / 開業ロードマップ 81 / スカウトDM運用論 37 /
        #     マネージャーとは 15 / 開業して最初の10人 14
        #   募集型（「代理店になりませんか」に相当する制度説明）… 月間PV合計 29
        #     代理店とは 4 / 代理店になる方法 2 / 代理店は稼げる？ 12 / 在宅副業で代理店に 1
        # つまり **代理店パートナーを集めたいなら「募集」を書くのではなく
        # 「代理店の実務でいちばん役に立つ場所」になるのが正解**。募集型は退役させ、
        # 実務型（スカウト・育成・立ち上げ・運営）をp3に寄せる。
        # なお「事務所の選び方/口コミ/面談の流れ」系は読者がライバー志望であって
        # 代理店志望ではない。実測でも全滅（大学生向け事務所選び 0.02/日など）なので
        # このカテゴリからは外した（comparison 側に同種のキーワードが残っている）。
        {"keyword": "ライバー代理店 スカウト 返信率 コツ", "slug": "代理店スカウト返信率", "p": 3, "hashtags": ["代理店", "スカウト", "DM", "ライバー事務所"]},
        {"keyword": "ライバー事務所 立ち上げ 集客", "slug": "事務所立ち上げ集客", "p": 3, "hashtags": ["ライバー事務所", "立ち上げ", "集客", "開業"]},
        {"keyword": "ライバー事務所 開業 準備 手順", "slug": "事務所開業準備手順", "p": 3, "hashtags": ["ライバー事務所", "開業", "手順", "独立"]},
        {"keyword": "ライバー代理店 育成 サポート 方法", "slug": "代理店ライバー育成", "p": 3, "hashtags": ["代理店", "育成", "マネジメント", "ライバー事務所"]},
        {"keyword": "ライバー マネージャー 仕事内容", "slug": "ライバーマネージャー仕事", "p": 3, "hashtags": ["マネージャー", "仕事内容", "ライバー事務所", "転職"]},
        {"keyword": "ライバー事務所 代理店 ビジネス", "slug": "事務所代理店ビジネス", "p": 2, "hashtags": ["代理店", "ビジネス", "ライバー事務所", "副業"]},
        {"keyword": "ライバー事務所 運営 トラブル 対応", "slug": "事務所運営トラブル", "p": 2, "hashtags": ["ライバー事務所", "運営", "トラブル", "代理店"]},
        {"keyword": "ライバー代理店 SNS 集客 方法", "slug": "代理店SNS集客", "p": 2, "hashtags": ["代理店", "SNS", "集客", "ライバー事務所"]},
        {"keyword": "会社員 ライバー代理店 両立", "slug": "会社員代理店両立", "p": 2, "hashtags": ["会社員", "代理店", "両立", "副業"]},
    ],
    "advanced": [
        {"keyword": "Pococha S帯 なり方 コツ", "slug": "PocochaS帯なり方", "p": 3, "hashtags": ["Pococha", "S帯", "なり方", "ライバー"]},
        {"keyword": "Pococha B帯 から 上の帯", "slug": "PocochaB帯から上", "p": 3, "hashtags": ["Pococha", "B帯", "ランクアップ", "ライバー"]},
        {"keyword": "TikTokLIVE バトル 勝ち方", "slug": "TikTokLIVEバトル勝ち方", "p": 3, "hashtags": ["TikTokLIVE", "バトル", "勝ち方", "ギフト"]},
        {"keyword": "ライバー イベント 攻略法 2026", "slug": "イベント攻略法2026", "p": 2, "hashtags": ["イベント", "攻略", "ライバー", "2026"]},
        {"keyword": "専業ライバー 生活 リアル", "slug": "専業ライバー生活", "p": 2, "hashtags": ["専業ライバー", "生活", "リアル", "収入"]},
        {"keyword": "ライブ配信 コラボ やり方", "slug": "配信コラボやり方", "p": 1, "hashtags": ["コラボ", "やり方", "ライブ配信", "ライバー"]},
        {"keyword": "ライバー ブランディング SNS", "slug": "ライバーブランディング", "p": 1, "hashtags": ["ブランディング", "SNS", "ライバー", "戦略"]},
        {"keyword": "配信者 SNS運用 戦略", "slug": "配信者SNS運用", "p": 1, "hashtags": ["SNS運用", "配信者", "戦略", "ライバー"]},
    ],
    "troubleshooting": [
        # クラスタ全体では PV/日中央 0.20 で最下位。ただし「重い枠」型（読者の行動を
        # 名指しで裏返す切り口）だけは 2.50/日 と突出する。総花的な悩み記事は当たらない
        {"keyword": "配信 頑張りすぎ リスナーさん 離れる", "slug": "頑張りすぎリスナー離れる", "p": 3, "hashtags": ["ライブ配信", "リスナー", "重い枠", "ライバー"]},
        {"keyword": "Pococha 新人期間後 応援 減る", "slug": "新人期間後応援減る", "p": 3, "hashtags": ["Pococha", "新人期間", "31日目", "対策"]},
        {"keyword": "ライバー 伸びない 理由 対策", "slug": "ライバー伸びない対策", "p": 2, "hashtags": ["伸びない", "対策", "ライバー", "ライブ配信"]},
        {"keyword": "ライブ配信 リスナー 来ない", "slug": "配信リスナー来ない", "p": 2, "hashtags": ["リスナー", "来ない", "ライブ配信", "対策"]},
        {"keyword": "ライブ配信 過疎 脱出", "slug": "配信過疎脱出", "p": 2, "hashtags": ["過疎", "脱出", "ライブ配信", "ライバー"]},
        {"keyword": "Pococha ランク 下がった 対策", "slug": "Pocochaランク下がった", "p": 2, "hashtags": ["Pococha", "ランク", "下がった", "対策"]},
        {"keyword": "配信 アンチ 対処法", "slug": "配信アンチ対処法", "p": 1, "hashtags": ["アンチ", "対処法", "配信", "ライバー"]},
        {"keyword": "ライバー メンタル 保ち方", "slug": "ライバーメンタル", "p": 1, "hashtags": ["メンタル", "ライバー", "対処法", "配信"]},
        {"keyword": "配信 マンネリ 打破 方法", "slug": "配信マンネリ打破", "p": 1, "hashtags": ["マンネリ", "打破", "配信", "ライバー"]},
        {"keyword": "配信 モチベーション 維持", "slug": "配信モチベーション維持", "p": 1, "hashtags": ["モチベーション", "維持", "配信", "ライバー"]},
    ],
    "sidejob": [
        # 副業・両立クラスタは PV/日中央 0.26・月間7.1 で下位。旧 CATEGORY_WEIGHTS は
        # ここを最優先(3)にしていたが、実測は逆だったので重みを最低に落とした
        {"keyword": "会社員 ライバー 両立 方法", "slug": "会社員ライバー両立", "p": 2, "hashtags": ["会社員", "ライバー", "両立", "副業"]},
        {"keyword": "副業 バレない ライバー", "slug": "副業バレないライバー", "p": 2, "hashtags": ["副業", "バレない", "ライバー", "確定申告"]},
        {"keyword": "副業 ライバー おすすめ 理由", "slug": "副業ライバーおすすめ", "p": 1, "hashtags": ["副業", "ライバー", "おすすめ", "在宅"]},
        {"keyword": "夜 副業 おすすめ 在宅", "slug": "夜副業おすすめ", "p": 1, "hashtags": ["夜", "副業", "在宅", "ライバー"]},
        {"keyword": "スキマ時間 副業 配信", "slug": "スキマ時間副業配信", "p": 1, "hashtags": ["スキマ時間", "副業", "配信", "ライバー"]},
        {"keyword": "在宅ワーク 配信 稼ぐ", "slug": "在宅ワーク配信", "p": 1, "hashtags": ["在宅ワーク", "配信", "稼ぐ", "ライバー"]},
    ],
}

CATEGORIES = list(SEO_KEYWORDS.keys())

# カテゴリ重み。2026-08-10 のPV実測（公開124本・経過21日以上の108本で集計）に差し替えた。
# 旧値は「income/sidejob/beginner はNoteの副業・お金系アルゴリズムに乗りやすい」という
# 推測ベースで sidejob を最優先(3)にしていたが、実測では副業・両立クラスタが
# PV/日中央 0.26・月間平均7.1 で下から2番目だった。以下は実測順:
#   40-50代 1.33 / TikTokLIVE 0.58 / 収入 0.58 / Pococha 0.53 / 17LIVE 0.44 /
#   顔出しなし 0.44 / 新人期間 0.44 / 事務所 0.41 / 配信テク 0.39 / 比較 0.38 /
#   副業・両立 0.26 / 主婦ママ 0.23 / メンタル 0.20 / 税金制度 0.18
#
# 2026-08-28 再測定（公開140本 / 経過21日以上の120本）でクラスタ順はほぼ再現した:
#   顔出しなし 0.89 / 配信テク 0.79 / TikTokLIVE 0.73 / 40-50代 0.67 / 収入 0.60 /
#   Pococha 0.53 / 比較 0.46 / 新人期間 0.43 / 17LIVE 0.43 / 事務所 0.40 /
#   副業・両立 0.25 / メンタル 0.25 / 主婦ママ 0.21 / 税金制度 0.16
# agency を 2 → 3 に上げた。カテゴリ中央値は 0.50 と中位だが、これは募集型（月間PV合計29）が
# 実務型（同253）の足を引っ張っていた合成値で、プールから募集型を外した以上いまの中身の
# 実力は 0.9 前後。代理店パートナー獲得が主軸（[[project-agency-shift]]）である以上、
# 産出量の配分もそちらに寄せる。ただし**記事量産は今の伸びの主因ではない**点に注意:
# 8/10→8/28 の全期間PV +2,393 のうち、その間に出した新記事16本の寄与は 120（5.0%）で、
# 残り95%は既存記事の検索流入の積み上がりだった。増やすより既存記事の導線を直すほうが効く。
CATEGORY_WEIGHTS = {
    "lifestyle": 4, "platform": 4,
    "income": 3, "skills": 3, "beginner": 3, "agency": 3,
    "comparison": 2, "advanced": 2,
    "troubleshooting": 1, "sidejob": 1,
}

# ─── Gemini プロンプト（Note特化・エンゲージメント最適化） ──────────
# 変更点:
#  - タイトルを「数字/逆説/断言」系の4パターンからランダム選択に
#  - 冒頭をストーリー/体験談フック必須に（プレビューで離脱されない）
#  - 教科書調を禁止、「本音」「失敗談」「現場の数字」を要求
#  - 見出しH2をキャッチコピー化
#  - 文字数を2500〜3500に圧縮（Note読者は長文離脱しやすい）
#
# 2026-08-10 [[feedback_ai_prompt_teaches_violations]]:
# このプロンプトは**手本として確定ファクト違反を4つ提示していた**:
#   - 断言型の例「9割の人が半年で消える」          → 出典なしの割合統計
#   - H2の例「『還元率50%』の裏で、7割のライバーが〜」→ 他社還元率＋割合統計
#   - 体験の例「Pocochaで月300万円稼いでいた頃」    → 最高月収は「3桁」が確定ファクト
#   - 冒頭の例「DM300通送って返信は2通」           → 根拠なしのDM返信率
# さらに「具体数字（金額・割合・期間・人数）を最低5箇所ちりばめる」＝捏造の指示だった。
# 全部差し替えたうえで、確定ファクトのブロックを本文に足した。
#
# 教訓: **違反を「真似すべき手本」の位置に置かないこと**。
# 禁止語を列挙するのは（禁止だと分かる文脈なので）問題ないが、
# タイトル例・体験例・見出し例のような**模倣される位置**に違反を置くと、
# AIはそれを目標として学習する。修正の履歴や理由はこのコメント側に書き、
# プロンプト本文には「直した後の姿」だけを残す。
#
# 2026-08-10 PV実測に合わせた改訂（data/note_pv_analysis_20260810.md）:
#   - 文字数を4000〜5000に戻した。上位15本の中央値4,620字 / 下位15本3,464字
#   - 具体数字を最低5→最低20箇所に。上位中央39個 / 下位中央15個で最大の差だった
#   - 箇条書きを「1セクション1回まで」から「3〜5箇所必須」に反転。公開124本を
#     走査したところ本文中の箇条書きは実質ゼロで、AI(GEO)が引用できる形が無かった
#   - 「〇〇とは」の定義文を必須化（実測 上位・下位ともほぼ0個）
#   - 体験談の例文を確定ファクト内の数字に差し替えた（旧例は月300万/18時間配信で
#     data/facts に反する数字をAIに手本として教えていた）
ARTICLE_PROMPT = """あなたはNote.comで月間10万PVを出すライバー/副業系ライターです。
以下の条件で、読者が「最後まで読んで、いいね/フォロー/リンクタップしたくなる」記事を1本作ります。

【ターゲットキーワード】{keyword}
【文字数】4000〜5000文字
【文体】親しみやすい「です・ます」調。たまに体言止め・改行を使い、読みやすくリズムを作る。

【タイトル（1行目・必須）】
**{title_pattern}**
SEOキーワードを自然に含めること。
※例文の言い回しをそのまま流用しないこと。**型だけ借りて、言葉は毎回変える**。
※「｜」で副題を区切り、末尾に【2026年版】を付ける。
※「完全ガイド」「徹底解説」など教科書ワードは絶対に使わない。

【冒頭（最初の3〜5行・最重要）】
プレビューで表示される部分。以下のどれかの「フック」で始める:
  ① 衝撃的な具体的場面・事実（「初配信、視聴者0人のまま2時間しゃべり続けました」）
  ② 読者が自分のことだと思う一人称シーン（「深夜2時、配信を切った瞬間に泣いたことがあります」）
  ③ 業界の建前を裏切る本音（「『誰でも稼げます』は嘘です。でも、『○○な人』なら稼げます」）
※「〜と悩んでいませんか？」の3連Q構文は絶対に使わない（既視感が出る）。

【本文構成】
- たいたん自身の体験を1つ以上必ず入れる（成功でも失敗でも）。場面を具体に。
  例: 「Pocochaで一番配信していた頃は、1日8時間マイクの前にいました」
- H2（##）は8〜12個。「見出し」ではなく「キャッチコピー」にする
  ✕「事務所選びのポイント」 → ○「『還元率』を確認しないまま契約した人の話」
- H3（###）を適宜使い、段落は3〜5行で区切る
- 太字（**）は1段落につき1〜2箇所だけ
- 「よくある質問」は2個だけ、Q&Aは各2〜3行に圧縮
- 「まとめ」は箇条書きではなく、たいたんから読者への短い手紙調（3〜5行）で締める

【AIに引用される構造（必須・ここが弱いと検索AIに拾われない）】
ChatGPTなどのAI経由で記事が読まれ、実際の入会につながっている。
AIが「答えとして切り出せる形」で置くこと。以下は必須:
- 具体性は「期間・回数・配信時間・手順の数」で出し、本文に**最低20箇所**入れる。
  「けっこう続けた」ではなく「3ヶ月続けた」と必ず数える形にする。
  **金額と割合だけは【使ってよい数字】に挙がっているものに限る**。箇所数を埋めるために
  金額を作らない（20箇所は期間・回数・手順の数だけで足りる）
- 記事のキーワードを**1文で定義する文**を、冒頭の見出しの直後に1つ置く。
  型:「〇〇とは、△△な人が□□するための××です。」
- 箇条書き（-）を記事全体で**3〜5箇所**使う。1つの箇条書きは3〜6項目。
  「手順」「条件」「必要なもの」「やってはいけないこと」のような、
  そのまま答えとして切り出せる塊を箇条書きにする
- 各H2セクションは、その見出しへの答えを最初の2〜3行で言い切ってから詳細に入る
  （結論を後ろに置かない）

【使ってよい数字・実績（これ以外の数字・金額・割合・実績は書かない）】
- 報酬は「還元率100%+α」。**「手数料」という単語そのものが禁止**（なし/0円/他社は引かれる、も全部禁止）。他社の還元率も書かない
- 収入は 3ヶ月で15〜20万 / 6ヶ月で30〜40万 / Pococha B帯 月20〜30万 のみ。
  **月15万未満の金額（「月3万」「月10万」「お小遣い程度」）は、稼げていない側の描写でも書かない**
- 代表たいたん：元Pococha Sランク、ミクチャ8000人中ミスターコン1位、Pococha歴4年。最高月収は「3桁」とだけ（具体額NG）
- 所属ライバー数は「200名」固定（「200名以上」「累計◯名」は書かない）
- 扱うのは Pococha・TikTok LIVE・17LIVE の3つ。IRIAM/SHOWROOM/ふわっち/REALITY は出さない
- Pocochaの「オフの日」は月4日の強制休配信日（おやすみチケットとは別制度）

【絶対NG】
- **出典なしの割合統計**。「9割が挫折する」「99%が知らない」「10人に1人も成功しない」型に加えて、
  「9割の副業ライバーは〜」のように**割合が主語を修飾する形も禁止**。
  断定したいときは割合ではなく「多い」「よく見る」で書く
- **業界の市場規模・成長率**。率（「毎年130%成長」）だけでなく、
  **金額（「国内1,500億円規模」「グローバル7兆円」）も国別順位（「日本は世界で3番目」）も同じく禁止**。
  裏の取れる出典が無いので必ず捏造になる（2026-09-04に公開記事3本から削除した）。
  市場の話を書くときは規模を出さず、**伸びている理由**（5Gの普及・投げ銭文化の定着・
  企業のライブコマース参入）という構造だけで書く
- 視聴者の呼び捨て。**必ず「リスナーさん」**と書く（「リスナー」単独はNG。「固定リスナー」等の複合語も開く）
- 「絶対稼げる」「必ず」「誰でも」「保証」などの断定・誇大表現
- 「不労所得」「権利収入」「多数輩出」「多くの実績」「続々と」など、裏の取れない表現
- 「カーブアウト（パートナー）」という呼称（名乗るなら TAITAN PRO）
- 「オンライン無料相談」（CTAはLINE導線に統一）
- 「いつでも退所OK」「違約金なし」「違約金0」「いつでも辞められる」など、退所・契約解除が自由だと示す表現は禁止（契約条件は面談で説明する、とだけ書く）
- ミクチャ・ツイキャスを勧める記述（上のIRIAM/SHOWROOM/ふわっち/REALITYと同じく取り扱い外。
  集客対象は Pococha・TikTok LIVE・17LIVE の3つだけなので、キーワードもプールから外してある）
- Markdownテーブル（| | | 形式）
- 水平線（---）
- コードブロック（```）
- **本文中に半角「#」で始まる語**（例: `#副業` `#Pococha`）。noteの公開画面が本文の
  「空白・行頭の直後にある半角#語」を記事タグへ勝手に昇格させ、記事と無関係なタグが付く。
  ハッシュタグの例を挙げるときは#を付けず「副業探し / 在宅ワーク」のように鉤括弧かスラッシュで列挙する
- 「完全ガイド」「徹底解説」「全手順」「完全図解」などのテンプレ語
- 「筆者」表記（→「たいたん」「私」）
- 記事末尾のCTA/宣伝（別途追加）
- 毎記事同じ自己紹介テンプレの長文コピペ（初出で簡潔に1〜2行で済ませる）

【権威性の出し方】
初出で1回だけ「※元Pococha Sランク、ミクチャ8000人中ミスターコン1位のたいたんです」のように
自然に差し込む。以降は「私」「たいたん」で統一。

記事本文のみをMarkdownで出力。前置き・メタ情報・コードフェンス不要。"""


# 代理店（＝事務所を"作る側"）記事のときだけ本文プロンプトに足すブロック。
#
# 2026-08-30、agency カテゴリで6本生成したら5本が確定ファクト違反だった（計36件）。
# 内訳は「手数料」「月3〜10万」「月1〜5万」「契約期間」「現役ライバー」「確実に」。
# ARTICLE_PROMPT には**これら全部の禁止が既に書いてあった**のに破られている。
#
# 原因は禁止が足りないことではなく、**プロンプトがライバー視点だけで書かれていること**。
# 確定ファクトの金額は「3ヶ月15〜20万 / 6ヶ月30〜40万 / B帯 月20〜30万」＝すべて
# ライバー本人の収入で、代理店側の収入・マージンには承認された数字が1つも無い。
# 「ライバー事務所の開業手順」を書けと言われたモデルは、報酬構造に触れざるを得ず、
# 埋める数字が無いので捏造する。禁止語を増やしても、穴が空いている限り埋めにくる。
#
# なので**穴そのものを塞ぐ**: 代理店側のお金は「書かない」が正解だと明示し、
# 代わりに何を書けばいいのか（実務の手順・時間の使い方）を与える。
# [[feedback-dont-make-up-numbers]] / [[feedback-ai-prompt-teaches-violations]]
AGENCY_PROMPT_EXTRA = """

【この記事は「代理店・事務所を"作る側"」向け（最重要）】
読者はライバー本人ではなく、**紹介して育てる側**になろうとしている人です。
「代理店とは何か」の制度説明ではなく、**実務でつまずく場所**を書いてください。

- **代理店側・事務所側のお金の話は数字を一切書かない**。報酬率・マージン・取り分・
  月商・利益・初期費用・損益分岐、どれも承認された数字が無いので**書けません**。
  「収入の話は人によって条件が変わるので、LINEで個別に説明しています」と逃がすこと。
  上の【確定ファクト】の金額は**ライバー本人の収入**であって、代理店の収入ではない。
  代理店の収入として転用しない
- **「手数料」「マージン」「取り分」「中抜き」という単語を使わない**。報酬に触れる必要が
  あるときは「還元率100%+α」とだけ書く
- 契約期間・違約金・退所条件には触れない（「条件は面談で説明します」で止める）
- たいたんは**元**Pococha Sランクで、いまは事務所の代表。「現役ライバー」と書かない
- 「確実に」「安定して稼げる」「必ず伸びる」は禁止（育成の話で出やすい）
- ライバー本人の視点に戻らないこと。「あなたの枠」「あなたの配信」ではなく
  「担当するライバーさんの枠」と書く

代わりに厚く書くのはこちら（読まれているのはここ）:
  - 声をかけてから所属が決まるまでに実際にやりとりする順番
  - 1日・1週間のうち、どこに時間が溶けるのか
  - 続く人と辞める人で、最初の1ヶ月の動き方がどう違うか
  - 会社員と兼ねる場合、どの作業を夜に寄せられてどれが寄せられないか
  - 自分のSNSから相談が来る状態をどう作るか
"""


# ─── ユーティリティ ───────────────────────────────────

def get_gemini_api_key():
    """Gemini APIキーを取得"""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        try:
            sys.path.insert(0, BASE_DIR)
            from config import GEMINI_API_KEY
            key = GEMINI_API_KEY
        except (ImportError, AttributeError):
            pass
    return key


def load_tracker():
    """キーワードトラッカーを読み込む"""
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"used": [], "last_category_index": -1}


def save_tracker(tracker):
    """キーワードトラッカーを保存"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(tracker, f, ensure_ascii=False, indent=2)


def get_used_keywords(tracker):
    """抽選から外すキーワードのセットを返す。

    used     … このスクリプトで生成済み
    covered  … 別経路（Claude直書き等）で既に公開されている同テーマ
    retired  … PV実測で負けたので意図的に外したもの
    """
    out = {item["keyword"] for item in tracker.get("used", [])}
    out |= set(tracker.get("covered", []))
    out |= {item["keyword"] for item in tracker.get("retired", [])}
    return out


def get_next_keyword(tracker, only_category=None):
    """重み付き抽選で次のキーワードを選ぶ。

    確率は「カテゴリ重み × キーワード優先度 p」。どちらも 2026-08-10 の
    PV実測（data/note_pv_20260810.csv）に基づく。直近カテゴリは連続を
    避けるため重みを半減させる。

    only_category を渡すとそのカテゴリだけから選ぶ（連続回避の半減もしない）。
    特定テーマを意図的に補充したいときに使う。2026-08-28 に代理店パートナー
    獲得を強化したときは、抽選任せだと agency（重み3・9キーワード）が
    まとまって出てこないので、このオプションで6本まとめて生成した。
    """
    used = get_used_keywords(tracker)
    last_category = tracker.get("last_category", None)

    if only_category:
        if only_category not in SEO_KEYWORDS:
            raise ValueError(
                f"未知のカテゴリ {only_category!r}（有効: {', '.join(CATEGORIES)}）")
        last_category = None  # 指定時は連続回避を効かせない

    # 未使用キーワードを「カテゴリ重み × p」の回数だけ抽選箱に入れる
    candidates = []
    for cat in CATEGORIES:
        if only_category and cat != only_category:
            continue
        unused = [kw for kw in SEO_KEYWORDS[cat] if kw["keyword"] not in used]
        if not unused:
            continue
        weight = CATEGORY_WEIGHTS.get(cat, 1)
        # 直近と同じカテゴリは重みを半減（連続回避）
        if cat == last_category:
            weight = max(1, weight // 2)
        for kw in unused:
            candidates.extend([(cat, kw)] * (weight * kw.get("p", 1)))

    if not candidates:
        return None  # 全キーワード使用済み

    category, kw = random.choice(candidates)
    chosen = dict(kw)  # 破壊的変更を避けるためコピー
    chosen["category"] = category
    tracker["last_category"] = category
    return chosen


def get_next_article_number():
    """次の記事番号を取得"""
    pattern = os.path.join(ARTICLES_DIR, "*.md")
    files = glob.glob(pattern)
    max_num = 0
    for f in files:
        match = re.match(r"(\d+)_", os.path.basename(f))
        if match:
            max_num = max(max_num, int(match.group(1)))
    return max_num + 1


def post_process_article(body):
    """記事の後処理（テーブル除去、整形）"""
    # note_publisher.pyの関数をインポート
    try:
        sys.path.insert(0, BASE_DIR)
        from note_publisher import convert_table_to_list, format_for_note
        body = convert_table_to_list(body)
        body = format_for_note(body)
    except ImportError:
        # フォールバック: 簡易テーブル変換
        lines = body.split("\n")
        result = []
        for line in lines:
            if re.match(r"^\|.+\|$", line.strip()):
                if not re.match(r"^\|[\s\-:|]+$", line.strip()):
                    cells = [c.strip() for c in line.split("|")[1:-1]]
                    result.append("- " + " / ".join(c for c in cells if c))
            else:
                result.append(line)
        body = "\n".join(result)

    # 水平線を除去
    body = re.sub(r"^---+$", "", body, flags=re.MULTILINE)
    # コードブロックを除去
    body = re.sub(r"```[\s\S]*?```", "", body)
    # 連続空行を圧縮
    body = re.sub(r"\n{4,}", "\n\n\n", body)

    return body.strip()


# タイトル行だけに効く後始末と検査。
# 2026-08-30 の実測で、本文の検品を通ったタイトルにこれらが出た:
#   「**100組の新規ライバーさんを支えて気づいた**、…**トラブル**を**未然に防ぐ**5つの秘訣」
#     → 見出し行に ** が散らばる（noteのタイトルはMarkdownを解釈しないので記号がそのまま出る）
#   「私が送ったスカウトメール、99通で撃沈した話｜返信率0%から」
#     → 送信数・返信率はどれも裏が取れない（プロンプトから一度消したはずの捏造が別の顔で戻った）
#   「未経験から月間200名のライバーさんを抱えるまでに」
#     → 200名は所属の総数であって「月間」ではない。確定ファクトの誤用
_TITLE_BAD = [
    (re.compile(r"\d+\s*(?:通|組|人|名)(?:の|を|に|で|送)"), "実績を数量で語っている（裏が取れない）"),
    (re.compile(r"返信率\s*\d"), "返信率の具体数字（裏が取れない）"),
    (re.compile(r"月間\s*200\s*名"), "所属200名は総数であって月間ではない"),
    (re.compile(r"\d+\s*%"), "割合の具体数字（還元率100%を除き裏が取れない）"),
]


def clean_title_line(body):
    """1行目の見出しから装飾記号を落とす。noteはタイトルのMarkdownを解釈しない。"""
    lines = body.split("\n")
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        t = ln.lstrip("#").strip()
        t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)   # **強調** を外す
        t = t.replace("**", "").replace("__", "").strip()
        lines[i] = "# " + t
        break
    return "\n".join(lines)


def title_violations(body):
    """タイトル行だけを見た違反。本文用の facts_patterns では拾えない型を補う。"""
    for ln in body.split("\n"):
        if ln.strip():
            title = ln.lstrip("#").strip()
            break
    else:
        return []
    out = []
    for rx, label in _TITLE_BAD:
        m = rx.search(title)
        if m:
            if "還元率" in title and m.group(0).strip() == "100%":
                continue
            out.append((label, m.group(0)))
    return out


def facts_violations(text):
    """確定ファクト違反を (ラベル, 該当語) のリストで返す。正本は facts_patterns。"""
    import facts_patterns as fp
    out = []
    for fn in (fp.common_violations, fp.money_violations, fp.ng_violations,
               fp.ratio_violations, fp.contract_axis_violations,
               fp.line_link_violations):
        try:
            out += list(fn(text) or [])
        except TypeError:
            pass  # 引数の形が違う検査は飛ばす
    # 同じ違反が何度も出るので畳む
    seen, uniq = set(), []
    for v in out:
        k = str(v)
        if k not in seen:
            seen.add(k)
            uniq.append(v)
    return uniq


def repair_article(api_key, keyword_info, body, violations):
    """検出した違反だけを指摘して直させる。本文の構成は変えさせない。"""
    from google import genai
    lines = "\n".join(f"- 「{v[1]}」… {v[0]}" for v in violations)
    prompt = (
        "以下はNote記事の本文です。**書いてはいけない表現**が含まれています。\n"
        "該当箇所だけを自然な日本語に直し、それ以外は1文字も変えないでください。\n"
        "構成・見出し・文字数は保つこと。記事本文のみを出力し、説明は書かないこと。\n\n"
        "【直す対象】\n" + lines + "\n\n"
        "【直し方】\n"
        "- 金額は、承認された数字（3ヶ月15〜20万 / 6ヶ月30〜40万 / Pococha B帯 月20〜30万）"
        "以外は**その文ごと消すか、数字を使わない言い方に変える**。別の数字に置き換えない\n"
        "- 「手数料」「マージン」「取り分」は報酬の話ごと削り、必要なら「還元率100%+α」とだけ書く\n"
        "- 契約期間・違約金・退所条件の話は「条件は面談で説明します」に置き換える\n"
        "- 「リスナー」単独は「リスナーさん」に開く\n"
        "- 「確実に」「安定して稼げる」などの断定は「〜しやすい」「〜する人が多い」に緩める\n"
        "- 「現役ライバー」は「元Pococha Sランク」または「事務所の代表」に直す\n"
        "- **「オンライン面談」は「LINE通話でお話し」に直す**（『面談』単独は残してよい）\n"
        "- 所属ライバー数は「200名」固定。「約200名」「200名以上」「累計」は付けない\n"
        "- 指摘された語が**1つも残らない**ようにする。言い換えではなく、"
        "その語を含む文ごと書き直してよい\n"
        "- タイトル（1行目）の指摘なら、**タイトルごと作り直す**。"
        "自分の実績を数量（通数・人数・返信率・割合）で語らない形にすること\n\n"
        "【本文】\n" + body
    )
    client = genai.Client(api_key=api_key)
    r = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    return r.text


def generate_article(api_key, keyword_info):
    """Gemini APIで記事を生成（503/429エラー時は自動リトライ＋フォールバックモデル）"""
    import time
    from google import genai

    client = genai.Client(api_key=api_key)

    # 型は記事番号で順送りにする。ランダムだと同じ型が続くことがあり、
    # モデル任せだと全部同じ型になる（実測: 6本中6本がD型）。
    pattern = TITLE_PATTERNS[keyword_info.get("article_number", 0) % len(TITLE_PATTERNS)]
    prompt = ARTICLE_PROMPT.format(keyword=keyword_info["keyword"],
                                   title_pattern=pattern)
    if keyword_info.get("category") == "agency":
        prompt += AGENCY_PROMPT_EXTRA

    # 複数モデルを順に試行（503/429エラー時はフォールバック）
    models = ["gemini-2.5-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash"]
    max_retries_per_model = 2
    last_error = None

    for model_idx, model_name in enumerate(models):
        is_last_model = (model_idx == len(models) - 1)
        print(f"  Gemini生成中（{model_name}）... キーワード: {keyword_info['keyword']}")
        for attempt in range(max_retries_per_model):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                return response.text
            except Exception as e:
                last_error = e
                error_str = str(e)
                is_retryable = any(code in error_str for code in ["503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "high demand"])
                if is_retryable and attempt < max_retries_per_model - 1:
                    wait_sec = (attempt + 1) * 20  # 20s, 40s
                    print(f"  ⚠ {model_name} 一時エラー（リトライ {attempt+1}/{max_retries_per_model-1}、{wait_sec}秒後）: {error_str[:80]}")
                    time.sleep(wait_sec)
                elif is_retryable and not is_last_model:
                    print(f"  ⚠ {model_name} が利用不可、次のモデルに切替...")
                    break  # 次のモデルへ
                else:
                    raise

    # 全モデル失敗時
    raise last_error


def save_article(number, slug, content):
    """記事をファイルに保存"""
    os.makedirs(ARTICLES_DIR, exist_ok=True)
    filename = f"{number:02d}_{slug}.md"
    filepath = os.path.join(ARTICLES_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


# ─── メイン処理 ───────────────────────────────────────

# generate_one の戻り値。None は「確定ファクト検品で落ちた（次のキーワードへ）」、
# EXHAUSTED は「もう選べるキーワードが無い（ループを止める）」。
# 2026-08-30 まで両方 None で、検品を入れた途端に**1本落ちるとバッチ全体が止まって
# いた**（5本頼んで2本目で停止、生成は1本）。呼び出し側が区別できる必要がある。
EXHAUSTED = "__exhausted__"


def generate_one(api_key, dry_run=False, only_category=None):
    """1記事を生成"""
    tracker = load_tracker()
    keyword_info = get_next_keyword(tracker, only_category=only_category)

    if keyword_info is None:
        msg = (f"  カテゴリ {only_category} の未使用キーワードがありません。"
               if only_category else "  全キーワードを使い切りました。")
        print(msg)
        return EXHAUSTED

    article_num = get_next_article_number()

    print(f"\n── 記事 #{article_num} ──────────────────────────")
    print(f"  カテゴリ: {keyword_info['category']}")
    print(f"  キーワード: {keyword_info['keyword']}")
    print(f"  ハッシュタグ: {' '.join('#' + t for t in keyword_info['hashtags'])}")

    if dry_run:
        print("  [dry-run] 生成スキップ")
        return {"number": article_num, "keyword": keyword_info, "dry_run": True}

    # Gemini で記事生成（タイトル型のローテーションに記事番号を使う）
    keyword_info["article_number"] = article_num
    raw_article = generate_article(api_key, keyword_info)

    # 後処理
    processed = post_process_article(raw_article)

    # 確定ファクト検品。ここまで検品が一切なく、違反したままの記事が投稿キューに
    # 入っていた（2026-08-30、agency 6本中5本・計36件）。content_facts_guard は
    # 毎日走るが、その前に note_auto_poster が公開してしまえば手遅れになる。
    # 違反があれば該当箇所だけ直させ、それでも消えなければ**保存しない**。
    processed = clean_title_line(processed)
    v = facts_violations(processed) + title_violations(processed)
    if v:
        print(f"  確定ファクト違反 {len(v)}件 → 修正を試みます")
        for lab, word in v:
            print(f"    - 「{word}」 {lab}")
        try:
            processed = post_process_article(
                repair_article(api_key, keyword_info, processed, v))
        except Exception as e:
            print(f"  !! 修正に失敗: {type(e).__name__}: {e}")
        processed = clean_title_line(processed)
        v = facts_violations(processed) + title_violations(processed)
        if v:
            print(f"  !! 違反が {len(v)}件 残ったので保存しません（キーワードは未使用のまま）")
            for lab, word in v:
                print(f"    - 「{word}」 {lab}")
            return None
        print("  修正後は違反0件")

    # CTA追加（カテゴリで出し分ける。agency は代理店LP＋代理店向け特典へ）
    final_content = processed + cta_block_for(keyword_info["category"])

    # 保存
    filepath = save_article(article_num, keyword_info["slug"], final_content)
    print(f"  保存: {filepath}")
    print(f"  文字数: {len(final_content)}文字")

    # トラッカー更新
    tracker["used"].append({
        "keyword": keyword_info["keyword"],
        "category": keyword_info["category"],
        "slug": keyword_info["slug"],
        "article_number": article_num,
        "generated_at": datetime.now().isoformat(),
        "published": False,
    })
    save_tracker(tracker)

    return {
        "number": article_num,
        "keyword": keyword_info,
        "filepath": filepath,
        "char_count": len(final_content),
    }


def show_stats():
    """統計情報を表示"""
    tracker = load_tracker()
    total_keywords = sum(len(v) for v in SEO_KEYWORDS.values())
    used_kw = get_used_keywords(tracker)
    # used_kw にはプールから既に消したキーワードも入りうるので、実在するものだけ数える
    in_pool = {kw["keyword"] for v in SEO_KEYWORDS.values() for kw in v}
    consumed = len(in_pool & used_kw)

    print(f"\n{'='*50}")
    print(f"  SEOキーワード統計")
    print(f"{'='*50}")
    print(f"  総キーワード数: {total_keywords}")
    print(f"  抽選対象外: {consumed}"
          f"（生成済み {len(tracker.get('used', []))} / "
          f"別経路で公開済み {len(tracker.get('covered', []))} / "
          f"実測で退役 {len(tracker.get('retired', []))}）")
    print(f"  残り: {total_keywords - consumed}")
    print(f"  残日数（1記事/日）: {total_keywords - consumed}日")
    print()

    for cat in CATEGORIES:
        total = len(SEO_KEYWORDS[cat])
        cat_used = sum(1 for kw in SEO_KEYWORDS[cat] if kw["keyword"] in used_kw)
        bar = "█" * cat_used + "░" * (total - cat_used)
        print(f"  {cat:16s} w={CATEGORY_WEIGHTS[cat]} [{bar}] {cat_used}/{total}")
    print()


def list_unused():
    """未使用キーワード一覧（抽選されやすい順）"""
    tracker = load_tracker()
    used = get_used_keywords(tracker)

    print(f"\n未使用キーワード一覧（重み = カテゴリ重み × p。大きいほど選ばれやすい）:")
    rows = []
    for cat in CATEGORIES:
        for kw in SEO_KEYWORDS[cat]:
            if kw["keyword"] not in used:
                rows.append((CATEGORY_WEIGHTS[cat] * kw.get("p", 1), cat, kw))
    for weight, cat, kw in sorted(rows, key=lambda x: -x[0]):
        print(f"    重み{weight:2d}  [{cat:16s}] {kw['keyword']}")
    print(f"\n  計 {len(rows)}個")

    retired = tracker.get("retired", [])
    if retired:
        print(f"\n  実測で退役させたキーワード（{len(retired)}個）:")
        for item in retired:
            print(f"    - {item['keyword']}  … {item.get('reason', '')}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Note記事 自動生成（Gemini API）")
    parser.add_argument("--generate", action="store_true", help="記事を生成")
    parser.add_argument("-n", type=int, default=1, help="生成する記事数（デフォルト: 1）")
    parser.add_argument("--dry-run", action="store_true", help="生成せずにキーワード選択のみ確認")
    parser.add_argument("--category", help="このカテゴリだけから選ぶ（例: agency）")
    parser.add_argument("--list-unused", action="store_true", help="未使用キーワード一覧")
    parser.add_argument("--stats", action="store_true", help="統計情報")

    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if args.list_unused:
        list_unused()
        return

    if args.generate or args.dry_run:
        api_key = get_gemini_api_key()
        if not api_key and not args.dry_run:
            print("GEMINI_API_KEY が設定されていません")
            print("  export GEMINI_API_KEY='your-api-key'")
            sys.exit(1)

        print("=" * 50)
        print("  Note記事 自動生成")
        print(f"  生成数: {args.n}記事")
        print("=" * 50)

        results = []
        rejected = 0
        # 検品落ちは「その1本を捨てて次のキーワードへ」。ただし全部落ち続けると
        # APIを叩き続けるので、連続で落ちた回数に上限を置く。
        attempts = 0
        while len(results) < args.n and attempts < args.n * 3:
            attempts += 1
            result = generate_one(api_key, dry_run=args.dry_run,
                                  only_category=args.category)
            if result == EXHAUSTED:
                break
            if result is None:
                rejected += 1
                continue
            results.append(result)

        print(f"\n生成完了: {len(results)}記事"
              + (f"（確定ファクト検品で不合格 {rejected}本）" if rejected else ""))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
