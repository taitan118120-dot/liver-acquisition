"""
Instagramバズ特化カルーセル生成（2026-07-11 全面刷新）

旧 ig_content_generator（ブログ要約×1枚絵）はリーチ0だったため、
バズ狙いの縦型カルーセル（4:5・表紙フック＋1スライド1メッセージ）に全面転換。

設計方針:
  - ネタは記事要約ではなく「バズ特化テーマバンク」（あるある/ぶっちゃけ/診断/NG集/実話）
  - 数字・実績は THEME 内の facts に書かれた確定ファクトのみ使用（捏造禁止）
  - 画像は Imagen を使わず Pillow 完全ローカル生成（API予算節約・統一ブランドルック）
  - キャプションは短くフック重視。宣伝CTAは1行のみ（広告臭がリーチを殺すため）

使い方:
  python ig_viral_generator.py --generate           # 1件生成
  python ig_viral_generator.py --generate --count 3 # 3件生成
  python ig_viral_generator.py --dry-run            # Gemini/画像なしで動作確認
  python ig_viral_generator.py --render-test        # ダミーデータでスライド描画のみ確認
"""

import argparse
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

from ig_content_generator import (  # noqa: E402
    POSTS_FILE,
    IMAGES_DIR,
    _get_font,
    _wrap_japanese,
    load_posts,
    save_posts,
)

# =====================================================================
# 確定ファクト（これ以外の数字・実績をAIに書かせない）
# memory: project_taitan_pro_note_facts / project_sidejob_income_fact
# =====================================================================
APPROVED_FACTS = """- TAITAN PROは還元率100%+α（事務所の取り分なし）
- 代表はPococha歴4年。B帯で月20万円、最高月収は3桁万円
- 所属のむうくん（20歳・大学生）はPococha開始2ヶ月でB2ランク到達。配信は22:15固定で毎日
- 所属のSさんは会社員から始めて配信月100万円、代理店業と並行して150万円、その後専業に
- 副業の目安実例: 1日4時間・週4日ペースの男性ライバーが2〜3ヶ月で月20〜30万円
- Pocochaの「オフの日」は月4日の強制休配信日（おやすみチケット週2枚とは別の制度）"""

# =====================================================================
# バズ特化テーマバンク
# type: aruaru(共感) / honne(ぶっちゃけ) / shindan(診断) / ng(NG集) /
#       story(実話) / howto(即効ノウハウ) / mental(メンタル)
# use_facts: True のテーマだけ APPROVED_FACTS をプロンプトに渡す
# =====================================================================
VIRAL_THEMES = [
    {"id": "aruaru_1st_year", "type": "aruaru", "tag": "ライバーあるある",
     "title": "ライバー1年目あるある7選",
     "angle": "始めたばかりの人が「わかりすぎる」と共感してコメントしたくなる、リアルで少し笑えるあるある。配信前の緊張、初ギフトの嬉しさ、身内バレの恐怖など"},
    {"id": "ng_actions", "type": "ng", "tag": "配信の落とし穴",
     "title": "配信で絶対やってはいけないNG行動5つ",
     "angle": "初心者が無自覚にやりがちで、リスナーさんが静かに離れていく行動。ネガティブ発言の垂れ流し、コメント読み飛ばし、他ライバーとの比較愚痴など"},
    {"id": "silent_leave", "type": "honne", "tag": "配信のリアル",
     "title": "リスナーさんが静かに離れていく配信の特徴",
     "angle": "ブロックも文句もなく、ただ来なくなる。その原因は配信者側が気づいていない小さな積み重ね。ドキッとさせて保存させる"},
    {"id": "shindan_muiteru", "type": "shindan", "tag": "ライバー適性診断",
     "title": "ライバーに向いてる人・向いてない人",
     "angle": "意外な診断。「話が上手い人」ではなく「返しが丁寧な人」が向いてる等、常識をひっくり返す視点でコメント欄に「私どっち？」を発生させる"},
    {"id": "tsumaranai_haishin", "type": "howto", "tag": "配信の技術",
     "title": "「配信がつまらない人」がやってない3つのこと",
     "angle": "トーク力の問題ではなく準備と設計の問題。リアクションの大きさ、リスナーさんの名前を呼ぶ頻度、話題の引き出しのストック"},
    {"id": "pre_stream_routine", "type": "howto", "tag": "配信の技術",
     "title": "伸びてるライバーが配信前にやってる準備",
     "angle": "配信は始まる前に半分決まっている。告知、話題メモ、枠タイトル、入室時の第一声の設計など、今日から真似できる具体行動"},
    {"id": "first_stream_no_one", "type": "honne", "tag": "配信のリアル",
     "title": "初配信で人が来ないのは当たり前という話",
     "angle": "初配信0人で心が折れる人を救う。誰でも最初は0人スタート、来ないのが正常。最初の1ヶ月にやるべきことを添えて絶望→希望の構成に"},
    {"id": "jimusho_kangen", "type": "story", "tag": "事務所のリアル", "use_facts": True,
     "title": "事務所選びで手取りが変わるという話",
     "angle": "事務所によって還元率が違う事実を知らずに契約する人が多い。TAITAN PROは還元率100%+αという事実を1枚だけさらっと入れる（宣伝臭は最小限に）"},
    {"id": "off_day", "type": "howto", "tag": "Pococha攻略",
     "title": "Pococha「オフの日」の正しい使い方", "use_facts": True,
     "angle": "月4日の強制休配信日を知らない初心者向け。おやすみチケットとの違い、オフの日にやるべき裏準備（分析・企画・リスナーさんへの告知）"},
    {"id": "muukun_story", "type": "story", "tag": "所属ライバーの実話", "use_facts": True,
     "title": "20歳大学生が2ヶ月でB2まで行った話",
     "angle": "フォロワー0の普通の大学生むうくんの実話。配信時間固定・データ振り返り・イベントに飛びつかない、の3点を淡々と。誇張せずリアルに"},
    {"id": "s_san_story", "type": "story", "tag": "所属ライバーの実話", "use_facts": True,
     "title": "会社員から専業になったSさんの話",
     "angle": "会社員→配信月100万→代理店並行150万→専業。順番と決断のタイミングを時系列で。夢物語ではなく「段階を踏んだ」ことを強調"},
    {"id": "yametai_night", "type": "mental", "tag": "ライバーのメンタル",
     "title": "配信を辞めたくなった夜に読む話",
     "angle": "数字が伸びない夜、他のライバーと比べて落ち込む夜に効く考え方。共感→視点の転換→小さな行動1つ。感動系はシェアされやすい"},
    {"id": "silence_comment_zero", "type": "howto", "tag": "配信の技術",
     "title": "コメントゼロの沈黙を乗り切る技術",
     "angle": "全ライバー共通の恐怖「無言の枠」。実況法、未来のリスナーさんへ話す意識、過去コメント拾い直しなど具体テク"},
    {"id": "kaodashi_nashi", "type": "howto", "tag": "配信の始め方",
     "title": "顔出しなしでも配信できるという話",
     "angle": "顔出しが怖くて始められない層向け。ラジオ配信・バーチャル配信の選択肢と、顔出しなしで戦うときのポイント"},
    {"id": "liver_schedule", "type": "aruaru", "tag": "ライバーのリアル",
     "title": "副業ライバーのリアルな1日",
     "angle": "仕事終わり→ご飯→配信準備→配信→リスナーさんへのお礼、の生活タイムライン。「意外とできそう」と思わせる現実的な密度で"},
    {"id": "mental_care", "type": "mental", "tag": "ライバーのメンタル",
     "title": "配信で病まないための考え方",
     "angle": "数字を自分の価値と混ぜない、比較はきのうの自分とだけ、休む勇気。メンタル系は保存率が高い"},
    {"id": "3byou_ridatsu", "type": "ng", "tag": "配信の落とし穴",
     "title": "新規リスナーさんが3秒で離脱する配信",
     "angle": "画面が暗い、無言、何の枠かわからない、常連の内輪ノリ。入室した瞬間の視点で書くとドキッとする"},
    {"id": "gift_pattern", "type": "honne", "tag": "配信のリアル",
     "title": "ギフトが飛ぶ瞬間には共通点がある",
     "angle": "金額の話ではなく心理の話。目標を一緒に追いかけてる瞬間、名前を呼ばれた瞬間、ここぞの場面。リスナーさん心理の解説"},
    {"id": "zatsudan_sa", "type": "howto", "tag": "配信の技術",
     "title": "雑談配信が伸びる人と伸びない人の差",
     "angle": "同じ雑談でも「独り言」と「会話」は別物。質問の投げ方、コメントの広げ方、話題の畳み方"},
    {"id": "ayashii_scout", "type": "ng", "tag": "事務所のリアル",
     "title": "怪しいライバー勧誘の見分け方",
     # 「辞められない契約」を危険サインに置かない。自社は2年契約なので、期間の
     # 長さや辞めにくさを基準にした瞬間に自分を撃つ（[[feedback_no_free_exit_claim]]）。
     # 危険サインは「条件を説明しない」側に寄せる。
     "angle": "DMスカウトの全部が悪ではないが、危険なパターンは明確にある。還元率を濁す、契約を急かす、辞めるときの手続きを聞いても具体的に答えない。業界側からの注意喚起は信頼を生む"},
    {"id": "first_month_todo", "type": "howto", "tag": "配信の始め方",
     "title": "配信1ヶ月目にやることはこれだけ",
     "angle": "初心者は情報過多で動けなくなる。「毎日同じ時間に30分」「プロフィール整備」「挨拶を返す」レベルまで絞って安心させる"},
    {"id": "follower_sukunai", "type": "honne", "tag": "配信の始め方",
     "title": "「フォロワー少ないから無理」が間違いな理由",
     "angle": "ライブ配信はSNSフォロワー数と別ゲーム。アプリ内の新規導線から始まる世界であることを解説。始める言い訳を1つ潰す"},
    {"id": "shufu_aruaru", "type": "aruaru", "tag": "ライバーあるある",
     "title": "主婦ライバーあるある",
     "angle": "家事の合間配信、子どもの乱入、夕飯の話題が一番盛り上がる等。共感でコメントが伸びるテーマ"},
    {"id": "kizai_sumaho", "type": "howto", "tag": "配信の始め方",
     "title": "配信機材、最初はスマホだけでいい話",
     "angle": "機材を揃えてから始めようとして一生始まらない人へ。スマホ1台で十分な理由と、あとから足すならこの順番、という優先順位"},
    {"id": "event_shoumou", "type": "ng", "tag": "Pococha攻略",
     "title": "イベントで消耗する人の共通点",
     "angle": "全イベントに走って疲弊するパターン。出るべきイベントの選び方、「走らない勇気」の話"},
    {"id": "orei_iikata", "type": "howto", "tag": "配信の技術",
     "title": "リスナーさんに愛されるお礼の言い方",
     "angle": "「ありがとう」の質で差がつく。名前+具体+気持ちの3点セット、あとから枠外で伝えるお礼など"},
    {"id": "ma_kowakunai", "type": "mental", "tag": "配信の技術",
     "title": "配信の「間」が怖くなくなる考え方",
     "angle": "沈黙=失敗ではない。ラジオの間、作業配信の間、あえての間。間を埋めようと早口になる初心者への処方箋"},
    {"id": "rank_shippai", "type": "ng", "tag": "Pococha攻略",
     "title": "ランク上げで失敗する人の典型パターン",
     "angle": "無計画な長時間配信、体力の前借り、数字だけ見てリスナーさんを見ない。持続可能なランク戦略へ誘導"},
    {"id": "fukugyou_genjitsu", "type": "honne", "tag": "ライバーのリアル", "use_facts": True,
     "title": "副業ライバーの現実を正直に話す",
     "angle": "すぐ稼げる系の発信への対抗。最初の数ヶ月の現実、続けた人だけが見る景色、副業実例(facts)を1つ。誠実さで信頼を取る"},
    {"id": "tsuzukerareru_hito", "type": "mental", "tag": "ライバーのメンタル",
     "title": "配信を続けられる人の共通点",
     "angle": "才能ではなく仕組み。時間固定、ハードルを下げる、記録をつける、仲間がいる。「これなら私も」と思わせて締める"},
    {"id": "weekend_only", "type": "howto", "tag": "配信の始め方", "use_facts": True,
     "title": "土日だけ副業ライバーという選択肢",
     "angle": "平日は仕事で無理でも、土日だけ・夜だけで成立する理由。時間ダイヤ（配信時間に応じた報酬）×ノルマなしの環境選び、週2回でも「同じ曜日・同じ時間」の固定で枠は育つ。副業ペース実例(facts)を1枚だけ。誇張せず「変動あり」を添える"},
    {"id": "kaisha_bare", "type": "honne", "tag": "ライバーのリアル",
     "title": "副業ライバーの会社バレが怖い人へ",
     "angle": "バレる原因はほぼ住民税・顔バレ・自分で話す、の3つに絞られる話。普通徴収や顔出しなし配信など一般知識レベルの対策を誠実に。断定せず「詳しくは税理士や自治体へ」と添えて信頼を取る"},

    # ── 代理店パートナー向け（2026-08-11 追加）─────────────────────
    # audience="agency" のテーマはキャプションのCTAと想定読者が切り替わる。
    # 読者は「配信する側」ではなく「人を紹介して育てる側」なので、
    # 配信ノウハウのトーンをそのまま流用すると刺さらない。
    {"id": "agency_what", "type": "howto", "tag": "代理店という働き方", "audience": "agency",
     "title": "ライバー代理店パートナーって何する仕事？",
     "angle": "①興味がある人と出会う ②所属と初配信まで伴走する ③活動が続く間ずっと報酬が積み上がる、の3ステップだけで説明する。在庫を持たない・スマホで完結という事実を淡々と。育成は事務所のマネージャーと二人三脚なので一人で背負わない点を必ず入れる"},
    {"id": "agency_ng", "type": "ng", "tag": "代理店の落とし穴", "audience": "agency",
     "title": "代理店で失敗する人がやっていること",
     "angle": "知らない人への一斉DM、金額の話から入る、所属させたら放置、ひとりで全部抱える、1ヶ月で結果を求める、数だけ追う。とくに『所属後の30日を放置すると継続報酬ごと止まる』を主役に。自社もDMを大量に送って届かなかった、という失敗談として書くと信頼が出る"},
    {"id": "agency_muiteru", "type": "shindan", "tag": "代理店の適性", "audience": "agency",
     "title": "代理店に向いてる人・向いてない人",
     "angle": "営業が得意な人ではなく『人の小さな変化を面白がれる人』が向いている、という逆説。コメントを返せるようになった、配信時間を守れるようになった等の変化を喜べるか。営業未経験でも研修とツールがあるので始められる点を添える"},
    {"id": "agency_number", "type": "honne", "tag": "代理店のリアル", "audience": "agency",
     "title": "代理店が毎月見るべき数字は報酬額じゃない",
     "angle": "追うべきは『先月紹介した人が今月も配信しているか』という継続率。人数だけ増やしても継続率が低いと穴の空いたバケツになる。自分の利益と紹介した人の幸せが同じ方向を向く構造だという話に着地させる。金額は書かない"},
    {"id": "agency_player", "type": "story", "tag": "代理店のリアル", "audience": "agency",
     "use_facts": True,
     "title": "配信で伸びた人が代理店を始めると強い理由",
     "angle": "プレイヤーとして積んだ経験がそのまま『教える側』の武器になる話。Sさんの実例(facts)を1枚だけ、誇張せず時系列で。夢物語ではなく段階を踏んだことを強調し、成果には個人差があると添える"},
]

# ブランドカラー（スライドの統一ルック）
INK = (26, 32, 44)          # ほぼ黒
SUB = (90, 98, 112)         # 本文グレー
BG = (250, 247, 240)        # クリーム
PALETTES = [
    {"accent": (226, 88, 62), "accent_soft": (250, 226, 218)},   # バーミリオン
    {"accent": (43, 76, 126), "accent_soft": (219, 228, 240)},   # ネイビー
    {"accent": (59, 122, 87), "accent_soft": (218, 236, 226)},   # フォレスト
    {"accent": (142, 69, 133), "accent_soft": (238, 222, 236)},  # プラム
]

W, H = 1080, 1350  # 4:5 縦型（フィードで最大面積・カルーセル推奨比率）

# スライドに焼き込む署名。@ハンドルは書かない（2026-08-10 ユーザー確定）:
# 画像は生成後に差し替えられないので、アカウント名が変わると画像だけ古い誘導先を
# 指し続ける。事務所名なら賞味期限が切れない。ハンドルの正本は config.OFFICE_INSTAGRAM。
BRAND = config.OFFICE_NAME

# =====================================================================
# Gemini でスライド構成＋キャプションを生成
# =====================================================================

# 想定読者とキャプションCTAは audience で切り替える。
# 代理店テーマに配信者向けのCTA（新人期ガイド）を付けると、
# 受け取った人の期待と配布物がズレるため必ず対で持たせる。
READER_BLOCKS = {
    "liver": "ライブ配信をやっている・これから始めたい20〜30代。スマホで高速スクロール中に出会う。",
    "agency": (
        "自分が配信するのではなく、配信に興味がある人を紹介して育てる側（代理店パートナー）に\n"
        "興味がある20〜40代。副業を探している人・営業や人材の経験がある人・物販などを\n"
        "やってみて在庫や単発収入に疲れた人。スマホで高速スクロール中に出会う。\n"
        "※この読者は配信者ではないので、配信テクニックの話をしても刺さらない。"
    ),
}
# 1本生成するときに代理店テーマを優先して引く確率（pick_theme で使う）。
# ここを外れた場合も通常ローテーションに代理店5本が混ざるので、
# 実効の代理店比率は 0.20 + 0.80×(5/37) ≒ 30%。Threads・Xと同じ水準に揃えている。
# 代理店テーマは5本しかないので、これ以上上げると同じテーマの再利用が増える。
AGENCY_THEME_RATE = 0.20

CTA_LINES = {
    "liver": ("🎁 プロフィールのリンクから『ライバー新人期スタートダッシュガイド』"
              "（非売品PDF）を無料配布中"),
    "agency": ("🎁 プロフィールのリンクから『ライバー代理店パートナー スタートガイド』"
               "（非売品PDF）を無料配布中"),
}


def _build_prompt(theme):
    audience = theme.get("audience", "liver")
    reader_block = READER_BLOCKS[audience]
    cta_line = CTA_LINES[audience]
    facts_block = ""
    if theme.get("use_facts"):
        facts_block = f"""
【使用してよい数字・実績（この箇条書きにあるものだけ。それ以外の数字・金額・割合・実績は一切書かない）】
{APPROVED_FACTS}
"""
    else:
        facts_block = """
【数字の扱い】
- 収入・時給・金額・割合などの具体的な数字は一切書かない（確証のない数字の捏造は厳禁）。
- 「◯選」「3つ」などスライド構成上の個数表現はOK。
"""

    return f"""あなたはInstagramでライバー・ライブ配信ジャンルのバズ投稿を量産しているコンテンツ制作者です。
以下のテーマで、カルーセル投稿（画像スライド）の構成テキストとキャプションをJSONで出力してください。

【テーマ】{theme['title']}
【切り口】{theme['angle']}
{facts_block}
【ターゲット読者】
{reader_block}

【文体・トーン】
- 教科書やLPの文体は禁止。仲のいい先輩が本音で話す口調（です・ます基調だが、体言止めや「〜という話」など砕けた表現OK）
- 抽象論・きれいごと禁止。具体的な場面・行動・セリフで書く
- リスナーは必ず「リスナーさん」と書く（呼び捨て禁止）
- 「絶対稼げる」「必ず」「誰でも」「保証」などの断定・誇大表現は禁止
- 「手数料」という単語そのものが禁止（「手数料なし」「0円」だけでなく、他社が引いている、という比較も禁止）。報酬の話は「還元率100%+α」のみ可
- 「いつでも退所OK」「違約金なし」「違約金0」「いつでも辞められる」など、退所・契約解除が自由だと示す表現は禁止（契約条件は面談で説明する、とだけ書く）
- 他社や悪質事務所を語るときも、**契約期間の長さ・違約金の有無そのものを危険サインにしない**。「最低契約期間が1年以上」「2年以上の長期契約は要注意」「契約期間は短期を選べ」「違約金ありは避けろ」はすべて禁止（自社が2年契約なので、その基準で面談に来られると自分に跳ね返る）。判断軸は「契約期間・更新・中途解約の条件が契約書に明記され、面談でも同じ説明が受けられるか」の一点に揃える
- DM誘導・URL・「公式LINE」の文言は一切書かない（誘導は下記キャプションルールの指定CTA1行のみ）
- 金額を出すなら 3ヶ月15〜20万 / 6ヶ月30〜40万 / B帯 月20〜30万 のみ。
  **月15万未満の金額（「月3万」「月10万」「お小遣い程度」）は、稼げていない側の描写でも書かない**
- 所属ライバー数は「200名」固定（「200名以上」「累計◯名」は書かない）
- 扱うのは Pococha・TikTok LIVE・17LIVE の3つ。IRIAM/SHOWROOM/ふわっち/REALITY は出さない
- 「不労所得」「権利収入」「多数輩出」「多くの実績」など、裏の取れない表現は書かない

【出力JSONスキーマ】
{{
  "caption": "キャプション全文",
  "slides": [
    {{"type": "cover", "hook": "表紙の一撃コピー(改行\\nで2〜3行、合計36文字以内。読者がスワイプせずにいられない引き。疑問形・逆説・ドキッとする断言のいずれか)", "sub": "補足1行(15文字以内、省略可)"}},
    {{"type": "point", "heading": "見出し(16文字以内)", "body": "本文(120文字以内。改行\\nを2〜3回入れて読みやすく。具体的に)"}},
    ... pointスライドを5〜7枚 ...
    {{"type": "last", "heading": "締めの見出し(14文字以内)", "body": "締めの本文(90文字以内。読後に前向きになる一言＋明日からやる1アクション)", "summary": ["まとめ箇条書き(各16文字以内)", "..."] }}
  ]
}}

【キャプションのルール】
- 300〜600文字。1行目はスライド表紙と別表現のフック（20〜35文字、途中で1回句点を入れてリズムを作る）
- 中身はスライドの補足or裏話を2〜3段落。全部は書かない（画像を読ませる）
- 終盤に必ずコメント誘導の質問を1つ（「あなたはどっち？」「経験ある人コメントで教えて」等）
- 「📌 保存して配信前に見返してね」の1行を入れる
- 宣伝は「{cta_line}」の1行だけ。無料相談・事務所の勧誘文は書かない
- 最後にハッシュタグを5個ちょうど、1行で。#ライバー #ライブ配信 は固定、残り3個はテーマに合わせる（#Pococha #ポコチャ #TikTokLIVE #配信初心者 #ポコチャライバー #雑談配信 #ライバー事務所 などから）。#副業 系は最大1個
- 絵文字はキャプション全体で3個まで

JSONのみを出力してください。"""


def generate_slide_content(theme, dry_run=False):
    """Geminiでスライド構成JSONを生成"""
    if dry_run:
        return _dummy_content(theme)

    from google import genai

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    prompt = _build_prompt(theme)

    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash"]
    for model_name in models_to_try:
        for attempt in range(4):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(
                        temperature=0.9,
                        response_mime_type="application/json",
                    ),
                )
                data = json.loads(response.text)
                _validate_content(data)
                return data
            except Exception as e:
                wait = 10 * (attempt + 1)
                print(f"  [RETRY] {model_name} 生成失敗({e}) {wait}秒待機 ({attempt + 1}/4)")
                time.sleep(wait)
        print(f"  [WARNING] {model_name} で失敗、次のモデルへ")

    raise RuntimeError("全モデルでスライド生成に失敗")


def _dummy_content(theme):
    return {
        "caption": f"{theme['title']}のテストキャプション。\n\n📌 保存して配信前に見返してね\n\n🎁 プロフィールのリンクから『ライバー新人期スタートダッシュガイド』（非売品PDF）を無料配布中\n\n#ライバー #ライブ配信 #Pococha #配信初心者 #ポコチャ",
        "slides": [
            {"type": "cover", "hook": "初配信、\n誰も来なくて\n当たり前です。", "sub": "むしろ正常"},
            {"type": "point", "heading": "0人スタートが普通", "body": "有名人以外は全員0人から。\n来ないのは失敗じゃなくて、\nただのスタートラインです。"},
            {"type": "point", "heading": "最初の壁は「継続」", "body": "多くの人が1週間でやめます。\nつまり続けるだけで\n上位に入れるということ。"},
            {"type": "last", "heading": "今日の一歩", "body": "まずは同じ時間に30分。\nそれだけで十分です。",
             "summary": ["0人は正常", "続けるだけで上位", "時間を固定する"]},
        ],
    }


_BANNED_PATTERNS = [
    r"手数料(なし|無し|0円|ゼロ)", r"絶対稼げる", r"必ず稼げる", r"誰でも稼げる",
    # DMへの誘導のみ禁止（「DMで勧誘してくる事務所」等の言及はOK）
    r"DM(して|ください|で(ご)?(相談|連絡|お問い合わせ|質問)|待って)",
    r"公式LINE", r"lin\.ee", r"https?://",
    r"無料相談",
]


def _validate_content(data):
    """生成JSONの構造と禁止表現をチェック"""
    slides = data.get("slides", [])
    if not slides or slides[0].get("type") != "cover":
        raise ValueError("coverスライドがない")
    if len(slides) < 5 or len(slides) > 10:
        raise ValueError(f"スライド枚数が不正: {len(slides)}")
    if slides[-1].get("type") != "last":
        raise ValueError("lastスライドがない")

    caption = data.get("caption", "")
    if len(caption) < 250:
        raise ValueError(f"キャプションが短すぎる: {len(caption)}文字")

    all_text = data.get("caption", "") + json.dumps(slides, ensure_ascii=False)
    for pat in _BANNED_PATTERNS:
        if re.search(pat, all_text):
            raise ValueError(f"禁止表現を検出: {pat}")

    # 判断軸の矛盾（契約期間の長さ・違約金の有無で他社を裁く形）は、上の
    # _BANNED_PATTERNS のような語の一覧では捕まらない。正本の facts_patterns に
    # 判定を任せる（ここに書き写すと必ずどちらかが古くなる）。
    # 2026-08-12: プロンプト側だけ直しても、モデルは「怪しい事務所＝長期契約」を
    # 一般知識として持っているので生成時に再発しうる。機械側にも同じ線を引く。
    from facts_patterns import contract_axis_violations
    axis = contract_axis_violations(all_text)
    if axis:
        raise ValueError(f"自社と矛盾する判断軸を検出: {axis[0][1]}")

    # リスナー呼び捨てチェック（「リスナーさん」以外の「リスナー」単独使用を修正）
    return True


def _fix_listener_san(text):
    """「リスナー」単独表記を「リスナーさん」に補正"""
    return re.sub(r"リスナー(?!さん)", "リスナーさん", text)


# =====================================================================
# Pillow スライドレンダラー（統一ブランドルック・完全ローカル）
# =====================================================================

def _new_canvas(palette):
    from PIL import Image
    return Image.new("RGB", (W, H), BG)


def _wrap_no_orphan(text, width):
    """折り返しで1〜2文字の孤立行を作らない（前の行に結合、幅は後段の縮小処理が吸収）"""
    lines = _wrap_japanese(text, width)
    if len(lines) >= 2 and len(lines[-1]) <= 2:
        lines[-2] += lines[-1]
        lines.pop()
    return lines


def _draw_footer(draw, page, total, palette):
    """ページ番号とブランド名（全スライド共通フッター）"""
    f = _get_font(700, 30)
    page_text = f"{page:02d} / {total:02d}"
    draw.text((70, H - 88), page_text, font=f, fill=SUB)
    bbox = draw.textbbox((0, 0), BRAND, font=f)
    draw.text((W - 70 - (bbox[2] - bbox[0]), H - 88), BRAND, font=f, fill=palette["accent"])


def _draw_corner_deco(img, palette):
    """右上に大きなアクセント円（画面外に半分はみ出し）で単調さ回避"""
    from PIL import Image, ImageDraw
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    r = 210
    d.ellipse([W - r, -r, W + r, r], fill=palette["accent_soft"] + (255,))
    d.ellipse([W - 68 - 14, 80 - 14, W - 68 + 14, 80 + 14], fill=palette["accent"] + (255,))
    img.paste(layer, (0, 0), layer)


def render_cover(slide, tag, palette, path, total):
    from PIL import Image, ImageDraw

    img = _new_canvas(palette)
    _draw_corner_deco(img, palette)
    draw = ImageDraw.Draw(img)

    # 上部タグピル
    tag_font = _get_font(800, 34)
    tb = draw.textbbox((0, 0), tag, font=tag_font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    px, py = 28, 16
    draw.rounded_rectangle([70, 110, 70 + tw + px * 2, 110 + th + py * 2 + 6],
                           radius=(th + py * 2 + 6) // 2, fill=palette["accent"])
    draw.text((70 + px, 110 + py - 2), tag, font=tag_font, fill=(255, 255, 255))

    # フック本文（手動改行を尊重、なければ自動折返し）
    hook = slide.get("hook", "").strip()
    lines = []
    for seg in hook.split("\n"):
        seg = seg.strip()
        if seg:
            lines.extend(_wrap_no_orphan(seg, 11))
    lines = lines[:4]

    size = 128 if len(lines) <= 3 else 108
    font = _get_font(900, size)
    # 幅超過なら縮小
    for _ in range(8):
        max_w = max(draw.textbbox((0, 0), ln, font=font)[2] for ln in lines)
        if max_w <= W - 180:
            break
        size = int(size * 0.92)
        font = _get_font(900, size)

    line_h = int(size * 1.28)
    total_h = line_h * len(lines)
    y = (H - total_h) // 2 - 40

    for i, ln in enumerate(lines):
        bbox = draw.textbbox((0, 0), ln, font=font)
        lw = bbox[2] - bbox[0]
        x = 90
        # 最終行にマーカー
        if i == len(lines) - 1:
            draw.rectangle([x - 8, y + int(size * 0.62), x + lw + 8, y + int(size * 1.08)],
                           fill=palette["accent_soft"])
        draw.text((x, y), ln, font=font, fill=INK)
        y += line_h

    # サブコピー
    sub = slide.get("sub", "").strip()
    if sub:
        sub_font = _get_font(700, 42)
        draw.text((92, y + 24), f"── {sub}", font=sub_font, fill=SUB)

    # 下部スワイプ誘導
    sw_font = _get_font(800, 38)
    sw_text = "スワイプして読む →"
    sb = draw.textbbox((0, 0), sw_text, font=sw_font)
    sw_w, sw_h = sb[2] - sb[0], sb[3] - sb[1]
    bx0, by0 = 70, H - 200
    draw.rounded_rectangle([bx0, by0, bx0 + sw_w + 64, by0 + sw_h + 40],
                           radius=(sw_h + 40) // 2, fill=INK)
    draw.text((bx0 + 32, by0 + 18), sw_text, font=sw_font, fill=(255, 255, 255))

    _draw_footer(draw, 1, total, palette)
    img.save(path, "PNG", optimize=True)


def render_point(slide, index, palette, path, total):
    from PIL import Image, ImageDraw

    img = _new_canvas(palette)
    draw = ImageDraw.Draw(img)

    # 大きな番号
    num_font = _get_font(900, 150)
    num_text = f"{index:02d}"
    draw.text((70, 100), num_text, font=num_font, fill=palette["accent_soft"])
    # 番号の上に細アクセント線
    draw.rectangle([76, 300, 76 + 120, 308], fill=palette["accent"])

    # 見出し
    heading = slide.get("heading", "").strip()
    h_lines = _wrap_no_orphan(heading, 10)[:2]
    h_size = 84 if len(h_lines) == 1 else 72
    h_font = _get_font(900, h_size)
    for _ in range(6):
        max_w = max(draw.textbbox((0, 0), ln, font=h_font)[2] for ln in h_lines)
        if max_w <= W - 160:
            break
        h_size = int(h_size * 0.92)
        h_font = _get_font(900, h_size)
    y = 370
    for ln in h_lines:
        draw.text((80, y), ln, font=h_font, fill=INK)
        y += int(h_size * 1.3)

    # 本文
    body = slide.get("body", "").strip()
    b_font = _get_font(500, 46)
    b_lines = []
    for seg in body.split("\n"):
        seg = seg.strip()
        if seg:
            b_lines.extend(_wrap_japanese(seg, 18))
    y += 50
    for ln in b_lines[:9]:
        draw.text((84, y), ln, font=b_font, fill=SUB)
        y += int(46 * 1.75)

    _draw_footer(draw, index + 1, total, palette)
    img.save(path, "PNG", optimize=True)


def render_last(slide, palette, path, total):
    from PIL import Image, ImageDraw

    img = _new_canvas(palette)
    _draw_corner_deco(img, palette)
    draw = ImageDraw.Draw(img)

    # 見出し
    heading = slide.get("heading", "まとめ").strip()
    h_font = _get_font(900, 88)
    draw.text((80, 150), heading, font=h_font, fill=INK)
    draw.rectangle([84, 280, 84 + 140, 290], fill=palette["accent"])

    # まとめ箇条書き
    y = 360
    summary = slide.get("summary") or []
    s_font = _get_font(700, 48)
    for item in summary[:5]:
        draw.ellipse([88, y + 18, 112, y + 42], fill=palette["accent"])
        draw.text((136, y), str(item).strip(), font=s_font, fill=INK)
        y += 92

    # 締め本文
    body = slide.get("body", "").strip()
    if body:
        b_font = _get_font(500, 42)
        y += 30
        for seg in body.split("\n"):
            for ln in _wrap_japanese(seg.strip(), 20):
                draw.text((88, y), ln, font=b_font, fill=SUB)
                y += int(42 * 1.7)

    # 保存・フォローボックス
    box_y0 = H - 400
    draw.rounded_rectangle([70, box_y0, W - 70, box_y0 + 250],
                           radius=36, fill=palette["accent_soft"])
    c_font1 = _get_font(900, 52)
    t1 = "＼ 保存して見返してね ／"
    b1 = draw.textbbox((0, 0), t1, font=c_font1)
    draw.text(((W - (b1[2] - b1[0])) // 2, box_y0 + 44), t1, font=c_font1, fill=INK)
    c_font2 = _get_font(700, 40)
    # NotoSansJPに絵文字グリフがないため画像内は絵文字なし
    t2 = "プロフのリンクで新人ガイド無料配布中"
    b2 = draw.textbbox((0, 0), t2, font=c_font2)
    draw.text(((W - (b2[2] - b2[0])) // 2, box_y0 + 140), t2, font=c_font2,
              fill=palette["accent"])

    _draw_footer(draw, total, total, palette)
    img.save(path, "PNG", optimize=True)


def render_carousel(content, theme, base_index):
    """全スライドを描画して相対パスのリストを返す"""
    os.makedirs(IMAGES_DIR, exist_ok=True)
    palette = PALETTES[base_index % len(PALETTES)]
    slides = content["slides"]
    total = len(slides)

    paths = []
    point_idx = 0
    for i, slide in enumerate(slides):
        path = os.path.join(IMAGES_DIR, f"viral_{base_index:03d}_{i + 1:02d}.png")
        stype = slide.get("type")
        if stype == "cover":
            render_cover(slide, theme["tag"], palette, path, total)
        elif stype == "last":
            render_last(slide, palette, path, total)
        else:
            point_idx += 1
            render_point(slide, point_idx, palette, path, total)
        paths.append(path)
        print(f"  スライド描画: {os.path.basename(path)} [{stype}]")

    project_root = os.path.dirname(os.path.dirname(IMAGES_DIR))
    return [os.path.relpath(p, project_root) for p in paths]


# =====================================================================
# キャプション後処理
# =====================================================================

# キャプションの特典CTA（プロフのリンク＝LINE友だち追加へ誘導）
CAPTION_CTA = "🎁 プロフィールのリンクから『ライバー新人期スタートダッシュガイド』（非売品PDF）を無料配布中"


def polish_caption(caption):
    caption = _fix_listener_san(caption.strip())
    # URL除去（保険）
    caption = re.sub(r"https?://\S+", "", caption)
    # 旧CTA（アカウント宣伝行）が残っていたら特典CTAに置換
    caption = re.sub(r"^.*配信ノウハウを週3で発信中.*$", CAPTION_CTA, caption, flags=re.MULTILINE)
    # ハッシュタグ個数を5個に強制
    tags = re.findall(r"#[\wぁ-んァ-ヶー一-龥0-9_]+", caption)
    seen, uniq = set(), []
    sidejob = False
    for t in tags:
        if t in seen:
            continue
        if t in ("#副業", "#副業女子", "#スマホ副業", "#副業始めたい"):
            if sidejob:
                continue
            sidejob = True
        seen.add(t)
        uniq.append(t)
    body = re.sub(r"#[\wぁ-んァ-ヶー一-龥0-9_]+", "", caption).rstrip()
    body = re.sub(r"\n{3,}", "\n\n", body).rstrip()
    # 特典CTAが抜けていたら末尾に足す（保険）
    if "スタートダッシュガイド" not in body:
        body += "\n\n" + CAPTION_CTA
    pool = ["#ライバー", "#ライブ配信", "#Pococha", "#ポコチャ", "#配信初心者",
            "#TikTokLIVE", "#ポコチャライバー", "#雑談配信"]
    for t in pool:
        if len(uniq) >= 5:
            break
        if t not in seen:
            uniq.append(t)
            seen.add(t)
    return body + "\n\n" + " ".join(uniq[:5])


# =====================================================================
# メイン生成フロー
# =====================================================================

def pick_theme(existing_posts):
    """未使用テーマを選ぶ。全部使い切ったら使用回数が最少のものを再利用"""
    used = {}
    for p in existing_posts:
        sf = p.get("source_file", "")
        if sf.startswith("viral_"):
            tid = sf[len("viral_"):]
            used[tid] = used.get(tid, 0) + 1

    unused = [t for t in VIRAL_THEMES if t["id"] not in used]

    # 2026-08-11: 代理店パートナー募集を厚くする方針。
    # 素の均等ローテーションだと代理店テーマは全37本中5本＝13%しか出ない。
    # AGENCY_THEME_RATE の確率で代理店テーマを優先して引く。
    # （在庫が尽きていたら通常のローテーションに落ちる）
    if random.random() < AGENCY_THEME_RATE:
        agency_unused = [t for t in unused if t.get("audience") == "agency"]
        if agency_unused:
            return random.choice(agency_unused)
        agency_all = [t for t in VIRAL_THEMES if t.get("audience") == "agency"]
        if agency_all:
            return min(agency_all, key=lambda t: used.get(t["id"], 0))

    if unused:
        return random.choice(unused)
    # 全消化 → 最少使用のテーマを再利用（Geminiのtemperatureで別内容になる）
    return min(VIRAL_THEMES, key=lambda t: used.get(t["id"], 0))


def generate_viral_posts(count=1, dry_run=False):
    """バズカルーセル投稿を生成して ig_posts.json に追加"""
    posts = load_posts()
    new_posts = []

    for _ in range(count):
        theme = pick_theme(posts + new_posts)
        print(f"[THEME] {theme['title']} ({theme['type']})")

        try:
            content = generate_slide_content(theme, dry_run=dry_run)
        except Exception as e:
            print(f"  [ERROR] スライド生成失敗、スキップ: {e}")
            continue

        # スライドテキストにもリスナーさん補正
        for s in content["slides"]:
            for k in ("hook", "sub", "heading", "body"):
                if s.get(k):
                    s[k] = _fix_listener_san(s[k])
            if s.get("summary"):
                s["summary"] = [_fix_listener_san(x) for x in s["summary"]]

        caption = polish_caption(content.get("caption", ""))
        print(f"  キャプション: {caption[:70]}...")

        base_index = len([p for p in posts + new_posts
                          if p.get("source_type") == "viral"])
        if dry_run:
            image_paths = []
            print("  [DRY RUN] スライド描画スキップ")
        else:
            image_paths = render_carousel(content, theme, base_index)

        post = {
            "id": f"ig_viral_{base_index:03d}",
            "source_file": f"viral_{theme['id']}",
            "source_type": "viral",
            "title": theme["title"],
            "caption": caption,
            "image_path": image_paths[0] if image_paths else None,
            "image_paths": image_paths,
            "slides": content["slides"],
            "posted": False,
        }
        new_posts.append(post)
        print()

    if new_posts and not dry_run:
        save_posts(posts + new_posts)
        print(f"{len(new_posts)}件のカルーセル投稿を生成 → {POSTS_FILE}")

    return new_posts


def render_test():
    """ダミーデータで描画だけ確認（Gemini不要）"""
    theme = VIRAL_THEMES[6]  # first_stream_no_one
    content = _dummy_content(theme)
    paths = render_carousel(content, theme, 999)
    print("\n描画テスト完了:")
    for p in paths:
        print(f"  {p}")


def main():
    parser = argparse.ArgumentParser(description="Instagramバズカルーセル生成")
    parser.add_argument("--generate", action="store_true", help="投稿を生成")
    parser.add_argument("--count", type=int, default=1, help="生成数")
    parser.add_argument("--dry-run", action="store_true", help="API/描画なしで確認")
    parser.add_argument("--render-test", action="store_true", help="ダミーデータで描画テスト")
    args = parser.parse_args()

    if args.render_test:
        render_test()
    elif args.generate or args.dry_run:
        generate_viral_posts(count=args.count, dry_run=args.dry_run)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
