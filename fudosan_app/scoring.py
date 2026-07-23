"""ガイド §0 の式で「買えるか / いくらなら買えるか」を出す。

    総投資上限（物件+諸費用+修繕） = 年間手残り × 5

判定は3つ:
  BUY   … 売出価格のままで式に収まる
  NEGO  … 指値すれば収まる（指値上限を提示）
  PASS  … 家賃想定に対して価格が高すぎ、指値しても無理
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

import config
from sources import Bukken


@dataclass
class Verdict:
    status: str            # BUY / NEGO / PASS / INFO
    rent: int              # 想定家賃（円/月）
    rent_basis: str        # 家賃をどう出したか
    annual_net: int        # 年間手残り
    max_total: int         # 総投資上限
    total_invest: int      # 売出価格で買った場合の総投資
    max_offer: int         # 指値の上限（この額以下で買えば利回り20%）
    real_yield: float      # 売出価格で買った場合の実質利回り
    renovation: int
    other_costs: int


# 戸建て賃貸として現実的な㎡単価の範囲。事業用・一棟貸しの外れ値を弾く
# （台帳には家賃16万/月のような明らかに用途の違う行が混ざる）
UNIT_MIN, UNIT_MAX = 250.0, 900.0


def build_rent_model(bukkens: list[Bukken]) -> dict:
    """台帳の賃貸物件から ㎡単価を出す。校下ごと＋全体の中央値。"""
    per_school: dict[str, list[float]] = {}
    overall: list[float] = []
    dropped = 0
    for b in bukkens:
        if b.kind != "賃貸" or not b.rent or not b.floor_area:
            continue
        if b.floor_area < 30:      # 実質ワンルームは戸建の比較対象にしない
            continue
        unit = b.rent / b.floor_area
        if not (UNIT_MIN <= unit <= UNIT_MAX):
            dropped += 1
            continue
        overall.append(unit)
        per_school.setdefault(b.school, []).append(unit)

    overall_med = statistics.median(overall) if overall else None
    schools = {k: statistics.median(v) for k, v in per_school.items() if len(v) >= 2}
    if overall_med:
        # 校下のサンプルが2〜3件だと中央値も跳ねる。全体から離れすぎたら丸める
        schools = {k: min(v, overall_med * 1.4) for k, v in schools.items()}
    return {"overall": overall_med, "per_school": schools, "n": len(overall), "dropped": dropped}


def estimate_rent(b: Bukken, model: dict, override: dict | None = None) -> tuple[int, str]:
    if override and override.get("rent"):
        return int(override["rent"]), "手入力（overrides.json）"

    unit, basis = None, ""
    school_unit = model["per_school"].get(b.school)
    if b.floor_area and school_unit:
        unit, basis = school_unit, f"校下「{b.school}」の賃貸実績"
    elif b.floor_area and model["overall"]:
        unit, basis = model["overall"], f"小松市空き家バンクの賃貸{model['n']}件"

    if unit is None:
        return config.FALLBACK_RENT, "サンプル不足のためガイドの想定4.5万"

    rent = int(round(unit * b.floor_area / 1000) * 1000)

    # ガイド §6/§8: 小松は車社会。駐車場0台は論外、1台は弱い
    if b.parking == 0:
        rent = int(rent * 0.85)
        basis += "／駐車場なしで▲15%"
    elif b.parking == 1:
        rent = int(rent * 0.95)
        basis += "／駐車場1台で▲5%"

    rent = max(config.RENT_MIN, min(config.RENT_MAX, rent))
    return rent, basis


def annual_net_income(rent: int) -> int:
    """年間手残り。ガイド §5 の内訳そのまま（家賃54万→手残り約33〜35万）"""
    gross = rent * 12
    deductions = gross * (config.MGMT_RATE + config.REPAIR_RESERVE_RATE + config.VACANCY_RATE)
    return int(gross - deductions - config.PROPERTY_TAX_YEAR - config.INSURANCE_YEAR)


def judge(b: Bukken, model: dict, override: dict | None = None) -> Verdict:
    override = override or {}
    rent, basis = estimate_rent(b, model, override)
    net = annual_net_income(rent)
    max_total = net * config.YIELD_MULTIPLE

    reno = int(override.get("renovation", config.RENOVATION_DEFAULT))
    other = config.OTHER_COSTS
    max_offer = max_total - other - reno

    price = b.price or 0
    total = price + other + reno
    real_yield = (net / total * 100) if total else 0.0

    if not b.price:
        status = "INFO"
    elif total <= max_total:
        status = "BUY"
    elif max_offer > 0 and max_offer >= price * 0.6:
        # 6割まで叩けば収まる = 交渉の現実的レンジ内
        status = "NEGO"
    else:
        status = "PASS"

    return Verdict(
        status=status,
        rent=rent,
        rent_basis=basis,
        annual_net=net,
        max_total=max_total,
        total_invest=total,
        max_offer=max_offer,
        real_yield=real_yield,
        renovation=reno,
        other_costs=other,
    )


def man(yen: int | None) -> str:
    """円 → '180万' 表記"""
    if yen is None:
        return "—"
    return f"{yen / 10_000:,.0f}万"
