"""精査基準の判定ロジック。profile情報 + 設定から passed/reasons を返す

target_type:
  - beginner: 未経験/初心者向け（現行ロジック）
  - existing_liver: 既存ライバー（Pococha以外で配信中）→ 移籍勧誘
  - agency: 代理店/事務所/スカウト → ライバー事業者向け提携提案
"""
import re


FOREIGN_SCRIPT_RE = re.compile(r"[\u3131-\u318F\uAC00-\uD7A3\u4E00-\u9FFF]")
JAPANESE_KANA_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FF]")
CARVEOUT_RE = re.compile(r"(carveout|カーブアウト|カ-ブアウト)", re.IGNORECASE)

# 英語ロマ字表記の日本人姓・名（英語プロフ誤排除防止）
_JP_ROMAJI_RE = re.compile(
    r"\b(sato|suzuki|takahashi|tanaka|watanabe|ito|kato|yamamoto|nakamura|"
    r"kobayashi|saito|kondo|maeda|ogawa|inoue|kimura|hayashi|shimizu|"
    r"yamaguchi|matsumoto|fujita|abe|hashimoto|yamada|mori|ikeda|ishikawa|"
    r"nakajima|fukuda|okada|hasegawa|murata|nishimura|goto|fujiwara|otsuka|"
    r"matsuda|harada|ono|tamura|wada|nishida|ueda|hara|miura|tsubota|"
    r"yoshida|kuroki|suganuma|tachibana|yoshimura|kawaguchi|ishida|nomura|"
    r"nagata|okamoto|sakamoto|hirano|sugiyama|asano|sakurai|aoki|endo|"
    r"fujii|noda|nakanishi|kuroda|koike|nagai|kirizume|"
    r"yukari|keiko|yuki|miku|haruka|sakura|honoka|hinata|nanami|ayaka|"
    r"mizuho|shiori|kaori|nana|rena|ruka|asumi|junna|akina|michi|miyu|"
    r"yuna|rina|mana|sena|kana|hana|momo|yua|ria|mai|yui|rei|sora)\b",
    re.IGNORECASE,
)

# 名前検査時に「英語の一般語＝日本人による装飾」とみなして除外する語
# (Best Life / Tokyo Love 等を外国人名と誤判定しないため)
_NON_NAME_WORDS = frozenset({
    "best", "life", "love", "peace", "good", "happy", "tokyo", "japan",
    "world", "dream", "real", "true", "free", "work", "style", "smile",
    "vibe", "vibes", "mood", "only", "ever", "forever", "shop", "shops",
    "store", "official", "studio", "team", "channel", "diary", "blog",
    "club", "cafe", "kitchen", "art", "design", "fashion", "beauty",
    "model", "modeling", "actress", "singer", "dancer", "hello", "from",
    "with", "and", "the", "for", "her", "his", "girl", "girls", "boy",
    "boys", "lady", "ladies", "girly", "lover", "fan", "fans",
})

# === ターゲット判定用キーワード ===
# 既存代理店/事務所/スカウト系（同業者=DM対象外。検出だけして qualify で除外する）
ESTABLISHED_AGENCY_RE = re.compile(
    r"(ライバー事務所|ライバープロダクション|ライバー代理店|ライバースカウト|"
    r"配信代理|配信事務所|スカウト事業|スカウター|スカウトマン|"
    r"事務所代表|事務所運営|事務所経営|プロダクション代表|"
    r"ライバーマネジメント|ライバー育成|ライバー専属|ライバー所属事務所|"
    r"キャスティング事業|タレント事務所|芸能事務所|"
    r"事務所|プロダクション|代理店|"
    r"配信MG|ライブ配信メディア|ライブ配信MG|"
    r"ライバー社長|ライバー戦術|ライバー(?:育成)?スクール|"
    r"ライバー支援|ライバーサポート|配信スクール|配信プロ|"
    r"\bcorp\b|\bllc\b|\binc\b|\.co\.jp|株式会社|合同会社|有限会社|"
    r"\bagency\b|\brecruit(?:er)?\b|\bcasting\b|\bbigo agency\b|"
    r"\bproduction\b|"
    # オンラインサロン・コミュニティ系（同業者：LINE誘導でDMが期待できない）
    r"オンラインサロン|online ?salon|"
    r"\d+期生|[一二三四五六七八九十]期生|期生募集|期生の声|"
    r"主宰|主催者)",
    re.IGNORECASE,
)

# 新agency=「副業/起業/事業オーナー希望者」系
AGENCY_DETECT_RE = re.compile(
    # 4カテゴリ
    # 🏪 実店舗経営者
    r"(経営|オーナー|owner|代表|社長|店長(?!として)|founder|ceo|"
    r"ネイルサロン|美容室|エステサロン|コンカフェ|カフェ経営|治療院|サロン経営|"
    # 💻 SNSビジネス層
    r"SNS運用|SNS代行|SNS集客|インスタ運用|コンテンツ販売|"
    r"無在庫転売|物販ビジネス|ネット副業|アフィリエイト|"
    # 🌃 水商売・キャスト
    r"ラウンジ嬢|キャバ嬢|キャバクラ|ホステス|銀座ホステス|六本木ラウンジ|"
    r"夜職|夜のお仕事|歌舞伎町|ナイトワーク|"
    # 🎤 ライバー憧れ層（「推し活」は beginner に移動 2026-05-06）
    r"ライバーになりたい|ライバー憧れ|配信者好き|"
    # 副業/起業全般
    r"副業ママ|副業女子|副業初心者|起業女子|起業ママ|起業準備中|"
    r"フリーランスママ|在宅ワーク|月収\d+万|稼ぎたい)",
    re.IGNORECASE,
)


def _is_established_agency(text: str) -> bool:
    return bool(ESTABLISHED_AGENCY_RE.search(text))

# 既存ライバー（Pococha以外）
EXISTING_LIVER_DETECT_RE = re.compile(
    r"(17LIVE|17ライブ|イチナナ|IRIAM|イリアム|ふわっち|FUWACCH|BIGO|ビゴ|"
    r"ミクチャ|MixChannel|ツイキャス|TwitCasting|SHOWROOM|ショールーム|"
    r"DOKIDOKI|HAKUNA|ハクナ|Palmu|パルム|tiktok ?live|TikTok ?LIVE|"
    r"配信者|配信中|ライブ配信|LIVE配信|生配信|"
    r"ライバー(?!事務所|プロダクション|代理店|スカウト|マネジメント|育成|専属)|"
    r"\bliver\b|\bstreamer\b|\blivestream\b)",
    re.IGNORECASE,
)

# Pococha は除外指示（ユーザ要件）
POCOCHA_RE = re.compile(r"(pococha|ポコチャ|ぽこちゃ|Pococha|POCOCHA)", re.IGNORECASE)


def detect_target_type(profile: dict) -> str:
    """profile から target_type を推定。
    優先度: agency > existing_liver > beginner
    """
    bio = (profile.get("biography") or "")
    full_name = (profile.get("full_name") or "")
    text = bio + " " + full_name

    # 既存代理店（同業者）も agency として検出 → qualify で除外される
    if AGENCY_DETECT_RE.search(text) or ESTABLISHED_AGENCY_RE.search(text):
        return "agency"
    if EXISTING_LIVER_DETECT_RE.search(text):
        return "existing_liver"
    return "beginner"


def _guess_foreign(bio: str, full_name: str) -> bool:
    bio = bio or ""
    full_name = full_name or ""
    text = bio + " " + full_name

    # \u30D5\u30EB\u30CD\u30FC\u30E0\u304C\u82F1\u5B57\u8907\u6570\u8A9E\u306E\u897F\u6D0B\u540D\u30D1\u30BF\u30FC\u30F3 \u2192 bio\u6709\u7121\u30FB\u30AB\u30CA\u6709\u7121\u30FB\u7D75\u6587\u5B57\u88C5\u98FE\u306B\u95A2\u308F\u3089\u305A\u5916\u56FD\u4EBA\u78BA\u5B9A
    # \u88C5\u98FE\u7D75\u6587\u5B57\u3084\u8A18\u53F7\u3092\u7A7A\u767D\u306B\u7F6E\u63DB\u3057\u305F\u4E0A\u3067\u300C\u82F1\u5B57\u5358\u8A9E\u304C2\u3064\u4EE5\u4E0A\u300D\u3092\u5224\u5B9A
    # ("Jerry Ross", "Jerry Ross \uD83D\uDC95", "Mary-Anne Smith", "John  Smith" \u7B49\u3092\u53D6\u308A\u3053\u307C\u3055\u306A\u3044)
    fn = full_name.strip()
    if fn and not JAPANESE_KANA_RE.search(fn) and not re.search(r"[\u4E00-\u9FFF]", fn):
        # \u82F1\u5B57\u4EE5\u5916\uFF08\u7D75\u6587\u5B57\u30FB\u8A18\u53F7\uFF09\u3092\u7A7A\u767D\u5316
        fn_latin = re.sub(r"[^A-Za-z'\-\.\s]", " ", fn)
        # \u5358\u8A9E\u62BD\u51FA: 2\u6587\u5B57\u4EE5\u4E0A\u306E\u82F1\u5B57\u30B7\u30FC\u30B1\u30F3\u30B9
        words = re.findall(r"[A-Za-z][A-Za-z'\-\.]*[A-Za-z]|[A-Za-z]{2,}", fn_latin)
        words = [w for w in words if len(w) >= 2]
        if len(words) >= 2:
            joined = " ".join(words).lower()
            # JP\u30ED\u30DE\u5B57\u3092\u542B\u3080\u5834\u5408\u306F\u65E5\u672C\u4EBA\u3068\u5224\u5B9A
            if not _JP_ROMAJI_RE.search(joined):
                # \u5168\u5358\u8A9E\u304C\u300C\u82F1\u8A9E\u306E\u4E00\u822C\u88C5\u98FE\u8A9E\u300D\u3067\u306F\u306A\u3044\u3053\u3068\u3092\u78BA\u8A8D\uFF08"Best Life" \u7B49\u3092\u9664\u5916\uFF09
                if not all(w.lower() in _NON_NAME_WORDS for w in words):
                    return True

    # \u30AB\u30CA\u304C\u3042\u308C\u3070\u65E5\u672C\u4EBA\u78BA\u5B9A\uFF08\u4ED6\u30B9\u30AF\u30EA\u30D7\u30C8\u691C\u51FA\u3088\u308A\u512A\u5148\u3002\u7D75\u6587\u5B57\u88C5\u98FE\u3067\u30AD\u30EA\u30EB\u6587\u5B57\u7B49\u3092\u4F7F\u3046\u65E5\u672C\u4EBA\u5BFE\u7B56\uFF09
    if JAPANESE_KANA_RE.search(bio) or JAPANESE_KANA_RE.search(full_name):
        return False
    # \u97D3\u56FD\u8A9E
    if re.search(r"[\uAC00-\uD7A3]", text):
        return True
    # \u30BF\u30A4\u8A9E
    if re.search(r"[\u0E00-\u0E7F]", text):
        return True
    # \u30A2\u30E9\u30D3\u30A2\u8A9E\uFF08\u30DA\u30EB\u30B7\u30E3\u8A9E\u542B\u3080\uFF09
    if re.search(r"[\u0600-\u06FF]", text):
        return True
    # \u30D2\u30F3\u30C7\u30A3\u30FC\u8A9E/\u30C7\u30FC\u30F4\u30A1\u30CA\u30FC\u30AC\u30EA\u30FC
    if re.search(r"[\u0900-\u097F]", text):
        return True
    # \u30AD\u30EA\u30EB\u6587\u5B57\uFF08\u30ED\u30B7\u30A2\u8A9E\u7B49\uFF09
    if re.search(r"[\u0400-\u04FF]", text):
        return True
    # \u305D\u306E\u4ED6\u30B9\u30AF\u30EA\u30D7\u30C8
    if re.search(r"[\u0590-\u05FF\u0980-\u09FF\u0B80-\u0BFF\u0C00-\u0C7F\u0C80-\u0CFF\u0D00-\u0D7F]", text):
        return True
    # \u30AB\u30CA\u306A\u3057\u3067 bio \u306B\u6F22\u5B573\u6587\u5B57\u4EE5\u4E0A \u2192 \u4E2D\u56FD\u8A9E\u570F
    if re.search(r"[\u4E00-\u9FFF]{3,}", bio):
        return True
    # \u30AB\u30CA\u3082\u6F22\u5B57\u3082\u4E00\u5207\u306A\u3044\u5834\u5408\u306E\u307F\u82F1\u8A9E\u30C1\u30A7\u30C3\u30AF
    if not re.search(r"[\u4E00-\u9FFF]", text):
        # \u82F1\u5B5715\u6587\u5B57\u4EE5\u4E0A \u2192 \u82F1\u8A9E\u30D7\u30ED\u30D5\u30A3\u30FC\u30EB\uFF08\u5916\u56FD\u4EBA\u7591\u3044\uFF09
        # \u305F\u3060\u3057\u65E5\u672C\u4EBA\u59D3\u30FB\u540D\u306E\u30ED\u30DE\u5B57\u8868\u8A18\u304C\u542B\u307E\u308C\u308B\u5834\u5408\u306F\u9664\u5916
        if len(re.findall(r"[a-zA-Z]", text)) >= 15 and not _JP_ROMAJI_RE.search(text):
            return True
        # 2\u5358\u8A9E\u4EE5\u4E0A\u306E\u82F1\u8A9E\u540D \u304B\u3064 bio\u306B\u3082\u82F1\u5B57\u3042\u308A \u2192 \u5916\u56FD\u4EBA\u7591\u3044\uFF08\u65E5\u672C\u8A9E\u30ED\u30DE\u5B57\u540D+\u7A7Abio\u306F\u5BFE\u8C61\u5916\uFF09
        if (re.match(r"^[a-zA-Z]+(?:\s[a-zA-Z]+)+$", full_name.strip())
                and len(re.findall(r"[a-zA-Z]", bio)) >= 10
                and not _JP_ROMAJI_RE.search(text)):
            return True
    return False


# \u5916\u56FD\u7C4D\u30FB\u5728\u5916\u306E\u660E\u793A\u30DE\u30FC\u30AB\u30FC\uFF08\u30B9\u30AF\u30EA\u30D7\u30C8\u691C\u51FA\u3092\u3059\u308A\u629C\u3051\u308B\u30B1\u30FC\u30B9\u5411\u3051\uFF09
FOREIGN_PERSON_RE = re.compile(
    r"(\u97D3\u56FD\u4EBA|\u671D\u9BAE\u4EBA|\u4E2D\u56FD\u4EBA|\u53F0\u6E7E\u4EBA|\u30D5\u30A3\u30EA\u30D4\u30F3\u4EBA|\u30D9\u30C8\u30CA\u30E0\u4EBA|\u30A4\u30F3\u30C9\u30CD\u30B7\u30A2\u4EBA|\u30BF\u30A4\u4EBA|"
    r"\u30DE\u30EC\u30FC\u30B7\u30A2\u4EBA|\u30B7\u30F3\u30AC\u30DD\u30FC\u30EB\u4EBA|\u30A4\u30F3\u30C9\u4EBA|\u30DF\u30E3\u30F3\u30DE\u30FC\u4EBA|\u30D6\u30E9\u30B8\u30EB\u4EBA|\u30ED\u30B7\u30A2\u4EBA|"
    r"\u97D3\u56FD\u5728\u4F4F|\u97D3\u56FD\u4F4F\u307F|\u30BD\u30A6\u30EB\u5728\u4F4F|\u4E2D\u56FD\u5728\u4F4F|\u4E0A\u6D77\u5728\u4F4F|\u5317\u4EAC\u5728\u4F4F|\u53F0\u6E7E\u5728\u4F4F|"
    r"\u30D5\u30A3\u30EA\u30D4\u30F3\u5728\u4F4F|\u30DE\u30CB\u30E9\u5728\u4F4F|\u30D9\u30C8\u30CA\u30E0\u5728\u4F4F|\u30CF\u30CE\u30A4\u5728\u4F4F|\u30DB\u30FC\u30C1\u30DF\u30F3\u5728\u4F4F|"
    r"\u30BF\u30A4\u5728\u4F4F|\u30D0\u30F3\u30B3\u30AF\u5728\u4F4F|\u30DE\u30EC\u30FC\u30B7\u30A2\u5728\u4F4F|\u30AF\u30A2\u30E9\u30EB\u30F3\u30D7\u30FC\u30EB\u5728\u4F4F|"
    r"\u30A4\u30F3\u30C9\u30CD\u30B7\u30A2\u5728\u4F4F|\u30B8\u30E3\u30AB\u30EB\u30BF\u5728\u4F4F|\u30B7\u30F3\u30AC\u30DD\u30FC\u30EB\u5728\u4F4F|\u30A4\u30F3\u30C9\u5728\u4F4F|"
    r"\u5728\u65E5\u5916\u56FD\u4EBA|\u5916\u56FD\u4EBA(?!\u5411\u3051|\u5BFE\u8C61|\u3054|\u306E\u305F\u3081|\u89B3\u5149|\u65C5\u884C)|"
    r"I['']m (?:korean|chinese|filipin[ao]|thai|vietnamese|indonesian|malaysian|singaporean|indian))",
    re.IGNORECASE,
)

# \u975E\u65E5\u672C\u56FD\u65D7\u306E\u7D75\u6587\u5B57\u691C\u51FA
_RI_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")
_JP_FLAG = "\U0001F1EF\U0001F1F5"  # \uD83C\uDDEF\uD83C\uDDF5


def _has_foreign_flag(text: str) -> bool:
    """\u65E5\u672C\u4EE5\u5916\u306E\u56FD\u65D7\u7D75\u6587\u5B57\u304C\u542B\u307E\u308C\u3066\u3044\u308C\u3070 True"""
    return any(m.group() != _JP_FLAG for m in _RI_RE.finditer(text))


def _guess_age_ok(bio: str, age_min: int, age_max: int) -> bool:
    if re.search(r"(40代|50代|60代|70代|アラフォー|アラフィフ|アラカン)", bio):
        return False
    if re.search(r"(4[0-9]歳|5[0-9]歳|6[0-9]歳)", bio):
        return False
    if re.search(r"(?:^|[\s|/｜.、]|age[:：]?\s?)(4[1-9]|5[0-9]|6[0-9])(?:[\s|/｜.、]|代|歳|$)", bio, re.IGNORECASE):
        return False
    if re.search(r"(高校生|中学生|JK|JC|小学生)", bio):
        return False
    # 生年は「XXXX年生まれ/生」の文脈でのみ解釈（"2025年目標"等を誤排除しない）
    m = re.search(r"(19[6-9]\d|20\d{2})\s*年?\s*(?:生まれ|生|産まれ)|born\s*(?:in\s*)?(19[6-9]\d|20\d{2})", bio, re.IGNORECASE)
    if m:
        from datetime import datetime
        year_str = m.group(1) or m.group(2)
        year = int(year_str)
        age = datetime.now().year - year
        if age < age_min or age > age_max:
            return False
    return True


# beginner 用: 他社所属/肩書ありNG（既存事業者は除外したい）
AGENCY_RE = re.compile(
    r"(staff|スタッフ|ショップ|\b店舗\b|プレス|press|インフルエンサー|influencer|アンバサダー|ambassador|stylehinter|styling ?hinter|公式|official|shop[a-z ]*staff|shopstaff|shop ?snap|公式ブロガー|公認|認定|専属|選抜|バイヤー|ディレクター|director|コンサルタント|アドバイザー|アナリスト|店長|事業所|リユース|セレクトショップ|@[a-z0-9_]+_official|@[a-z0-9_]+\.official|@[a-z0-9_]+_store|@[a-z0-9_]+_staff|@[a-z0-9_]+\.official|ららぽーと|ルミネ|パルコ|マルイ|イオンモール|大丸|高島屋|タカシマヤ|三越|伊勢丹|セノバ|テラス|タワーズ|ルクア|アトレ|GINZA SIX|ソラマチ|センター北|ショッピングセンター|[一-龥ぁ-んァ-ヶ]{1,8}(店)[^員客]|元アパレル|アパレル歴|アパレル店員|イメコン|イメージコンサルタント|ピラティスインストラクター|イラストレーター|看護師|ハンドメイド作家|美容師|カウンセラー)",
    re.IGNORECASE,
)
BRAND_FULLNAME_RE = re.compile(r"(店|official|店舗|ショップ|shop|リサイクル|セレクト|boutique)", re.IGNORECASE)

# 紹介系/まとめ系アカウント（共通NG）
COMPILATION_RE = re.compile(
    r"(かわいい子まとめ|美女まとめ|美女紹介|女子紹介|モデル紹介|"
    r"美人図鑑|美女図鑑|可愛い子|べっぴん|オススメ女子|"
    r"\bgirls\b ?(?:photo|gallery|magazine|collection)|"
    r"美女bot|可愛い子bot)",
    re.IGNORECASE,
)

# ネイルサロン・ネイリスト系（全 target_type で DM 送らない）
NAIL_SALON_RE = re.compile(
    r"(ネイルサロン|nail\s*salon|ネイリスト|ネイルスクール|ネイル講師|"
    r"ジェルネイル教室|ネイル教室|ネイルアーティスト|自爪育成サロン|"
    r"ネイル検定|ネイルショップ|ネイル用品|"
    r"(?:^|[_\s|/・])ネイル(?:$|[_\s|/・の系師専])|"
    r"(?:^|[_\-\.])nail(?:$|[_\-\.s])|"
    r"ネイル(?:の|を)[^\s]{0,10}(?:道しるべ|サポート|指導|相談|ガイド|アドバイス)|"
    r"JNA)",
    re.IGNORECASE,
)

# まつ毛エクステ・美容師系（全 target_type で DM 送らない）
BEAUTY_PRO_RE = re.compile(
    r"(まつ毛エクステ|まつげエクステ|マツエク|まつエク|マツゲエクステ|"
    r"アイリスト|アイラッシュ|eyelash\s*(?:extension|artist|stylist)?|"
    r"lash\s*(?:artist|stylist|extension|tech)|"
    r"まつ毛パーマ|まつげパーマ|まつ毛カール|"
    r"アイブロウ(?:アーティスト|サロン|スクール|スタイリスト)|eyebrow\s*(?:artist|stylist)|"
    r"美容師|美容室|美容院|hair\s*(?:stylist|salon|dresser|artist)|hairdresser|hair\s*designer|"
    r"スタイリスト歴|現役美容師|美容師歴|美容師さん|"
    r"(?:^|[_\s|/・])美容師(?:$|[_\s|/・])|"
    r"(?:^|[_\s|/・])マツエク(?:$|[_\s|/・の系師専])|"
    r"(?:^|[_\-\.])lash(?:$|[_\-\.es])|"
    r"アイデザイナー|eye\s*designer)",
    re.IGNORECASE,
)

# ライバー事務所・配信事務所系（競合・同業者。全 target_type で除外）
LIVER_AGENCY_RE = re.compile(
    r"(ライバー事務所|ライバープロダクション|ライバー代理店|ライバースカウト|"
    r"配信事務所|ライブ配信事務所|配信代理|ライバーマネジメント|"
    r"ライバー専属|ライバー所属事務所|ライバー育成事務所|"
    r"liver\s*agency|live\s*streaming\s*agency|"
    r"IRIAM事務所|17LIVE事務所|ぽこちゃ事務所)",
    re.IGNORECASE,
)

# SNSフォロワー販売/増加代行スパム（共通NG・agencyタグから多発混入）
SNS_SPAM_RE = re.compile(
    r"(フォロワー販売|フォロワー増加|増加代行|フォロワー[購売]入|"
    r"いいね販売|SNS増加|SNSフォロワー|高品質フォロワー|"
    r"フォロワー[U|UP|アップ]|follower[\s_]*(?:sale|sales|sell|increase))",
    re.IGNORECASE,
)

# ペット/犬猫アカウント（本人ではなくペット主体・全 target_type で除外）
PET_BIO_RE = re.compile(
    r"(うちの(?:わんこ|ワンコ|愛犬|愛猫|猫|犬|にゃんこ|ニャンコ)|"
    r"愛犬日記|愛猫日記|わんこ日記|にゃんこ日記|わんこグラム|にゃんこグラム|"
    r"トイプー|トイプードル|チワワ|柴犬|ポメラニアン|ポメ|"
    r"ミニチュアダックス|ダックスフン|マルチーズ|フレブル|フレンチブルドッグ|キャバリア|"
    r"スコティッシュフォールド|マンチカン|ラグドール|アメショ|ベンガル|スコ猫|"
    r"保護犬|保護猫|里親|"
    r"わんすたぐらむ|にゃんすたぐらむ|"
    r"\b(?:dog|cat|puppy|kitten|pet)stagram\b|\bdoggram\b|\bcatgram\b|"
    r"#dogstagram|#catstagram|#petstagram)",
    re.IGNORECASE,
)
PET_NAME_RE = re.compile(
    r"(🐶|🐕|🐩|🐾|🐱|🐈|🦮|"
    r"わんころ|ワンコちゃん|ニャンこ|わんちゃん|ニャンちゃん|"
    r"専用のわんこ|専用のにゃんこ|専用わんこ|専用ニャンこ)"
)
PET_USERNAME_RE = re.compile(
    r"(?:^|[_\.\-])"
    r"(?:dog|cat|nyan|neko|inu|wanko|wanchan|nyanko|"
    r"puppy|kitten|chihu|toypoo|shiba|poodle|pome|maltese|frenchie)"
    r"(?:[_\.\-\d]|$)",
    re.IGNORECASE,
)

# ご飯/グルメ/カフェ紹介アカウント（本人不在の紹介系・全 target_type で除外）
FOOD_GUIDE_RE = re.compile(
    r"(グルメ紹介|グルメ巡り|グルメ垢|グルメアカ|グルメスポット|"
    r"ご飯紹介|ご飯垢|ご飯日記|"
    r"飯テロ|食べ歩き|食べログ|食レポ|"
    r"カフェ紹介|カフェ巡り|カフェ垢|カフェ日記|カフェ好きと繋がりたい|"
    r"スイーツ紹介|スイーツ巡り|スイーツ垢|"
    r"ランチ紹介|ランチ巡り|ラーメン巡り|ラーメン紹介|"
    r"(?:東京|関東|関西|大阪|名古屋|福岡|横浜|京都|札幌|神戸|沖縄|北海道)"
    r"\s*(?:グルメ|ランチ|カフェ|スイーツ|ラーメン|うどん|そば|ディナー)|"
    r"(?:グルメ|ランチ|カフェ|スイーツ|ラーメン|うどん|そば|ディナー)"
    r"\s*(?:紹介|巡り|スポット|まとめ|図鑑|マップ|案内|散歩|MAP)|"
    r"\bfoodie\b|\bfoodgram\b|\bfoodstagram\b|food\s*blog|food\s*review|"
    r"\bfoodlover\b|\bfoodaholic\b|\bcafestagram\b)",
    re.IGNORECASE,
)
FOOD_USERNAME_RE = re.compile(
    r"(?:^|[_\.\-])"
    r"(?:foodie|foodgram|gourmet|tabelog|tabearuki|"
    r"gohan|meshi|gurume|"
    r"ramen|sushi|sweets|cafestagram)"
    r"(?:[_\.\-\d]|$)",
    re.IGNORECASE,
)

# 推し活/ファン/ヲタ専用アカウント（本人ライバー候補ではない・全 target_type で除外）
OSHIKATSU_RE = re.compile(
    r"(推し活|推し事|推ししか勝たん|推しのいる生活|推しと繋がりたい|"
    r"ガチ恋|ガチ恋勢|担当|単担|箱推し|現場|遠征|参戦|"
    r"@[^\s]{1,20}専用|"
    r"\bジャニ(?:ヲタ|オタ|担)|ジャニーズJr|"
    r"アイドルヲタ|アイドルオタ|地下アイドル|地下アイドル現場|メン地下|"
    r"V垢|VTuber推し|Vtuber推し|"
    r"二次元|オタ垢|オタクアカウント|趣味垢|"
    r"ヲタクと繋がりたい|オタクと繋がりたい|"
    r"\boshi\b|\boshikatsu\b)",
    re.IGNORECASE,
)

# beginner用: full_nameにビジネスキーワード = 既存事業者（先生/コーチ/コンサル系）
# AGENCY_DETECT_REでカバーしきれない肩書きをここで補完
NAME_BUSINESS_RE = re.compile(
    r"(先生|講師|コーチ|coach|集客|専門家|インストラクター|instructor|"
    r"セラピスト|therapist|カウンセラー|counselor|"
    r"コンサル|consult|アドバイザー|advisor|"
    r"プロデューサー|producer|ディレクター|director|"
    r"フリーランス|freelance|"
    r"\bCEO\b|\bCFO\b|\bCMO\b|\bCTO\b|\bowner\b|\bfounder\b|"
    r"代表(?!作)|社長|オーナー|"
    r"教科書|スクール|アカデミー|academy|"
    r"集客術|集客サポート|集客プロ|集客コンサル|"
    r"運用代行|運用サポート|運用コンサル|発信のお手伝い|発信サポート|"
    r"主婦の副業|ママの副業|働き方|ボッチママ|"
    r"オンラインビジネス|オンラインサロン|"
    r"〇から始める|0から始める|ゼロから始める)",
    re.IGNORECASE,
)


def _is_pet_account(profile: dict) -> bool:
    bio = (profile.get("biography") or "").strip()
    name = (profile.get("full_name") or "").strip()
    username = (profile.get("username") or "").strip()
    text_all = bio + " " + name + " " + username
    if PET_BIO_RE.search(text_all):
        return True
    if PET_NAME_RE.search(name):
        return True
    if PET_USERNAME_RE.search(username) and len(bio) < 30:
        return True
    return False


def _is_food_guide(profile: dict) -> bool:
    bio = (profile.get("biography") or "").strip()
    name = (profile.get("full_name") or "").strip()
    username = (profile.get("username") or "").strip()
    text_all = bio + " " + name + " " + username
    if FOOD_GUIDE_RE.search(text_all):
        return True
    if FOOD_USERNAME_RE.search(username) and len(bio) < 30:
        return True
    return False


def _is_oshikatsu(profile: dict) -> bool:
    bio = (profile.get("biography") or "").strip()
    name = (profile.get("full_name") or "").strip()
    text_all = bio + " " + name
    return bool(OSHIKATSU_RE.search(text_all))


def qualify_profile(profile: dict, cfg: dict, target_type: str = "beginner") -> tuple[bool, list[str]]:
    """target_type ごとにルールを切り替えて精査"""
    reasons = []
    fl = profile.get("followers")
    fw = profile.get("following")
    bio = profile.get("biography", "") or ""
    full_name = profile.get("full_name", "") or ""
    username = profile.get("username", "") or ""

    post_count = profile.get("post_count")
    min_posts = cfg.get("min_posts", 3)

    # === 共通NG ===
    if profile.get("is_verified"):
        reasons.append("認証済（大型アカ）")
    if profile.get("is_private"):
        reasons.append("非公開アカ")
    # ビジネスアカでメッセージボタンが別CTAに置換 = 確実にDM不可
    # EMAIL/CALL/TEXT のみ確定除外。UNKNOWN/None は曖昧なので除外しない（保守的）
    if profile.get("is_business") and profile.get("business_contact_method") in ("EMAIL", "CALL", "TEXT"):
        reasons.append(f"DM不可（外部CTA={profile.get('business_contact_method')}）")
    # 投稿ゼロ/極少 = ゴーストアカウント or DM受信オフ設定が多いため除外
    if post_count is not None and post_count < min_posts:
        reasons.append(f"投稿{post_count}件（{min_posts}件未満・DM不達リスク）")
    if CARVEOUT_RE.search(bio):
        reasons.append("カーブアウト所属")
    if _guess_foreign(bio, full_name):
        reasons.append("外国籍疑い")
    if FOREIGN_PERSON_RE.search(bio) or FOREIGN_PERSON_RE.search(full_name):
        reasons.append("外国籍/在外明示")
    if _has_foreign_flag(bio + " " + full_name):
        reasons.append("外国籍/在外明示")
    if target_type != "agency" and not _guess_age_ok(bio, cfg.get("age_min", 18), cfg.get("age_max", 40)):
        reasons.append("年齢レンジ外")
    if COMPILATION_RE.search(bio) or COMPILATION_RE.search(full_name):
        reasons.append("紹介/まとめ系アカ")
    if SNS_SPAM_RE.search(bio) or SNS_SPAM_RE.search(full_name) or SNS_SPAM_RE.search(username):
        reasons.append("SNS販売/増加代行スパム")
    # ネイルサロン・ネイリスト（全 target_type で DM 送らない）
    text_all = bio + " " + full_name + " " + username
    if NAIL_SALON_RE.search(text_all):
        reasons.append("ネイルサロン/ネイリスト（対象外）")
    # まつ毛エクステ・美容師系（全 target_type で DM 送らない）
    if BEAUTY_PRO_RE.search(text_all):
        reasons.append("美容師/まつ毛エクステ（対象外）")
    # ペット/犬猫アカウント（全 target_type で DM 送らない）
    if _is_pet_account(profile):
        reasons.append("ペット/犬猫アカ（対象外）")
    # ご飯/グルメ/カフェ紹介アカウント（全 target_type で DM 送らない）
    if _is_food_guide(profile):
        reasons.append("グルメ/カフェ紹介アカ（対象外）")
    # 推し活/ファン専用アカウントは除外しない（ライバー視聴者として有望なターゲット）

    # === target_type 別ルール ===
    if target_type == "agency":
        # 新agency=副業希望者/事業オーナー候補。既存代理店（同業者）・ライバー事務所は除外
        text_for_check = bio + " " + full_name + " " + username
        if LIVER_AGENCY_RE.search(text_for_check):
            reasons.append("ライバー/配信事務所（競合）")
        if ESTABLISHED_AGENCY_RE.search(text_for_check):
            reasons.append("既存代理店/同業者")
        # external_urlのLINE誘導 = 同業者の典型導線（DM受け取らずLINEで囲い込み）
        ext_url = (profile.get("external_url") or "").lower()
        if "lin.ee/" in ext_url or "line.me/" in ext_url or "liff.line.me/" in ext_url:
            reasons.append("LINE誘導（同業者の囲い込み導線）")
        # ブランド公式/店舗のfull_nameは除外
        if BRAND_FULLNAME_RE.search(full_name):
            reasons.append("full_nameがブランド名")
        if profile.get("is_business"):
            category = (profile.get("category") or "").lower()
            if any(k in category for k in ("ショッピング", "アパレル", "衣料品", "ブランド", "shop", "小売")):
                reasons.append("ブランド公式アカウント")
        # フォロワー数値ルール: min/max/ratio すべて適用（業者bot弾き）
        max_fl_agency = cfg.get("max_followers_agency", 30000)
        min_fl_agency = cfg.get("min_followers_agency", 50)
        if fl is None or fw is None:
            reasons.append("数値未取得")
        else:
            if fl >= max_fl_agency:
                reasons.append(f"フォロワー{fl}人（{max_fl_agency}以上・上限超）")
            if fl < min_fl_agency:
                reasons.append(f"フォロワー不足（{fl}<{min_fl_agency}）")
            if fw < 1:
                reasons.append("フォロー数ゼロ")
            elif fl >= 1 and fw >= 1:
                ratio = max(fl, fw) / min(fl, fw)
                if ratio > cfg.get("max_ratio", 5.0):
                    reasons.append(f"比率{ratio:.1f}倍（{cfg.get('max_ratio',5.0)}倍超・業者bot疑い）")

    elif target_type == "existing_liver":
        # 既存ライバー: Pococha は除外（ユーザ要件）
        if POCOCHA_RE.search(bio) or POCOCHA_RE.search(full_name):
            reasons.append("Pococha所属（対象外）")
        # ライバー/配信キーワードはNGじゃない（=AGENCY_RE は無効）
        # ブランド公式・店舗系のみ除外
        if BRAND_FULLNAME_RE.search(full_name):
            reasons.append("full_nameがブランド名")
        if profile.get("is_business"):
            category = (profile.get("category") or "").lower()
            if any(k in category for k in ("ショッピング", "アパレル", "衣料品", "ブランド", "shop", "小売")):
                reasons.append("ブランド公式アカウント")
        # フォロワー上限は緩める（既存ライバーは数千〜数万でも候補）
        max_fl_existing = cfg.get("max_followers_existing", 1000)
        if fl is None or fw is None:
            reasons.append("数値未取得")
        else:
            if fl >= max_fl_existing:
                reasons.append(f"フォロワー{fl}人（{max_fl_existing}以上・上限超）")
            if fl < cfg.get("min_followers", 1):
                reasons.append("フォロワー不足")
            if fw < 1:
                reasons.append("フォロー数ゼロ")
            elif fl >= 1 and fw >= 1:
                ratio = max(fl, fw) / min(fl, fw)
                if ratio > cfg.get("max_ratio", 5.0):
                    reasons.append(f"比率{ratio:.1f}倍（{cfg.get('max_ratio',5.0)}倍超）")
        # 男性は対象外（既存ライバーも女性ライバーターゲット）
        if re.search(r"(大人男子|メンズ|男性|パパ|40代パパ|\bmen\b|僕|俺)", bio, re.IGNORECASE):
            reasons.append("男性疑い")

    else:  # beginner
        # username にブランド/公式ワード
        if re.search(r"(\.official|_official|\.store|_store|\.staff|_staff|_shop|\.shop|\.jp|_jp\b|official_)", username, re.IGNORECASE):
            reasons.append("ブランド名のusername")
        if fl is None or fw is None:
            reasons.append("数値未取得")
        else:
            if fl >= cfg.get("max_followers", 10000):
                reasons.append(f"フォロワー{fl}人（{cfg['max_followers']}以上・上限超）")
            if fl < cfg.get("min_followers", 1):
                reasons.append("フォロワー不足")
            if fw < 1:
                reasons.append("フォロー数ゼロ")
            elif fl >= 1 and fw >= 1:
                ratio = max(fl, fw) / min(fl, fw)
                if ratio > cfg.get("max_ratio", 5.0):
                    reasons.append(f"比率{ratio:.1f}倍（{cfg['max_ratio']}倍超）")
        # business_account かつ fashion/shop系 カテゴリ
        category = (profile.get("category") or "").lower()
        if profile.get("is_business") and any(k in category for k in ("ショッピング", "アパレル", "衣料品", "ブランド", "shop", "小売")):
            reasons.append("ブランド公式アカウント")
        # 他社所属/肩書
        if AGENCY_RE.search(bio):
            reasons.append("他社所属・肩書あり")
        if BRAND_FULLNAME_RE.search(full_name):
            reasons.append("full_nameがブランド名")
        # full_name に先生/コーチ/コンサル等のビジネス肩書（既存事業者）
        if NAME_BUSINESS_RE.search(full_name):
            reasons.append("full_nameに事業者肩書")
        # 男性
        if re.search(r"(大人男子|メンズ|男性|パパ|40代パパ|\bmen\b|僕|俺)", bio, re.IGNORECASE):
            reasons.append("男性疑い")

    return (len(reasons) == 0, reasons)


def personalize(template: str, name: str, username: str) -> str:
    return template.replace("{name}", name or username).replace("{username}", username)
