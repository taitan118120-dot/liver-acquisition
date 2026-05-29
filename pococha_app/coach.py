"""所属ライバーの成績コーチング自動要約.

/publishers/{id} 由来の rank_history / streams / event_history / dia_balance /
livers プロフィール ＋ 既存 snapshots・comments から、各ライバーの
「現状・伸び・要サポート・次の目標」をテキスト要約する。

使い方:
    python3 coach.py                 # 全ライバー
    python3 coach.py むう             # 名前部分一致
    python3 coach.py 11874524        # user_id 指定
    python3 coach.py --json          # 機械可読JSONで全件

方針(重要): ランク昇格に必要なダイヤ数など未確認の閾値は捏造しない。
データから読み取れる事実と、その方向性だけを述べる。
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from db import connect

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
TODAY = NOW.strftime("%Y-%m-%d")
THIS_MONTH = TODAY[:7]


def _d(s):
    """'2026-05-29 19:01:59' or '2026-05-29' → date or None."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _days_since(s):
    d = _d(s)
    return (NOW.date() - d).days if d else None


def _fmt_min(m):
    if m is None:
        return "-"
    return f"{m // 60}h{m % 60:02d}m"


def load_liver(conn, uid):
    liver = conn.execute("SELECT * FROM livers WHERE user_id=?", (uid,)).fetchone()
    snaps = conn.execute(
        "SELECT * FROM snapshots WHERE user_id=? ORDER BY captured_on", (uid,)
    ).fetchall()
    rank_hist = conn.execute(
        "SELECT * FROM rank_history WHERE user_id=? ORDER BY change_date DESC", (uid,)
    ).fetchall()
    streams = conn.execute(
        "SELECT * FROM streams WHERE user_id=? ORDER BY started_at DESC", (uid,)
    ).fetchall()
    results = conn.execute(
        "SELECT * FROM event_history WHERE user_id=? AND kind='result' ORDER BY period DESC",
        (uid,),
    ).fetchall()
    entries_active = conn.execute(
        "SELECT * FROM event_history WHERE user_id=? AND kind='entry' AND status LIKE '%参加中%'",
        (uid,),
    ).fetchall()
    dia = conn.execute(
        "SELECT * FROM dia_balance WHERE user_id=? ORDER BY captured_on DESC LIMIT 1", (uid,)
    ).fetchone()
    offs_month = conn.execute(
        "SELECT off_date FROM off_days WHERE user_id=? AND off_date LIKE ? ORDER BY off_date",
        (uid, THIS_MONTH + "%"),
    ).fetchall()

    name = liver["name"] if liver else None
    fans = comments = 0
    last_comment = None
    if name:
        row = conn.execute(
            "SELECT count(*) c, count(DISTINCT commenter) p, max(posted_at) l "
            "FROM comments WHERE liver=?", (name,),
        ).fetchone()
        comments, fans, last_comment = row["c"], row["p"], row["l"]

    return {
        "liver": liver, "snaps": snaps, "rank_hist": rank_hist, "streams": streams,
        "results": results, "entries_active": entries_active, "dia": dia,
        "offs_month": [o["off_date"] for o in offs_month],
        "fans": fans, "comments": comments, "last_comment": last_comment,
    }


def analyze_streams(streams):
    """直近の配信実態を集計（streamsは最新20件程度）."""
    if not streams:
        return None
    dates = [_d(s["started_at"]) for s in streams]
    dates = [d for d in dates if d]
    span_days = (max(dates) - min(dates)).days + 1 if dates else 0
    recent7 = [s for s in streams if (_d(s["started_at"]) and (NOW.date() - _d(s["started_at"])).days < 7)]
    active_days7 = len({_d(s["started_at"]) for s in recent7})
    ng = [s for s in streams if (s["payable"] or "").startswith("NG")]
    shinki = [s for s in streams if "新規" in (s["kind"] or "")]
    return {
        "n": len(streams), "span_days": span_days,
        "recent7_n": len(recent7),
        "recent7_min": sum((s["duration_min"] or 0) for s in recent7),
        "recent7_active_days": active_days7,
        "ng_n": len(ng),
        "shinki_n": len(shinki),
        "last_started": streams[0]["started_at"],
        "last_gap_days": _days_since(streams[0]["started_at"]),
    }


def analyze(data):
    liver = data["liver"]
    snaps = data["snaps"]
    cur = snaps[-1] if snaps else None
    rh = data["rank_hist"]
    st = analyze_streams(data["streams"])

    flags, trend, goals = [], [], []

    # 現在ランク：rank_history 最新を優先、なければ snapshot
    cur_rank = rh[0]["after_rank"] if rh else (f"{cur['rank']} ({cur['rank_meter']})" if cur else None)

    # --- 要サポート ---
    if st:
        if st["last_gap_days"] is not None and st["last_gap_days"] >= 3:
            flags.append(f"最終配信から {st['last_gap_days']} 日空いている（最後: {st['last_started']}）。離脱の兆候、声かけを")
        if st["recent7_active_days"] <= 2 and (st["last_gap_days"] or 0) >= 2:
            flags.append(f"直近7日の配信日数 {st['recent7_active_days']} 日と少ない。配信習慣の立て直しを")
        if st["ng_n"] >= 2:
            flags.append(f"5分未満で終了した支払対象外(NG)配信が {st['ng_n']} 件。開始即終了の癖を確認")
    else:
        flags.append("配信一覧データなし（詳細ページ未取得）")

    # ランク降格・メーターマイナス
    if rh:
        latest = rh[0]
        if latest["meter_delta"] is not None and latest["meter_delta"] < 0:
            flags.append(f"直近のランクメーターがマイナス({latest['meter_delta']})。降格圏の可能性")
        # before>after の降格を検出（A>B>C>D>E の順）
        order = "ESDCBA"  # ざっくり：左ほど下位（厳密な小ランクは無視）
        def tier(r):
            return order.find((r or "")[0]) if r else -1
        if tier(latest["after_rank"]) < tier(latest["before_rank"]):
            flags.append(f"ランク降格: {latest['before_rank']} → {latest['after_rank']}（{latest['change_date']}）")
    if cur and cur["agreed"] == 0:
        flags.append("運営同意が未取得（同意済みフラグ=NO）")

    # --- 伸び/推移 ---
    if rh:
        # 直近の上位入り日数（上位X%）
        top_days = [r for r in rh if "上位" in (r["reason"] or "")]
        up = sum((r["meter_delta"] or 0) for r in rh)
        trend.append(f"ランク変動履歴(直近{len(rh)}日): メーター累計 {'+' if up>=0 else ''}{up}、上位入り {len(top_days)}日")
        if rh[-1]["before_rank"] != rh[0]["after_rank"]:
            trend.append(f"  期間内ランク: {rh[-1]['before_rank']} → {rh[0]['after_rank']}")
    if st:
        trend.append(
            f"直近7日: {st['recent7_active_days']}日配信 / 計 {_fmt_min(st['recent7_min'])}"
            f" / 新規歓迎枠 {st['shinki_n']}件(最新{st['n']}枠中)"
        )
    if data["results"]:
        r0 = data["results"][0]
        trend.append(f"直近イベント入賞: {r0['event_name']} {r0['place']}({r0['status']})")

    # --- 次の目標 ---
    if data["entries_active"]:
        ev = data["entries_active"][0]
        goals.append(f"開催中イベント「{ev['event_name']}」に参加中 → 期間中の配信量・コア来場を最大化")
    if st and st["recent7_active_days"] <= 2:
        goals.append("まず継続配信の習慣化。固定枠を作り週の配信日数を増やす")
    elif st:
        goals.append("配信日数を維持しつつ、ランクメーターをプラス圏でキープ")
    if st and st["shinki_n"] == 0:
        goals.append("新規歓迎配信が直近に無い。新規流入の枠を意図的に作る")
    if data["fans"] >= 30:
        goals.append(f"常連 {data['fans']} 人の基盤あり。コアファンの来場頻度を落とさない接触を")

    return {"flags": flags, "trend": trend, "goals": goals, "cur": cur, "cur_rank": cur_rank, "st": st}


def render(data, res):
    liver = data["liver"]
    cur = res["cur"]
    name = liver["name"] if liver else "?"
    lines = [f"━━━ {name}  (user_id={liver['user_id']}) ━━━"]
    if liver["display_name"] and liver["display_name"] != name:
        lines.append(f"  表示名: {liver['display_name']}")

    # プロフィール／現状
    tenure = _days_since(liver["agency_since"]) or _days_since(liver["member_since"])
    prof = []
    if liver["level"] is not None:
        prof.append(f"Lv{liver['level']}")
    if liver["followers"] is not None:
        prof.append(f"フォロワー{liver['followers']}")
    if tenure is not None:
        prof.append(f"事務所歴{tenure}日")
    if liver["region"]:
        prof.append(liver["region"])
    if prof:
        lines.append("  " + " / ".join(prof))

    dia = data["dia"]
    diabal = f"  ダイヤ残高 {dia['diamonds']:,}" if dia and dia["diamonds"] is not None else ""
    lines.append(f"  現状: ランク {res['cur_rank']}{diabal}  今月オフ {len(data['offs_month'])}日")
    if cur:
        lines.append(
            f"        週ダイヤ {cur['diamonds_week']:,} / 月 {cur['diamonds_month']:,}"
            + (f"  同意済" if cur["agreed"] else "  ⚠未同意")
        )
    if data["fans"]:
        lines.append(f"        常連 {data['fans']} 人 / 収集コメント {data['comments']:,} 件（直近 {data['last_comment']}）")

    if res["flags"]:
        lines.append("  ◆要サポート:")
        lines += [f"    - {f}" for f in res["flags"]]
    else:
        lines.append("  ◆要サポート: 特になし（健全）")

    lines.append("  ◆伸び/推移:")
    lines += [f"    - {t}" for t in res["trend"]] or ["    - データ蓄積中"]

    lines.append("  ◆次の目標:")
    lines += [f"    - {g}" for g in res["goals"]]
    return "\n".join(lines)


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv[1:]
    query = args[0] if args else None

    conn = connect()
    if query and query.isdigit():
        ids = [int(query)]
    elif query:
        rows = conn.execute("SELECT user_id FROM livers WHERE name LIKE ? OR display_name LIKE ?",
                            (f"%{query}%", f"%{query}%")).fetchall()
        ids = [r["user_id"] for r in rows]
        if not ids:
            raise SystemExit(f"'{query}' に一致するライバーなし")
    else:
        ids = [r["user_id"] for r in conn.execute("SELECT user_id FROM livers ORDER BY user_id")]

    out = []
    for uid in ids:
        data = load_liver(conn, uid)
        res = analyze(data)
        if as_json:
            out.append({
                "user_id": uid, "name": data["liver"]["name"],
                "rank": res["cur_rank"], "flags": res["flags"],
                "trend": res["trend"], "goals": res["goals"],
                "streams": res["st"], "fans": data["fans"],
            })
        else:
            out.append(render(data, res))
    conn.close()
    print(json.dumps(out, ensure_ascii=False, indent=2) if as_json else "\n\n".join(out))


if __name__ == "__main__":
    main()
