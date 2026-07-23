"""Pococha 運営の月次レポートを自動同期 → SQLite → ダッシュボード再生成.

Chrome のセッションCookieを browser_cookie3 で読み、organizer-ope に HTTP GET。
ブラウザを開かずに完結する。launchd で毎日叩く想定。

使い方:
    python3 sync_monthly.py                # 今月分を同期 → dashboard.html 再生成
    python3 sync_monthly.py --month 2026-04  # 過去月を指定（前月遷移ボタン相当）
    python3 sync_monthly.py --no-dashboard   # ダッシュボード再生成を省略
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta

import browser_cookie3
import requests

sys.path.insert(0, os.path.dirname(__file__))
from db import connect

JST = timezone(timedelta(hours=9))
BASE = "https://organizer-ope.pococha.com"
DOMAIN = "organizer-ope.pococha.com"

LABEL_KEYS = [
    ("最終ランク", "final_rank", "str"),
    ("最高ランク", "max_rank", "str"),
    ("応援ポイント（累計）", "support_points", "int"),
    ("配信時間（累計）", "stream_min", "time"),
    ("配信日数", "stream_days", "int"),
    ("月間獲得ダイヤ", "total_dia", "int"),
    ("時間ダイヤ（累計）", "time_dia", "int"),
    ("盛り上がりダイヤ（累計）", "hype_dia", "int"),
    ("フォロワー数", "followers", "int"),
    ("コメント数（累計）", "comments", "int"),
    ("コメント人数（累計）", "comment_people", "int"),
    ("いいね数（累計）", "likes", "int"),
    ("いいね人数（累計）", "like_people", "int"),
    ("視聴された時間（累計）", "viewed_min", "time"),
    ("リスナー数（累計）", "listeners", "int"),
    ("デイリー最高順位", "daily_best", "int"),
    ("マンスリー順位", "monthly_rank", "int"),
]

INSERT_COLS = [
    "user_id", "month", "final_rank", "max_rank",
    "total_dia", "time_dia", "hype_dia",
    "stream_min", "stream_days", "support_points",
    "comments", "comment_people", "likes", "like_people",
    "viewed_min", "listeners", "daily_best", "monthly_rank",
    "followers", "captured_at",
]


def chrome_cookies():
    """Chromeから pococha.com 系のCookieを取得（macOS Keychainパスフレーズ自動解決）.
    domain_name='organizer-ope.pococha.com' だと .pococha.com で登録されてる Cookie が
    マッチしないので、全体取得して pococha が含まれるものだけ返す."""
    import http.cookiejar
    full = browser_cookie3.chrome()
    out = http.cookiejar.CookieJar()
    for c in full:
        if "pococha" in (c.domain or "").lower():
            out.set_cookie(c)
    return out


def hms_to_min(s):
    if not s:
        return None
    m = re.match(r"^(\d+):(\d+)(?::(\d+))?$", s.strip())
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2)) + (
        round(int(m.group(3)) / 60) if m.group(3) else 0
    )


def to_int(s):
    if s is None:
        return None
    s = re.sub(r"[,\s]", "", str(s))
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def parse_monthly_html(html, user_id):
    """SSRされた HTML から「label の後ろの __score 値」をスクレイプ"""
    out = {"user_id": int(user_id), "captured_at": datetime.now(JST).isoformat()}

    # 月ラベル "2026年5月" を見つけて YYYY-MM 化
    m = re.search(r"(\d{4})年(\d{1,2})月", html)
    out["month"] = f"{m.group(1)}-{int(m.group(2)):02d}" if m else None

    # ランク (B2 など) — 最終/最高で構造が違う
    rank_blocks = re.findall(
        r'liver-report-monthly-rank-label[^>]*>([^<]+)</div>.*?'
        r'liver-report-monthly-rank-name-first[^>]*>([^<]+)</span>.*?'
        r'liver-report-monthly-rank-name-second[^>]*>([^<]+)</span>',
        html, re.DOTALL,
    )
    for label, a, b in rank_blocks:
        key = {"最終ランク": "final_rank", "最高ランク": "max_rank"}.get(label.strip())
        if key:
            out[key] = (a + b).strip()

    # ラベル → 直後の __score の値（数値系）
    for label, key, kind in LABEL_KEYS:
        if kind == "str" and key in out:
            continue  # 既にrank_blocksで取得済み
        # ラベル と __score の間には </span></div> など可変要素が挟まる
        pat = (re.escape(label) +
               r'[^<]*(?:<[^>]+>)*\s*<div class="liver-report-summary-result__score">([^<]+)</div>')
        m = re.search(pat, html, re.DOTALL)
        if not m:
            continue
        v = m.group(1).strip()
        if kind == "int":
            out[key] = to_int(v)
        elif kind == "time":
            out[key] = hms_to_min(v)
        else:
            out[key] = v
    return out


def fetch_publishers(session):
    r = session.get(f"{BASE}/publishers?max_display=1000", timeout=20)
    r.raise_for_status()
    # tbody tr 内の td を抽出。IDが先頭列
    livers = []
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", r.text, re.DOTALL):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", m.group(1), re.DOTALL)
        if not cells:
            continue
        # HTMLタグ除去
        plain = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if plain and re.fullmatch(r"\d+", plain[0]):
            livers.append({"id": plain[0], "name": plain[1] if len(plain) > 1 else ""})
    return livers


def fetch_monthly(session, user_id, month=None):
    url = f"{BASE}/monthly_liver_report?user_id={user_id}"
    if month:
        # 過去月: ページャの prev_year/prev_month クエリは未確認のため未対応
        url += f"&month={month}"
    r = session.get(url, timeout=20)
    r.raise_for_status()
    return parse_monthly_html(r.text, user_id)


def upsert(conn, rec):
    if not rec.get("month") or not rec.get("user_id"):
        return False
    values = [rec.get(c) for c in INSERT_COLS]
    placeholders = ",".join(["?"] * len(INSERT_COLS))
    update = ",".join(f"{c}=excluded.{c}" for c in INSERT_COLS if c not in ("user_id", "month"))
    conn.execute(
        f"INSERT INTO monthly_reports ({','.join(INSERT_COLS)}) VALUES ({placeholders}) "
        f"ON CONFLICT(user_id, month) DO UPDATE SET {update}",
        values,
    )
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM 過去月指定（既定: 今月）")
    ap.add_argument("--no-dashboard", action="store_true")
    args = ap.parse_args()

    print("Chrome Cookieを読み込み中...")
    jar = chrome_cookies()
    session = requests.Session()
    session.cookies = jar
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    print("ライバー一覧取得中...")
    livers = fetch_publishers(session)
    if not livers:
        raise SystemExit("ライバーが取れなかった。Cookie切れ or ログアウトの可能性")
    print(f"  {len(livers)}名")

    conn = connect()
    n_ok, n_fail = 0, 0
    for lv in livers:
        try:
            rec = fetch_monthly(session, lv["id"], args.month)
            if upsert(conn, rec):
                print(f"  ✅ {lv['name']} ({lv['id']}) {rec.get('month')}: "
                      f"月間ダイヤ {rec.get('total_dia')}")
                n_ok += 1
            else:
                print(f"  ⚠️  {lv['name']} ({lv['id']}): month/user_id 取得失敗")
                n_fail += 1
        except Exception as e:
            print(f"  ❌ {lv['name']} ({lv['id']}): {e}")
            n_fail += 1
    conn.commit()
    conn.close()

    print(f"\n完了: 成功{n_ok} 失敗{n_fail}")

    if not args.no_dashboard:
        print("\nダッシュボード再生成...")
        subprocess.run([sys.executable, "dashboard.py"],
                       cwd=os.path.dirname(__file__), check=False)


if __name__ == "__main__":
    main()
