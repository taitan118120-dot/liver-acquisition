"""PocoStudio コメント受け取りサーバー（ローカル専用）.

Tampermonkey ユーザースクリプトが配信中コメントをここにPOSTし、SQLiteに保存する。

起動:
    python3 comment_server.py            # http://127.0.0.1:5057
画面:
    /            … 取得済みコメント一覧（新しい順、ライバー絞り込み可）
    /export.csv  … CSVダウンロード
API:
    POST /api/comments  body=[{commenter, text, level?, liver?, client_ts?}, ...]
"""
import os
import sys

from flask import Flask, request, jsonify, Response, render_template_string

sys.path.insert(0, os.path.dirname(__file__))
from db import connect

app = Flask(__name__)
PORT = int(os.environ.get("PORT", "5057"))


@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
    return resp


@app.route("/api/comments", methods=["POST", "OPTIONS"])
def post_comments():
    if request.method == "OPTIONS":
        return ("", 204)
    items = request.get_json(force=True, silent=True) or []
    if isinstance(items, dict):
        items = [items]
    conn = connect()
    saved = 0
    for it in items:
        commenter = (it.get("commenter") or "").strip()
        text = (it.get("text") or "").strip()
        if not commenter or "*****" in commenter:
            continue
        liver = (it.get("liver") or "").strip()
        stream_id = (it.get("stream_id") or "").strip()
        level = (it.get("level") or "").strip()
        timing = (it.get("timing") or "").strip()
        posted_at = (it.get("posted_at") or "").strip()
        client_ts = (it.get("client_ts") or "").strip()
        source = (it.get("source") or ("history" if posted_at else "live")).strip()
        key = f"{liver}|{stream_id}|{commenter}|{text}|{posted_at or client_ts}"
        cur = conn.execute(
            """INSERT OR IGNORE INTO comments
                 (liver, stream_id, commenter, level, text, timing, posted_at,
                  client_ts, source, dedupe_key)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (liver, stream_id, commenter, level, text, timing, posted_at,
             client_ts, source, key),
        )
        saved += cur.rowcount
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "received": len(items), "saved": saved})


MONTHLY_COLS = [
    "user_id", "month", "final_rank", "max_rank",
    "total_dia", "time_dia", "hype_dia",
    "stream_min", "stream_days", "support_points",
    "comments", "comment_people", "likes", "like_people",
    "viewed_min", "listeners", "daily_best", "monthly_rank",
    "followers", "captured_at",
]


@app.route("/api/monthly", methods=["POST", "OPTIONS"])
def post_monthly():
    """月次レポート(/monthly_liver_report) を取り込む.
    body: 単体オブジェクト or 配列。extract_monthly.js / userscript と同じJSON形。"""
    if request.method == "OPTIONS":
        return ("", 204)
    items = request.get_json(force=True, silent=True) or []
    if isinstance(items, dict):
        items = [items]
    conn = connect()
    saved = 0
    for it in items:
        try:
            uid = int(it.get("user_id"))
        except (TypeError, ValueError):
            continue
        month = (it.get("month") or "").strip()
        if not month:
            continue
        values = [uid, month] + [it.get(c) for c in MONTHLY_COLS[2:]]
        placeholders = ",".join(["?"] * len(MONTHLY_COLS))
        update = ",".join(f"{c}=excluded.{c}" for c in MONTHLY_COLS if c not in ("user_id", "month"))
        conn.execute(
            f"INSERT INTO monthly_reports ({','.join(MONTHLY_COLS)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT(user_id, month) DO UPDATE SET {update}",
            values,
        )
        saved += 1
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "received": len(items), "saved": saved})


PAGE = """
<!doctype html><meta charset="utf-8">
<title>Pococha コメント</title>
<style>
 body{font-family:system-ui,-apple-system,sans-serif;margin:20px;background:#fafafa}
 h1{font-size:18px} table{border-collapse:collapse;width:100%;background:#fff}
 th,td{border:1px solid #e3e3e3;padding:6px 8px;font-size:13px;text-align:left}
 th{background:#f3f3f3} tr:nth-child(even){background:#fafafa}
 .meta{color:#888;font-size:12px} a.btn{display:inline-block;margin:8px 8px 8px 0;
   padding:6px 12px;background:#ff5b8a;color:#fff;border-radius:6px;text-decoration:none}
 form{margin:10px 0}
</style>
<h1>Pococha コメント取得 <span class="meta">({{total}}件)</span></h1>
<form method="get">
  ライバー:
  <select name="liver" onchange="this.form.submit()">
    <option value="">(すべて)</option>
    {% for l in livers %}<option value="{{l}}" {{'selected' if l==sel else ''}}>{{l}}</option>{% endfor %}
  </select>
</form>
<a class="btn" href="/export.csv{{ '?liver='+sel if sel else '' }}">CSVダウンロード</a>
<table>
 <tr><th>投稿時刻</th><th>ライバー</th><th>配信ID</th><th>コメントした人</th><th>コメント</th></tr>
 {% for r in rows %}
 <tr><td class="meta">{{r['posted_at'] or r['server_ts']}}</td><td>{{r['liver']}}</td>
     <td class="meta">{{r['stream_id']}}</td><td>{{r['commenter']}}</td><td>{{r['text']}}</td></tr>
 {% endfor %}
</table>
"""


@app.route("/")
def index():
    conn = connect()
    sel = request.args.get("liver", "")
    livers = [r[0] for r in conn.execute(
        "SELECT DISTINCT liver FROM comments WHERE liver<>'' ORDER BY liver").fetchall()]
    if sel:
        rows = conn.execute(
            "SELECT * FROM comments WHERE liver=? ORDER BY id DESC LIMIT 500", (sel,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM comments ORDER BY id DESC LIMIT 500").fetchall()
    total = conn.execute("SELECT count(*) FROM comments").fetchone()[0]
    conn.close()
    return render_template_string(PAGE, rows=rows, livers=livers, sel=sel, total=total)


@app.route("/export.csv")
def export_csv():
    import csv
    import io
    conn = connect()
    sel = request.args.get("liver", "")
    q = ("SELECT COALESCE(posted_at, server_ts), liver, stream_id, "
         "commenter, text, timing FROM comments")
    args = ()
    if sel:
        q += " WHERE liver=?"
        args = (sel,)
    q += " ORDER BY id"
    rows = conn.execute(q, args).fetchall()
    conn.close()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["投稿時刻", "ライバー", "配信ID", "コメントした人", "コメント", "配信内経過"])
    for r in rows:
        w.writerow([r[0], r[1], r[2], r[3], r[4], r[5]])
    return Response(buf.getvalue().encode("utf-8-sig"),
                    mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=comments.csv"})


if __name__ == "__main__":
    print(f"コメント受け取りサーバー起動: http://127.0.0.1:{PORT}")
    app.run(host="127.0.0.1", port=PORT, debug=False)
