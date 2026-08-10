"""
投稿自動進化スクリプト（Gemini AI版）
伸びた投稿パターンを分析 → Gemini AIで毎回ユニークな投稿を生成

テンプレ投稿はXアルゴリズムに嫌われるため、
毎週AIで新鮮なコンテンツを自動生成する

使い方:
  python3 cloud_evolve.py                # 生成してキューに追加（本番）
  python3 cloud_evolve.py --dry-run      # 生成するが保存しない。検品通過率を出す
  python3 cloud_evolve.py --check-facts  # 検品ルールとFACTSの対応漏れを検査（API不要）
"""

import argparse
import os
import json
import random
import sys
import time

import tweepy

from x_post_guard import NG_PATTERNS, violations

try:
    from google import genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
POSTS_FILE = "posts/twitter_posts.json"

# 生成→検品の通過率。FACTSと検品がズレていると rejected が跳ね上がる＝
# Gemini呼び出しの空振り。--dry-run と本番の両方でサマリを出す。
GUARD_STATS = {"checked": 0, "rejected": 0, "reasons": {}}

# --- 対立軸テーマ（論争・引用を誘発）---
# 人間化改修(2026-06-15): これ「だけ」だと毎投稿が同じ煽りテンプレでbot臭くなる。
# 下の EXPERIENCE_THEMES と交互に使い、生成プロンプトも分ける。
THEMES = [
    "事務所所属 vs フリーランスのライバー、結局どっちが得か（対立軸）",
    # 取扱は Pococha・TikTok LIVE・17LIVE の3つ。IRIAM等は書かない
    "Pococha vs 17LIVE vs TikTok LIVE、稼げるアプリ論争（対立軸）",
    "ライバー副業を会社にバレずにやる方法（ツッコミ歓迎の言い切り）",
    "「ライバーは楽して稼いでる」論への反論（噛みつき誘発）",
    "顔出しなしライバー vs 顔出しライバー、収入の現実差（対立軸）",
    # 「月収格差」は金額を並べたくなるテーマ。少額表記は確定レンジ違反なので、
    # 金額でなく「要因」で語らせる（2026-08-10: 破棄理由の1位が少額表記だった）
    "ライバーの月収格差を生んでいる要因は何か（金額でなく要因で語る／強めの主張）",
    "ライバー事務所の取り分は搾取か投資か（業界論争）",
    "副業勢ライバー vs 専業ライバー、続くのはどっち（対立軸）",
    "20代女性が会社員辞めてライバー専業になるのはアリかナシか",
    "男性ライバーが稼げない説は本当か（少数派視点で反論）",
    "ライバー初月でつまずく人に共通する準備不足（言い切り）",
    # 旧「実数字で殴る」は数字の捏造を指示していたのと同じなので削除
    "代理店ビジネスは稼げる/稼げない論争（構造で殴る）",
    "ライブ配信は若い子のもの説に40代が反論（世代論争）",
    "イベント期間中の課金圧、ファンに頼るのはアリかナシか",
    "「楽しいから配信してる」勢 vs 「金のため」勢、どっちが伸びるか",
]

# --- 経験・一次情報テーマ（AIに書けない「中の人」ネタ）---
# たいたん＝Pococha歴4年・運営ダッシュボードで所属ライバーの成績が見える立場。
# 対立軸の煽りではなく、現場で見てきた具体的な観察・気づきを淡々と書く。
EXPERIENCE_THEMES = [
    "Pococha運営4年で見てきた『伸びる配信者』と『消える配信者』の分かれ目",
    "所属ライバーを見ていて気づいた、配信続く人の共通点（地味な習慣）",
    "ライバー始めた人が最初の1ヶ月でつまずくポイントと、その乗り越え方",
    "事務所代表として実際にやっているサポートの中身（誇張なし・等身大）",
    "配信現場でよく聞かれる質問に、4年見てきた立場から正直に答える",
    "ランクが上がる子が配信前後でやっている、目立たない準備",
    "副業でライバーをしている人が、無理なく続けられている工夫",
    "数字が伸び悩んだ時期の配信者が、どう立て直していったかの観察",
    "コメントが少ない配信を、コメントが増える配信に変えた小さな変化",
    "『顔出ししたくない』人が実際にどう配信を組み立てているか",
]

# 両プロンプトの末尾に差し込む確定ファクト制約（[[project_taitan_pro_note_facts]]）。
# 2026-08-09 追加。これが無かった頃のプロンプトは「フリーで稼げる人は1割、
# 残り9割は事務所入った方が早い」を**勝ちパターンの手本として提示していた**ため、
# 生成物に出典なしの割合統計が量産され、そのままXに公開されていた。
# 文章での指示は破られる前提で、x_post_guard.violations() でも機械的に弾く。
#
# 2026-08-10 補完。x_post_guard.NG_PATTERNS / facts_patterns の全チェックと
# **1対1で対応させた**。以前は検品にあってFACTSに無い項目が10個あり
# （統括/傘下・現役表記・マージンゼロ・DM誘導・オンライン無料相談・カーブアウト・
#   旧特典PDF名・lit.link・不労所得/権利収入・実績誇張）、
# その分だけ「生成→検品で破棄」の空振りが出る状態だった。
# **検品側にチェックを足したら、必ずここにも同じ項目を足すこと。**
FACTS = """【割合統計の禁止（最優先・違反したら投稿は破棄される）】
- 業界の割合・率を**一切書かない**。裏が取れる出典が存在しないため全部でっち上げになる。
  禁止例: 「9割が挫折する」「99%が知らない」「10人に1人も成功しない」
          「9割の副業ライバーは〜」「90%以上が半年で撤退」「離職率80%」
- 「◯割の人が/◯%のライバーが」という**主語の修飾**も同じく禁止。
- 割合の代わりに、断定したいときは「多い」「よく見る」「ほとんど」で書く。

【金額の下限（違反が最も多い。必ず守る）】
- 収入は 3ヶ月15〜20万 / 6ヶ月30〜40万 / Pococha B帯 月20〜30万 のみ。
- **「月◯万」と書くとき、◯が15未満なら一律で違反**（「月3万」「月10万」「お小遣い程度」型）。
  これは **他人の失敗例・稼げていない側の描写・過去の自分の話であっても同じ**。
  月収格差や「稼げない人」の話をするときは、金額を出さずに
  「伸びない」「思ったより増えない」と**状態で書く**こと。

【リスナーの呼称（違反が2番目に多い。必ず守る）】
- 視聴者は **必ず「リスナーさん」**。「リスナー」という呼び捨ては1回でも使ったら破棄。
- 「リスナーが増えない」→「リスナーさんが増えない」。
  複合語（リスナー層・リスナー数・固定リスナー）も**すべて「リスナーさん」に開いて書く**。
  例:「固定リスナーがつく」→「いつも来てくれるリスナーさんがつく」

【その他の確定ファクト】
- 「手数料」という単語は使わない（他社が引いている、という比較も禁止）。報酬は「還元率100%+α」。
  「マージンゼロ」「ノーマージン」「マージン0%」も同義語なので禁止
- 所属ライバー数は「200名」固定。「200名以上」「累計◯名」「総勢◯名」「延べ◯名」は書かない
- 代理店との関係は「提携」。「統括」「傘下」とは書かない
- 代表たいたんは **元** Pococha S帯。「現役ライバー」「現役プレイヤー」とは書かない
- 扱うのは Pococha・TikTok LIVE・17LIVE の3つ。IRIAM/SHOWROOM/ふわっち/REALITY は出さない。
  「他アプリも多数」のような曖昧なまとめ方もしない
- 「いつでも退所」「違約金なし」「契約期間」には触れない
- 「絶対稼げる」「確実に」「必ず月◯万」「保証」等の断定・保証表現は使わない
- 「不労所得」「権利収入」は使わない（マルチ的表現）
- 「多数輩出」「多くの実績」「続々と」「数百人」「何百人」「数千」など、
  裏の取れない実績の誇張は書かない
- 「カーブアウト（パートナー）」という呼称は使わない。名乗るなら TAITAN PRO
- 特典PDFの名前は『ライバー新人期スタートダッシュガイド』。
  旧名の「Pococha新人期スタートダッシュ〜」は書かない
- CTAをDM誘導にしない（「DMで相談」「お気軽にDM」等）。導線は特典PDF→LINE登録に統一。
  「オンライン無料相談」という言い方もしない。
  ※そもそもこの投稿にURL・リンク（lin.ee / lit.link 等）は入れない
"""


# ── 検品ルール ↔ FACTS の対応表 ────────────────────────────────
# 2026-08-10。検品(x_post_guard)にだけルールを足してFACTSに書き忘れると、
# AIは違反を教わらないまま出し続け、生成のたびに捨てられる（＝Gemini呼び出しの
# 空振り）。それを検知するために、検品ラベルごとに「FACTSに必ず出現する語」を
# 明示する。--check-facts で照合し、対応が無ければ落とす。
#
# 検品側に新しいNG_PATTERNSを足したら、FACTSに1行足して、ここにも1行足す。
FACTS_COVERAGE = {
    "所属数が200名以外": "200名",
    "所属数の旧表記（累計/総勢）": "総勢◯名",
    "代理店の関係が「提携」でない（統括/傘下）": "統括",
    "代表は「元」Pococha S帯（現役表記はbioと矛盾）": "現役ライバー",
    "禁止語「手数料」": "手数料",
    "「マージンゼロ」＝手数料なしの同義語": "マージンゼロ",
    "「いつでも退所」「違約金なし」系／契約期間への言及": "違約金なし",
    "還元率が「100%+α」になっていない": "還元率100%+α",
    "還元率が確定値でない": "還元率100%+α",
    "取扱外プラットフォーム": "IRIAM",
    "取扱は Pococha・TikTok LIVE・17LIVE の3つで統一": "他アプリも多数",
    "CTAがDM誘導（導線は特典PDF→LINE登録に統一）": "DMで相談",
    "「オンライン無料相談」は使わない": "オンライン無料相談",
    "使用禁止ブランド（TAITAN PROで統一）": "カーブアウト",
    "旧・特典PDF名": "Pococha新人期スタートダッシュ",
    "リンクが lit.link（公式LINEでない）": "lit.link",
    "リスナーの呼び捨て": "リスナーさん",
    "断定・保証表現": "保証",
    "マルチ的表現": "不労所得",
    "根拠なしの実績誇張": "多数輩出",
    # facts_patterns.py（媒体共通の正本）由来。ラベルは実際に検品を通して集める
    "出典なしの割合統計（離脱/成功率）": "割合",
    "出典なしの割合統計（割合が主語を修飾）": "割合",
    "確定レンジ未満の少額表記（月15万が下限）": "15未満",
    "許可リスト外のLINEリンク": "lin.ee",
}

# facts_patterns 由来のラベルは動的に組み立てられるので、実際に違反サンプルを
# 検品に通してラベルを回収する（文字列をコピペすると必ず片方が古くなる）。
_SHARED_PROBES = [
    "9割が辞めていく現実",
    "9割のライバーはフリーで十分",
    "月3万くらいから始まる",
    "詳しくは https://lin.ee/xxxxxxx へ",
]


def check_facts_coverage(verbose=True):
    """検品ルールに対応するFACTSの記述が無い項目を返す。空なら1対1で揃っている。"""
    labels = [label for _pat, label in NG_PATTERNS]
    for probe in _SHARED_PROBES:
        labels += violations(probe)

    missing = []
    for label in dict.fromkeys(labels):          # 順序を保って重複除去
        anchor = FACTS_COVERAGE.get(label)
        if anchor is None:
            missing.append((label, "FACTS_COVERAGE に対応表が無い"))
        elif anchor not in FACTS:
            missing.append((label, f"FACTS に「{anchor}」が出てこない"))

    if verbose:
        if missing:
            print(f"[NG] 検品ルール {len(missing)}件が FACTS に書かれていない:")
            for label, why in missing:
                print(f"  - {label} … {why}")
        else:
            print(f"[OK] 検品ルール {len(set(labels))}件すべてが FACTS に対応済み")
    return missing

PROMPT_TEMPLATE = """あなたはX(Twitter)で「ライブ配信」「ライバー副業」「ライバー事務所」について発信しているアカウントの投稿を書きます。
目的は **インプレッション最大化** と **DM/LP流入**。そのために以下の収益構造を最大限利用します。

【X伸ばしの根幹原理（最重要）】
- Xの露出は「リプ欄を開かせた時間」「リプ数」「引用数」で決まる
- KPI: ①リプ欄を開かせる ②リプを書かせる ③引用させる
- そのために投稿には **意図的に「噛みつきたくなる隙」「ツッコミどころ」「断言」** を残す
- 完璧な情報を出し切らない。「続きはリプで」or「スレッドで答え」 で**リプ欄に誘導**する

【勝ちパターン3種（必ずどれかを使う）】
(A) **分割スレッド型** — 1ツイート目で強い問題提起・断言・ランキング予告で切る → リプライで答え/続きを書く
    例: 「ライバー事務所に入る前に見るべきポイント、全部書く ↓」→ 続きをスレッドで展開
(B) **対立軸・論争型** — ❌⭕や A vs B で立場をハッキリ取る。賛否両論を呼ぶ言い切り
    例: 「副業でやるならフリーで十分。事務所が効くのは本気で上を狙うときだけ。理由は3つ↓」
(C) **ツッコミどころ断言型** — わざと突っ込まれそうな極端な断言を入れる（事実ベースで）
    例: 「Pocochaで伸びない人、配信時間が足りないだけ」

【守るべきルール】
1. 出力は **必ずJSON配列**。各要素は **2〜4ツイートのスレッド配列**
2. 1ツイート目は120〜140文字（日本語全角）、強いフック。最後を「↓」「↓続く」「答えは下に」等で締めてリプ欄を開かせる
3. 2ツイート目以降は100〜140文字。具体ノウハウ・数字・箇条書きで本体を展開
4. 数字は「配信時間」「日数」「項目数」など**自分で確認できるもの**を使う。
   **業界の割合・率は絶対に書かない**（後述の【割合統計の禁止】を必ず読むこと）。
   金額を出すときは後述の確定レンジのみ。**月15万未満の金額は書かない**
5. 最終ツイートの末尾に **議論を呼ぶ問いかけ or 引用させる挑発** を入れる
   例: 「異論あれば引用で殴ってきてOK」「あなたはどっち派？」「これ反対する人おる？」
6. 絵文字は1スレッドにつき1〜2個まで。本文中の乱用は禁止
7. タメ口・断定調。「〜です／〜します」の丁寧語禁止
8. 宣伝臭・URL・事務所名は入れない
9. **「あるある」「人見知り」「エモい」系の内輪話は完全禁止**。論争・実数字・断言だけ
10. ブランド毀損になる過激ネタは禁止（性的・差別・違法・他社実名disり）。論争は「業界構造」「働き方」に限定

{facts}

【データに基づく勝ちパターン（直近の分析）】
- 伸びる: 箇条書き5項目、❌⭕対比、具体数字（配信時間・日数・項目数）、断言、リプ誘導
- 沈む: あるある、内輪話、抽象論、丁寧すぎる説明

テーマ: {theme}

{top_posts_context}

上記テーマで、3スレッド分の投稿案をJSONで出力してください。
出力フォーマット（**これ以外の文字を出力しない**、コードブロックも不要、純粋なJSONのみ）:
[
  ["1ツイート目（フック）", "2ツイート目", "3ツイート目"],
  ["1ツイート目", "2ツイート目", "3ツイート目", "4ツイート目"],
  ["1ツイート目", "2ツイート目"]
]
"""


EXPERIENCE_PROMPT_TEMPLATE = """あなたはX(Twitter)でライブ配信・ライバー事務所について発信しているアカウントの「中の人」です。
このアカウントの人物像：**Pococha歴4年。今はライバー事務所の代表で、所属ライバーの配信を日々見ている。**
今回は対立軸で煽る投稿ではなく、**現場で実際に見てきた等身大の気づき**を書きます。フォロワーに「この人は本物だ」と思わせるのが目的。

【このタイプの投稿が刺さる理由】
- AIや他のアカウントは一般論しか書けない。あなたは「4年見てきた具体的な場面」を書ける。ここが唯一の武器。
- 煽り・断言・ランキングではなく、**観察の解像度**で信頼を取る。

【守るべきルール】
1. 出力は **必ずJSON配列**。各要素は **2〜4ツイートのスレッド配列**
2. 1ツイート目は具体的な場面・観察から入る。フックは「煽り」ではなく「あ、それ分かる/それ知りたい」と思わせる具体性で作る
   良い例:「配信が続く子と辞める子、4年見てきて差が出るのは才能じゃなくて配信後の5分だった」
   悪い例:「99%が知らない裏側を全部書く↓」(←煽りテンプレ。今回は禁止)
3. 2ツイート目以降は具体的な行動・場面を描写する。抽象的な精神論にしない
4. **数字は、確実に言える範囲でだけ使う。盛らない・でっち上げない。** 数字が無くても「ある子は〜」「よく見るのは〜」と具体場面で語れば十分
5. 末尾は自然に終える。**「異論あれば引用で殴ってこい」「あなたはどっち派？」等の定型挑発は禁止。**
   問いかけるなら「みんなはどう？」程度の自然なトーン、もしくは静かに言い切って終わってもいい
6. タメ口・自然な語り口。ただし煽らない。先輩が後輩に話すくらいの温度
7. 絵文字は0〜1個。乱用禁止
8. 宣伝臭・URL・事務所名は入れない
9. **毎回同じ書き出し・同じ締めにしない。** スレッドごとに入り方を変える
10. 断定しすぎない。「〜なことが多い」「〜な子をよく見る」など、観察ベースの誠実な言い回しを混ぜる

{facts}

テーマ: {theme}

{top_posts_context}

上記テーマで、3スレッド分の投稿案をJSONで出力してください。
出力フォーマット（**これ以外の文字を出力しない**、コードブロックも不要、純粋なJSONのみ）:
[
  ["1ツイート目", "2ツイート目", "3ツイート目"],
  ["1ツイート目", "2ツイート目"],
  ["1ツイート目", "2ツイート目", "3ツイート目", "4ツイート目"]
]
"""


def analyze_tweets():
    """過去の投稿を分析して伸びたパターンを特定する"""
    try:
        client = tweepy.Client(
            bearer_token=os.environ.get("TWITTER_BEARER_TOKEN", ""),
            consumer_key=os.environ.get("TWITTER_API_KEY", ""),
            consumer_secret=os.environ.get("TWITTER_API_SECRET", ""),
            access_token=os.environ.get("TWITTER_ACCESS_TOKEN", ""),
            access_token_secret=os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", ""),
        )

        me = client.get_me()
        tweets = client.get_users_tweets(
            id=me.data.id,
            max_results=50,
            tweet_fields=["public_metrics", "text"],
        )

        if not tweets.data:
            return []

        scored = []
        for t in tweets.data:
            m = t.public_metrics
            score = (
                m["like_count"] * 1
                + m["retweet_count"] * 3
                + m["reply_count"] * 2
                + m["impression_count"] * 0.001
            )
            scored.append({"text": t.text, "score": score})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:10]

    except Exception as e:
        print(f"Twitter API分析をスキップ（{type(e).__name__}: {e}）")
        return []


def _extract_json_array(text):
    """Geminiの応答から最初のJSON配列を抽出（コードフェンス・前置きを許容）"""
    import re
    # コードフェンス除去
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    # 最初の '[' から対応する ']' までを抜き出す
    start = text.find("[")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def generate_with_gemini(theme, top_posts, style="debate"):
    """Gemini AIでスレッド投稿を生成。返り値は List[List[str]]
    style: "debate"=対立軸・煽り型 / "experience"=経験・一次情報型
    """
    if not HAS_GEMINI or not GEMINI_API_KEY:
        print("[WARN] Gemini API未設定。スキップ。")
        return []

    top_posts_context = ""
    if top_posts:
        top_posts_context = "【参考: 伸びた過去の投稿】\n"
        for i, p in enumerate(top_posts[:5], 1):
            text_preview = p["text"][:80].replace("\n", " ")
            top_posts_context += f"{i}. {text_preview}...\n"

    template = EXPERIENCE_PROMPT_TEMPLATE if style == "experience" else PROMPT_TEMPLATE
    prompt = template.format(
        theme=theme,
        top_posts_context=top_posts_context,
        facts=FACTS,
    )

    client = genai.Client(api_key=GEMINI_API_KEY)

    # リトライ（Gemini 503対策）
    # 2026-04: gemini-2.0-flash / 1.5-flash は deprecated/404。
    # 2.5-flash → 2.5-flash-lite → 3.1-flash-lite-preview の順にフォールバック。
    models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.1-flash-lite-preview"]
    for model_name in models:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                raw = response.text.strip()
                payload = _extract_json_array(raw)
                if not payload:
                    print(f"  [WARN] {model_name}: JSON配列が見つからない (試行{attempt+1})")
                    continue
                try:
                    threads = json.loads(payload)
                except json.JSONDecodeError as e:
                    print(f"  [WARN] {model_name}: JSON parse失敗 {e} (試行{attempt+1})")
                    continue

                # 構造バリデーション＋確定ファクトの機械検品
                cleaned = []
                for th in threads:
                    if not isinstance(th, list):
                        continue
                    tweets = [t.strip() for t in th if isinstance(t, str) and t.strip()]
                    # 各ツイート 30〜260 文字（X上限280）でフィルタ
                    tweets = [t for t in tweets if 20 < len(t) < 270]
                    if not 2 <= len(tweets) <= 5:
                        continue
                    # 2026-08-09 追加。プロンプトの文章指示だけでは割合統計が
                    # 止まらなかった（実測でXに公開まで到達）。スレッド全体を
                    # 連結して当て、1ツイートでも違反したらスレッドごと捨てる。
                    v = violations("\n".join(tweets))
                    GUARD_STATS["checked"] += 1
                    if v:
                        GUARD_STATS["rejected"] += 1
                        for label in v:
                            GUARD_STATS["reasons"][label] = \
                                GUARD_STATS["reasons"].get(label, 0) + 1
                        print(f"  [NG] 検品で破棄: {', '.join(v)}\n       {tweets[0][:40]}...")
                        continue
                    cleaned.append(tweets)
                if cleaned:
                    return cleaned
            except Exception as e:
                print(f"  Gemini {model_name} 試行{attempt+1}: {e}")
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))

    return []


def _print_guard_summary():
    """検品の通過率サマリ。rejected が多いなら FACTS と検品がズレている。"""
    checked = GUARD_STATS["checked"]
    if not checked:
        print("\n検品サマリ: 生成物なし（Gemini未設定 or 全リトライ失敗）")
        return
    ok = checked - GUARD_STATS["rejected"]
    print(f"\n検品サマリ: 生成 {checked}本 → 通過 {ok}本 / 破棄 "
          f"{GUARD_STATS['rejected']}本（破棄率 {GUARD_STATS['rejected'] / checked:.0%}）")
    for label, n in sorted(GUARD_STATS["reasons"].items(),
                           key=lambda kv: -kv[1]):
        print(f"  {n:3d}  {label}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="生成して検品するが、キューにもレポートにも書き込まない")
    ap.add_argument("--check-facts", action="store_true",
                    help="検品ルールとFACTSの対応漏れだけ検査する（Gemini呼び出しなし）")
    args = ap.parse_args()

    # 0. 検品ルールとFACTSの1対1対応を先に検査する。
    #    ここがズレたまま生成すると、AIは違反を教わらないまま出し続けて
    #    毎回捨てられる（＝Gemini呼び出しの空振り）。
    missing = check_facts_coverage()
    if args.check_facts:
        return 1 if missing else 0

    # 1. 過去の投稿を分析
    top_posts = analyze_tweets()
    if top_posts:
        print(f"トップ投稿 {len(top_posts)}件を分析済み")
    else:
        print("過去投稿の分析なし（新規生成モード）")

    # 2. 既存投稿を読み込み
    with open(POSTS_FILE, "r", encoding="utf-8") as f:
        existing = json.load(f)

    # 重複防止: 既存の先頭ツイート(または text)の頭30文字をキー化
    def _head_key(post):
        if "thread" in post and post["thread"]:
            return post["thread"][0][:30]
        return post.get("text", "")[:30]

    existing_keys = {_head_key(p) for p in existing}
    # evo_NNN の最大番号から続きを採番（カウント方式だと衝突する）
    import re
    used_nums = [int(m.group(1)) for p in existing
                 if (m := re.match(r"evo_(\d+)$", p.get("id", "")))]
    next_id = (max(used_nums) + 1) if used_nums else 1
    new_count = 0

    # 3. テーマ選定: 経験型を多めに(2)、対立軸を控えめに(2)。
    #    人間化改修(2026-06-15): 以前は対立軸4テーマ=全投稿が煽りテンプレでbot臭かった。
    #    経験・一次情報型を半分入れて「中の人」感を出す。
    exp_themes = [("experience", t) for t in random.sample(EXPERIENCE_THEMES, 2)]
    deb_themes = [("debate", t) for t in random.sample(THEMES, 2)]
    selected = exp_themes + deb_themes
    random.shuffle(selected)
    selected_themes = [t for _, t in selected]  # レポート用

    for style, theme in selected:
        print(f"\n[{style}] テーマ: {theme}")
        threads = generate_with_gemini(theme, top_posts, style=style)

        for thread in threads:
            head = thread[0][:30]
            if head in existing_keys:
                print(f"  [SKIP] 重複: {head}...")
                continue

            existing.append({
                "id": f"evo_{next_id:03d}",
                "phase": "growth",
                "style": style,
                "thread": thread,
            })
            existing_keys.add(head)
            new_count += 1
            next_id += 1
            print(f"  ✅ 追加({len(thread)}T): {thread[0][:40]}...")

    _print_guard_summary()

    if args.dry_run:
        print(f"\n[dry-run] {new_count}件を追加できたが書き込みはしない"
              f"（キューは {len(existing) - new_count}件のまま）")
        return 0

    # 4. 保存
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=4)

    print(f"\n{new_count}件の新投稿を追加（合計: {len(existing)}件）")

    # 分析レポート保存
    os.makedirs("data", exist_ok=True)
    with open("data/evolution_report.json", "w", encoding="utf-8") as f:
        json.dump({
            "top_posts": top_posts[:5] if top_posts else [],
            "themes_used": selected_themes,
            "new_posts_added": new_count,
            "total_posts": len(existing),
            # 検品の通過率。急に落ちたら FACTS と検品のズレを疑う
            "guard_checked": GUARD_STATS["checked"],
            "guard_rejected": GUARD_STATS["rejected"],
            "guard_reasons": GUARD_STATS["reasons"],
        }, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
