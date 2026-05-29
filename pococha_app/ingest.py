"""ライバー一覧ページの抽出JSON → SQLite 取り込み.

使い方:
    python3 ingest.py list_2026-05-28.json            # ファイルから
    cat list.json | python3 ingest.py -               # 標準入力から
    python3 ingest.py list.json --date 2026-05-28     # 取得日を明示

入力JSONは extract_list.js が返す {"headers": [...], "rows": [[...], ...]} 形式。
"""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from db import connect

JST = timezone(timedelta(hours=9))

# ヘッダ名 → 内部キー（部分一致で判定）
COL_MATCHERS = [
    ("id", "ID"),
    ("name", "名前"),
    ("x_name", "X"),
    ("off_days", "オフの日"),
    ("dia_time", "ダイヤ発生時間"),
    ("diamonds", "ダイヤ数"),
    ("rank", "ランク"),
    ("agreed", "同意"),
    ("stream", "配信時間"),
    ("group_name", "グループ名"),
]


def _map_columns(headers):
    idx = {}
    for key, needle in COL_MATCHERS:
        for i, h in enumerate(headers):
            if needle in h and key not in idx:
                idx[key] = i
                break
    return idx


def parse_int(s):
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def jp_date(s):
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s.strip())
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def time_to_min(s):
    """'5時間2分' / '62時間13分' / '0分' / '1時間' → 分."""
    if not s:
        return None
    h = re.search(r"(\d+)\s*時間", s)
    mi = re.search(r"(\d+)\s*分", s)
    if not h and not mi:
        return None
    return (int(h.group(1)) * 60 if h else 0) + (int(mi.group(1)) if mi else 0)


def parse_rank(s):
    m = re.match(r"([A-Z]\d)\s*\((-?\d+)\)", (s or "").strip())
    if m:
        return m.group(1), int(m.group(2))
    return (s or "").strip() or None, None


def parse_stream(s):
    """'114/0 (時間)' → (114, 0)."""
    m = re.match(r"(\d+)\s*/\s*(\d+)", (s or "").strip())
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _split_lines(cell):
    return [x.strip() for x in str(cell).split("\n") if x.strip()]


def parse_row(cells, idx):
    def get(key):
        i = idx.get(key)
        return cells[i] if i is not None and i < len(cells) else None

    user_id = parse_int(get("id"))
    if user_id is None:
        return None

    rank, meter = parse_rank(get("rank"))
    cur_h, limit_h = parse_stream(get("stream"))

    dia_time = _split_lines(get("dia_time") or "")
    diamonds = _split_lines(get("diamonds") or "")
    off_dates = [jp_date(d) for d in _split_lines(get("off_days") or "") if jp_date(d)]

    x_name = (get("x_name") or "").strip()
    if x_name == "-":
        x_name = None

    return {
        "user_id": user_id,
        "name": (get("name") or "").strip(),
        "x_name": x_name,
        "group_name": (get("group_name") or "").strip() or None,
        "rank": rank,
        "rank_meter": meter,
        "dia_min_week": time_to_min(dia_time[0]) if len(dia_time) > 0 else None,
        "dia_min_month": time_to_min(dia_time[1]) if len(dia_time) > 1 else None,
        "diamonds_week": parse_int(diamonds[0]) if len(diamonds) > 0 else None,
        "diamonds_month": parse_int(diamonds[1]) if len(diamonds) > 1 else None,
        "stream_cur_h": cur_h,
        "stream_limit_h": limit_h,
        "agreed": 1 if (get("agreed") or "").strip().upper() == "YES" else 0,
        "off_dates": off_dates,
    }


def ingest(payload, captured_on):
    headers = payload["headers"]
    rows = payload["rows"]
    idx = _map_columns(headers)
    missing = [k for k, _ in COL_MATCHERS if k not in idx and k != "x_name"]
    if "id" in missing or "diamonds" in missing:
        raise SystemExit(f"列マッピング失敗: headers={headers} idx={idx}")

    conn = connect()
    n = 0
    for cells in rows:
        rec = parse_row(cells, idx)
        if not rec:
            continue
        conn.execute(
            """INSERT INTO livers (user_id, name, x_name, group_name, first_seen, last_seen)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 name=excluded.name, x_name=excluded.x_name,
                 group_name=excluded.group_name, last_seen=excluded.last_seen""",
            (rec["user_id"], rec["name"], rec["x_name"], rec["group_name"],
             captured_on, captured_on),
        )
        conn.execute(
            """INSERT INTO snapshots
                 (user_id, captured_on, rank, rank_meter, diamonds_week, diamonds_month,
                  dia_min_week, dia_min_month, stream_cur_h, stream_limit_h,
                  agreed, off_days_count)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id, captured_on) DO UPDATE SET
                 rank=excluded.rank, rank_meter=excluded.rank_meter,
                 diamonds_week=excluded.diamonds_week, diamonds_month=excluded.diamonds_month,
                 dia_min_week=excluded.dia_min_week, dia_min_month=excluded.dia_min_month,
                 stream_cur_h=excluded.stream_cur_h, stream_limit_h=excluded.stream_limit_h,
                 agreed=excluded.agreed, off_days_count=excluded.off_days_count""",
            (rec["user_id"], captured_on, rec["rank"], rec["rank_meter"],
             rec["diamonds_week"], rec["diamonds_month"], rec["dia_min_week"],
             rec["dia_min_month"], rec["stream_cur_h"], rec["stream_limit_h"],
             rec["agreed"], len(rec["off_dates"])),
        )
        for d in rec["off_dates"]:
            conn.execute(
                "INSERT OR IGNORE INTO off_days (user_id, off_date) VALUES (?,?)",
                (rec["user_id"], d),
            )
        n += 1
    conn.commit()
    conn.close()
    return n


def main():
    args = [a for a in sys.argv[1:]]
    captured_on = datetime.now(JST).strftime("%Y-%m-%d")
    if "--date" in args:
        i = args.index("--date")
        captured_on = args[i + 1]
        del args[i:i + 2]
    if not args:
        raise SystemExit(__doc__)

    src = args[0]
    raw = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
    payload = json.loads(raw)
    n = ingest(payload, captured_on)
    print(f"取り込み完了: {n}件 (captured_on={captured_on}) → {os.path.relpath(connect_path())}")


def connect_path():
    from db import DB_PATH
    return DB_PATH


if __name__ == "__main__":
    main()
