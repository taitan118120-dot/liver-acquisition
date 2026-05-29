"""/publishers/{id} 詳細ページの抽出JSON → SQLite 取り込み.

extract_publisher.js が吐く publisher_{uid}_{date}.json を読み込み、
ランク変動履歴 / イベント履歴(エントリー・入賞) / 配信一覧 / ダイヤ残高 を投入し、
livers マスタのプロフィール列（レベル・性別・地域・フォロワー数など）も更新する。

使い方:
    python3 ingest_publisher.py                         # data/publishers/ の全JSON
    python3 ingest_publisher.py data/publishers/foo.json [...]   # ファイル指定
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from db import connect
from ingest import parse_int, time_to_min, parse_rank

PUB_DIR = os.path.join(os.path.dirname(__file__), "data", "publishers")


def find_section(sections, needle):
    for label, sec in sections.items():
        if needle in label:
            return sec
    return None


def hidx(headers, needle):
    for i, h in enumerate(headers):
        if needle in h:
            return i
    return None


def kv_dict(section):
    """[["キー","値"],...] → {キー: 値}."""
    return {row[0].strip(): (row[1] if len(row) > 1 else "") for row in section["rows"]}


def norm_dt(s):
    """'2026-05-29 19:01:59 JST' → '2026-05-29 19:01:59'."""
    return re.sub(r"\s*JST\s*$", "", (s or "").strip()) or None


def ingest_file(conn, path):
    payload = json.load(open(path, encoding="utf-8"))
    uid = parse_int(payload.get("user_id"))
    captured_on = payload.get("captured_on")
    sections = payload.get("sections", {})
    if uid is None:
        print(f"  skip(no user_id): {path}")
        return

    # --- ライバー情報 → livers プロフィール更新 ---
    info_sec = find_section(sections, "ライバー情報")
    if info_sec:
        kv = kv_dict(info_sec)
        ext_url = (kv.get("URL") or "").strip() or None
        # 詳細ページの名前はイベント幕付きで揮発的なので display_name に格納し、
        # コメント紐付けに使う name は新規ライバー時のみ設定（既存は上書きしない）。
        disp = (kv.get("名前") or "").strip() or None
        conn.execute(
            """INSERT INTO livers (user_id, name, display_name, first_seen, last_seen,
                 level, gender, region, follows, followers,
                 member_since, agency_since, close_time, ext_url)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 display_name=excluded.display_name, last_seen=excluded.last_seen,
                 level=excluded.level, gender=excluded.gender, region=excluded.region,
                 follows=excluded.follows, followers=excluded.followers,
                 member_since=excluded.member_since, agency_since=excluded.agency_since,
                 close_time=excluded.close_time, ext_url=excluded.ext_url""",
            (uid, disp, disp, captured_on, captured_on,
             parse_int(kv.get("レベル")), (kv.get("性別") or "").strip() or None,
             (kv.get("地域") or "").strip() or None,
             parse_int(kv.get("フォロー数")), parse_int(kv.get("フォロワー数")),
             norm_dt(kv.get("会員登録日時")), norm_dt(kv.get("事務所登録日")),
             (kv.get("締め時間") or "").strip() or None, ext_url),
        )

    # --- ダイヤ残高 ---
    dia_sec = find_section(sections, "ダイヤ")
    if dia_sec:
        kv = kv_dict(dia_sec)
        conn.execute(
            """INSERT INTO dia_balance (user_id, captured_on, diamonds, updated_at)
               VALUES (?,?,?,?)
               ON CONFLICT(user_id, captured_on) DO UPDATE SET
                 diamonds=excluded.diamonds, updated_at=excluded.updated_at""",
            (uid, captured_on, parse_int(kv.get("ダイヤ数")), norm_dt(kv.get("更新日時"))),
        )

    # --- 直近のランク変動履歴 ---
    rh = find_section(sections, "ランク変動履歴")
    n_rank = 0
    if rh and rh["rows"]:
        h = rh["headers"]
        ci = {k: hidx(h, k) for k in ("ID", "配信日", "Before", "After", "変動理由", "メーター増減")}
        for r in rh["rows"]:
            cid = parse_int(r[ci["ID"]]) if ci["ID"] is not None else None
            if cid is None:
                continue
            conn.execute(
                """INSERT INTO rank_history
                     (change_id, user_id, change_date, before_rank, after_rank, reason, meter_delta)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(change_id) DO UPDATE SET
                     change_date=excluded.change_date, before_rank=excluded.before_rank,
                     after_rank=excluded.after_rank, reason=excluded.reason,
                     meter_delta=excluded.meter_delta""",
                (cid, uid, r[ci["配信日"]].strip(), r[ci["Before"]].strip(),
                 r[ci["After"]].strip(), r[ci["変動理由"]].strip(),
                 parse_int(r[ci["メーター増減"]])),
            )
            n_rank += 1

    # --- イベント履歴（エントリー / 入賞）---
    n_event = 0
    for needle, kind in (("エントリー履歴", "entry"), ("入賞履歴", "result")):
        sec = find_section(sections, needle)
        if not sec or not sec["rows"]:
            continue
        h = sec["headers"]
        i_name = hidx(h, "イベント名")
        i_stage = hidx(h, "ステージ")
        i_block = hidx(h, "ブロック")
        i_status = hidx(h, "ステータス")
        i_place = hidx(h, "順位")
        i_entry = hidx(h, "エントリー日時")
        i_period = hidx(h, "開始日時")
        for r in sec["rows"]:
            ev = r[i_name].strip() if i_name is not None else None
            if not ev:
                continue
            conn.execute(
                """INSERT INTO event_history
                     (user_id, kind, event_name, stage, block, status, place, entry_at, period)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(user_id, kind, event_name, period) DO UPDATE SET
                     stage=excluded.stage, block=excluded.block, status=excluded.status,
                     place=excluded.place, entry_at=excluded.entry_at""",
                (uid, kind, ev,
                 r[i_stage].strip() if i_stage is not None else None,
                 r[i_block].strip() if i_block is not None else None,
                 r[i_status].strip() if i_status is not None else None,
                 r[i_place].strip() if i_place is not None else None,
                 norm_dt(r[i_entry]) if i_entry is not None else None,
                 r[i_period].strip() if i_period is not None else None),
            )
            n_event += 1

    # --- 配信一覧 ---
    sl = find_section(sections, "配信一覧")
    n_stream = 0
    if sl and sl["rows"]:
        h = sl["headers"]
        ci = {
            "id": hidx(h, "ID"), "title": hidx(h, "タイトル"), "dur": hidx(h, "配信時間"),
            "start": hidx(h, "開始時間"), "state": hidx(h, "状態"),
            "format": hidx(h, "配信形態"), "kind": hidx(h, "配信種別"), "pay": hidx(h, "支払対象"),
        }
        for r in sl["rows"]:
            sid = parse_int(r[ci["id"]]) if ci["id"] is not None else None
            if sid is None:
                continue
            raw_title = r[ci["title"]].strip() if ci["title"] is not None else ""
            title = raw_title.split("/")[-1].strip() if "/" in raw_title else raw_title
            conn.execute(
                """INSERT INTO streams
                     (stream_id, user_id, title, duration_min, started_at, state, format, kind, payable)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(stream_id) DO UPDATE SET
                     title=excluded.title, duration_min=excluded.duration_min,
                     started_at=excluded.started_at, state=excluded.state,
                     format=excluded.format, kind=excluded.kind, payable=excluded.payable""",
                (sid, uid, title,
                 time_to_min(r[ci["dur"]]) if ci["dur"] is not None else None,
                 norm_dt(r[ci["start"]]) if ci["start"] is not None else None,
                 r[ci["state"]].strip() if ci["state"] is not None else None,
                 r[ci["format"]].strip() if ci["format"] is not None else None,
                 r[ci["kind"]].strip() if ci["kind"] is not None else None,
                 r[ci["pay"]].strip() if ci["pay"] is not None else None),
            )
            n_stream += 1

    print(f"  {os.path.basename(path)}: uid={uid} rank_hist={n_rank} events={n_event} streams={n_stream}")


def main():
    args = sys.argv[1:]
    files = args if args else sorted(glob.glob(os.path.join(PUB_DIR, "publisher_*.json")))
    if not files:
        raise SystemExit(f"対象JSONなし: {PUB_DIR}/publisher_*.json")
    conn = connect()
    for path in files:
        ingest_file(conn, path)
    conn.commit()
    conn.close()
    print(f"取り込み完了: {len(files)}ファイル")


if __name__ == "__main__":
    main()
