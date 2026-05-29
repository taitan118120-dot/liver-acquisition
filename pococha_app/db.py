"""Pococha 運営ダッシュボードのデータ蓄積用 SQLite."""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "pococha.sqlite")

SCHEMA = """
CREATE TABLE IF NOT EXISTS livers (
  user_id    INTEGER PRIMARY KEY,
  name       TEXT,
  x_name     TEXT,
  group_name TEXT,
  first_seen TEXT,
  last_seen  TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id         INTEGER NOT NULL,
  captured_on     TEXT NOT NULL,           -- YYYY-MM-DD (JST, 1日1件)
  rank            TEXT,                     -- 例: B1
  rank_meter      INTEGER,                  -- 例: 0
  diamonds_week   INTEGER,
  diamonds_month  INTEGER,
  dia_min_week    INTEGER,                  -- ダイヤ発生時間(週) を分換算
  dia_min_month   INTEGER,
  stream_cur_h    INTEGER,                  -- 現在の配信時間(時)
  stream_limit_h  INTEGER,                  -- 配信時間上限(時)
  agreed          INTEGER,                  -- 同意済み 1/0
  off_days_count  INTEGER,
  UNIQUE(user_id, captured_on)
);

CREATE TABLE IF NOT EXISTS off_days (
  user_id  INTEGER NOT NULL,
  off_date TEXT NOT NULL,                   -- YYYY-MM-DD
  UNIQUE(user_id, off_date)
);

CREATE INDEX IF NOT EXISTS idx_snap_user ON snapshots(user_id, captured_on);

CREATE TABLE IF NOT EXISTS comments (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  liver       TEXT,                      -- 配信ライバー名/ID（任意ラベル）
  stream_id   TEXT,                      -- 配信ID（過去配信クロール時）
  commenter   TEXT,                      -- コメントした人の表示名
  level       TEXT,                      -- リスナーレベル（取れれば）
  text        TEXT,                      -- コメント本文
  timing      TEXT,                      -- 配信内の経過時間（過去配信のみ）
  posted_at   TEXT,                      -- 絶対時刻 JST（過去配信のみ）
  client_ts   TEXT,                      -- ライブ取得時のブラウザ時刻(ISO)
  source      TEXT,                      -- 'history' or 'live'
  server_ts   TEXT DEFAULT (datetime('now','+9 hours')),
  dedupe_key  TEXT UNIQUE                -- 重複排除キー
);

CREATE INDEX IF NOT EXISTS idx_comments_liver ON comments(liver, posted_at);
CREATE INDEX IF NOT EXISTS idx_comments_commenter ON comments(commenter);
CREATE INDEX IF NOT EXISTS idx_comments_stream ON comments(stream_id);

-- /publishers/{id} 詳細ページ由来（ingest_publisher.py が投入）

CREATE TABLE IF NOT EXISTS rank_history (
  change_id   INTEGER PRIMARY KEY,      -- 変動履歴行のID（ページ提供）
  user_id     INTEGER NOT NULL,
  change_date TEXT,                      -- 配信日 YYYY-MM-DD
  before_rank TEXT,                      -- 例: B1 (0)
  after_rank  TEXT,
  reason      TEXT,                      -- 上位30% / おやチケ使用/オフの日 / 変動なし 等
  meter_delta INTEGER                    -- メーター増減
);

CREATE TABLE IF NOT EXISTS event_history (
  user_id    INTEGER NOT NULL,
  kind       TEXT,                       -- 'entry'(エントリー) / 'result'(入賞)
  event_name TEXT,
  stage      TEXT,                       -- ステージ名
  block      TEXT,                       -- ブロック名
  status     TEXT,                       -- 参加中/終了済み/ぽこ賞/上位入賞 等
  place      TEXT,                       -- 順位（入賞のみ）
  entry_at   TEXT,                       -- エントリー日時（entryのみ）
  period     TEXT,                       -- 開始〜終了
  UNIQUE(user_id, kind, event_name, period)
);

CREATE TABLE IF NOT EXISTS streams (
  stream_id    INTEGER PRIMARY KEY,
  user_id      INTEGER NOT NULL,
  title        TEXT,
  duration_min INTEGER,                  -- 配信時間（分換算）
  started_at   TEXT,                     -- 開始時間 JST
  state        TEXT,                     -- 配信中/終了
  format       TEXT,                     -- 配信形態（動画配信 等）
  kind         TEXT,                     -- 配信種別（通常配信/ご新規歓迎配信/おしのび配信）
  payable      TEXT                      -- 支払対象（OK / NG(...)）
);

CREATE INDEX IF NOT EXISTS idx_rank_user ON rank_history(user_id, change_date);
CREATE INDEX IF NOT EXISTS idx_event_user ON event_history(user_id);
CREATE INDEX IF NOT EXISTS idx_streams_user ON streams(user_id, started_at);

CREATE TABLE IF NOT EXISTS dia_balance (
  user_id     INTEGER NOT NULL,
  captured_on TEXT NOT NULL,             -- 取得日 YYYY-MM-DD
  diamonds    INTEGER,                   -- ダイヤ残高
  updated_at  TEXT,                      -- ページ上の更新日時
  UNIQUE(user_id, captured_on)
);
"""

# livers マスタに後から足したプロフィール列（ALTER で追補）
LIVER_EXTRA_COLS = {
    "display_name": "TEXT",
    "level": "INTEGER",
    "gender": "TEXT",
    "region": "TEXT",
    "follows": "INTEGER",
    "followers": "INTEGER",
    "member_since": "TEXT",
    "agency_since": "TEXT",
    "close_time": "TEXT",
    "ext_url": "TEXT",
}


def _migrate(conn):
    have = {r["name"] for r in conn.execute("PRAGMA table_info(livers)")}
    for col, typ in LIVER_EXTRA_COLS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE livers ADD COLUMN {col} {typ}")


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn
