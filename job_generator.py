"""
求人プラットフォーム自動掲載 - 求人原稿ジェネレーター

Indeed / Wantedly / Engage 向けの求人原稿を自動生成。
3ターゲット（未経験者/既存ライバー/副業希望者）× 3プラットフォーム = 9パターン。

使い方:
  python3 job_generator.py --all              # 全原稿一括生成
  python3 job_generator.py --platform indeed   # Indeed用のみ
  python3 job_generator.py --dry-run --platform wantedly --target beginner
  python3 job_generator.py --status            # 掲載状況確認
  python3 job_generator.py --register indeed beginner "https://..."
"""

import argparse
import csv
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "job_posts", "templates")
OUTPUT_DIR = os.path.join(BASE_DIR, "job_posts")
TRACKER_PATH = os.path.join(BASE_DIR, "data", "job_tracker.csv")

PLATFORMS = ["indeed", "wantedly", "engage"]
TARGETS = ["beginner", "liver", "sidejob", "partner"]

LINE_URL = "https://lin.ee/xchCfdn"
LP_URLS = {
    "beginner": "https://taitan-pro-lp-targets.netlify.app/beginner/",
    "liver": "https://taitan-pro-lp-targets.netlify.app/liver/",
    "sidejob": "https://taitan-pro-lp-targets.netlify.app/sidejob/",
    "partner": "https://taitan-pro-lp-targets.netlify.app/",
}

# ============================================================
# 共通コンテンツ
# ============================================================
COMPANY_INFO = (
    "TAITAN PRO（タイタンプロ）\n"
    "所属ライバー数: 150人以上\n"
    "提携配信代理店: 11社\n"
    "未経験スタート率: 93%\n"
    "代表: 元Pococha Sランク達成者 / ミクチャ8,000人中ミスターコン1位\n"
    "対応プラットフォーム: Pococha, 17LIVE, SHOWROOM 他"
)

COMMON_BENEFITS = (
    "・初期費用・月額費用 完全0円\n"
    "・専属マネージャーによるマンツーマンサポート\n"
    "・配信データ分析と週次レポート提供\n"
    "・収益戦略のプラン設計サポート\n"
    "・いつでもLINEで相談OK\n"
    "・退所時の違約金なし（いつでも退所可能）"
)

COMMON_PROCESS = (
    "1. LINEで無料相談（気軽にどうぞ）\n"
    "2. オンライン面談（15分程度）\n"
    "3. 配信プラン決定・スタート"
)

# ============================================================
# ターゲット別コンテンツ
# ============================================================
TARGET_DATA = {
    "beginner": {
        "job_title": "【未経験OK】ライブ配信者（ライバー）募集｜在宅・スマホ1台で月10万円目指せる",
        "salary": (
            "完全歩合制（配信プラットフォームからの報酬）\n"
            "・1ヶ月目目安: 月1〜3万円\n"
            "・3ヶ月目目安: 月5〜10万円\n"
            "・6ヶ月目以降: 月10〜20万円\n"
            "※ 1日1〜2時間配信の場合。報酬保証あり。"
        ),
        "description": (
            "スマホ1台でライブ配信を行い、視聴者からの応援（投げ銭）で収益を得るお仕事です。\n\n"
            "配信ジャンルは自由。雑談、歌、ゲーム実況、料理、メイクなど、\n"
            "あなたの「好き」や「得意」を活かせます。\n\n"
            "TAITAN PROでは、完全未経験向けの研修制度があり、\n"
            "配信の始め方から収益化のコツまでマンツーマンでサポートします。\n"
            "何もわからなくて大丈夫。93%の方が未経験からスタートしています。"
        ),
        "requirements": (
            "・18歳以上\n"
            "・スマートフォンをお持ちの方\n"
            "・Wi-Fi環境がある方\n"
            "・週3日以上、1日1〜2時間の配信が可能な方"
        ),
        "welcome": (
            "・人と話すのが好きな方\n"
            "・SNSに興味がある方\n"
            "・新しいことにチャレンジしたい方\n"
            "・在宅でできる副業を探している方\n"
            "・顔出しなしでもOK（ラジオ配信・Vtuber形式も可）"
        ),
        "work_hours": (
            "完全自由シフト\n"
            "・1日1〜2時間からOK\n"
            "・配信時間帯は自由（朝・昼・夜いつでも）\n"
            "・週3日〜OK"
        ),
        "highlights": (
            "・完全在宅OK、通勤なし\n"
            "・特別なスキル不要、未経験93%\n"
            "・初期費用0円、スマホだけで始められる\n"
            "・専属マネージャーがつくので安心\n"
            "・顔出しなしでも活躍可能"
        ),
        # Wantedly用
        "what_we_do": (
            "TAITAN PROは、150人以上のライバーが所属するライバーマネジメント事務所です。\n\n"
            "Pococha、17LIVE、SHOWROOMなど11社の配信プラットフォームと提携し、\n"
            "一人ひとりに最適な配信環境を提供しています。\n\n"
            "所属ライバーの93%が完全未経験からスタート。\n"
            "「スマホ1台で、自分のペースで稼げる」新しい働き方を広げています。"
        ),
        "why_we_do": (
            "「やりたいことが見つからない」「副業したいけど何をすればいいかわからない」\n\n"
            "そんな方に、ライブ配信という選択肢を届けたい。\n\n"
            "代表自身が元ブラック企業社員からライバーに転身し、Pococha Sランクを達成した経験があります。\n"
            "だからこそ「始め方がわからない不安」も「続ける大変さ」も理解しています。\n\n"
            "一人でも多くの人が、自分の魅力を活かして収入を得られる世界を作りたい。\n"
            "それがTAITAN PROの原動力です。"
        ),
        "how_we_do": (
            "・専属マネージャー制：一人ひとりに担当がつき、配信戦略から収益化まで伴走\n"
            "・データドリブン：視聴者データ・収益推移を分析し、具体的なアクションを提案\n"
            "・研修制度：配信の基本からファンづくりまで、段階的にレクチャー\n"
            "・プラットフォーム最適化：11社の中から、あなたに合った配信先を選定\n"
            "・LINE相談：困ったらいつでもすぐ聞ける体制"
        ),
        "job_description": (
            "スマホ1台でライブ配信にチャレンジしてみませんか？\n\n"
            "配信ジャンルは完全自由。雑談、歌、ゲーム、料理、メイク...\n"
            "「これが好き」「これなら話せる」があれば、それが配信のネタになります。\n\n"
            "未経験でも全く問題なし。\n"
            "専属マネージャーが配信の始め方から収益化まで、マンツーマンでサポートします。"
        ),
        "ideal_person": (
            "・人と話すのが好き\n"
            "・自分のペースで働きたい\n"
            "・在宅でできることを探している\n"
            "・新しいことにチャレンジしたい\n"
            "・SNSに興味がある（見る専でもOK）"
        ),
        "meeting_info": (
            "15分のオンライン面談で、ライバーの仕事内容や収入の仕組みを詳しくお話しします。\n"
            "「聞いてみたい」だけでもOK。無理な勧誘は一切しません。\n"
            "合わなければ、それで全然大丈夫です。"
        ),
    },
    "liver": {
        "job_title": "【既存配信者歓迎】ライバー事務所移籍で収入150%UP｜TAITAN PRO",
        "salary": (
            "完全歩合制（現在の収入を上回るプランを提案）\n"
            "・移籍後の平均収益アップ率: 150%\n"
            "・還元率は個別相談で決定\n"
            "※ 現在の条件をお聞きした上で、上回るプランを提示します。"
        ),
        "description": (
            "「配信は続けたい。でも伸び悩んでいる。」\n"
            "「マネージャーが放置気味で相談できない。」\n"
            "「還元率に不満があるけど、言い出しにくい。」\n\n"
            "それ、事務所を変えるだけで解決するかもしれません。\n\n"
            "TAITAN PROでは、専属マネージャーが配信データを分析し、\n"
            "あなたの収益を最大化する戦略を一緒に設計します。\n"
            "移籍手続きも全面サポート。ファンの引き継ぎノウハウもあります。"
        ),
        "requirements": (
            "・現在ライブ配信を行っている方（プラットフォーム不問）\n"
            "・配信経験1ヶ月以上\n"
            "・収入アップやサポート体制の改善を希望する方"
        ),
        "welcome": (
            "・月収を上げたいと考えている方\n"
            "・フリーで活動していて限界を感じている方\n"
            "・今の事務所のサポートに不満がある方\n"
            "・データに基づいた配信戦略に興味がある方"
        ),
        "work_hours": (
            "現在の配信スケジュールを維持でOK\n"
            "・配信時間帯・頻度の変更は任意\n"
            "・マネージャーと相談の上、最適なスケジュールを設計"
        ),
        "highlights": (
            "・移籍後の平均収益アップ率150%\n"
            "・専属マネージャーによる週次データ分析\n"
            "・移籍手続き全面サポート\n"
            "・相談段階では現事務所にバレません\n"
            "・退所時の違約金なし"
        ),
        # Wantedly用
        "what_we_do": (
            "TAITAN PROは、150人以上のライバーが所属するマネジメント事務所です。\n\n"
            "11社の配信プラットフォームと提携し、ライバー一人ひとりの収益最大化を支援。\n"
            "移籍後の平均収益アップ率は150%を達成しています。\n\n"
            "代表自身が元Pococha Sランク達成者であり、\n"
            "配信者の「リアルな悩み」を理解した上でサポートしています。"
        ),
        "why_we_do": (
            "頑張って配信しているのに、サポートが足りなくて伸び悩む。\n"
            "還元率に不満があっても、一人では交渉しにくい。\n\n"
            "そんなライバーの声をたくさん聞いてきました。\n\n"
            "「サポートを変えるだけで、ここまで伸びる」\n"
            "その事実を、一人でも多くの配信者に届けたいと思っています。"
        ),
        "how_we_do": (
            "・専属マネージャー制：兼任ではなく、あなた専属の担当がつきます\n"
            "・週次データ分析：視聴者データ・収益推移を分析し、改善アクションを提案\n"
            "・収益戦略設計：あなたの目標に合わせた配信プランを共同設計\n"
            "・プラットフォーム最適化：今のアプリがベストか、他の可能性も検討\n"
            "・移籍全面サポート：手続きからファン引き継ぎまでサポート"
        ),
        "job_description": (
            "今の配信活動はそのまま。環境だけをアップグレードしませんか？\n\n"
            "あなたの配信データを分析し、「どうすれば収益が上がるか」を一緒に考えます。\n"
            "事務所の比較表を見て、気になったらまず話を聞きにきてください。\n\n"
            "相談段階では現事務所に一切バレません。秘密厳守でお話しします。"
        ),
        "ideal_person": (
            "・今の収入に満足していない\n"
            "・マネージャーにもっとサポートしてほしい\n"
            "・データに基づいた戦略で配信を伸ばしたい\n"
            "・フリーで活動していて、事務所のサポートに興味がある"
        ),
        "meeting_info": (
            "15分のオンライン面談で、今の状況をヒアリングします。\n"
            "「今より良くなるか知りたい」だけでもOK。\n"
            "秘密厳守。現事務所にバレることはありません。"
        ),
    },
    "sidejob": {
        "job_title": "【在宅副業】帰宅後2時間で月10万円｜ライブ配信のお仕事｜スキル不要",
        "salary": (
            "完全歩合制（配信プラットフォームからの報酬）\n"
            "・1ヶ月目目安: 月1〜3万円\n"
            "・3ヶ月目目安: 月5〜10万円\n"
            "・6ヶ月目目安: 月10〜20万円\n"
            "・1年目以降: 月20万円〜（トップ層は月50万超え）\n"
            "※ 1日1〜2時間配信の場合"
        ),
        "description": (
            "本業の後、帰宅してからスマホでライブ配信をするお仕事です。\n\n"
            "「副業したいけど初期投資が怖い」\n"
            "「プログラミングや動画編集のスキルがない」\n"
            "「在宅じゃないと本業と両立できない」\n\n"
            "ライバーなら全部解決します。\n"
            "初期費用0円、特別なスキル不要、完全在宅。\n"
            "TAITAN PROが本業の勤務時間に合わせた無理のない配信プランを設計します。"
        ),
        "requirements": (
            "・18歳以上\n"
            "・スマートフォンとWi-Fi環境がある方\n"
            "・週3日以上、1日1〜2時間の配信が可能な方\n"
            "・本業をお持ちの方も大歓迎"
        ),
        "welcome": (
            "・在宅でできる副業を探している方\n"
            "・初期費用をかけずに始めたい方\n"
            "・人と話すのが好きな方\n"
            "・顔出しなしで副業したい方（身バレ対策サポートあり）\n"
            "・男性も女性も歓迎"
        ),
        "work_hours": (
            "完全自由シフト\n"
            "・1日1〜2時間からOK\n"
            "・本業後の夜の時間帯、休日のスキマ時間など\n"
            "・週3日〜OK、あなたのペースに合わせます"
        ),
        "highlights": (
            "・完全在宅、通勤なし\n"
            "・初期費用・月額費用 0円\n"
            "・スキル不要、話すのが好きならOK\n"
            "・顔出しなしOK（身バレ対策サポートあり）\n"
            "・初月から収益発生\n"
            "・いつでも退所可能（違約金なし）"
        ),
        # Wantedly用
        "what_we_do": (
            "TAITAN PROは、150人以上のライバーが所属するマネジメント事務所です。\n\n"
            "「副業としてのライブ配信」に特化したサポートを提供。\n"
            "本業がある方でも無理なく続けられる配信プランの設計から、\n"
            "身バレ対策、確定申告のアドバイスまでトータルで支援しています。"
        ),
        "why_we_do": (
            "副業を始めたいけど、何をすればいいかわからない。\n"
            "せどりは在庫リスクが怖い。プログラミングは難しそう。\n\n"
            "そんな方に「ライバー」という選択肢を届けたい。\n\n"
            "スマホ1台、初期費用0円で始められて、初月から収益が出る。\n"
            "本業+αの収入源として、ライブ配信の可能性を広げています。"
        ),
        "how_we_do": (
            "・副業特化の配信プラン：本業のスケジュールに合わせた無理のない計画を設計\n"
            "・身バレ対策：顔出しなし配信のノウハウ、SNSプライバシー設定をアドバイス\n"
            "・確定申告サポート：副業収入の税務アドバイス\n"
            "・専属マネージャー：困ったらいつでもLINEで相談OK\n"
            "・段階的ステップアップ：無理せず少しずつ配信時間を伸ばす計画"
        ),
        "job_description": (
            "帰宅後の2時間をスマホで配信する。それだけで月10万円の副収入を目指せます。\n\n"
            "ライバーは他の副業と比べて、\n"
            "・初期費用0円（せどりの在庫リスクなし）\n"
            "・特別なスキル不要（プログラミング不要）\n"
            "・完全在宅（通勤なし）\n"
            "・初月から収益発生（成果が即反映）\n\n"
            "「副業の選択肢を増やしてみたい」くらいの気持ちでOKです。"
        ),
        "ideal_person": (
            "・本業以外の収入源がほしい\n"
            "・在宅でできることを探している\n"
            "・初期費用をかけたくない\n"
            "・会社にバレずに副業したい\n"
            "・自分のペースで働きたい"
        ),
        "meeting_info": (
            "15分のオンライン面談で、副業ライバーの始め方と収入の仕組みをお話しします。\n"
            "「ライバーって実際どうなの？」の一言からでOK。\n"
            "完全無料・秘密厳守・強引な勧誘なしです。"
        ),
    },
    "partner": {
        "job_title": "【在宅・副業OK】ライバー事務所の代理店パートナー募集｜紹介するだけで継続報酬",
        "salary": (
            "完全歩合制（継続型レベニューシェア）\n"
            "・ライバー5人紹介: 月3〜5万円\n"
            "・ライバー15人紹介: 月10〜20万円\n"
            "・ライバー30人以上: 月30万円〜\n"
            "※ 紹介したライバーが活動を続ける限り毎月報酬が発生"
        ),
        "description": (
            "ライバー事務所TAITAN PROの代理店パートナーとして、\n"
            "ライバー候補の紹介・スカウトを行うお仕事です。\n\n"
            "あなたがライバー候補を見つけてTAITAN PROに紹介し、\n"
            "その方がライバーとして活動を開始すると、\n"
            "ライバーの報酬に連動してあなたにも継続的に報酬が入ります。\n\n"
            "一般的な人材紹介と異なり、紹介して終わりではなく\n"
            "ストック型の継続収益が得られるのが最大の特徴です。\n\n"
            "スカウト方法のマニュアル完備、研修あり。未経験からでもスタートできます。"
        ),
        "requirements": (
            "・18歳以上\n"
            "・スマートフォンとPC（またはタブレット）をお持ちの方\n"
            "・週に数時間の活動が可能な方\n"
            "・LINEでのコミュニケーションが可能な方"
        ),
        "welcome": (
            "・SNSのフォロワーが多い方、インフルエンサー\n"
            "・営業・人材紹介の経験がある方\n"
            "・元ライバー・配信経験がある方\n"
            "・副業で安定した収入を作りたい方\n"
            "・人に何かを紹介するのが好きな方\n"
            "・キャリアアドバイザー・コーチング経験がある方"
        ),
        "work_hours": (
            "完全自由（ノルマなし）\n"
            "・1日1〜2時間からOK\n"
            "・活動時間帯は自由\n"
            "・本業の合間、休日だけでもOK\n"
            "・自分のペースで活動できます"
        ),
        "highlights": (
            "・紹介するだけで毎月継続報酬（ストック型収益）\n"
            "・初期費用・月額費用 完全0円\n"
            "・ノルマなし、自分のペースで活動OK\n"
            "・スカウトマニュアル＆研修制度あり\n"
            "・完全在宅、全国どこからでも可能\n"
            "・11の配信プラットフォームと提携で紹介先が豊富"
        ),
        # Wantedly用
        "what_we_do": (
            "TAITAN PROは、150人以上のライバーが所属するライバーマネジメント事務所です。\n\n"
            "11社の配信プラットフォームと提携し、未経験者からトップライバーまで幅広くサポート。\n"
            "現在、事業拡大に伴い代理店パートナーを募集しています。\n\n"
            "代理店パートナーとは、ライバー候補をTAITAN PROに紹介していただく方のこと。\n"
            "紹介したライバーが活動を続ける限り、あなたにも毎月報酬が入り続けます。"
        ),
        "why_we_do": (
            "ライブ配信市場は年々拡大し、ライバーになりたい人も増えています。\n"
            "でも「どの事務所がいいかわからない」「始め方がわからない」という声が圧倒的に多い。\n\n"
            "そこで、SNSや日常の人脈を通じてライバー候補を見つけ、\n"
            "TAITAN PROに繋いでくれるパートナーの存在が不可欠なのです。\n\n"
            "あなたの紹介が、誰かの新しいキャリアのきっかけになる。\n"
            "それがパートナービジネスのやりがいです。"
        ),
        "how_we_do": (
            "・スカウトマニュアル完備：SNSでの声かけ方法から契約まで全手順をカバー\n"
            "・代理店向け研修：定期的な勉強会でノウハウをアップデート\n"
            "・代表が直接サポート：困ったらいつでも相談OK\n"
            "・報酬の透明性：紹介ライバーの活動状況と報酬をダッシュボードで確認可能\n"
            "・ライバーの還元率100%維持：紹介先として自信を持って勧められる"
        ),
        "job_description": (
            "あなたのSNSや人脈を活かして、ライバー候補をTAITAN PROに紹介してください。\n\n"
            "「友達にライバーに向いてそうな人がいる」\n"
            "「SNSで副業を探してる人をよく見かける」\n"
            "「元ライバーとして配信の魅力を伝えたい」\n\n"
            "そんな方にぴったりのお仕事です。\n"
            "紹介したライバーが活動を続ける限り、あなたにも毎月報酬が発生します。\n"
            "ノルマなし、完全在宅、自分のペースで活動OK。"
        ),
        "ideal_person": (
            "・SNSのフォロワーが多い、影響力がある\n"
            "・人と繋がるのが好き\n"
            "・営業や人材紹介の経験がある\n"
            "・ライバー経験があり、配信の魅力を知っている\n"
            "・副業でストック型の収入を作りたい"
        ),
        "meeting_info": (
            "15分のオンライン面談で、代理店制度の詳細と報酬の仕組みをお話しします。\n"
            "「まだ迷っている」「話だけ聞きたい」でもOK。\n"
            "ノルマなし・違約金なし。合わなければいつでも辞められます。"
        ),
    },
}


def load_template(platform):
    path = os.path.join(TEMPLATE_DIR, f"{platform}_template.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def generate(platform, target):
    template = load_template(platform)
    data = TARGET_DATA[target]
    lp_url = LP_URLS[target]

    cta = (
        f"LINE で無料相談: {LINE_URL}\n"
        f"Web から応募: {lp_url}"
    )

    fill = {**data,
            "benefits": COMMON_BENEFITS,
            "process": COMMON_PROCESS,
            "company_info": COMPANY_INFO,
            "cta": cta}

    result = template
    for key, val in fill.items():
        result = result.replace(f"{{{key}}}", val)

    return result


def write_post(platform, target, content):
    out_dir = os.path.join(OUTPUT_DIR, platform)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{target}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def load_tracker():
    if not os.path.exists(TRACKER_PATH):
        return []
    with open(TRACKER_PATH, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_tracker(rows):
    os.makedirs(os.path.dirname(TRACKER_PATH), exist_ok=True)
    fields = ["platform", "target_type", "post_url", "posted_date", "last_updated", "status"]
    with open(TRACKER_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def show_status():
    rows = load_tracker()
    if not rows:
        print("掲載データなし。--register で URL を登録してください。")
        print(f"\n例: python3 {sys.argv[0]} --register indeed beginner \"https://...\"")
        return

    print(f"\n{'プラットフォーム':<14} {'ターゲット':<12} {'状態':<8} {'最終更新':<12} URL")
    print("-" * 90)
    for r in rows:
        print(f"{r['platform']:<14} {r['target_type']:<12} {r['status']:<8} {r['last_updated']:<12} {r.get('post_url', '-')}")
    print()


def register_url(platform, target, url):
    rows = load_tracker()
    now = datetime.now().strftime("%Y-%m-%d")
    found = False
    for r in rows:
        if r["platform"] == platform and r["target_type"] == target:
            r["post_url"] = url
            r["last_updated"] = now
            r["status"] = "掲載中"
            found = True
            break
    if not found:
        rows.append({
            "platform": platform,
            "target_type": target,
            "post_url": url,
            "posted_date": now,
            "last_updated": now,
            "status": "掲載中",
        })
    save_tracker(rows)
    print(f"登録完了: {platform} / {target}")
    print(f"  URL: {url}")


def main():
    parser = argparse.ArgumentParser(description="求人原稿ジェネレーター")
    parser.add_argument("--all", action="store_true", help="全プラットフォーム×全ターゲット一括生成")
    parser.add_argument("--platform", choices=PLATFORMS, help="対象プラットフォーム")
    parser.add_argument("--target", choices=TARGETS, help="対象ターゲット")
    parser.add_argument("--dry-run", action="store_true", help="ファイル出力せずターミナルにプレビュー")
    parser.add_argument("--status", action="store_true", help="掲載状況を表示")
    parser.add_argument("--register", nargs=3, metavar=("PLATFORM", "TARGET", "URL"),
                        help="掲載URLを登録 例: --register indeed beginner https://...")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.register:
        p, t, u = args.register
        if p not in PLATFORMS:
            print(f"エラー: プラットフォームは {PLATFORMS} から選んでください")
            sys.exit(1)
        if t not in TARGETS:
            print(f"エラー: ターゲットは {TARGETS} から選んでください")
            sys.exit(1)
        register_url(p, t, u)
        return

    if args.all:
        platforms_to_gen = PLATFORMS
        targets_to_gen = TARGETS
    elif args.platform:
        platforms_to_gen = [args.platform]
        targets_to_gen = [args.target] if args.target else TARGETS
    elif args.target:
        platforms_to_gen = PLATFORMS
        targets_to_gen = [args.target]
    else:
        parser.print_help()
        return

    count = 0
    for p in platforms_to_gen:
        for t in targets_to_gen:
            content = generate(p, t)
            if args.dry_run:
                print(f"\n{'='*60}")
                print(f"  {p.upper()} / {t}")
                print(f"{'='*60}\n")
                print(content)
            else:
                path = write_post(p, t, content)
                print(f"生成: {path}")
            count += 1

    if not args.dry_run:
        print(f"\n{count}件の求人原稿を生成しました。")
        print(f"出力先: {OUTPUT_DIR}/")
        print(f"\n次のステップ:")
        print(f"  1. 生成された原稿を確認・微調整")
        print(f"  2. 各プラットフォームにコピペで掲載")
        print(f"  3. 掲載URLを登録: python3 {sys.argv[0]} --register <platform> <target> <url>")


if __name__ == "__main__":
    main()
