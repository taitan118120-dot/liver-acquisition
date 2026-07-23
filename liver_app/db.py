"""SQLite DB管理: leadsテーブルとsettingsテーブル"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.environ.get(
    "LIVER_APP_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.sqlite"),
)

_DEFAULT_BEGINNER_TEMPLATE = (
    "✨スマホ1台で月20万円以上のライバー育成中✨\n"
    "TAITAN PROからのご連絡です！\n代表は元S帯ライバーのたいたん(@taitanblog)で、ミスターコン日本一・CM出演・駅広告・有名雑誌掲載など実績ある事務所です。\n\n💪所属ライバー実績💪\n月収100万円超のライバー多数在籍✨\n最高月収600万円以上(Pococha S6帯)✨\n総勢150名所属\n\n"
    "投稿拝見してご連絡しました🙏\n"
    "未経験〜経験者まで幅広くサポートしているライバー事務所です。\n\n"
    "🎁所属メリット🎁\n"
    "・専属マネージャーが1on1で配信戦略コンサル\n"
    "・未経験でも稼げる「初動加速プログラム」完備\n"
    "・大型イベント時のリスナー集客サポート\n"
    "・案件・コラボ配信の優先紹介\n\n"
    "📱スマホ1台でOK／全国どこでも所属可能\n"
    "📝所属費用は一切かかりません\n\n"
    "🎙ラジオライバー可能\n\n"
    "「ちょっと気になるかも…」と思っていただけたら、\n"
    "『興味あり』とだけご返信ください♪\n"
    "詳細を即お送りします！\n\n"
    "→ https://taitan-pro-lp.netlify.app/#apply"
)

_DEFAULT_BEGINNER_TEMPLATE_OSHIKATSU = (
    "✨推し活してる方へ🎁ライバーデビューのご案内✨\n"
    "TAITAN PROからのご連絡です！\n代表は元S帯ライバーのたいたん(@taitanblog)で、ミスターコン日本一・CM出演・駅広告・有名雑誌掲載など実績ある事務所です。\n\n💪所属ライバー実績💪\n月収100万円超のライバー多数在籍✨\n最高月収600万円以上(Pococha S6帯)✨\n総勢150名所属\n\n"
    "投稿拝見してご連絡しました🙏\n"
    "推しを応援してきた方ほど、実はライバー側になると伸びやすいです。\n"
    "リスナー目線が分かるから、初配信から濃いファンが付きます🌸\n\n"
    "🎁選べる3つの配信スタイル🎁\n"
    "🎙ラジオライバー：声だけでOK・顔出し不要\n"
    "🧚‍♀️Vライバー：AIで作ったアバターで配信・本人特定なし\n"
    "📱通常配信：もちろん顔出しもOK\n\n"
    "🌷本業・学業と両立OK（副業）🌷\n"
    "・週2〜3日、1日2時間程度から\n"
    "・スマホ1台で完結\n"
    "・全国どこでも所属可能\n\n"
    "📝所属費用は一切かかりません\n\n"
    "「話聞いてみたい」と思っていただけたら、\n"
    "『興味あり』とだけご返信ください♪\n"
    "詳細を即お送りします！\n\n"
    "→ https://taitan-pro-lp.netlify.app/#apply"
)

_DEFAULT_AGENCY_TEMPLATE_SHOP = (
    "✨経営者さま向け：ライバー事業のご紹介✨\n"
    "TAITAN PROからのご連絡です！\n代表は元S帯ライバーのたいたん(@taitanblog)で、ミスターコン日本一・CM出演・駅広告・有名雑誌掲載など実績ある事務所です。\n\n💪所属ライバー実績💪\n月収100万円超のライバー多数在籍✨\n最高月収600万円以上(Pococha S6帯)✨\n総勢150名所属／提携代理店11社あり\n\n"
    "ご自身でも経営されてるとのこと、頑張られてて尊敬です🙏\n"
    "ネイルサロン/美容室/カフェ等を運営される方の追加収益として\n"
    "ライバースカウト事業をご紹介してます。\n\n"
    "🎯既存スタッフ・お客様をライバー化→月20万以上の副収入\n"
    "🎯店舗の集客にもなる（フォロワー流入・SNSバズ）\n"
    "🎯弊社が育成・配信ノウハウ全部代行（手間ゼロ）\n"
    "🎯既存事業との相性◎・初期費用なし\n\n"
    "🎙ラジオライバー可能\n\n"
    "「興味あり」とご返信いただければ詳細お送りします💌\n\n"
    "→ https://taitan-pro-lp.netlify.app/#apply"
)

_DEFAULT_AGENCY_TEMPLATE_SNS = (
    "✨SNS運用されてる方へ：ライバースカウト事業ご紹介✨\n"
    "TAITAN PROからのご連絡です！\n代表は元S帯ライバーのたいたん(@taitanblog)で、ミスターコン日本一・CM出演・駅広告・有名雑誌掲載など実績ある事務所です。\n\n💪所属ライバー実績💪\n月収100万円超のライバー多数在籍✨\n最高月収600万円以上(Pococha S6帯)✨\n総勢150名所属／提携代理店11社あり\n\n"
    "SNS運用/コンテンツ販売されてるのを拝見しました🙏\n"
    "SNSスキル活かして、ライバースカウト事業始めませんか？\n\n"
    "🎯1人スカウト→月20万以上の継続収益（既存事業と相性◎）\n"
    "🎯完全在宅・スマホ完結\n"
    "🎯弊社が育成サポート全部代行\n"
    "🎯SNSの集客導線そのまま使える\n\n"
    "🎙ラジオライバー可能\n\n"
    "「興味あり」とご返信いただければ詳細お送りします💌\n\n"
    "→ https://taitan-pro-lp.netlify.app/#apply"
)

_DEFAULT_AGENCY_TEMPLATE_CAST = (
    "✨夜のお仕事の方へ：ライバー事業のご案内✨\n"
    "TAITAN PROからのご連絡です！\n代表は元S帯ライバーのたいたん(@taitanblog)で、ミスターコン日本一・CM出演・駅広告・有名雑誌掲載など実績ある事務所です。\n\n💪所属ライバー実績💪\n月収100万円超のライバー多数在籍✨\n最高月収600万円以上(Pococha S6帯)✨\n総勢150名所属／提携代理店11社あり\n\n"
    "お仕事拝見してご連絡しました🙏\n"
    "夜のお仕事と並行で／or 卒業後のキャリアとして\n"
    "ライバースカウト事業のご案内です。\n\n"
    "🎯昼間の隙間時間で月20万以上の継続収益\n"
    "🎯水商売の人脈ですぐスカウトできる\n"
    "🎯ご自身がライバーになるのもアリ（時給上乗せ最大5000円/h）\n"
    "🎯完全在宅・スマホ完結\n\n"
    "🎙ラジオライバー可能\n\n"
    "「興味あり」とご返信いただければ詳細お送りします💌\n\n"
    "→ https://taitan-pro-lp.netlify.app/#apply"
)

_DEFAULT_AGENCY_TEMPLATE_LIVER_FAN = (
    "✨ライバー興味ある方へ：別ルートのご紹介✨\n"
    "TAITAN PROからのご連絡です！\n代表は元S帯ライバーのたいたん(@taitanblog)で、ミスターコン日本一・CM出演・駅広告・有名雑誌掲載など実績ある事務所です。\n\n💪所属ライバー実績💪\n月収100万円超のライバー多数在籍✨\n最高月収600万円以上(Pococha S6帯)✨\n総勢150名所属／提携代理店11社あり\n\n"
    "ライバー興味あるとのこと、ご連絡しました🙏\n"
    "実は「ライバーをスカウトする側」も参入しやすい副業で\n\n"
    "🎯顔出しせず月20万以上の継続収益\n"
    "🎯既にライバーやってる方の中継役として\n"
    "🎯弊社サポートで未経験でも初月から成果\n"
    "🎯ご自身がライバーになるルートもサポート可能\n\n"
    "🎙ラジオライバー可能\n\n"
    "「興味あり」とご返信いただければ詳細お送りします💌\n\n"
    "→ https://taitan-pro-lp.netlify.app/#apply"
)

_DEFAULT_EXISTING_LIVER_TEMPLATE = (
    "✨他事務所からの移籍/個人勢の所属サポート✨\n"
    "TAITAN PROからのご連絡です！\n代表は元S帯ライバーのたいたん(@taitanblog)で、ミスターコン日本一・CM出演・駅広告・有名雑誌掲載など実績ある事務所です。\n\n💪所属ライバー実績💪\n月収100万円超のライバー多数在籍✨\n最高月収600万円以上(Pococha S6帯)✨\n総勢150名所属\n\n"
    "投稿を拝見してご連絡しました🙏\n"
    "未経験〜経験者まで幅広くサポートしているライバー事務所です。\n\n"
    "🎁所属メリット🎁\n"
    "・イベント時のリスナーブースト・集客支援\n"
    "・専属マネージャーによる配信戦略コンサル\n"
    "・案件・コラボ配信の優先紹介\n"
    "・他事務所の縛りや待遇でお悩みの方の相談もOK\n\n"
    "📱現プラットフォーム継続OK\n"
    "📝所属費用は一切かかりません\n\n"
    "🎙ラジオライバー可能\n\n"
    "「ちょっと話聞いてみたい」と思っていただけたら、\n"
    "『興味あり』とだけご返信ください♪\n"
    "具体的な所属条件をすぐにお送りします！\n\n"
    "→ https://taitan-pro-lp.netlify.app/#apply"
)

_DEFAULT_EXISTING_LIVER_TEMPLATE_2 = (
    "✨ポコチャ以外のライバーさん向け 特別キャンペーンのご案内✨\n"
    "ライバー事務所TAITAN PROからのご連絡です！\n代表は元S帯ライバーのたいたん(@taitanblog)で、ミスターコン日本一・CM出演・駅広告・有名雑誌掲載など実績ある事務所です。\n\n💪所属ライバー実績💪\n月収100万円超のライバー多数在籍✨\n最高月収600万円以上(Pococha S6帯)✨\n総勢150名所属\n\n"
    "投稿を拝見してご連絡しました🙏\n"
    "現在ご活動中のライバーさん向けに、収益アップをサポートする\n"
    "【特別マネジメントプラン】をご案内しています。\n\n"
    "🎁プランの内容🎁\n"
    "✨ 達成条件に応じて時給上乗せ報酬（最大5,000円/h）\n"
    "✨ 過去には90日で月収100万円超を達成したライバーも在籍\n"
    "✨ いま活動中のアプリと並行配信OK\n"
    "✨ 案件・コラボ配信の優先紹介\n\n"
    "📱現プラットフォーム継続OK／全国どこでも所属可能\n"
    "📝所属費用は一切かかりません\n\n"
    "🎙ラジオライバー可能\n\n"
    "少しでも「気になる」「話だけ聞いてみたい」でも大歓迎です！\n"
    "『興味あり』とだけご返信ください🙏\n"
    "詳細をすぐにお送りします。\n\n"
    "→ https://taitan-pro-lp.netlify.app/#apply"
)

# ハッシュタグプリセット（target_type別）
_DEFAULT_HASHTAGS_BEGINNER = [
    # 既存
    "UNIQLOコーデ", "プチプラコーデ", "ママコーデ",
    # ライフスタイル
    "お洒落さんと繋がりたい", "カフェ好きさんと繋がりたい",
    "カフェ巡り", "カフェ活", "映えスイーツ",
    # 地名+カフェ
    "渋谷カフェ", "新宿カフェ", "原宿カフェ", "表参道カフェ",
    "下北沢カフェ", "横浜カフェ", "みなとみらいカフェ",
    "福岡カフェ", "大阪カフェ", "京都カフェ", "名古屋カフェ",
    # コーデ系
    "低身長コーデ", "古着女子", "古着男子", "淡色女子",
    # アパレルブランド名（ルミネエスト新宿クラス・要編集）
    "nikoand", "LOWRYSFARM", "GLOBALWORK", "ROPEPICNIC", "LEPSIM",
    "earthmusicandecology", "INGNI", "WEGO", "Lilybrown", "dazzlin",
    # 映えスポット
    "渋谷スカイ", "赤レンガ倉庫",
    # 🆕 推し活系 (2026-05-06) — リスナー目線あり・ラジオ/Vライバー訴求で beginner として獲得
    "推し活", "推し活女子", "推し活アカ", "推し活仲間募集",
    "推し活初心者", "推しのいる生活", "推し事",
    "ジャニヲタ", "ジャニーズ担当", "アイドル好き",
    "Vtuber推し", "二次元推し", "担当", "単担", "箱推し",
    "ガチ恋", "現場参戦",
    # 🆕 推し活拡張 (2026-07-01) — 推し/アニメ/オタ活軸で母数拡大。
    #   応援・視聴文化圏＝ライバー予備軍（リスナー→配信者転換）を beginner で狙う
    # 推し活アイデンティティ / 発見タグ
    "推し", "推し様", "推しのいる暮らし", "推しのいる生活最高",
    "推し活垢", "推し活記録", "推し活はじめました",
    "推し活グッズ", "推し活デコ", "推ししか勝たん",
    # オタ活アイデンティティ
    "オタ活", "オタク女子", "オタクさんと繋がりたい", "ヲタ活",
    # アニメ / 2次元 / 声優（親和性高い視聴層）
    "アニメ好き", "アニメ好きな人と繋がりたい", "アニメ好きさんと繋がりたい",
    "アニメ垢", "声優好き", "声優オタク",
    "2.5次元", "2.5次元舞台", "2.5次元俳優",
    # アイドル / K-POP
    "アイドルオタク", "ドルオタ", "地下アイドル好き",
    "K-POP好き", "韓国アイドル好き",
    # Vtuber / 配信文化（リスナー予備軍として最有力）
    "Vtuber好き", "にじさんじ", "ホロライブ", "ゲーム実況好き",
    # 現場 / 参戦文化
    "ライブ参戦", "参戦服", "現場担", "遠征オタク",
]

_DEFAULT_HASHTAGS_EXISTING_LIVER = [
    "17LIVE", "イチナナライブ", "IRIAM", "イリアム",
    "ふわっち", "BIGOLIVE", "ミクチャ", "ツイキャス",
    "SHOWROOM", "ライブ配信", "配信者", "ライバーさんと繋がりたい",
]

_DEFAULT_HASHTAGS_AGENCY = [
    # 🏪 実店舗経営者（ネイル/美容室/まつ毛系は除外対象なのでタグからも外す）
    "コンカフェオーナー",
    "エステサロン経営", "カフェ経営", "治療院経営",
    # 💻 SNSビジネス層
    "SNS運用代行", "コンテンツ販売初心者", "無在庫転売",
    "物販", "ネット副業", "インスタ運用代行",
    # 🌃 水商売・キャスト系
    "ラウンジ嬢", "キャバクラ嬢", "銀座ホステス", "六本木ラウンジ",
    # 🎤 ライバー憧れ層（「推し活」は beginner に移動 2026-05-06）
    "ライバーになりたい", "配信者好きと繋がりたい",
    # 🆕 代理店希望/副業希望（直接シグナル）
    "代理店希望", "代理店募集", "スカウト副業",
    "ライバースカウト", "業務委託募集", "業務委託希望",
    "副業希望", "副業始めたい", "副業探してます",
    "在宅副業", "週末副業", "ママ副業",
    "完全在宅ワーク", "業務委託ママ", "スマホ副業",
    # 🆕 副業バリエーション拡張 (2026-05-01)
    "副業ママ", "副業初心者",
    "すきま時間で副業", "子育てしながら副業",
    "主婦副業", "主婦の副業",
    "副業女子", "副業仲間", "副業始めました", "副業スタート",
    "ダブルワーク", "Wワーク",
    # 🆕 在宅ワーク変種 (2026-05-01)
    "在宅ワーク主婦", "在宅ワークママ",
    "家でできる副業", "おうちで稼ぐ", "おうちワーク",
    # 🆕 案件/スカウト追加 (2026-05-01)
    "スカウト募集", "代理店探してます",
    "業務委託案件", "案件募集", "案件探してます",
    # 🆕 ライバー憧れ層 強化 (2026-05-01) — STRONG扱い
    "配信者になりたい", "ライブ配信始めたい",
    "ライバー目指す", "ライバーデビュー", "ライバー始めたい",
    "配信デビュー", "配信始めたい", "ライブ配信興味あり",
]

# （旧プリセット保持: 既存代理店検出に使う場合のため）
_LEGACY_HASHTAGS_AGENCY = [
    "ライバー事務所", "ライバープロダクション", "ライバー代理店",
    "ライバースカウト", "配信代理", "ライバーマネジメント",
    "ライバー育成", "ライバー募集",
]

DEFAULT_SETTINGS = {
    # 旧key（互換のため残す。実体は templates / hashtags_by_type を見る）
    "hashtags": _DEFAULT_HASHTAGS_BEGINNER,
    "template": _DEFAULT_BEGINNER_TEMPLATE,
    # 新key（B案: バリエーション複数化。リスト構造で各タイプ複数テンプレ持てる）
    "templates": {
        "beginner": [_DEFAULT_BEGINNER_TEMPLATE, _DEFAULT_BEGINNER_TEMPLATE_OSHIKATSU],
        "agency": [
            _DEFAULT_AGENCY_TEMPLATE_SHOP,
            _DEFAULT_AGENCY_TEMPLATE_SNS,
            _DEFAULT_AGENCY_TEMPLATE_CAST,
            _DEFAULT_AGENCY_TEMPLATE_LIVER_FAN,
        ],
        "existing_liver": [_DEFAULT_EXISTING_LIVER_TEMPLATE, _DEFAULT_EXISTING_LIVER_TEMPLATE_2],
    },
    "hashtags_by_type": {
        "beginner": _DEFAULT_HASHTAGS_BEGINNER,
        "agency": _DEFAULT_HASHTAGS_AGENCY,
        "existing_liver": _DEFAULT_HASHTAGS_EXISTING_LIVER,
    },
    "max_followers": 10000,
    "max_followers_existing": 1000,  # 既存ライバー: 1000以下（小規模ライバー狙い 2026-04-25）
    "max_followers_agency": 30000,  # agency: 副業希望者狙いなので30k超は成熟済として除外
    "min_followers": 1,
    "min_followers_agency": 50,  # agency: 50未満はほぼ死んだアカ・noise (2026-04-30)
    "max_ratio": 5.0,
    "daily_limit": 20,
    "age_min": 18,
    "age_max": 40,
    "ig_cookie_raw": "",
}


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                name TEXT,
                bio TEXT,
                followers INTEGER,
                following INTEGER,
                source_tag TEXT,
                target_type TEXT DEFAULT 'beginner',
                status TEXT DEFAULT '未接触',
                qualified INTEGER DEFAULT 0,
                qualified_reasons TEXT DEFAULT '[]',
                auto_qualified INTEGER DEFAULT 1,
                found_date TEXT,
                dm_sent_date TEXT,
                notes TEXT DEFAULT '',
                skip_reason TEXT DEFAULT '',
                sent_by TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
            CREATE INDEX IF NOT EXISTS idx_leads_qualified ON leads(qualified);

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS research_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT,
                finished_at TEXT,
                candidates_fetched INTEGER DEFAULT 0,
                qualified_added INTEGER DEFAULT 0,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'worker',
                auth_token TEXT UNIQUE NOT NULL,
                daily_limit INTEGER DEFAULT 20,
                rate_per_lead INTEGER DEFAULT 60,
                active INTEGER DEFAULT 1,
                created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_users_token ON users(auth_token);
            """
        )
        # 旧スキーマ → カラム追加（idempotent）
        try:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(leads)").fetchall()]
            if "skip_reason" not in cols:
                conn.execute("ALTER TABLE leads ADD COLUMN skip_reason TEXT DEFAULT ''")
            if "sent_by" not in cols:
                conn.execute("ALTER TABLE leads ADD COLUMN sent_by TEXT")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_sent_by ON leads(sent_by)")
            if "post_count" not in cols:
                conn.execute("ALTER TABLE leads ADD COLUMN post_count INTEGER")
        except Exception:
            pass
        # デフォルト設定投入（未設定キーのみ）
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (k, json.dumps(v, ensure_ascii=False)),
            )
        # 旧スキーマからの移行（dict-of-str → dict-of-list に正規化のみ）
        try:
            tpl_row = conn.execute("SELECT value FROM settings WHERE key='templates'").fetchone()
            if tpl_row:
                templates = json.loads(tpl_row["value"])
                if isinstance(templates, dict):
                    changed = False
                    for k in list(templates.keys()):
                        v = templates[k]
                        if isinstance(v, str):
                            templates[k] = [v] if v else []
                            changed = True
                        elif not isinstance(v, list):
                            templates[k] = []
                            changed = True
                    # existing_liver に2つ目のデフォルトが無ければ追加（初回マイグレーションのみ）
                    el = templates.get("existing_liver") or []
                    if isinstance(el, list) and _DEFAULT_EXISTING_LIVER_TEMPLATE_2 not in el and len(el) < 2:
                        templates["existing_liver"] = el + [_DEFAULT_EXISTING_LIVER_TEMPLATE_2]
                        changed = True
                    # beginner に推し活向けテンプレが無ければ追加 (2026-05-06)
                    bg = templates.get("beginner") or []
                    if isinstance(bg, list) and _DEFAULT_BEGINNER_TEMPLATE_OSHIKATSU not in bg:
                        templates["beginner"] = bg + [_DEFAULT_BEGINNER_TEMPLATE_OSHIKATSU]
                        changed = True
                    if changed:
                        conn.execute(
                            "UPDATE settings SET value=? WHERE key='templates'",
                            (json.dumps(templates, ensure_ascii=False),),
                        )
            # hashtags_by_type も同様: 旧 hashtags のカスタマイズを beginner に移行
            hbt_row = conn.execute("SELECT value FROM settings WHERE key='hashtags_by_type'").fetchone()
            old_hash_row = conn.execute("SELECT value FROM settings WHERE key='hashtags'").fetchone()
            if hbt_row and old_hash_row:
                hbt = json.loads(hbt_row["value"])
                old_hash = json.loads(old_hash_row["value"])
                if isinstance(hbt, dict) and isinstance(old_hash, list):
                    # 旧 hashtags が新規デフォルトと違うなら、ユーザカスタムなのでマージ（重複除外して beginner に追加）
                    if hbt.get("beginner") == _DEFAULT_HASHTAGS_BEGINNER and old_hash != _DEFAULT_HASHTAGS_BEGINNER:
                        merged = list(dict.fromkeys(old_hash + _DEFAULT_HASHTAGS_BEGINNER))
                        hbt["beginner"] = merged
                        conn.execute(
                            "UPDATE settings SET value=? WHERE key='hashtags_by_type'",
                            (json.dumps(hbt, ensure_ascii=False),),
                        )
            # 代理店希望系タグの追加マイグレーション (2026-04-30)
            # 既存customizationを尊重しつつ、新タグだけ末尾に追加
            if hbt_row:
                hbt2 = json.loads(hbt_row["value"])
                if isinstance(hbt2, dict):
                    NEW_AGENCY_TAGS = [
                        # 2026-04-30 追加分
                        "代理店希望", "代理店募集", "スカウト副業",
                        "ライバースカウト", "業務委託募集", "業務委託希望",
                        "副業希望", "副業始めたい", "副業探してます",
                        "在宅副業", "週末副業", "ママ副業",
                        "完全在宅ワーク", "業務委託ママ", "スマホ副業",
                        # 2026-05-01 追加分
                        "副業ママ", "副業初心者",
                        "すきま時間で副業", "子育てしながら副業",
                        "主婦副業", "主婦の副業",
                        "副業女子", "副業仲間", "副業始めました", "副業スタート",
                        "ダブルワーク", "Wワーク",
                        "在宅ワーク主婦", "在宅ワークママ",
                        "家でできる副業", "おうちで稼ぐ", "おうちワーク",
                        "スカウト募集", "代理店探してます",
                        "業務委託案件", "案件募集", "案件探してます",
                        "配信者になりたい", "ライブ配信始めたい",
                        "ライバー目指す", "ライバーデビュー", "ライバー始めたい",
                        "配信デビュー", "配信始めたい", "ライブ配信興味あり",
                    ]
                    cur_agency = hbt2.get("agency") or []
                    if isinstance(cur_agency, list):
                        missing = [t for t in NEW_AGENCY_TAGS if t not in cur_agency]
                        if missing:
                            hbt2["agency"] = cur_agency + missing
                            conn.execute(
                                "UPDATE settings SET value=? WHERE key='hashtags_by_type'",
                                (json.dumps(hbt2, ensure_ascii=False),),
                            )
            # 推し活系タグを agency → beginner に移行 (2026-05-06)
            if hbt_row:
                hbt3 = json.loads(conn.execute("SELECT value FROM settings WHERE key='hashtags_by_type'").fetchone()["value"])
                if isinstance(hbt3, dict):
                    OSHIKATSU_TAGS = [
                        "推し活", "推し活女子", "推し活アカ", "推し活仲間募集",
                        "推し活初心者", "推しのいる生活", "推し事",
                        "ジャニヲタ", "ジャニーズ担当", "アイドル好き",
                        "Vtuber推し", "二次元推し", "担当", "単担", "箱推し",
                        "ガチ恋", "現場参戦",
                    ]
                    cur_agency_o = hbt3.get("agency") or []
                    cur_beginner_o = hbt3.get("beginner") or []
                    moved = False
                    if isinstance(cur_agency_o, list):
                        new_agency = [t for t in cur_agency_o if t not in OSHIKATSU_TAGS]
                        if new_agency != cur_agency_o:
                            hbt3["agency"] = new_agency
                            moved = True
                    if isinstance(cur_beginner_o, list):
                        missing_o = [t for t in OSHIKATSU_TAGS if t not in cur_beginner_o]
                        if missing_o:
                            hbt3["beginner"] = cur_beginner_o + missing_o
                            moved = True
                    if moved:
                        conn.execute(
                            "UPDATE settings SET value=? WHERE key='hashtags_by_type'",
                            (json.dumps(hbt3, ensure_ascii=False),),
                        )
            # 推し活タグ拡張 (2026-07-01) — 推し/アニメ/オタ活軸で beginner 母数拡大
            # 既存customizationを尊重し、未登録の新タグだけ beginner 末尾に追加
            if hbt_row:
                hbt4 = json.loads(conn.execute("SELECT value FROM settings WHERE key='hashtags_by_type'").fetchone()["value"])
                if isinstance(hbt4, dict):
                    NEW_OSHIKATSU_TAGS_2026_07 = [
                        "推し", "推し様", "推しのいる暮らし", "推しのいる生活最高",
                        "推し活垢", "推し活記録", "推し活はじめました",
                        "推し活グッズ", "推し活デコ", "推ししか勝たん",
                        "オタ活", "オタク女子", "オタクさんと繋がりたい", "ヲタ活",
                        "アニメ好き", "アニメ好きな人と繋がりたい", "アニメ好きさんと繋がりたい",
                        "アニメ垢", "声優好き", "声優オタク",
                        "2.5次元", "2.5次元舞台", "2.5次元俳優",
                        "アイドルオタク", "ドルオタ", "地下アイドル好き",
                        "K-POP好き", "韓国アイドル好き",
                        "Vtuber好き", "にじさんじ", "ホロライブ", "ゲーム実況好き",
                        "ライブ参戦", "参戦服", "現場担", "遠征オタク",
                    ]
                    cur_beginner_4 = hbt4.get("beginner") or []
                    if isinstance(cur_beginner_4, list):
                        missing_4 = [t for t in NEW_OSHIKATSU_TAGS_2026_07 if t not in cur_beginner_4]
                        if missing_4:
                            hbt4["beginner"] = cur_beginner_4 + missing_4
                            conn.execute(
                                "UPDATE settings SET value=? WHERE key='hashtags_by_type'",
                                (json.dumps(hbt4, ensure_ascii=False),),
                            )
        except Exception:
            pass  # マイグレーションは best-effort
        # 代表紹介行追加マイグレーション (2026-04-29)
        # 旧: "TAITAN PROのたいたんと申します！" → 新: 事務所からの連絡 + 代表プロフィール
        try:
            OLD_INTRO_B = "ライバー事務所TAITAN PROのたいたんと申します！"
            OLD_INTRO_A = "TAITAN PROのたいたんと申します！"
            NEW_INTRO_B = (
                "ライバー事務所TAITAN PROからのご連絡です！\n"
                "代表は元S帯ライバーのたいたん(@taitanblog)で、ミスターコン日本一・CM出演・駅広告・有名雑誌掲載など実績ある事務所です。"
            )
            NEW_INTRO_A = (
                "TAITAN PROからのご連絡です！\n"
                "代表は元S帯ライバーのたいたん(@taitanblog)で、ミスターコン日本一・CM出演・駅広告・有名雑誌掲載など実績ある事務所です。"
            )

            # 「配信されている」表現は嘘になる場合があるため「投稿」に置換
            OLD_HAIKEN = "配信されているのを拝見してご連絡しました"
            NEW_HAIKEN = "投稿を拝見してご連絡しました"

            def _patch(text: str) -> tuple[str, bool]:
                if not isinstance(text, str):
                    return text, False
                changed = False
                if OLD_INTRO_B in text:
                    text = text.replace(OLD_INTRO_B, NEW_INTRO_B)
                    changed = True
                elif OLD_INTRO_A in text:
                    text = text.replace(OLD_INTRO_A, NEW_INTRO_A)
                    changed = True
                if OLD_HAIKEN in text:
                    text = text.replace(OLD_HAIKEN, NEW_HAIKEN)
                    changed = True
                return text, changed

            tpl_row = conn.execute("SELECT value FROM settings WHERE key='templates'").fetchone()
            if tpl_row:
                templates = json.loads(tpl_row["value"])
                changed = False
                if isinstance(templates, dict):
                    for k, v in templates.items():
                        if isinstance(v, list):
                            for i, tpl in enumerate(v):
                                new_tpl, did = _patch(tpl)
                                if did:
                                    v[i] = new_tpl
                                    changed = True
                if changed:
                    conn.execute(
                        "UPDATE settings SET value=? WHERE key='templates'",
                        (json.dumps(templates, ensure_ascii=False),),
                    )

            old_tpl_row = conn.execute("SELECT value FROM settings WHERE key='template'").fetchone()
            if old_tpl_row:
                old_tpl = json.loads(old_tpl_row["value"])
                new_tpl, did = _patch(old_tpl)
                if did:
                    conn.execute(
                        "UPDATE settings SET value=? WHERE key='template'",
                        (json.dumps(new_tpl, ensure_ascii=False),),
                    )
        except Exception:
            pass
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_setting(key, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])


def set_setting(key, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        conn.commit()


def all_settings():
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: json.loads(r["value"]) for r in rows}


def upsert_lead(lead):
    """leadは dict: id, username, name, bio, followers, following, source_tag,
    target_type, qualified, qualified_reasons(list), notes

    既存レコードは status='未接触' の場合のみ qualify/数値を更新する。
    （送信済・スキップ済は状態保持）"""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, status FROM leads WHERE username = ?", (lead["username"],)
        ).fetchone()
        if existing:
            if existing["status"] == "未接触":
                conn.execute(
                    """UPDATE leads SET name=?, bio=?, followers=?, following=?, post_count=?,
                                        target_type=?, qualified=?, qualified_reasons=?
                       WHERE username=?""",
                    (
                        lead.get("name", ""),
                        lead.get("bio", ""),
                        lead.get("followers"),
                        lead.get("following"),
                        lead.get("post_count"),
                        lead.get("target_type", "beginner"),
                        1 if lead.get("qualified") else 0,
                        json.dumps(lead.get("qualified_reasons", []), ensure_ascii=False),
                        lead["username"],
                    ),
                )
                conn.commit()
            return existing["id"], False
        conn.execute(
            """
            INSERT INTO leads (id, username, name, bio, followers, following, post_count,
                               source_tag, target_type, status, qualified,
                               qualified_reasons, auto_qualified, found_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '未接触', ?, ?, 1, ?, ?)
            """,
            (
                lead["id"],
                lead["username"],
                lead.get("name", ""),
                lead.get("bio", ""),
                lead.get("followers"),
                lead.get("following"),
                lead.get("post_count"),
                lead.get("source_tag", ""),
                lead.get("target_type", "beginner"),
                1 if lead.get("qualified") else 0,
                json.dumps(lead.get("qualified_reasons", []), ensure_ascii=False),
                datetime.now().strftime("%Y-%m-%d"),
                lead.get("notes", ""),
            ),
        )
        conn.commit()
    return lead["id"], True


def update_lead_target_type(lead_id, target_type):
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET target_type=? WHERE id=?", (target_type, lead_id)
        )
        conn.commit()


def get_queue():
    """精査通過・未送信のリード一覧"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM leads
            WHERE status = '未接触' AND qualified = 1 AND (dm_sent_date IS NULL OR dm_sent_date = '')
            ORDER BY found_date DESC, id ASC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_lead(lead_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return dict(row) if row else None


def mark_sent(lead_id, sent_by=None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET status = 'DM送信済', dm_sent_date = ?, sent_by = ? WHERE id = ?",
            (datetime.now().strftime("%Y-%m-%d"), sent_by, lead_id),
        )
        conn.commit()


# ---------- users ----------
def _gen_token() -> str:
    """LINE等のURL自動リンク化で末尾が切れるのを防ぐため、末尾に -/_ を含めない。"""
    import secrets
    while True:
        t = secrets.token_urlsafe(18)
        if t[-1] not in "-_":
            return t


def create_user(name, role="worker", daily_limit=20, rate_per_lead=60):
    import secrets
    token = _gen_token()
    user_id = f"u_{secrets.token_hex(4)}"
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO users(id, name, role, auth_token, daily_limit, rate_per_lead, active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
            (user_id, name, role, token, daily_limit, rate_per_lead,
             datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    return get_user(user_id)


def get_user(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_token(token):
    if not token:
        return None
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE auth_token = ?", (token,)).fetchone()
    return dict(row) if row else None


def list_users(include_inactive=True):
    with get_conn() as conn:
        if include_inactive:
            rows = conn.execute("SELECT * FROM users ORDER BY role DESC, created_at ASC").fetchall()
        else:
            rows = conn.execute("SELECT * FROM users WHERE active = 1 ORDER BY role DESC, created_at ASC").fetchall()
    return [dict(r) for r in rows]


def update_user(user_id, **fields):
    allowed = {"name", "daily_limit", "rate_per_lead", "active"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return get_user(user_id)
    cols = ", ".join(f"{k}=?" for k in sets)
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET {cols} WHERE id=?", (*sets.values(), user_id))
        conn.commit()
    return get_user(user_id)


def rotate_user_token(user_id):
    token = _gen_token()
    with get_conn() as conn:
        conn.execute("UPDATE users SET auth_token=? WHERE id=?", (token, user_id))
        conn.commit()
    return get_user(user_id)


def has_any_users():
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    return row["c"] > 0


def ensure_owner_seeded(token):
    """APP_PASSWORD を auth_token に持つ owner ユーザがいなければ作成。冪等。"""
    if not token:
        return None
    u = get_user_by_token(token)
    if u:
        return u
    user_id = "u_owner"
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if existing:
            conn.execute("UPDATE users SET auth_token=?, active=1 WHERE id=?", (token, user_id))
        else:
            conn.execute(
                """INSERT INTO users(id, name, role, auth_token, daily_limit, rate_per_lead, active, created_at)
                   VALUES (?, ?, 'owner', ?, 9999, 0, 1, ?)""",
                (user_id, "オーナー", token, datetime.now().isoformat(timespec="seconds")),
            )
        conn.commit()
    return get_user(user_id)


def stats_for_user(user_id):
    """指定ユーザの送信統計（本日 / 今月 / 累計）"""
    today = datetime.now().strftime("%Y-%m-%d")
    month_prefix = datetime.now().strftime("%Y-%m")
    with get_conn() as conn:
        today_c = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE sent_by=? AND dm_sent_date=?",
            (user_id, today),
        ).fetchone()["c"]
        month_c = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE sent_by=? AND dm_sent_date LIKE ?",
            (user_id, month_prefix + "%"),
        ).fetchone()["c"]
        total_c = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE sent_by=? AND status='DM送信済'",
            (user_id,),
        ).fetchone()["c"]
    return {"sent_today": today_c, "sent_month": month_c, "sent_total": total_c}


def stats_by_worker():
    """全 worker の送信統計（owner ダッシュボード用）"""
    today = datetime.now().strftime("%Y-%m-%d")
    month_prefix = datetime.now().strftime("%Y-%m")
    out = []
    for u in list_users():
        s = stats_for_user(u["id"])
        s.update({
            "id": u["id"],
            "name": u["name"],
            "role": u["role"],
            "active": u["active"],
            "daily_limit": u["daily_limit"],
            "rate_per_lead": u["rate_per_lead"],
            "payout_month": s["sent_month"] * (u["rate_per_lead"] or 0),
            "payout_total": s["sent_total"] * (u["rate_per_lead"] or 0),
            "auth_token": u["auth_token"],
            "created_at": u.get("created_at"),
        })
        out.append(s)
    return {"users": out, "today": today, "month": month_prefix}


def _extract_tokens(text: str) -> list[str]:
    """名前/usernameから 学習用トークン抽出。
    - 区切り分割後 ASCII は小文字化・長さ>=4 のみ
    - CJKは3-gram のみ（2-gramは誤爆が多いため廃止）
    """
    import re as _re
    if not text:
        return []
    tokens = set()
    # 区切り分割
    parts = _re.split(r"[\s_./|｜・\-、,，:：;；()（）【】\[\]<>\!?！？★☆♪♥♡🌟✨💎👑🌸🌷🌹🌺🌻🌼🍀🍒🍑🍎🍇🐶🐱🐭🐰🐻🦄🦋🐧🐤🐣🐔🦅🦉🦆🐦]+", text)
    for p in parts:
        if not p:
            continue
        if _re.search(r"[A-Za-z0-9]", p) and len(p) >= 4:
            tokens.add(p.lower())
    # CJK 3-gram のみ（2-gramは短すぎて誤爆多発）
    cjk = "".join(_re.findall(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]", text))
    for i in range(len(cjk) - 2):
        tokens.add(cjk[i:i+3])
    return list(tokens)


_SKIP_TOKEN_STOPWORDS = {
    # 一般的すぎる単語（ブロック誤爆防止）
    "official", "japan", "tokyo", "love", "channel", "studio", "team",
    "ちゃん", "さん", "くん", "です", "ます", "して", "から", "まで",
    "私の", "あなた", "毎日", "今日", "明日", "昨日",
    "love", "life", "work", "shop", "good", "best", "happy",
    # ターゲットキーワード（誤ってブロックリスト化されるのを防ぐ）
    "副業", "起業", "スカウト", "ライバー", "ライバー事務所", "配信", "在宅", "ワーク",
    "代理店", "業務委託", "案件", "フォロワー", "インスタ", "sns",
    # 推し活/オタク系ターゲット (2026-07-01) — 集客対象タグ本体。ブロック学習禁止。
    #   ※これが原因で「推し活」タブが0だった（'推し活' が block token 化していた）
    "推し活", "推し事", "オタ活", "ヲタ活", "推し活記", "し活記",
    "アニメ", "声優", "アイドル", "vtuber", "ドルオタ", "オタク",
    "ライブ", "参戦", "遠征", "現場", "担当", "箱推し", "ガチ恋",
    "にじさんじ", "ホロライブ", "kpop", "live",
}


_BLOCKLIST_EXCLUDED_REASONS = {
    "同業者",
    "送信不可",  # DM技術的失敗 = ターゲット自体は悪くない
    "その他",    # 理由が曖昧 = 学習データとして不適切
}


def get_skip_blocklist(min_count: int = 3) -> dict:
    """skip_reason別に学習されたブロック語を返す。
    {reason: {token: count}}"""
    from collections import Counter
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT username, name, source_tag, skip_reason FROM leads WHERE status='見送り' AND skip_reason IS NOT NULL AND skip_reason != ''"
        ).fetchall()
    by_reason: dict[str, Counter] = {}
    for r in rows:
        reason = r["skip_reason"]
        if reason in _BLOCKLIST_EXCLUDED_REASONS:
            continue
        text = " ".join([(r["username"] or ""), (r["name"] or "")])
        tokens = _extract_tokens(text)
        c = by_reason.setdefault(reason, Counter())
        for t in tokens:
            if t in _SKIP_TOKEN_STOPWORDS:
                continue
            c[t] += 1
    out = {}
    for reason, cnt in by_reason.items():
        out[reason] = {t: n for t, n in cnt.items() if n >= min_count}
    return out


def get_skip_stats() -> dict:
    """スキップ統計（理由別件数, タグ別件数, 学習ブロック語）"""
    from collections import Counter
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT skip_reason, source_tag FROM leads WHERE status='見送り' AND skip_reason IS NOT NULL AND skip_reason != ''"
        ).fetchall()
    reason_count = Counter()
    reason_tags: dict[str, Counter] = {}
    for r in rows:
        reason = r["skip_reason"]
        reason_count[reason] += 1
        if r["source_tag"]:
            reason_tags.setdefault(reason, Counter())[r["source_tag"]] += 1
    return {
        "total": sum(reason_count.values()),
        "by_reason": dict(reason_count),
        "top_tags_by_reason": {r: dict(c.most_common(5)) for r, c in reason_tags.items()},
        "blocklist": get_skip_blocklist(),
    }


def mark_skip(lead_id, reason):
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE leads SET status = '見送り',
                             skip_reason = ?,
                             notes = COALESCE(notes, '') || ' | skip:' || ?
            WHERE id = ?
            """,
            (reason, reason, lead_id),
        )
        conn.commit()


def stats(user=None):
    """user が worker のときは self の本日送信数 / 自分の daily_limit を返す。
    owner / None のときは全体集計 + 全体 daily_limit。"""
    today = datetime.now().strftime("%Y-%m-%d")
    is_worker = bool(user) and user.get("role") == "worker"
    if is_worker:
        daily_limit = user.get("daily_limit") or 20
    else:
        daily_limit = get_setting("daily_limit", 20)
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
        queue = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE status='未接触' AND qualified=1"
        ).fetchone()["c"]
        if is_worker:
            sent_today = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE dm_sent_date=? AND sent_by=?",
                (today, user["id"]),
            ).fetchone()["c"]
            sent_total = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE status='DM送信済' AND sent_by=?",
                (user["id"],),
            ).fetchone()["c"]
        else:
            sent_today = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE dm_sent_date = ?", (today,)
            ).fetchone()["c"]
            sent_total = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE status='DM送信済'"
            ).fetchone()["c"]
        disqualified = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE qualified=0"
        ).fetchone()["c"]
    return {
        "total": total,
        "queue": queue,
        "sent_today": sent_today,
        "sent_total": sent_total,
        "disqualified": disqualified,
        "daily_limit": daily_limit,
        "remaining": max(0, daily_limit - sent_today),
    }


def recent_sent(limit=20, sent_by=None):
    with get_conn() as conn:
        if sent_by:
            rows = conn.execute(
                "SELECT * FROM leads WHERE status='DM送信済' AND sent_by=? ORDER BY dm_sent_date DESC, id DESC LIMIT ?",
                (sent_by, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM leads WHERE status='DM送信済' ORDER BY dm_sent_date DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def log_research_start():
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO research_runs(started_at) VALUES (?)",
            (datetime.now().isoformat(timespec="seconds"),),
        )
        conn.commit()
        return cur.lastrowid


def log_research_finish(run_id, fetched, added, error=None):
    with get_conn() as conn:
        conn.execute(
            """UPDATE research_runs
               SET finished_at=?, candidates_fetched=?, qualified_added=?, error=?
               WHERE id=?""",
            (
                datetime.now().isoformat(timespec="seconds"),
                fetched,
                added,
                error,
                run_id,
            ),
        )
        conn.commit()


def recent_runs(limit=5):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM research_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
