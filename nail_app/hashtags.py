"""
ハッシュタグの土台（小松市・石川県のネイルサロン向け固定タグ）。

AIが写真から生成する「デザイン系タグ」に、この固定タグを毎回混ぜて
合計25〜30個にする（Instagram上限は30個）。
"""

# 地域タグ（小松市＋近隣＝集客の要）。近隣を入れると来店可能圏が広がる。
AREA_TAGS = [
    "小松市ネイル",       # ①ピンポイント（最重要・高来店率）
    "石川ネイル",         # ②広域（母数が大きい）— 5枠なので上位2つは範囲を分ける
    "小松ネイル",
    "小松市ネイルサロン",
    "石川県ネイル",
    "石川ネイルサロン",
    "金沢ネイル",       # 近隣・検索母数が大きい
    "加賀ネイル",
    "能美市ネイル",
    "白山市ネイル",
    "野々市ネイル",
]

# ネイル一般タグ（定番・検索されやすい）
NAIL_BASE_TAGS = [
    "ネイル",
    "ネイルサロン",
    "ネイルデザイン",
    "ジェルネイル",
    "お客様ネイル",
    "nail",
    "nailart",
    "gelnail",
    "nailstagram",
    "大人ネイル",
]

# 何個ずつ混ぜるか（合計5個運用。近年は絞る方が届きやすい）
# 配分: 地域タグ2 ＋ AIデザインタグ3。足りなければ一般タグで埋める。
NUM_AREA = 2       # 地域タグ（小松の集客が最重要なので必ず確保）
NUM_DESIGN = 3     # AI生成デザインタグ（写真に合った具体タグ）
NUM_BASE = 0       # 一般タグ（枠が余った時だけ）
MAX_TAGS = 5       # 合計上限


def build_hashtags(design_tags):
    """
    design_tags: AI が写真から抽出したデザイン系タグ（# なしの文字列リスト）。
    戻り値: '#xxx #yyy ...' の1行文字列。重複を除き最大 MAX_TAGS 個。
    地域タグを先に確保し、残りをAIデザインタグ→一般タグの順で埋める。
    """
    seen = set()
    result = []

    def add(tag):
        t = str(tag).strip().lstrip("#").replace(" ", "").replace("　", "")
        if not t:
            return
        low = t.lower()
        if low in seen:
            return
        seen.add(low)
        result.append(t)

    # 1) 地域タグ（最優先）
    for t in AREA_TAGS[:NUM_AREA]:
        add(t)
    # 2) AI デザインタグ
    for t in (design_tags or [])[:NUM_DESIGN]:
        add(t)
    # 3) 一般タグ
    for t in NAIL_BASE_TAGS[:NUM_BASE]:
        add(t)
    # 4) まだ枠があれば残りの地域・一般タグで埋める
    for t in AREA_TAGS[NUM_AREA:] + NAIL_BASE_TAGS[NUM_BASE:]:
        if len(result) >= MAX_TAGS:
            break
        add(t)

    result = result[:MAX_TAGS]
    return " ".join("#" + t for t in result)
