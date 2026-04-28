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
    r"production)",
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
    # 🎤 ライバー憧れ層
    r"ライバーになりたい|ライバー憧れ|配信者好き|推し活|"
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
    if JAPANESE_KANA_RE.search(bio) or JAPANESE_KANA_RE.search(full_name):
        return False
    if re.search(r"[\uAC00-\uD7A3]", bio or ""):
        return True
    if re.search(r"[\u4E00-\u9FFF]{3,}", bio or "") and not JAPANESE_KANA_RE.search(bio or ""):
        return True
    return False


def _guess_age_ok(bio: str, age_min: int, age_max: int) -> bool:
    if re.search(r"(40代|50代|60代|70代|アラフォー|アラフィフ|アラカン)", bio):
        return False
    if re.search(r"(4[0-9]歳|5[0-9]歳|6[0-9]歳)", bio):
        return False
    if re.search(r"(?:^|[\s|/｜.、]|age[:：]?\s?)(4[1-9]|5[0-9]|6[0-9])(?:[\s|/｜.、]|代|歳|$)", bio, re.IGNORECASE):
        return False
    if re.search(r"(高校生|中学生|JK|JC|小学生)", bio):
        return False
    m = re.search(r"(19[6-9]\d)|(20\d{2})", bio)
    if m:
        from datetime import datetime
        year = int(m.group(0))
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

# SNSフォロワー販売/増加代行スパム（共通NG・agencyタグから多発混入）
SNS_SPAM_RE = re.compile(
    r"(フォロワー販売|フォロワー増加|増加代行|フォロワー[購売]入|"
    r"いいね販売|SNS増加|SNSフォロワー|高品質フォロワー|"
    r"フォロワー[U|UP|アップ]|follower[\s_]*(?:sale|sales|sell|increase))",
    re.IGNORECASE,
)

# メディア/出版/プロ系（agencyタグから誤検出されがち）
MEDIA_PUBLISHER_RE = re.compile(
    r"(出版社|出版|publisher|新聞社|報道|テレビ局|TV局|"
    r"プロデューサー|producer|"
    r"作家|小説家|作詞家|作曲家|脚本家|画家|漫画家|"
    r"記者|編集部|編集長|編集者|編集主任|編集|"
    r"角川|講談社|集英社|文藝春秋|新潮社|小学館|"
    r"PR\s*TIMES|プレスリリース|press[ _]?release|"
    r"局アナ|アナウンサー|キャスター|"
    r"声優|タレント|アーティスト|ミュージシャン|"
    r"_news\b|_media\b|_press\b|_tv\b|_book\b|_publish|"
    r"\bpartner\b|\bcoach\b|\bbrand\b|"
    r"投資家|アカデミー|スクール|コーチング|コンサル(?:タント)?|"
    r"先生|教授|博士|医師|弁護士|税理士|司法書士|社労士)",
    re.IGNORECASE,
)


def qualify_profile(profile: dict, cfg: dict, target_type: str = "beginner") -> tuple[bool, list[str]]:
    """target_type ごとにルールを切り替えて精査"""
    reasons = []
    fl = profile.get("followers")
    fw = profile.get("following")
    bio = profile.get("biography", "") or ""
    full_name = profile.get("full_name", "") or ""
    username = profile.get("username", "") or ""

    # === 共通NG ===
    # X(Twitter) Blue は課金で誰でも青バッジ取得可能なので is_verified だけでは除外しない
    # 公式organizationバッジ判定は profile から取れないので、bio/full_name でしか判断できない
    if profile.get("is_private"):
        reasons.append("非公開アカ（鍵）")
    if CARVEOUT_RE.search(bio):
        reasons.append("カーブアウト所属")
    if _guess_foreign(bio, full_name):
        reasons.append("外国籍疑い")
    if not _guess_age_ok(bio, cfg.get("age_min", 18), cfg.get("age_max", 40)):
        reasons.append("年齢レンジ外")
    if COMPILATION_RE.search(bio) or COMPILATION_RE.search(full_name):
        reasons.append("紹介/まとめ系アカ")
    if SNS_SPAM_RE.search(bio) or SNS_SPAM_RE.search(full_name) or SNS_SPAM_RE.search(username):
        reasons.append("SNS販売/増加代行スパム")
    if MEDIA_PUBLISHER_RE.search(bio) or MEDIA_PUBLISHER_RE.search(full_name):
        reasons.append("メディア/出版/プロ系（対象外）")
    # アラビア/ヒンディー
    if re.search(r"[\u0600-\u06FF\u0900-\u097F]", bio):
        reasons.append("外国籍疑い")

    # === target_type 別ルール ===
    if target_type == "agency":
        # 新agency=副業希望者/事業オーナー候補。既存代理店（同業者）は除外
        text_for_check = bio + " " + full_name + " " + username
        if ESTABLISHED_AGENCY_RE.search(text_for_check):
            reasons.append("既存代理店/同業者")
        # bio に副業/起業関連キーワードがないと「単に副業kw でひっかかっただけのノイズ」になる
        # → 強制的に AGENCY_DETECT_RE にマッチを要求
        if not AGENCY_DETECT_RE.search(bio + " " + full_name):
            reasons.append("agency属性が確認できない（hint由来のみ）")
        # フォロワー上限（巨大アカは届きにくい・代理店候補としては既に成熟しすぎ）
        max_fl_agency = cfg.get("max_followers_agency", 5000)
        if fl is None or fw is None:
            reasons.append("数値未取得")
        else:
            if fl > max_fl_agency:
                reasons.append(f"フォロワー{fl}人（{max_fl_agency}超・成熟済）")
            if fl < 1:
                reasons.append("フォロワー不足")

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
            if fl > max_fl_existing:
                reasons.append(f"フォロワー{fl}人（{max_fl_existing}超）")
            if fl < cfg.get("min_followers", 1):
                reasons.append("フォロワー不足")
            if fw < 1:
                reasons.append("フォロー数ゼロ")
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
            if fl > cfg.get("max_followers", 10000):
                reasons.append(f"フォロワー{fl}人（{cfg['max_followers']}超）")
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
        # 男性
        if re.search(r"(大人男子|メンズ|男性|パパ|40代パパ|\bmen\b|僕|俺)", bio, re.IGNORECASE):
            reasons.append("男性疑い")

    return (len(reasons) == 0, reasons)


def personalize(template: str, name: str, username: str) -> str:
    return template.format(name=name or username, username=username)
