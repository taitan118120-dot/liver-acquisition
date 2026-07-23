"""見た物件を覚えておく。新規と値下げだけを通知するため。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from config import DB_PATH, DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS bukken (
    no          TEXT PRIMARY KEY,
    kind        TEXT,
    price       INTEGER,
    rent        INTEGER,
    town        TEXT,
    payload     TEXT,
    first_seen  TEXT,
    last_seen   TEXT
);
CREATE TABLE IF NOT EXISTS price_history (
    no       TEXT,
    price    INTEGER,
    seen_at  TEXT
);
CREATE TABLE IF NOT EXISTS run_log (
    ran_at   TEXT,
    total    INTEGER,
    new_cnt  INTEGER,
    drop_cnt INTEGER,
    note     TEXT
);
"""


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def diff_and_save(conn: sqlite3.Connection, bukkens) -> tuple[list, list]:
    """(新規, 値下げ[(bukken, 旧価格)]) を返しつつDBを更新する"""
    now = datetime.now().isoformat(timespec="seconds")
    known = {r["no"]: r for r in conn.execute("SELECT * FROM bukken")}
    first_run = not known

    new_items, price_drops = [], []
    for b in bukkens:
        row = known.get(b.no)
        payload = json.dumps(b.to_dict(), ensure_ascii=False)
        if row is None:
            if not first_run:
                new_items.append(b)
            conn.execute(
                "INSERT INTO bukken VALUES (?,?,?,?,?,?,?,?)",
                (b.no, b.kind, b.price, b.rent, b.town, payload, now, now),
            )
        else:
            old = row["price"]
            if b.price and old and b.price < old:
                price_drops.append((b, old))
            if b.price != old:
                conn.execute(
                    "INSERT INTO price_history VALUES (?,?,?)", (b.no, b.price, now)
                )
            conn.execute(
                "UPDATE bukken SET kind=?, price=?, rent=?, town=?, payload=?, last_seen=? "
                "WHERE no=?",
                (b.kind, b.price, b.rent, b.town, payload, now, b.no),
            )
        if row is None:
            conn.execute("INSERT INTO price_history VALUES (?,?,?)", (b.no, b.price, now))

    conn.commit()
    return new_items, price_drops


def log_run(conn, total: int, new_cnt: int, drop_cnt: int, note: str = "") -> None:
    conn.execute(
        "INSERT INTO run_log VALUES (?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), total, new_cnt, drop_cnt, note),
    )
    conn.commit()
