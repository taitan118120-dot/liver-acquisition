"""TAITAN PRO X DM PWA バックエンド"""
import functools
import hmac
import json
import os
import sys
import threading
import time
from typing import Optional

from flask import Flask, g, jsonify, make_response, request, send_from_directory

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import x_api
from qualify import detect_target_type, personalize, qualify_profile

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# 旧: 単一共有パスワード。互換のため残す（owner ユーザの token として登録される）
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()
AUTH_COOKIE = "x_dm_auth"
PWA_PUBLIC_PATHS = {"/manifest.webmanifest", "/sw.js", "/icon-192.png", "/icon-512.png", "/login", "/login.html", "/logout"}

app = Flask(__name__, static_folder=None)
app.config["JSON_AS_ASCII"] = False


def _resolve_user(token: str):
    """cookie/header の token から user を解決。
    APP_PASSWORD と一致した場合は owner ユーザを seed して返す。"""
    if not token:
        return None
    user = db.get_user_by_token(token)
    if user and user.get("active"):
        return user
    if APP_PASSWORD and hmac.compare_digest(token, APP_PASSWORD):
        return db.ensure_owner_seeded(APP_PASSWORD)
    return None


def _auth_disabled():
    return not APP_PASSWORD and not db.has_any_users()


@app.before_request
def _require_auth():
    if request.method == "OPTIONS":
        return
    path = request.path

    # ローカル/LAN: APP_PASSWORD 未設定 & users 空 → auth 無効、owner 扱い
    if _auth_disabled():
        g.user = {"id": "local", "name": "ローカル", "role": "owner",
                  "daily_limit": 9999, "rate_per_lead": 0}
        return

    # Magic link: /?w=TOKEN または /w/TOKEN → リダイレクトせず index.html を直接返す
    w = request.args.get("w") if request.method == "GET" else None
    if not w and request.method == "GET" and path.startswith("/w/"):
        w = path[3:].split("/", 1)[0]
    if w:
        u = db.get_user_by_token(w)
        if u and u.get("active"):
            resp = make_response(send_from_directory(STATIC_DIR, "index.html"))
            resp.set_cookie(
                AUTH_COOKIE, w,
                max_age=60 * 60 * 24 * 365,
                secure=True, httponly=True, samesite="Lax", path="/",
            )
            g.user = u
            return resp

    if path in PWA_PUBLIC_PATHS:
        return

    token = request.cookies.get(AUTH_COOKIE) or request.headers.get("X-Auth-Token") or ""
    user = _resolve_user(token)
    if user:
        g.user = user
        return
    if path.startswith("/api/"):
        return jsonify({"error": "unauthorized"}), 401
    return send_from_directory(STATIC_DIR, "login.html"), 401


def require_owner(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        u = getattr(g, "user", None)
        if not u or u.get("role") != "owner":
            return jsonify({"error": "forbidden"}), 403
        return fn(*a, **kw)
    return wrapper


@app.post("/login")
def login():
    body = request.get_json(silent=True) or request.form or {}
    pw = (body.get("password") or "").strip()
    user = _resolve_user(pw)
    if not user:
        return jsonify({"error": "bad_password"}), 401
    resp = make_response(jsonify({"ok": True, "role": user["role"], "name": user["name"]}))
    resp.set_cookie(
        AUTH_COOKIE, pw,
        max_age=60 * 60 * 24 * 365,
        secure=True, httponly=True, samesite="Lax", path="/",
    )
    return resp


@app.post("/logout")
def logout():
    resp = make_response(jsonify({"ok": True}))
    resp.delete_cookie(AUTH_COOKIE, path="/")
    return resp


@app.get("/api/me")
def api_me():
    u = getattr(g, "user", None)
    if not u:
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({
        "id": u["id"], "name": u["name"], "role": u["role"],
        "daily_limit": u.get("daily_limit", 20),
        "rate_per_lead": u.get("rate_per_lead", 0),
    })

# 進行中リサーチの状態（単純な単一プロセス想定）
_research_state = {"running": False, "stage": "", "fetched": 0, "added": 0, "log": [], "error": None}
_research_lock = threading.Lock()


# ---------- 静的ファイル ----------
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(STATIC_DIR, path)


# ---------- API ----------
@app.get("/api/status")
def api_status():
    user = getattr(g, "user", None)
    return jsonify({
        "stats": db.stats(user=user),
        "research": _research_state if (user and user.get("role") == "owner") else {"running": _research_state["running"]},
    })


def _pick_template(templates_for_type, lead_id: str, fallback: str) -> tuple[str, int]:
    """templates_for_type は str / list[str] / 空 のいずれか。
    lead_id を seed にして deterministic に選択（同じリードは常に同じバリエーション）"""
    if isinstance(templates_for_type, list) and templates_for_type:
        idx = abs(hash(lead_id)) % len(templates_for_type)
        return templates_for_type[idx], idx
    if isinstance(templates_for_type, str) and templates_for_type:
        return templates_for_type, 0
    return fallback, 0


@app.get("/api/queue")
def api_queue():
    templates = db.get_setting("templates", {}) or {}
    fallback_template = db.get_setting("template", "") or ""
    leads = db.get_queue()
    # スキップ学習: 理由ごとに学習されたブロック語にヒットする候補を除外
    blocklist = db.get_skip_blocklist()
    # 全理由のブロック語を集約（理由は問わず、いずれかにヒットしたら除外）
    block_tokens: set[str] = set()
    for tokens_map in blocklist.values():
        block_tokens.update(tokens_map.keys())

    def _is_blocked(lead) -> bool:
        if not block_tokens:
            return False
        text = ((lead.get("username") or "") + " " + (lead.get("name") or "")).lower()
        return any(t in text for t in block_tokens)

    leads = [l for l in leads if not _is_blocked(l)]
    for lead in leads:
        name = lead.get("name") or lead["username"]
        ttype = lead.get("target_type") or "beginner"
        tpl, var_idx = _pick_template(templates.get(ttype), lead["id"], fallback_template)
        lead["message"] = personalize(tpl, name, lead["username"])
        lead["template_variation"] = var_idx
        # 全バリエーションを personalize して返す（UIで切替）
        type_tpls = templates.get(ttype)
        if isinstance(type_tpls, list) and type_tpls:
            lead["messages"] = [personalize(t, name, lead["username"]) for t in type_tpls]
        elif isinstance(type_tpls, str) and type_tpls:
            lead["messages"] = [personalize(type_tpls, name, lead["username"])]
        else:
            lead["messages"] = [lead["message"]]
        lead["profile_url"] = f"https://x.com/{lead['username']}"
        # iOS X(Twitter)アプリのスキーム: twitter://user?screen_name=<username>
        lead["app_url"] = f"twitter://user?screen_name={lead['username']}"
        lead["qualified_reasons"] = json.loads(lead.get("qualified_reasons") or "[]")
    return jsonify({"count": len(leads), "leads": leads})


@app.post("/api/leads/<lead_id>/mark-sent")
def api_mark_sent(lead_id):
    if not db.get_lead(lead_id):
        return jsonify({"error": "not_found"}), 404
    user = getattr(g, "user", None)
    # 1日上限チェック（worker のみ）
    if user and user.get("role") == "worker":
        s = db.stats(user=user)
        if s["remaining"] <= 0:
            return jsonify({"error": "daily_limit_reached", "stats": s}), 429
    db.mark_sent(lead_id, sent_by=(user or {}).get("id"))
    return jsonify({"ok": True, "stats": db.stats(user=user)})


@app.post("/api/leads/<lead_id>/skip")
def api_skip(lead_id):
    if not db.get_lead(lead_id):
        return jsonify({"error": "not_found"}), 404
    user = getattr(g, "user", None)
    reason = (request.json or {}).get("reason", "manual_skip")
    db.mark_skip(lead_id, reason)
    return jsonify({"ok": True, "stats": db.stats(user=user)})


@app.post("/api/leads/bulk-skip")
@require_owner
def api_bulk_skip():
    """target_type 等の条件で一括スキップ。学習データ化に使う。
    body: {target_type:str, reason:str, only_qualified:bool=True}"""
    body = request.json or {}
    ttype = body.get("target_type")
    reason = body.get("reason", "bulk_skip")
    only_qualified = body.get("only_qualified", True)
    if not ttype:
        return jsonify({"error": "target_type required"}), 400
    with db.get_conn() as conn:
        sql = "SELECT id FROM leads WHERE target_type=? AND status='未接触'"
        params = [ttype]
        if only_qualified:
            sql += " AND qualified=1"
        rows = conn.execute(sql, params).fetchall()
        ids = [r["id"] for r in rows]
        for lead_id in ids:
            db.mark_skip(lead_id, reason)
    return jsonify({"ok": True, "skipped": len(ids), "reason": reason})


@app.get("/api/settings")
@require_owner
def api_settings_get():
    return jsonify(db.all_settings())


@app.put("/api/settings")
@require_owner
def api_settings_put():
    body = request.json or {}
    for k, v in body.items():
        db.set_setting(k, v)
    return jsonify(db.all_settings())


@app.get("/api/skip-stats")
@require_owner
def api_skip_stats():
    """スキップ理由別の統計と学習されたブロック語"""
    return jsonify(db.get_skip_stats())


@app.get("/api/recent-sent")
def api_recent_sent():
    user = getattr(g, "user", None)
    sent_by = user["id"] if (user and user.get("role") == "worker") else None
    return jsonify({"leads": db.recent_sent(limit=30, sent_by=sent_by)})


@app.get("/api/recent-runs")
@require_owner
def api_recent_runs():
    return jsonify({"runs": db.recent_runs(limit=10)})


# ---------- ユーザ管理（owner 専用） ----------
def _user_public(u):
    """token も含めて返す（owner UI でリンク発行用）"""
    return {
        "id": u["id"], "name": u["name"], "role": u["role"],
        "daily_limit": u["daily_limit"], "rate_per_lead": u["rate_per_lead"],
        "active": bool(u["active"]), "auth_token": u["auth_token"],
        "created_at": u.get("created_at"),
    }


@app.get("/api/users")
@require_owner
def api_users_list():
    return jsonify({"users": [_user_public(u) for u in db.list_users()]})


@app.post("/api/users")
@require_owner
def api_users_create():
    body = request.json or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    role = body.get("role", "worker")
    if role not in ("worker", "owner"):
        return jsonify({"error": "invalid role"}), 400
    daily_limit = int(body.get("daily_limit", 20))
    rate_per_lead = int(body.get("rate_per_lead", 60))
    u = db.create_user(name=name, role=role, daily_limit=daily_limit, rate_per_lead=rate_per_lead)
    return jsonify({"user": _user_public(u)})


@app.put("/api/users/<user_id>")
@require_owner
def api_users_update(user_id):
    body = request.json or {}
    fields = {}
    for k in ("name", "daily_limit", "rate_per_lead", "active"):
        if k in body:
            fields[k] = body[k]
    if "active" in fields:
        fields["active"] = 1 if fields["active"] else 0
    u = db.update_user(user_id, **fields)
    if not u:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"user": _user_public(u)})


@app.post("/api/users/<user_id>/rotate-token")
@require_owner
def api_users_rotate(user_id):
    u = db.rotate_user_token(user_id)
    if not u:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"user": _user_public(u)})


@app.get("/api/stats/by-worker")
@require_owner
def api_stats_by_worker():
    return jsonify(db.stats_by_worker())


# ---------- リサーチ実行（バックグラウンド） ----------
def _run_research(query_specs: list[dict], max_candidates_per_query: int = 30):
    """query_specs: [{"query": "ライバー始めたい", "target_type": "beginner"}, ...]
    X API v2 (Bearer Token) で検索ツイート→投稿者抽出→qualify。
    Bearer 未設定時は XAuthError を握って終了する。"""
    with _research_lock:
        if _research_state["running"]:
            return
        _research_state.update({"running": True, "stage": "開始", "fetched": 0, "added": 0, "log": [], "error": None})

    run_id = db.log_research_start()
    cfg = db.all_settings()
    manual_bearer = (cfg.get("x_bearer_token") or "").strip()

    total_fetched = 0
    total_added = 0
    log = []

    try:
        # 1. 検索クエリから投稿者抽出（プロフィール情報も同時に取れる）
        all_candidates: dict[str, dict] = {}
        for spec in query_specs:
            query = spec["query"]
            ttype_hint = spec.get("target_type", "beginner")
            _research_state["stage"] = f"検索: {query}"
            try:
                users = x_api.fetch_search_users(
                    query, max_users=max_candidates_per_query, manual_bearer=manual_bearer
                )
                for u in users:
                    if u["username"] not in all_candidates:
                        all_candidates[u["username"]] = {
                            **u, "source_tag": query, "target_type_hint": ttype_hint
                        }
                log.append({"query": query, "type": ttype_hint, "found": len(users)})
                _research_state["log"] = log.copy()
            except x_api.XAuthError:
                raise
            except Exception as e:
                log.append({"query": query, "error": str(e)})
                _research_state["log"] = log.copy()
            time.sleep(1.0)  # X API rate limit に配慮

        # 2. 既存ユーザー除外 + 非公開アカ除外
        from db import get_conn
        with get_conn() as conn:
            existing = {r["username"] for r in conn.execute("SELECT username FROM leads").fetchall()}
        new_candidates = [c for c in all_candidates.values() if c["username"] not in existing]
        new_candidates = [c for c in new_candidates if not c.get("is_private")]

        _research_state["stage"] = f"{len(new_candidates)}件 qualify中"
        _research_state["log"] = log.copy()

        # 3. qualify（プロフィール情報は検索時に取得済み・追加API call不要）
        for i, cand in enumerate(new_candidates, 1):
            total_fetched += 1
            ttype = detect_target_type(cand)
            tag_hint = cand.get("target_type_hint")
            if ttype == "beginner" and tag_hint in ("agency", "existing_liver"):
                ttype = tag_hint
            passed, reasons = qualify_profile(cand, cfg, target_type=ttype)

            lead_id = "x_" + cand["username"].replace(".", "_").replace("-", "_")
            db.upsert_lead({
                "id": lead_id,
                "username": cand["username"],
                "name": cand.get("full_name") or cand["username"],
                "bio": (cand.get("biography") or "")[:500],
                "followers": cand.get("followers"),
                "following": cand.get("following"),
                "source_tag": cand.get("source_tag", ""),
                "target_type": ttype,
                "qualified": passed,
                "qualified_reasons": reasons,
                "notes": f"X検索:{cand.get('source_tag','')} 自動精査",
            })
            if passed:
                total_added += 1
            _research_state["fetched"] = total_fetched
            _research_state["added"] = total_added

        _research_state["stage"] = "完了"
        db.log_research_finish(run_id, total_fetched, total_added)

    except x_api.XAuthError as e:
        _research_state["error"] = f"認証エラー: {e}"
        _research_state["stage"] = "エラー"
        db.log_research_finish(run_id, total_fetched, total_added, error=str(e))
    except Exception as e:
        _research_state["error"] = str(e)
        _research_state["stage"] = "エラー"
        db.log_research_finish(run_id, total_fetched, total_added, error=str(e))
    finally:
        _research_state["running"] = False


@app.post("/api/requalify")
@require_owner
def api_requalify():
    """現在のDB内リード（status=未接触）を最新qualifyルールで再判定。
    既存 target_type を保持（NULL/空なら detect_target_type で再判定）"""
    cfg = db.all_settings()
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, username, name, bio, followers, following, target_type FROM leads WHERE status='未接触'"
        ).fetchall()
        changed = 0
        passed = 0
        for r in rows:
            profile = {
                "username": r["username"],
                "full_name": r["name"] or "",
                "biography": r["bio"] or "",
                "followers": r["followers"],
                "following": r["following"],
                "is_private": False,
                "is_verified": False,
                "is_business": False,
                "category": None,
            }
            # detect_target_type を強めにかけ直す: 既存値より強い種別なら採用
            # 強さ: agency > existing_liver > beginner
            current = r["target_type"] or "beginner"
            detected = detect_target_type(profile)
            rank = {"agency": 2, "existing_liver": 1, "beginner": 0}
            ttype = detected if rank.get(detected, 0) > rank.get(current, 0) else current
            if not profile["biography"] or len(profile["biography"]) < 5:
                fl, fw = profile.get("followers"), profile.get("following")
                # bio 未取得 → 数値が通っていれば「要目視」
                if ttype == "agency":
                    ok_numeric = fl is not None and fl >= 1
                elif ttype == "existing_liver":
                    max_fl = cfg.get("max_followers_existing", 1000)
                    ok_numeric = (fl is not None and fw is not None and 1 <= fl <= max_fl and 1 <= fw)
                else:  # beginner
                    ok_numeric = (fl is not None and fw is not None and 1 <= fl < 10000 and 1 <= fw and max(fl, fw)/min(fl, fw) <= 5)
                bad_name = any(k in profile.get("full_name", "") for k in (
                    "店", "ショップ", "shop", "official", "公式", "教室", "幼稚園", "保育園",
                    "ほいく", "ぴあのる", "ピアノ教室", "学校", "スタジオ", "サロン", "アトリエ",
                    "コワーキング", "事業所", "Boutique", "Atelier", "Studio"
                ))
                if ttype == "agency":
                    bad_name = False  # agency は店舗/事業所もOK
                if ok_numeric and not bad_name:
                    conn.execute(
                        "UPDATE leads SET qualified=?, qualified_reasons=?, target_type=? WHERE id=?",
                        (1, json.dumps(["bio未取得・要目視"], ensure_ascii=False), ttype, r["id"]),
                    )
                    passed += 1
                else:
                    reasons = []
                    if not ok_numeric:
                        reasons.append("数値NG")
                    if bad_name:
                        reasons.append("名前にbrand/教室")
                    conn.execute(
                        "UPDATE leads SET qualified=?, qualified_reasons=?, target_type=? WHERE id=?",
                        (0, json.dumps(reasons or ["bio情報不足"], ensure_ascii=False), ttype, r["id"]),
                    )
                changed += 1
                continue
            ok, reasons = qualify_profile(profile, cfg, target_type=ttype)
            conn.execute(
                "UPDATE leads SET qualified=?, qualified_reasons=?, target_type=? WHERE id=?",
                (1 if ok else 0, json.dumps(reasons, ensure_ascii=False), ttype, r["id"]),
            )
            if ok:
                passed += 1
            changed += 1
        conn.commit()
    return jsonify({"total": changed, "passed": passed})


@app.post("/api/ingest")
@require_owner
def api_ingest():
    """外部（Chrome MCP等）から取得したプロフィール情報を受け取りauto-qualify"""
    body = request.json or {}
    profiles = body.get("profiles") or []
    cfg = db.all_settings()
    added = 0
    updated = 0
    for p in profiles:
        username = p.get("u") or p.get("username")
        if not username:
            continue
        profile = {
            "username": username,
            "full_name": p.get("n") or p.get("full_name") or "",
            "biography": p.get("b") or p.get("biography") or "",
            "followers": p.get("fl") if "fl" in p else p.get("followers"),
            "following": p.get("fw") if "fw" in p else p.get("following"),
            "is_private": p.get("pv") or p.get("is_private", False),
            "is_verified": p.get("vf") or p.get("is_verified", False),
            "is_business": p.get("bz") or p.get("is_business", False),
            "category": p.get("c") or p.get("category"),
        }
        ttype = detect_target_type(profile)
        # 呼出側からヒントが渡れば優先（タグ由来の弱いヒント）
        hint = p.get("target_type_hint") or p.get("target_type")
        if ttype == "beginner" and hint in ("agency", "existing_liver"):
            ttype = hint
        passed, reasons = qualify_profile(profile, cfg, target_type=ttype)
        with db.get_conn() as conn:
            existing = conn.execute("SELECT id FROM leads WHERE username=?", (username,)).fetchone()
            if existing:
                conn.execute(
                    """UPDATE leads SET bio=?, followers=?, following=?, qualified=?, qualified_reasons=?, target_type=?
                       WHERE username=?""",
                    (profile["biography"][:500], profile["followers"], profile["following"],
                     1 if passed else 0, json.dumps(reasons, ensure_ascii=False), ttype, username),
                )
                updated += 1
            else:
                lead_id = "x_" + username.replace(".", "_").replace("-", "_")
                db.upsert_lead({
                    "id": lead_id, "username": username,
                    "name": profile["full_name"], "bio": profile["biography"][:500],
                    "followers": profile["followers"], "following": profile["following"],
                    "source_tag": p.get("tag", ""), "target_type": ttype,
                    "qualified": passed,
                    "qualified_reasons": reasons, "notes": "ingested",
                })
                added += 1
            conn.commit()
    return jsonify({"added": added, "updated": updated, "total": len(profiles)})


@app.after_request
def add_cors(resp):
    # 開発利便: 同一マシン内のCORS許可
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp


@app.route("/api/<path:_>", methods=["OPTIONS"])
def cors_preflight(_):
    return ("", 204)


@app.post("/api/research")
@require_owner
def api_research():
    """body.target_types で対象タイプを限定可（["beginner","existing_liver"] 等）。
    body.keywords で個別検索クエリ配列も受け付ける（target_type=beginner として扱う）。
    省略時は settings.keywords_by_type 全部から取得"""
    if _research_state["running"]:
        return jsonify({"error": "already_running", "state": _research_state}), 409
    cfg = db.all_settings()
    body = request.json or {}

    query_specs: list[dict] = []
    explicit_queries = body.get("keywords") or body.get("queries")
    if explicit_queries:
        forced_type = body.get("target_type", "beginner")
        query_specs = [{"query": q, "target_type": forced_type} for q in explicit_queries]
    else:
        target_types = body.get("target_types") or ["beginner", "agency", "existing_liver"]
        kbt = cfg.get("keywords_by_type") or {}
        for tt in target_types:
            for q in kbt.get(tt, []):
                query_specs.append({"query": q, "target_type": tt})

    if not query_specs:
        return jsonify({"error": "no_keywords"}), 400
    per_query = int(body.get("per_query", body.get("per_tag", 30)))
    t = threading.Thread(target=_run_research, args=(query_specs, per_query), daemon=True)
    t.start()
    return jsonify({"ok": True, "started": True, "query_specs": query_specs})


# ---------- 起動 ----------
db.init_db()  # gunicorn worker 起動時にも実行されるよう module レベルに


def main():
    port = int(os.environ.get("PORT", 5050))
    host = os.environ.get("HOST", "0.0.0.0")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
