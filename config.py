"""
ライバー・代理店パートナー自動集客システム - 設定ファイル

使い方:
1. このファイルの API キーを自分のものに書き換える
2. 事務所情報を更新する
3. 検索キーワードやハッシュタグを必要に応じてカスタマイズする
"""

import os

# ============================================================
# X (Twitter) API 設定
# https://developer.twitter.com/ で取得
# ============================================================
TWITTER_API_KEY = os.environ.get("TWITTER_API_KEY", "")
TWITTER_API_SECRET = os.environ.get("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_TOKEN_SECRET = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", "")
TWITTER_BEARER_TOKEN = os.environ.get("TWITTER_BEARER_TOKEN", "")

# ============================================================
# Instagram 設定
# instagrapi 用のログイン情報
# ============================================================
INSTAGRAM_USERNAME = ""
INSTAGRAM_PASSWORD = ""

# ============================================================
# Instagram Graph API 設定
# https://developers.facebook.com/ で取得
# ============================================================
INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_BUSINESS_ID = os.environ.get("INSTAGRAM_BUSINESS_ID", "")

# ============================================================
# Google Gemini API 設定
# https://aistudio.google.com/apikey で取得
# ============================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# ============================================================
# 事務所情報
# ============================================================
OFFICE_NAME = "TAITAN PRO"
OFFICE_URL = "https://taitan-pro-lp.netlify.app/#apply"
OFFICE_TWITTER = "@taitan_LIVER"
OFFICE_INSTAGRAM = "@taitan_pro"
CONTACT_LINE = "@816qtxyj"

# ============================================================
# リード検索設定
# ============================================================
# ハッシュタグ検索（DM送付対象を探す）
TWITTER_SEARCH_HASHTAGS = [
    # アパレル系（ルミネ系ブランド）
    "#SNIDEL", "#FRAY_ID", "#JILL_STUART", "#MERCURYDUO",
    "#mystic", "#MURUA", "#rienda", "#EMODA", "#GYDA",
    "#お洒落さんと繋がりたい", "#低身長コーデ", "#古着女子",
    "#古着男子", "#淡色女子", "#韓国コーデ",
    # カフェ系
    "#カフェ好きさんと繋がりたい", "#カフェ巡り", "#カフェ活",
    "#映えスイーツ",
    "#渋谷カフェ", "#新宿カフェ", "#原宿カフェ", "#表参道カフェ",
    "#下北沢カフェ", "#横浜カフェ", "#福岡カフェ", "#大阪カフェ",
    "#京都カフェ", "#名古屋カフェ", "#新大久保カフェ",
    # 映えスポット
    "#渋谷スカイ", "#赤レンガ倉庫", "#みなとみらい",
    "#teamLab", "#青山",
]

# 名前検索用（2002年前後に人気の名前）
TWITTER_NAME_SEARCH = [
    "ひなた", "あおい", "ゆい", "みゆ", "さくら",
    "はるか", "ゆな", "りこ", "めい", "ここな",
    "hinata", "aoi", "yui", "miyu", "sakura",
    "はると", "そうた", "ゆうと", "りく", "こうき",
]

INSTAGRAM_HASHTAGS = [
    "お洒落さんと繋がりたい", "カフェ好きさんと繋がりたい",
    "カフェ巡り", "カフェ活", "映えスイーツ",
    "低身長コーデ", "古着女子", "淡色女子",
    "渋谷カフェ", "表参道カフェ",
]

# ============================================================
# NGターゲット設定
# ============================================================
NG_PROFILE_KEYWORDS = [
    # 事務所所属
    "所属", "専属", "公式ライバー", "カーブアウト", "carveout",
    # ライバー・配信者（既にやってる人はNG）
    "ライバー", "配信者", "配信中", "17LIVE", "17live",
    "TikTokLIVE", "tiktok live", "IRIAM", "iriam",
    "Pococha", "pococha", "SHOWROOM", "showroom",
    "ライブ配信", "配信してます",
    # 起業家・事業家
    "起業家", "事業家", "CEO", "代表取締役", "経営者",
    "起業", "社長",
    # 企業アカウント
    "公式", "株式会社", "合同会社", "有限会社",
    "official", "inc", "corp",
]

# DM送付ルール
DM_RULES = {
    "target_age": {"min": 18, "max": 30},
    "female_ratio_min": 0.5,        # 毎日のDMの50%以上を女性に
    "likes_before_dm": 2,            # DM前に最低2件いいね
    "require_face_photo": True,      # 顔写真必須（プロフィールか投稿）
    "require_japanese": True,        # 日本人のみ
}

# ============================================================
# DM送信設定
# ============================================================
DM_RATE_LIMIT = {
    "twitter": {
        "per_hour": 10,      # 1時間あたりのDM送信数
        "per_day": 50,       # 1日あたりの上限
        "interval_sec": 360, # DM間の最小間隔（秒）
    },
    "instagram": {
        "per_hour": 5,
        "per_day": 20,
        "interval_sec": 720,
    },
}

# ============================================================
# 投稿スケジュール設定
# ============================================================
POST_SCHEDULE = {
    "twitter": {
        "times": ["10:00", "13:00", "19:00", "22:00"],  # 投稿時刻
        "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    },
    "instagram": {
        "times": ["07:30", "20:00"],
        "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    },
}

# ============================================================
# リードステータス定義
# ============================================================
LEAD_STATUSES = [
    "未接触",
    "DM送信済",
    "返信あり",
    "面談予定",
    "面談済",
    "契約",
    "見送り",
]

# ============================================================
# ファイルパス
# ============================================================
LEADS_CSV = "data/leads.csv"
DM_LOG_CSV = "data/dm_log.csv"
POST_LOG_CSV = "data/post_log.csv"
