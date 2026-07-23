"""小松市空き家バンクの登録台帳PDFを取ってきて行データに直す。

台帳PDFは市HPのリスト頁からリンクされている1枚もの。
列: 登録No/用途/ペット/登録日/町名/校下/延床/建築年/構造/駐車場/売値/敷金/家賃/駐車場代/その他
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from urllib.parse import urljoin

import pdfplumber
import requests

from config import KOMATSU_LIST_URL, USER_AGENT

WAREKI_BASE = {"令和": 2018, "平成": 1988, "昭和": 1925, "大正": 1911, "明治": 1867}


def _norm(s: str | None) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).replace("\n", " ").strip()


def _to_yen(text: str) -> int | None:
    """'370万' '1,599万' '116,000' → 円。'要相談' 等は None"""
    t = _norm(text)
    if not t:
        return None
    m = re.search(r"([\d,\.]+)\s*万", t)
    if m:
        try:
            return int(float(m.group(1).replace(",", "")) * 10_000)
        except ValueError:
            return None
    m = re.search(r"([\d,]{3,})", t)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _to_float(text: str) -> float | None:
    m = re.search(r"([\d,]+\.?\d*)", _norm(text))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _build_year(text: str) -> int | None:
    """'昭和51年' '平成4年' '令和1年' → 西暦"""
    t = _norm(text)
    for era, base in WAREKI_BASE.items():
        m = re.search(era + r"\s*(\d+)\s*年", t)
        if m:
            return base + int(m.group(1))
    m = re.search(r"(19|20)(\d{2})\s*年", t)
    return int(m.group(0)[:4]) if m else None


def _parking(text: str) -> int | None:
    """'2台' → 2 / 'なし' → 0 / '4台以上' → 4 / 近隣有料 → 0"""
    t = _norm(text)
    if not t:
        return None
    if "なし" in t:
        return 0
    m = re.search(r"(\d+)\s*台", t)
    if m:
        return int(m.group(1))
    return 0 if ("有料" in t or "近所" in t or "近隣" in t) else None


@dataclass
class Bukken:
    no: str
    kind: str                      # "売買" or "賃貸"
    town: str = ""
    school: str = ""               # 校下
    floor_area: float | None = None
    build_year: int | None = None
    structure: str = ""
    parking: int | None = None
    price: int | None = None       # 売値（円）
    rent: int | None = None        # 家賃（円/月）
    deposit: int | None = None
    pet: str = ""
    listed: str = ""               # 登録日（和暦のまま）
    note: str = ""
    detail_url: str = ""
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# その他欄から拾う危険信号（ガイド §2/§4）
RISK_PATTERNS = [
    (r"市街化調整区域", "市街化調整区域（属人性の許可か要確認・貸せないと即死）"),
    (r"再建築不可|接道", "接道／再建築の記載あり（2m以上か確認）"),
    (r"要相談", "価格が要相談"),
    (r"現状有姿", "現状有姿売買（契約不適合の免責特約を要確認）"),
    (r"未登記", "未登記部分あり（表題登記費用の負担を契約書に明記）"),
    (r"農地|畑", "農地・畑付きの可能性（農地法の許可）"),
    (r"借地", "借地権の可能性"),
]


def fetch_list_page(session: requests.Session) -> str:
    res = session.get(KOMATSU_LIST_URL, timeout=30)
    res.raise_for_status()
    res.encoding = res.apparent_encoding or res.encoding
    return res.text


def find_ledger_url(html: str) -> tuple[str, str]:
    """市HPのHTMLから最新の『空き家バンク登録リスト』PDFのURLと更新表記を返す"""
    m = re.search(
        r'href="([^"]*[Aa]kiya[Bb]ank[^"]*\.pdf)"[^>]*>(.*?)</a>', html, re.S | re.I
    )
    if not m:
        raise RuntimeError("登録台帳PDFのリンクが市HPで見つからない（頁構成が変わった可能性）")
    url = urljoin(KOMATSU_LIST_URL, m.group(1))
    label = _norm(re.sub(r"<[^>]+>", "", m.group(2)))
    return url, label


def find_detail_urls(html: str) -> dict[str, str]:
    """『390[売買]今江町(PDF...)』形式のリンクを 登録No → URL で拾う"""
    out: dict[str, str] = {}
    for href, text in re.findall(
        r'href="([^"]+\.pdf)"[^>]*>(.*?)</a>', html, re.S | re.I
    ):
        label = _norm(re.sub(r"<[^>]+>", "", text))
        m = re.match(r"(\d+)\s*[\[［]", label)
        if m:
            out[m.group(1)] = urljoin(KOMATSU_LIST_URL, href)
    return out


def parse_ledger(pdf_bytes: bytes, detail_urls: dict[str, str] | None = None) -> list[Bukken]:
    detail_urls = detail_urls or {}
    rows: list[list] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                rows.extend(table)

    out: list[Bukken] = []
    for row in rows:
        cells = [_norm(c) for c in row] + [""] * 15
        no = cells[0]
        if not re.fullmatch(r"\d+", no):
            continue  # ヘッダ行・見出し行
        price = _to_yen(cells[10])
        rent = _to_yen(cells[12])
        kind = "売買" if (cells[1] or price or "売" in cells[1]) else "賃貸"
        if price is None and rent is not None:
            kind = "賃貸"
        b = Bukken(
            no=no,
            kind=kind,
            pet=cells[2],
            listed=cells[3],
            town=cells[4],
            school=cells[5],
            floor_area=_to_float(cells[6]),
            build_year=_build_year(cells[7]),
            structure=cells[8],
            parking=_parking(cells[9]),
            price=price,
            deposit=_to_yen(cells[11]),
            rent=rent,
            note=cells[14],
            detail_url=detail_urls.get(no, ""),
        )
        haystack = " ".join([b.note, cells[10], cells[9]])
        b.flags = [msg for pat, msg in RISK_PATTERNS if re.search(pat, haystack)]
        out.append(b)
    return out


def fetch_all() -> tuple[list[Bukken], str]:
    """(物件リスト, 台帳の更新表記) を返す"""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    html = fetch_list_page(session)
    url, label = find_ledger_url(html)
    details = find_detail_urls(html)
    pdf = session.get(url, timeout=60)
    pdf.raise_for_status()
    return parse_ledger(pdf.content, details), label
