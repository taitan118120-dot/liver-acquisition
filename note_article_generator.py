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
CTA_BLOCK = """

---

## TAITAN PROで始めてみませんか？

TAITAN PROは、**150人以上のライバーが所属**する実績あるライバー事務所です。代表は元Pococha Sランク達成者＆ミクチャで8000人中ミスターコン1位。経験者だからこそできるサポートで、未経験からライバーデビューを全力で応援します。

- 専属マネージャーがマンツーマンサポート
- 11の配信代理店と提携、あなたに最適なプラットフォームをご提案
- 初期費用・月額費用0円
- いつでも退所可能（違約金なし）

まずは15分の無料オンライン面談で、あなたに合ったプランを一緒に考えましょう。

**[LINE で無料相談する →](https://lin.ee/xchCfdn)**

**[Web から応募する →](https://taitan-pro-lp.netlify.app/#apply)**
"""

# ─── SEO キーワードリスト（110個・10カテゴリ） ────────
SEO_KEYWORDS = {
    "beginner": [
        {"keyword": "ライバー 始め方 2026", "slug": "ライバー始め方2026", "hashtags": ["ライバー", "始め方", "ライブ配信", "副業", "2026"]},
        {"keyword": "ライブ配信 初心者 やり方", "slug": "配信初心者やり方", "hashtags": ["ライブ配信", "初心者", "配信", "副業"]},
        {"keyword": "配信アプリ おすすめ 初心者", "slug": "配信アプリおすすめ初心者", "hashtags": ["配信アプリ", "おすすめ", "ライバー", "初心者"]},
        {"keyword": "ライバー なるには 条件", "slug": "ライバーなるには", "hashtags": ["ライバー", "なり方", "条件", "ライブ配信"]},
        {"keyword": "ライバー 未経験 始める", "slug": "ライバー未経験", "hashtags": ["ライバー", "未経験", "始め方", "副業"]},
        {"keyword": "スマホ ライブ配信 始め方", "slug": "スマホ配信始め方", "hashtags": ["スマホ", "ライブ配信", "始め方", "ライバー"]},
        {"keyword": "ライバー デビュー 準備", "slug": "ライバーデビュー準備", "hashtags": ["ライバー", "デビュー", "準備", "初心者"]},
        {"keyword": "ライブ配信 何話す ネタ", "slug": "配信何話すネタ", "hashtags": ["ライブ配信", "ネタ", "トーク", "初心者"]},
        {"keyword": "初配信 コツ 緊張", "slug": "初配信コツ", "hashtags": ["初配信", "コツ", "ライバー", "緊張"]},
        {"keyword": "ライバー 向いてる人 特徴", "slug": "ライバー向いてる人", "hashtags": ["ライバー", "向いてる人", "適性", "ライブ配信"]},
        {"keyword": "ライバー 必要なもの 機材", "slug": "ライバー必要なもの", "hashtags": ["ライバー", "必要なもの", "機材", "始め方"]},
        {"keyword": "ライブ配信 緊張 克服", "slug": "配信緊張克服", "hashtags": ["ライブ配信", "緊張", "克服", "初心者"]},
    ],
    "income": [
        {"keyword": "ライバー 月収 平均 2026", "slug": "ライバー月収平均", "hashtags": ["ライバー", "月収", "収入", "ライブ配信"]},
        {"keyword": "ライバー 収入 現実 ぶっちゃけ", "slug": "ライバー収入ぶっちゃけ", "hashtags": ["ライバー", "収入", "現実", "副業"]},
        {"keyword": "ライブ配信 稼ぎ方 コツ", "slug": "配信稼ぎ方コツ", "hashtags": ["ライブ配信", "稼ぎ方", "コツ", "ライバー"]},
        {"keyword": "投げ銭 仕組み 配信", "slug": "投げ銭仕組み", "hashtags": ["投げ銭", "仕組み", "ライブ配信", "収入"]},
        {"keyword": "ライバー 時給 いくら", "slug": "ライバー時給", "hashtags": ["ライバー", "時給", "収入", "副業"]},
        {"keyword": "配信 収益化 最短", "slug": "配信収益化最短", "hashtags": ["配信", "収益化", "ライバー", "稼ぐ"]},
        {"keyword": "ライバー 年収 トップ", "slug": "ライバー年収トップ", "hashtags": ["ライバー", "年収", "トップ", "収入"]},
        {"keyword": "トップライバー 収入 ランキング", "slug": "トップライバー収入", "hashtags": ["トップライバー", "収入", "ランキング", "ライバー"]},
        {"keyword": "副業 ライバー 月5万", "slug": "副業ライバー月5万", "hashtags": ["副業", "ライバー", "月5万", "在宅"]},
        {"keyword": "ライバー 収入 ランキング アプリ別", "slug": "ライバー収入ランキング", "hashtags": ["ライバー", "収入", "ランキング", "アプリ"]},
        {"keyword": "ライブ配信 いくら稼げる 初心者", "slug": "配信いくら稼げる", "hashtags": ["ライブ配信", "稼げる", "初心者", "収入"]},
        {"keyword": "ライバー ダイヤ 換金 方法", "slug": "ライバーダイヤ換金", "hashtags": ["ライバー", "ダイヤ", "換金", "Pococha"]},
    ],
    "platform": [
        {"keyword": "Pococha 稼ぎ方 攻略 2026", "slug": "Pococha稼ぎ方2026", "hashtags": ["Pococha", "稼ぎ方", "攻略", "ライバー"]},
        {"keyword": "17LIVE 始め方 初心者", "slug": "17LIVE始め方", "hashtags": ["17LIVE", "始め方", "初心者", "ライバー"]},
        {"keyword": "IRIAM 稼げる Vtuber", "slug": "IRIAM稼げる", "hashtags": ["IRIAM", "稼げる", "Vtuber", "ライバー"]},
        {"keyword": "TikTokLIVE 収益化 条件", "slug": "TikTokLIVE収益化", "hashtags": ["TikTokLIVE", "収益化", "条件", "ライバー"]},
        {"keyword": "ツイキャス 始め方 稼ぐ", "slug": "ツイキャス始め方", "hashtags": ["ツイキャス", "始め方", "稼ぐ", "ライブ配信"]},
        {"keyword": "SHOWROOM 初心者 攻略", "slug": "SHOWROOM初心者", "hashtags": ["SHOWROOM", "初心者", "攻略", "ライバー"]},
        {"keyword": "Pococha ランク制度 仕組み", "slug": "Pocochaランク制度", "hashtags": ["Pococha", "ランク", "制度", "ライバー"]},
        {"keyword": "17LIVE イベント 攻略", "slug": "17LIVEイベント攻略", "hashtags": ["17LIVE", "イベント", "攻略", "ライバー"]},
        {"keyword": "ミクチャ 始め方 2026", "slug": "ミクチャ始め方", "hashtags": ["ミクチャ", "始め方", "ライブ配信", "ライバー"]},
        {"keyword": "Pococha 17LIVE どっち", "slug": "Pococha17LIVE比較", "hashtags": ["Pococha", "17LIVE", "比較", "ライバー"]},
        {"keyword": "ふわっち 稼げる 仕組み", "slug": "ふわっち稼げる", "hashtags": ["ふわっち", "稼げる", "仕組み", "ライバー"]},
        {"keyword": "Pococha 時間ダイヤ 計算 2026", "slug": "Pococha時間ダイヤ計算", "hashtags": ["Pococha", "時間ダイヤ", "計算", "収入"]},
    ],
    "agency": [
        {"keyword": "ライバー事務所 おすすめ 2026", "slug": "ライバー事務所おすすめ2026", "hashtags": ["ライバー事務所", "おすすめ", "2026", "ライバー"]},
        {"keyword": "ライバー事務所 メリット デメリット", "slug": "事務所メリットデメリット", "hashtags": ["ライバー事務所", "メリット", "デメリット", "ライバー"]},
        {"keyword": "ライバー事務所 還元率 比較", "slug": "事務所還元率比較", "hashtags": ["ライバー事務所", "還元率", "比較", "ライバー"]},
        {"keyword": "ライバー事務所 選び方 ポイント", "slug": "事務所選び方ポイント", "hashtags": ["ライバー事務所", "選び方", "ポイント", "ライバー"]},
        {"keyword": "フリーライバー 事務所 どっち", "slug": "フリーvs事務所", "hashtags": ["フリーライバー", "事務所", "比較", "ライバー"]},
        {"keyword": "ライバー事務所 ランキング 大手", "slug": "事務所ランキング", "hashtags": ["ライバー事務所", "ランキング", "大手", "ライバー"]},
        {"keyword": "ライバー事務所 辞めたい 退所", "slug": "事務所辞めたい退所", "hashtags": ["ライバー事務所", "辞めたい", "退所", "ライバー"]},
        {"keyword": "ライバー事務所 契約 注意点", "slug": "事務所契約注意点", "hashtags": ["ライバー事務所", "契約", "注意点", "ライバー"]},
        {"keyword": "事務所なし ライバー 個人", "slug": "事務所なしライバー", "hashtags": ["事務所なし", "フリーライバー", "個人", "ライバー"]},
        {"keyword": "ライバー事務所 面談 流れ", "slug": "事務所面談流れ", "hashtags": ["ライバー事務所", "面談", "流れ", "ライバー"]},
        {"keyword": "ライバー事務所 口コミ 評判", "slug": "事務所口コミ評判", "hashtags": ["ライバー事務所", "口コミ", "評判", "ライバー"]},
    ],
    "sidejob": [
        {"keyword": "副業 ライバー おすすめ 理由", "slug": "副業ライバーおすすめ", "hashtags": ["副業", "ライバー", "おすすめ", "在宅"]},
        {"keyword": "在宅 副業 スマホ 2026", "slug": "在宅副業スマホ2026", "hashtags": ["在宅副業", "スマホ", "副業", "2026"]},
        {"keyword": "副業 バレない ライバー", "slug": "副業バレないライバー", "hashtags": ["副業", "バレない", "ライバー", "確定申告"]},
        {"keyword": "会社員 ライバー 両立 方法", "slug": "会社員ライバー両立", "hashtags": ["会社員", "ライバー", "両立", "副業"]},
        {"keyword": "副業 確定申告 ライバー やり方", "slug": "副業確定申告ライバー", "hashtags": ["確定申告", "副業", "ライバー", "税金"]},
        {"keyword": "夜 副業 おすすめ 在宅", "slug": "夜副業おすすめ", "hashtags": ["夜", "副業", "在宅", "ライバー"]},
        {"keyword": "スキマ時間 副業 配信", "slug": "スキマ時間副業配信", "hashtags": ["スキマ時間", "副業", "配信", "ライバー"]},
        {"keyword": "副業 月5万 在宅 簡単", "slug": "副業月5万在宅", "hashtags": ["副業", "月5万", "在宅", "簡単"]},
        {"keyword": "在宅ワーク 配信 稼ぐ", "slug": "在宅ワーク配信", "hashtags": ["在宅ワーク", "配信", "稼ぐ", "ライバー"]},
        {"keyword": "副業 始め方 2026 初心者", "slug": "副業始め方2026", "hashtags": ["副業", "始め方", "2026", "初心者"]},
    ],
    "lifestyle": [
        {"keyword": "大学生 ライバー 稼ぐ 方法", "slug": "大学生ライバー稼ぐ", "hashtags": ["大学生", "ライバー", "稼ぐ", "副業"]},
        {"keyword": "主婦 ライバー 在宅 始め方", "slug": "主婦ライバー始め方", "hashtags": ["主婦", "ライバー", "在宅", "副業"]},
        {"keyword": "30代 ライバー 遅くない", "slug": "30代ライバー遅くない", "hashtags": ["30代", "ライバー", "副業", "ライブ配信"]},
        {"keyword": "40代 ライバー 始める", "slug": "40代ライバー始める", "hashtags": ["40代", "ライバー", "副業", "始め方"]},
        {"keyword": "男性ライバー コツ 稼ぐ", "slug": "男性ライバーコツ", "hashtags": ["男性ライバー", "コツ", "稼ぐ", "ライバー"]},
        {"keyword": "高校生 ライバー できる", "slug": "高校生ライバー", "hashtags": ["高校生", "ライバー", "ライブ配信", "始め方"]},
        {"keyword": "シングルマザー 副業 ライバー", "slug": "シンママ副業ライバー", "hashtags": ["シングルマザー", "副業", "ライバー", "在宅"]},
        {"keyword": "フリーター ライバー 生活", "slug": "フリーターライバー", "hashtags": ["フリーター", "ライバー", "生活", "収入"]},
        {"keyword": "地方 ライバー 稼げる", "slug": "地方ライバー稼げる", "hashtags": ["地方", "ライバー", "稼げる", "在宅"]},
        {"keyword": "社会人 ライバー 副業", "slug": "社会人ライバー副業", "hashtags": ["社会人", "ライバー", "副業", "両立"]},
        {"keyword": "看護師 副業 ライバー", "slug": "看護師副業ライバー", "hashtags": ["看護師", "副業", "ライバー", "在宅"]},
        {"keyword": "50代 ライブ配信 始める", "slug": "50代ライブ配信", "hashtags": ["50代", "ライブ配信", "ライバー", "始め方"]},
    ],
    "skills": [
        {"keyword": "ライブ配信 トーク術 コツ", "slug": "配信トーク術コツ", "hashtags": ["トーク術", "ライブ配信", "コツ", "ライバー"]},
        {"keyword": "ライバー リスナー 増やし方", "slug": "リスナー増やし方", "hashtags": ["リスナー", "増やし方", "ライバー", "ファン"]},
        {"keyword": "配信 ファン 作り方", "slug": "配信ファン作り方", "hashtags": ["配信", "ファン", "作り方", "ライバー"]},
        {"keyword": "ライブ配信 盛り上げ方 テクニック", "slug": "配信盛り上げ方", "hashtags": ["ライブ配信", "盛り上げ方", "テクニック", "ライバー"]},
        {"keyword": "配信 サムネイル 作り方", "slug": "配信サムネ作り方", "hashtags": ["サムネイル", "作り方", "配信", "ライバー"]},
        {"keyword": "配信 機材 おすすめ 2026", "slug": "配信機材おすすめ2026", "hashtags": ["配信機材", "おすすめ", "リングライト", "マイク"]},
        {"keyword": "リングライト おすすめ 配信", "slug": "リングライトおすすめ", "hashtags": ["リングライト", "おすすめ", "配信", "機材"]},
        {"keyword": "配信 照明 おすすめ 安い", "slug": "配信照明おすすめ", "hashtags": ["照明", "配信", "おすすめ", "ライバー"]},
        {"keyword": "マイク おすすめ ライブ配信", "slug": "マイクおすすめ配信", "hashtags": ["マイク", "おすすめ", "ライブ配信", "機材"]},
        {"keyword": "ライブ配信 背景 おしゃれ", "slug": "配信背景おしゃれ", "hashtags": ["配信背景", "おしゃれ", "ライブ配信", "ライバー"]},
    ],
    "troubleshooting": [
        {"keyword": "ライバー 伸びない 理由 対策", "slug": "ライバー伸びない対策", "hashtags": ["伸びない", "対策", "ライバー", "ライブ配信"]},
        {"keyword": "ライブ配信 辞めたい 対処法", "slug": "配信辞めたい対処法", "hashtags": ["辞めたい", "対処法", "ライバー", "メンタル"]},
        {"keyword": "配信 アンチ 対処法", "slug": "配信アンチ対処法", "hashtags": ["アンチ", "対処法", "配信", "ライバー"]},
        {"keyword": "ライバー メンタル 保ち方", "slug": "ライバーメンタル", "hashtags": ["メンタル", "ライバー", "対処法", "配信"]},
        {"keyword": "ライブ配信 リスナー 来ない", "slug": "配信リスナー来ない", "hashtags": ["リスナー", "来ない", "ライブ配信", "対策"]},
        {"keyword": "配信 マンネリ 打破 方法", "slug": "配信マンネリ打破", "hashtags": ["マンネリ", "打破", "配信", "ライバー"]},
        {"keyword": "ライバー 辛い しんどい", "slug": "ライバー辛い", "hashtags": ["辛い", "ライバー", "メンタル", "相談"]},
        {"keyword": "配信 モチベーション 維持", "slug": "配信モチベーション維持", "hashtags": ["モチベーション", "維持", "配信", "ライバー"]},
        {"keyword": "Pococha ランク 下がった 対策", "slug": "Pocochaランク下がった", "hashtags": ["Pococha", "ランク", "下がった", "対策"]},
        {"keyword": "ライブ配信 過疎 脱出", "slug": "配信過疎脱出", "hashtags": ["過疎", "脱出", "ライブ配信", "ライバー"]},
    ],
    "comparison": [
        {"keyword": "ライバー YouTuber 違い 比較", "slug": "ライバーYouTuber違い", "hashtags": ["ライバー", "YouTuber", "違い", "比較"]},
        {"keyword": "配信アプリ 比較 2026 一覧", "slug": "配信アプリ比較2026", "hashtags": ["配信アプリ", "比較", "2026", "おすすめ"]},
        {"keyword": "ライバー Vtuber どっち 向き", "slug": "ライバーVtuberどっち", "hashtags": ["ライバー", "Vtuber", "比較", "どっち"]},
        {"keyword": "顔出しなし 配信 方法 比較", "slug": "顔出しなし配信比較", "hashtags": ["顔出しなし", "配信", "比較", "Vtuber"]},
        {"keyword": "ライバー事務所 フリー 比較 2026", "slug": "事務所フリー比較2026", "hashtags": ["事務所", "フリー", "比較", "ライバー"]},
        {"keyword": "Pococha 17LIVE 比較 どっち", "slug": "Pococha17LIVE比較2", "hashtags": ["Pococha", "17LIVE", "比較", "どっち"]},
        {"keyword": "ライバー インフルエンサー 違い", "slug": "ライバーインフルエンサー違い", "hashtags": ["ライバー", "インフルエンサー", "違い", "比較"]},
        {"keyword": "稼げる 配信アプリ ランキング", "slug": "稼げる配信アプリランキング", "hashtags": ["稼げる", "配信アプリ", "ランキング", "ライバー"]},
        {"keyword": "副業 比較 ライバー 他", "slug": "副業比較ライバー", "hashtags": ["副業", "比較", "ライバー", "おすすめ"]},
        {"keyword": "ライバー チャットレディ 違い", "slug": "ライバーチャトレ違い", "hashtags": ["ライバー", "チャットレディ", "違い", "比較"]},
    ],
    "advanced": [
        {"keyword": "ライバー イベント 攻略法 2026", "slug": "イベント攻略法2026", "hashtags": ["イベント", "攻略", "ライバー", "2026"]},
        {"keyword": "Pococha S帯 なり方 コツ", "slug": "PocochaS帯なり方", "hashtags": ["Pococha", "S帯", "なり方", "ライバー"]},
        {"keyword": "ライバー ブランディング SNS", "slug": "ライバーブランディング", "hashtags": ["ブランディング", "SNS", "ライバー", "戦略"]},
        {"keyword": "配信者 SNS運用 戦略", "slug": "配信者SNS運用", "hashtags": ["SNS運用", "配信者", "戦略", "ライバー"]},
        {"keyword": "ライバー事務所 代理店 ビジネス", "slug": "事務所代理店ビジネス", "hashtags": ["代理店", "ビジネス", "ライバー事務所", "副業"]},
        {"keyword": "ライバー マネージャー 仕事内容", "slug": "ライバーマネージャー仕事", "hashtags": ["マネージャー", "仕事内容", "ライバー事務所", "転職"]},
        {"keyword": "専業ライバー 生活 リアル", "slug": "専業ライバー生活", "hashtags": ["専業ライバー", "生活", "リアル", "収入"]},
        {"keyword": "ライバー グッズ販売 収益化", "slug": "ライバーグッズ販売", "hashtags": ["グッズ販売", "収益化", "ライバー", "副収入"]},
        {"keyword": "ライブ配信 コラボ やり方", "slug": "配信コラボやり方", "hashtags": ["コラボ", "やり方", "ライブ配信", "ライバー"]},
        {"keyword": "ライバー 海外配信 方法", "slug": "ライバー海外配信", "hashtags": ["海外配信", "方法", "ライバー", "グローバル"]},
    ],
}

CATEGORIES = list(SEO_KEYWORDS.keys())

# ─── Gemini プロンプト ────────────────────────────────
ARTICLE_PROMPT = """あなたはライバー（ライブ配信者）専門のSEOライターです。
以下の条件で、Note.com向けのSEO記事を1本作成してください。

【ターゲットキーワード】{keyword}
【文字数】3000〜4000文字
【トーン】親しみやすく、でも信頼感のある文体。「です・ます」調。

【構成ルール】
- 最初の行にH1タイトル（# で始める）。SEOキーワードを含み、「｜」で副題を分ける。例:「# ○○｜△△な理由【2026年版】」
- 冒頭: 読者の悩みを共感する導入文（2〜3行、「」でセリフ調に）
- 権威付け: 「TAITAN PRO代表のたいたん」が解説する形式（元Pococha Sランク達成者＆ミクチャで8000人中ミスターコン1位）
- H2（##）で大見出し、H3（###）で小見出しを使う
- 箇条書き（- ）を多用して読みやすく
- 太字（**）で重要ワードを強調
- 具体的な数字を含める（統計、金額、期間など）
- 「よくある質問」セクション（Q&A形式で2〜3個）
- 最後に「まとめ」セクション

【絶対NGルール】
- Markdownテーブル（| | | 形式）は絶対に使わないこと。代わりに箇条書きで表現すること。
- 水平線（---）は使わないこと
- コードブロック（```）は使わないこと
- 「筆者」ではなく「たいたん」と表記すること
- 記事末尾にCTAや宣伝文を含めないこと（別途追加します）

記事本文のみをMarkdownで出力してください。説明文やメタ情報は不要です。"""


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
    """使用済みキーワードのセットを返す"""
    return {item["keyword"] for item in tracker.get("used", [])}


def get_next_keyword(tracker):
    """カテゴリローテーションで次のキーワードを選択"""
    used = get_used_keywords(tracker)
    last_idx = tracker.get("last_category_index", -1)

    # 全カテゴリを試す
    for offset in range(1, len(CATEGORIES) + 1):
        cat_idx = (last_idx + offset) % len(CATEGORIES)
        category = CATEGORIES[cat_idx]
        unused = [kw for kw in SEO_KEYWORDS[category] if kw["keyword"] not in used]
        if unused:
            chosen = random.choice(unused)
            chosen["category"] = category
            tracker["last_category_index"] = cat_idx
            return chosen

    return None  # 全キーワード使用済み


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


def generate_article(api_key, keyword_info):
    """Gemini APIで記事を生成（503/429エラー時は自動リトライ＋フォールバックモデル）"""
    import time
    from google import genai

    client = genai.Client(api_key=api_key)

    prompt = ARTICLE_PROMPT.format(keyword=keyword_info["keyword"])

    # 複数モデルを順に試行（503/429エラー時はフォールバック）
    models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
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

def generate_one(api_key, dry_run=False):
    """1記事を生成"""
    tracker = load_tracker()
    keyword_info = get_next_keyword(tracker)

    if keyword_info is None:
        print("  全キーワードを使い切りました。")
        return None

    article_num = get_next_article_number()

    print(f"\n── 記事 #{article_num} ──────────────────────────")
    print(f"  カテゴリ: {keyword_info['category']}")
    print(f"  キーワード: {keyword_info['keyword']}")
    print(f"  ハッシュタグ: {' '.join('#' + t for t in keyword_info['hashtags'])}")

    if dry_run:
        print("  [dry-run] 生成スキップ")
        return {"number": article_num, "keyword": keyword_info, "dry_run": True}

    # Gemini で記事生成
    raw_article = generate_article(api_key, keyword_info)

    # 後処理
    processed = post_process_article(raw_article)

    # CTA追加
    final_content = processed + CTA_BLOCK

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
    used = tracker.get("used", [])
    total_keywords = sum(len(v) for v in SEO_KEYWORDS.values())

    print(f"\n{'='*50}")
    print(f"  SEOキーワード統計")
    print(f"{'='*50}")
    print(f"  総キーワード数: {total_keywords}")
    print(f"  使用済み: {len(used)}")
    print(f"  残り: {total_keywords - len(used)}")
    print(f"  残日数（3記事/日）: {(total_keywords - len(used)) // 3}日")
    print()

    used_kw = get_used_keywords(tracker)
    for cat in CATEGORIES:
        total = len(SEO_KEYWORDS[cat])
        cat_used = sum(1 for kw in SEO_KEYWORDS[cat] if kw["keyword"] in used_kw)
        bar = "█" * cat_used + "░" * (total - cat_used)
        print(f"  {cat:20s} [{bar}] {cat_used}/{total}")
    print()


def list_unused():
    """未使用キーワード一覧"""
    tracker = load_tracker()
    used = get_used_keywords(tracker)

    print(f"\n未使用キーワード一覧:")
    for cat in CATEGORIES:
        unused = [kw for kw in SEO_KEYWORDS[cat] if kw["keyword"] not in used]
        if unused:
            print(f"\n  [{cat}] ({len(unused)}個)")
            for kw in unused:
                print(f"    - {kw['keyword']}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Note記事 自動生成（Gemini API）")
    parser.add_argument("--generate", action="store_true", help="記事を生成")
    parser.add_argument("-n", type=int, default=1, help="生成する記事数（デフォルト: 1）")
    parser.add_argument("--dry-run", action="store_true", help="生成せずにキーワード選択のみ確認")
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
        for i in range(args.n):
            result = generate_one(api_key, dry_run=args.dry_run)
            if result is None:
                break
            results.append(result)

        print(f"\n生成完了: {len(results)}記事")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
