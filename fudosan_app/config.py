"""小松市・築古戸建て 買い判定の前提値（ガイド v2 §0/§3/§5 準拠）

数字は全部「相場観」。実際に見学したら overrides.json で物件ごとに上書きする。
"""
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "bukken.sqlite"

# --- データ源 ---------------------------------------------------------------
# 小松市空き家バンク(リスト)。ここに登録台帳PDFへのリンクがある
KOMATSU_LIST_URL = (
    "https://www.city.komatsu.lg.jp/soshiki/1027/"
    "akiya_akishitsubanku_komatsuchoukajouhoubanku/16922.html"
)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) fudosan-watch/1.0"

# --- 判定の前提（ガイド §5 のモデルケース） --------------------------------
# 諸費用（登記・保険・取得税・手数料）
BROKER_FEE = 330_000        # 800万以下の特例上限。事前交渉で圧縮できたら下げる
REGISTRATION_FEE = 200_000  # 司法書士込み 15〜25万
ACQUISITION_TAX = 30_000    # 築古は評価が低く少額
FIRE_INSURANCE_INIT = 40_000
MISC_FEE = 50_000           # 残置物撤去・雑費のバッファ
OTHER_COSTS = BROKER_FEE + REGISTRATION_FEE + ACQUISITION_TAX + FIRE_INSURANCE_INIT + MISC_FEE

# 修繕（化粧直しレベル。見学前は分からないので上限側で置く）
RENOVATION_DEFAULT = 500_000

# 年間経費
PROPERTY_TAX_YEAR = 40_000
INSURANCE_YEAR = 35_000
MGMT_RATE = 0.05        # 管理会社（自主管理なら0）
REPAIR_RESERVE_RATE = 0.10
VACANCY_RATE = 0.10

# §0 の式：総投資上限 = 年間手残り × 5（実質利回り20%）
YIELD_MULTIPLE = 5

# --- 通知対象のふるい ------------------------------------------------------
MAX_PRICE = 3_000_000       # ガイドの探索レンジ上限（超えたら通知しない）
NOTIFY_PRICE_DROP = True    # 既知物件の値下げも通知する

# --- 家賃想定 --------------------------------------------------------------
# 同じ台帳の賃貸物件から ㎡単価を出して想定家賃にする。サンプルが無いときの保険
FALLBACK_RENT = 45_000      # ガイドのモデルケース
# 上限はガイド §8「法人契約・家具付きで月6〜7万も視野」に合わせる。
# 延床が広いだけで家賃が青天井に伸びる計算になると、判定が甘くなって危ない
RENT_MIN, RENT_MAX = 30_000, 70_000

# --- LINE 通知（既存の公式LINE Botのチャネルを流用） ------------------------
def _load_env():
    """fudosan_app/.env があれば読む（KEY=VALUE 形式）"""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_ADMIN_USER_ID = os.environ.get("LINE_ADMIN_USER_ID", "")


def load_overrides() -> dict:
    """見学して分かった実額を物件ごとに上書きする。

    data/overrides.json 例:
        {"390": {"renovation": 1200000, "rent": 50000, "note": "屋根要葺替え"}}
    """
    path = DATA_DIR / "overrides.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
