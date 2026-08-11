"""
Threads 投稿コンテンツ生成（Gemini）

ライバー集客のPull戦略に沿った投稿を生成してキューに足す。
コールドDM・自動フォロー・自動いいねは一切やらない（投稿だけ）。

■ 2026-08-07 全面改訂の根拠（data/threads_insights.csv / n=116の実測）
  宣伝型 平均17views ／ 混在型 33 ／ 本音型 141   → 宣伝ブロックは即死
  〜80字 189views ／ 81-180字 84 ／ 301字〜 15.5   → 長文は読まれない
  リンクあり 中央値10views ／ なし 25.5（生成分のみで比較） → リンクはリーチを半減させる
  手書きstory 246views ／ 生成liver 38 ／ agency 17
  さらに7月を通してリーチが単調減少（中央値43→10）＝宣伝の連投で沈められている
  よって「短い本音」を主軸にし、宣伝と外部リンクを絞る設計に変えた。

■ 2026-08-10 配分の是正（n=121で再集計）
  angle別 平均views: story 245.1(n=33) / liver 38.3(n=76) / agency 17.4(n=11)
  style別 平均views: 本音型 143.9(n=69) / 混在型 34.0(n=22) / 宣伝型 17.4(n=30)
  上位5本はすべて story×本音型（最高1,317views）。
  ところが実際に出していた配分は liver 62.8% / story 27.3% で、
  **いちばん伸びない型をいちばん多く出していた**。
  月別に見るとこれが直接リーチに出ている:
    6月前半 story 53% → 平均188views
    7月中旬 story  0% / liver 93% → 平均26.5views（リーチ崩壊）
  よって TARGET_MIX を story 60% / liver 25% / agency 15% に固定し、
  生成側(_mix)だけでなく投稿側(threads_poster._pick_by_mix)でも担保する。
  生成の配分を直しても、キューの消化がFIFOのままだと実際に世に出る比率は
  キューの並び順で決まってしまい、意味がなかったため。

3系統:
  - story  : 短い本音・現場のリアル（事務所名も誘導も入れない）。主力。
  - liver  : ライバー本人向けの気づき（役に立つ話→最後に小さく一言）
  - agency : 代理店パートナー募集（本数を絞る。滑りやすいので価値提供に徹する）
             LINE/代理店LPへの導線なので、ゼロにはせず1〜2割で残す。

確定ファクト（project_taitan_pro_note_facts）を厳守し、
生成後に _violations() で機械検品して、違反した投稿はキューに入れない。

使い方:
  python threads/threads_content.py --gen 8       # 型配分に沿って8本生成
  python threads/threads_content.py --angle story --gen 6
  python threads/threads_content.py --audit       # 既存キューを検品（未投稿分に違反があれば exit 1）
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POSTS_FILE = os.path.join(SCRIPT_DIR, "threads_posts.json")

# 割合統計のパターンはリポジトリ直下の facts_patterns.py が正本（媒体共通）。
# 2026-08-09: Threads のキューは実測で違反ゼロだったが、_violations() 自体には
# 割合統計の検査が無く、X と同じ事故（「9割の副業ライバーは〜」）を止められない
# 状態だった。潜在的な穴なので同じ正本に繋いでおく。
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))
from facts_patterns import ratio_violations  # noqa: E402

LP_AGENCY = ("https://taitan-pro-lp.netlify.app/agency/"
             "?utm_source=threads&utm_medium=post&utm_campaign=threads_post")
LINE_URL = "https://lin.ee/xchCfdn"

# ── 型の配分（実測ベース。threads_poster.py も投稿順の決定にこれを読む）─────
# data/threads_insights.csv n=121 の平均views:
#   story 245.1 (n=33) / liver 38.3 (n=76) / agency 17.4 (n=11)
# 上位5本はすべて story×本音型（最高1,317views）。宣伝型は25〜42viewsに張り付く。
# にもかかわらず2026-08-07以前の在庫は liver が6割で、いちばん伸びない型を
# いちばん多く出していた。生成・投稿の両方をこの配分に合わせる。
# agency をゼロにはしない（LINE/代理店LPへの導線が必要なため）。
# ── 2026-08-11 代理店を厚くする方針への変更 ───────────────────────
# ライバー募集より代理店パートナー募集を主軸にする方針になったので agency を増やす
# （15% → 30%）。ただし過去の agency 平均17.4viewsをそのまま3倍にすると
# アカウント全体のリーチが沈む。実測が示していたのは「agencyという題材が弱い」
# ではなく「agencyの投稿だけ宣伝型で書かれていた」ことなので、
# 本数を増やすと同時に STYLE_SPECS["agency"] を本音型に書き換える。
# 増やした分は liver から取る（storyは伸びる主力なので5割は死守する）。
TARGET_MIX = {"story": 0.50, "liver": 0.20, "agency": 0.30}
AGENCY_MAX_SHARE = 0.35   # 代理店は多くても35%まで
AGENCY_MIN_TOTAL = 3      # 3本以上まとめて作るときは最低1本は代理店を入れる

# リンク付き投稿はリーチが半分以下になる（実測）。6本に1本だけに絞る。
LINK_EVERY = 6

# 本文の上限。実測で300字超は平均15viewsまで落ちるので、上限自体を厳しくする。
MAX_LEN = 260
STORY_MAX_LEN = 120

# CTAは本文ではなく本投稿への返信に置く（本文リンクはリーチを半減させるため）。
LEAD_MAGNET_LINE = "新人期の30日でやることを全部まとめたPDF、LINEの友だち追加で配ってます。"
# 2026-08-11: 代理店側もLPではなくLINE（特典PDF）へ直接繋ぐ。
# [[feedback_leadmagnet_first]] CTAは特典PDF経由のLINE登録を最優先にする方針。
AGENCY_CTA_LINE = (
    "代理店パートナーの仕事の中身をまとめたPDF、LINEの友だち追加で配ってます。"
)

# 2026-08-10: FACTS が「月10万円未満は禁止」と教えていたのに、_violations() の
# 下限は15万だった。AIは「月12万」を安全だと思って書き、毎回検品で落ちる。
# 検品側に合わせて15万に統一し、あわせて検品にあってFACTSに無かった項目
# （不労所得/権利収入・カーブアウトパートナー・オンライン無料相談・オフの日の主語）を追記。
FACTS = """
【絶対に守る確定ファクト】
- 事務所名：TAITAN PRO
- 還元率100%+α。「90%」「相場70-85%」等は書かない。※「手数料」という単語は一切使わない（他社が引いている、という比較も禁止）
- 所属ライバー数：Pococha・TikTok合わせて200名。「200名以上」「約200名」ではなく200名
- 代表たいたん：元Pococha Sランク、ミクチャ8,000人中ミスターコン1位、Pococha歴4年
- 代表の最高月収は3桁（=100万円台）とだけ。「200万」等の具体額NG
- Pococha B帯月収＝月20〜30万（他レンジ禁止）。Pocochaは時間ダイヤで投げ銭ゼロでも時間報酬
- 「オフの日」は月4日の強制休配信日（配信できない日）
- TikTokギフト換金はフリーも事務所も同じ（事務所だと手取り増、は書かない）
- 副業ペースの実例：1日4時間・週4日で配信した男性ライバーが2〜3か月で月20〜30万円（「配信時間により変動」を必ず添える）
- 収入の目安を書くなら3か月で15〜20万／6か月で30〜40万のレンジだけ
- 視聴者のことは必ず「リスナーさん」と書く（「リスナー」の呼び捨てNG）
- LINE登録特典の非売品PDFの正式名は『ライバー新人期スタートダッシュガイド』（この表記以外で呼ばない）
【禁止表現】
- 旧特典PDF名『Pococha新人期スタートダッシュガイド』（2026-07-29に改名済み。Pocochaを頭に付けない）
- 「手数料」という語そのもの（なし/0円/ゼロ/他社は引かれる、すべて禁止）
- 「いつでも退所OK」「違約金なし」など退所・契約解除が自由だと示す表現、および契約期間への言及
- 「絶対稼げる」「確実に」「必ず月◯万」「安定して稼げる」等の断定・保証
- 月15万円未満の金額（「数万円」「お小遣い程度」等の少額表記。稼げていない側の描写でも書かない）
- 「不労所得」「権利収入」（マルチ的表現）
- 「カーブアウトパートナー」という呼称（名乗るなら TAITAN PRO）
- 「オンライン無料相談」（CTAはLINE導線に統一）
- 「オフの日」をTAITAN PROの制度として書くこと（Pococha側の制度なので主語を間違えない）
- 業界収入分布の%、DM返信率、倍率等の根拠なし数字。「多数輩出」「多くの実績」もNG
- 出典なしの割合統計。「9割が挫折する」「99%が知らない」「10人に1人も成功しない」型に加えて、
  「9割の副業ライバーは〜」のように**割合が主語を修飾する形も禁止**（Xで実際に公開まで到達した型）
- 他社事務所を下げる書き方（「多くの事務所は〜」「よくある事務所と違って〜」）
- 実在しないライバーのエピソードの捏造（FACTSにある実例だけ使う）
"""

VIRAL_RULES = """
【Threadsで読まれるための鉄則（実測に基づく。全投稿に適用）】
1. 短い。これが最大の要因。1投稿は3〜6行、多くても200字。長い投稿は読まれずリーチも落ちる。
2. 1行目で決まる。タイムラインでは最初の1〜2行しか見えない。
   「ライバー募集してます」「TAITAN PROです」のような告知始まりは絶対NG。
   実測で一番伸びた1行目はこの型：
   - 数字/年数を混ぜた断言：「4年見てきて、〜はマジで嘘だった」「4年前、0人の前で2時間喋ってた」
   - 業界の内側の本音：「ライバー事務所、入った瞬間に連絡来なくなるとこ多すぎ」
   - 偏見への反論：「“可愛くないと稼げない”は嘘」「“水商売でしょ”って言われるたびに思う」
   - 比較の意外性：「Aより、Bの方が結局〜」
3. 宣伝ブロックを本文に入れない。実測で宣伝型は本音型の1/8しか見られていない。
   「TAITAN PROでは〜サポートしています」「所属200名」「還元率100%+α」を説明として並べるのは禁止。
   事務所の話をするのは、投稿の最後の1行だけ。しかも自慢ではなく事実を一言。
4. 語り手は「4年この業界にいる人」。一人称の実感で書く。です・ます一辺倒にしない。
   広告コピーではなく、深夜にぽろっと書いた独り言のトーンにする。
5. 締めに定型の問いかけを付けない。
   「〜って人います？」「〜ですよね？」「気になる人はリプで」は使い古されていて逆効果。
   言い切って終わる、あるいは自分の感想で終わるほうが読まれる。問いかけるなら1投稿に1回だけ、自然に。
6. 絵文字は0〜1個。ハッシュタグは付けない（付けるなら1個まで）。
7. 「〜ではないでしょうか」「実は」「ぜひ」などのAIっぽい言い回しを避ける。
8. 同じ言い回しを何本もで使わない。特に「4年見てきて」「4年間この業界で」のような
   経歴の枕詞は、全体で1本だけ。他の投稿は経歴に触れずにいきなり中身から入る。
   締めも全部同じにしない（「〜だと痛感する」「〜は間違いない」の連発をやめる）。
"""

STYLE_SPECS = {
    "story": """【型：本音短文】40〜120字。3〜4行。
事務所名・LINE・リンク・募集の言葉は一切入れない。売り込みゼロ。
配信の現場で本当に見たこと、思っていることだけを書く。
読んだ人が「わかる」と思って保存・シェアしたくなるのが正解。""",
    "liver": """【型：気づき】100〜200字。4〜6行。
ライバーを始めたい人／伸び悩んでる人にとって役に立つ具体的な話を1つだけ。
情報を詰め込まない。事務所の話は最後の1行に、宣伝でなく事実として一言だけ添えるか、まったく触れない。""",
    # 2026-08-11 全面改稿。旧仕様は「仕事の実際を語る」としか書いておらず、
    # 実際に生成されたのは「代理店パートナー募集中です／在庫なし／継続報酬」型の
    # 説明文＝宣伝型で、実測17.4viewsに沈んでいた。伸びているのは全部 story の
    # 一人称の本音なので、agency も同じ書き方に寄せる。募集は最後の1行だけ、
    # しかも募集の言葉ではなく事実を一言。
    "agency": """【型：代理店】80〜160字。3〜5行。
storyと同じ「深夜の独り言」のトーンで書く。募集要項の説明文になったら失敗。
書くのは、人を紹介して育てる側から見えている景色・迷い・気づきの1つだけ。
「代理店パートナー募集中」「在庫なし・初期費用0円」のような条件の羅列は禁止。
条件に触れるなら最後の1行で、自慢ではなく事実を一言だけ。
「還元率100%+α」はライバーへの還元条件なので、代理店の報酬の話として書くのは禁止。
ライバーの月収実例も、代理店の収入と誤読されるので代理店投稿では書かない。""",
}

TOPICS = {
    "story": """- 4年間で見てきた、伸びる子と辞めていく子の違い
- 枠を閉じた後の静けさ、配信者のメンタルのリアル
- 「顔出ししたくない」「稼ぎたいと言うのが恥ずかしい」という相談の多さ
- 事務所に入ったのに放置される、という業界のよくある話（他社名は出さない）
- リスナーさんとの距離感、支えられている感覚
- 数字が伸びない時期に何を考えていたか
- 家族や職場に言えないまま配信してる人の葛藤
- 稼ぐより「居場所」で続いている人の話""",
    "liver": """- Pocochaの時間ダイヤ＝投げ銭ゼロの日でも配信時間で報酬が出る仕組み
- 毎日配信しなくていい（ノルマなし・月4日のオフの日）
- 最初の数週間でつまずくポイントと乗り越え方
- 顔・若さ・トーク力より続ける力
- 伸び悩んでいるとき、環境を変える選択肢がある（移籍視点）
- 副業ペースの実例（FACTSの男性ライバーの例だけ。変動ありを添える）
- 会社バレが不安な人へ：住民税と身バレが主な原因、一般論レベルの対策（断定せず）""",
    "agency": """- 「人の成長で食べていく」という仕事観
- ライバーを発掘して伸ばすプロセスの面白さと難しさ
- 個人で全部抱えなくていい、事務所と組む構造
- 営業や接客の経験が別の形で活きる話
- 在宅・スキマ時間でできる働き方としての実際
- 紹介して終わりにした人は続かない。所属後の最初の1ヶ月が全部という話
- 知らない人への一斉DMをやり尽くして分かったこと（届かない・アカウントが危ない）
- 発信を続けていたら「実はやってみたくて」と向こうから来た、という順番の話
- スカウトが上手い人より、伸び悩んだ子の隣にいられる人のほうが残る
- 自分の利益と、紹介した子が楽しく続けられるかが同じ方向を向いている構造
- 数字を追うなら報酬額ではなく「先月の子が今月も配信しているか」
- 配信を迷っている人が本当に気にしているのは、稼げるかではなく自分にできるか
- 人の小さな変化（コメントを返せるようになった等）を面白がれるかどうか""",
}

PROMPT = """あなたはライバー事務所TAITAN PROの代表の隣で4年間現場を見てきた人物として、Threadsに投稿する文章を書く。
広告コピーライターではない。宣伝文を書いたら失敗だと思ってほしい。

これから{n}本書く。全部ちがう切り口にすること。

{style}

ネタの引き出し（毎回ちがうものを選ぶ）：
{topics}

{viral}

{facts}

出力は必ず次のJSON配列のみ（前置き・説明・コードフェンス禁止）：
[
  {{"text":"投稿本文"}},
  ...
]
"""

# ── 機械検品 ───────────────────────────────────────────────
NG_PATTERNS = [
    (r"手数料", "禁止語「手数料」"),
    (r"いつでも退所|違約金|いつでも辞め|契約期間", "退所・契約条件への言及"),
    (r"絶対稼げ|確実に|必ず月|安定して稼|保証", "断定・保証表現"),
    (r"不労所得|権利収入", "マルチ的表現"),
    (r"月[0-9０-９]{1,2}万.{0,4}(から|〜|~|以上)?", None),  # 金額は個別判定
    (r"数万円|十数万|お小遣い程度", "少額表記"),
    (r"200名以上|約200名|200人以上", "所属数は「200名」固定"),
    (r"多数輩出|多くの実績|続々と|数百人|何百人|数千", "根拠なしの実績誇張"),
    (r"(TAITAN PRO|うち|当事務所|事務所)[^。]{0,16}月\s*4\s*日",
     "「オフの日」はPocochaの制度。事務所の制度として書かない"),
    (r"多くの事務所|一般的な事務所|他の事務所(では|は)", "他社を下げる書き方"),
    (r"カーブアウトパートナー", "使用禁止の呼称"),
    (r"オンライン無料相談", "CTAはLINE導線に統一"),
    # 2026-08-10: 特典PDFは2026-07-29に『Pococha新人期スタートダッシュガイド』から
    # 『ライバー新人期スタートダッシュガイド』へ改名済み（Pococha専用ではなくなったため）。
    # Note側は note_facts_fix_20260729.py で一括修正したが Threads は対象外で、
    # 7月の投稿11本に旧名が残ったまま公開されている。検品にも無かったので再発が止まらない。
    # 「ライバー」以外が頭に付く／頭に何も付かない形は全部落とす。
    (r"(?<!ライバー)新人期スタートダッシュ",
     "特典PDF名は『ライバー新人期スタートダッシュガイド』"),
    (r"リスナー(?!さん)", "「リスナーさん」と書く"),
]

# 「月◯万」で許可されるのは実測レンジのみ
ALLOWED_MONEY = [
    r"月20〜30万", r"月20~30万", r"月20-30万", r"20〜30万円", r"20万〜30万",
    r"15〜20万", r"30〜40万", r"3桁",
]

PROMO_TOKENS = [r"TAITAN PRO", r"還元率", r"所属.{0,3}200", r"マネージャー", r"サポート体制", r"提携"]

# 未投稿キュー内で各1回までしか使わせない決まり文句。
# 「4年見てきて」の枕詞と、Geminiが毎回使いたがる情緒フレーズ。
ONCE_PER_BATCH = [
    r"4年", r"痛感", r"胸が締め付け", r"いつも思う", r"尊い",
    r"めちゃくちゃ多い", r"本当に多い", r"山ほど", r"何度も見てきた",
]


def _violations(text, angle):
    """投稿1本の違反リストを返す。空なら合格。"""
    v = []
    n = len(text)
    limit = STORY_MAX_LEN if angle == "story" else MAX_LEN
    if n > limit:
        v.append(f"長すぎ({n}字 > {limit}字)")
    if n < 25:
        v.append(f"短すぎ({n}字)")

    for pat, label in NG_PATTERNS:
        if label is None:
            continue
        if re.search(pat, text):
            v.append(label)

    # 出典なしの割合統計（「9割が挫折」「9割の副業ライバーは〜」型）
    v += [reason for reason, _hit in ratio_violations(text)]

    # 金額表記：許可レンジ以外の「月◯万」を弾く
    for m in re.finditer(r"月\s*([0-9０-９]{1,3})\s*万", text):
        around = text[max(0, m.start() - 4): m.end() + 6]
        if any(re.search(a, around) for a in ALLOWED_MONEY):
            continue
        try:
            amount = int(m.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789")))
        except ValueError:
            continue
        if amount < 15:
            v.append(f"少額表記「月{amount}万」")
        else:
            v.append(f"未確定の金額表記「月{amount}万」")

    # 宣伝密度
    promo = sum(1 for p in PROMO_TOKENS if re.search(p, text))
    if angle == "story" and promo:
        v.append("story型に宣伝要素")
    elif promo >= 2:
        v.append(f"宣伝要素が多い({promo}種)")
    if text.count("TAITAN PRO") > 1:
        v.append("事務所名が2回以上")

    # 締めの定型問いかけ
    tail = text.strip()[-40:]
    if re.search(r"(いません|いますか|人います|ますよね|しませんか|思いません|どっち派)[？?]", tail):
        v.append("使い古された締めの問いかけ")
    if text.count("？") + text.count("?") >= 3:
        v.append("疑問符が多すぎ")

    # 代理店投稿でのライバー条件の流用
    if angle == "agency" and re.search(r"還元率|月20〜30万|20〜30万", text):
        v.append("代理店投稿にライバー向け条件を流用")
    return v


def audit_queue():
    """キュー全体を検品し、(全体の違反数, 未投稿分の違反数) を返す。

    2026-08-10: 以前は全件の違反数しか返しておらず、しかも --audit は
    `sys.exit(0 if audit_queue() == 0 else 0)` と両辺0の三項演算子だったので
    何件検出しても必ず exit 0 だった＝門番として死んでいた。
    終了コードの根拠に使えるのは未投稿分だけ。投稿済みの過去分は今から
    直せないうえ、基準を厳しくするたびに増える（現に50本ある）ので、
    全件で判定すると常時赤になって誰も見なくなる。
    """
    posts = _load_posts()
    bad = 0
    bad_unposted = 0
    for i, p in enumerate(posts):
        v = _violations(p.get("text", ""), p.get("angle", "liver"))
        if not v:
            continue
        bad += 1
        posted = bool(p.get("posted"))
        if not posted:
            bad_unposted += 1
        state = "投稿済" if posted else "未投稿"
        head = p.get("text", "").split("\n")[0][:34]
        print(f"[NG] #{i} {state} {p.get('angle')} :: {', '.join(v)}\n     {head}")
    print(f"\n合計 {len(posts)}本中 {bad}本が現在の基準に不適合"
          f"（未投稿分: {bad_unposted}本）")
    return bad, bad_unposted


# ── 生成 ───────────────────────────────────────────────────
def _extract_json_array(raw):
    raw = raw.strip()
    raw = re.sub(r"^```(json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    return m.group(0) if m else None


def _gen_one_angle(angle, n):
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY 未設定")
        return []
    prompt = PROMPT.format(
        n=n, style=STYLE_SPECS[angle], topics=TOPICS[angle],
        facts=FACTS, viral=VIRAL_RULES,
    )

    client = genai.Client(api_key=api_key)
    models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.1-flash-lite-preview"]
    for model_name in models:
        for attempt in range(3):
            try:
                resp = client.models.generate_content(model=model_name, contents=prompt)
                payload = _extract_json_array(resp.text or "")
                if not payload:
                    print(f"  [WARN] {model_name}: JSON無し（試行{attempt+1}）")
                    continue
                items = json.loads(payload)
                out, dropped = [], 0
                for it in items:
                    text = (it.get("text") or "").strip()
                    if not text:
                        continue
                    v = _violations(text, angle)
                    if v:
                        dropped += 1
                        print(f"  [DROP] {', '.join(v)} :: {text.splitlines()[0][:30]}")
                        continue
                    out.append({"angle": angle, "text": text})
                if out:
                    print(f"  [OK] {model_name}: {angle} {len(out)}本合格 / {dropped}本却下")
                    return out
            except Exception as e:
                print(f"  [WARN] {model_name} 失敗（試行{attempt+1}）: {e}")
    return []


def _grams(text, n=4):
    t = re.sub(r"\s+", "", text)
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def _too_similar(text, others, tight=False):
    """既存投稿とネタが被っていないか。同じ話を何度も投げると飽きられる。

    4-gramは言い回しレベルの重複を見る。過去全体との比較はこれだけを使う。
    2-gramは「言い方は違うが同じ話」まで拾えるが、日本語では話題が近いだけで
    0.2前後まで上がるので、過去ログ全体に当てると全部弾かれる。
    同じ生成バッチ内（tight=True）の言い換え重複を潰す用途に限定する。
    """
    checks = [(4, 0.35), (2, 0.25)] if tight else [(4, 0.35)]
    for n, threshold in checks:
        g = _grams(text, n)
        if not g:
            continue
        for o in others:
            go = _grams(o, n)
            if not go:
                continue
            if len(g & go) / min(len(g), len(go)) >= threshold:
                return True
    return False


def _tail_key(text):
    """締めの言い回し。同じ結びが並ぶと一気に量産感が出るので重複を弾く用。"""
    last = [s for s in re.split(r"[。\n]", text.strip()) if s.strip()]
    if not last:
        return ""
    return re.sub(r"[^\w]", "", last[-1])[-6:]


def _load_posts():
    if not os.path.exists(POSTS_FILE):
        return []
    with open(POSTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _mix(total):
    """型の配分。実測でstoryが圧勝しているので主力をstoryにする。

    以前は round() を型ごとに独立して掛けていたので、合計が総数に合わず
    余りを全部 agency に押し付ける形になっていた。結果 total=2,3,5,6 では
    agency が0本になり（宣伝が完全に消える）、total=6 では story 67%まで
    振れる。最大剰余法で TARGET_MIX に忠実に割り、そのうえで
    「agency は最低1本だが2割まで」「story は5割を切らない」を保証する。
    """
    n = max(1, total)
    raw = {a: n * w for a, w in TARGET_MIX.items()}
    alloc = {a: int(v) for a, v in raw.items()}
    # 端数の大きい型から1本ずつ配って合計を total に合わせる（最大剰余法）
    for a in sorted(raw, key=lambda k: -(raw[k] - alloc[k]))[: n - sum(alloc.values())]:
        alloc[a] += 1

    # 宣伝はゼロにしない（LINE導線が必要）。ただし2割を超えさせない。
    agency_cap = max(1, int(n * AGENCY_MAX_SHARE))
    if n >= AGENCY_MIN_TOTAL and alloc["agency"] == 0:
        alloc["agency"] = 1
        alloc["liver" if alloc["liver"] > alloc["story"] else "story"] -= 1
    while alloc["agency"] > agency_cap:
        alloc["agency"] -= 1
        alloc["story"] += 1

    # storyが過半を切ったらliverから寄せる（伸びる型を主力に保つ）
    while alloc["story"] * 2 < n and alloc["liver"] > 0:
        alloc["liver"] -= 1
        alloc["story"] += 1
    return alloc


def generate(total, angle_filter=None):
    posts = _load_posts()
    existing = {p.get("text", "").strip() for p in posts}
    # リンク間隔は「これまでに投入した本数」ではなくキュー全体で数える
    link_counter = sum(1 for p in posts if p.get("link"))

    plan = {angle_filter: total} if angle_filter else _mix(total)
    new_items = []
    for angle, n in plan.items():
        if n > 0:
            new_items += _gen_one_angle(angle, n)

    # ネタ被り判定は直近60本と比べる（全履歴だと重く、古い話は再利用してよい）
    recent = [p.get("text", "") for p in posts[-60:]]
    batch = [p.get("text", "") for p in posts if not p.get("posted")]
    tails = {_tail_key(t) for t in batch if _tail_key(t)}

    # 経歴の枕詞やGeminiが好む決まり文句が並ぶと一気に量産感が出る。
    # 未投稿キュー全体で各1回までに制限する。
    quota = {pat: max(0, 1 - sum(1 for t in batch if re.search(pat, t)))
             for pat in ONCE_PER_BATCH}

    added = 0
    for it in new_items:
        text = it["text"].strip()
        if text in existing:
            continue
        if _too_similar(text, recent) or _too_similar(text, batch, tight=True):
            print(f"  [DROP] 直近と内容が重複 :: {text.splitlines()[0][:30]}")
            continue
        tk = _tail_key(text)
        if tk and tk in tails:
            print(f"  [DROP] 締めの言い回しが重複({tk}) :: {text.splitlines()[0][:26]}")
            continue
        recent.append(text)
        batch.append(text)
        tails.add(tk)
        angle = it["angle"]
        over = next((p for p in ONCE_PER_BATCH
                     if re.search(p, text) and quota[p] <= 0), None)
        if over:
            print(f"  [DROP] 決まり文句が重複({over}) :: {text.splitlines()[0][:26]}")
            continue
        for p in ONCE_PER_BATCH:
            if re.search(p, text):
                quota[p] -= 1
        entry = {}
        # 本文にはリンクを付けない（リーチが半減する）。
        # storyは完全にノーCTA。それ以外はLINK_EVERY本に1本だけ、
        # 本投稿への「返信」としてCTAを出す（本投稿のリーチを落とさない）。
        if angle != "story" and (added + link_counter) % LINK_EVERY == 0:
            if angle == "agency":
                entry["reply_link"] = LINE_URL
                entry["reply_text"] = AGENCY_CTA_LINE
            else:
                entry["reply_link"] = LINE_URL
                entry["reply_text"] = LEAD_MAGNET_LINE
            link_counter += 1
        posts.append({
            "text": text,
            "angle": angle,
            "tags": [],
            "link": None,
            **entry,
            "reply_control": "everyone",
            "posted": False,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        existing.add(text)
        added += 1

    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    unposted = sum(1 for p in posts if not p.get("posted"))
    print(f"[DONE] {added}本追加。キュー総数{len(posts)}、未投稿{unposted}本。")
    return added


def main():
    ap = argparse.ArgumentParser(description="Threads コンテンツ生成")
    ap.add_argument("--gen", type=int, default=6, help="生成本数")
    ap.add_argument("--angle", choices=["story", "liver", "agency"], help="片方のみ生成")
    ap.add_argument("--audit", action="store_true", help="既存キューを検品して終了")
    args = ap.parse_args()

    if args.audit:
        _bad_all, bad_unposted = audit_queue()
        # 未投稿分に違反があるときだけ非ゼロ。投稿済みの過去分では落とさない。
        sys.exit(1 if bad_unposted else 0)
    generate(args.gen, args.angle)


if __name__ == "__main__":
    main()
