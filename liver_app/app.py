"""TAITAN PRO IG DM PWA バックエンド"""
import functools
import hmac
import json
import os
import sys
import threading
import time
from typing import Optional

from flask import Flask, g, jsonify, make_response, redirect, request, send_from_directory

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import ig_api
from qualify import detect_target_type, personalize, qualify_profile

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# 強信頼タグ: bio に副業/代理店キーワードがなくても hint を信用して agency に分類
# 「代理店希望」「副業希望」等は明示的意図表明＝高シグナル (2026-04-30)
STRONG_AGENCY_TAGS = frozenset({
    # 2026-04-30 追加分
    "代理店希望", "代理店募集", "スカウト副業",
    "ライバースカウト", "業務委託募集", "業務委託希望",
    "副業希望", "副業始めたい", "副業探してます",
    "在宅副業", "週末副業", "ママ副業",
    "完全在宅ワーク", "業務委託ママ", "スマホ副業",
    # 2026-05-01 追加分: 副業バリエーション
    "副業ママ", "副業初心者",
    "すきま時間で副業", "子育てしながら副業",
    "主婦副業", "主婦の副業",
    # 2026-05-01 追加分: 在宅ワーク変種
    "在宅ワーク主婦", "在宅ワークママ",
    "家でできる副業", "おうちで稼ぐ", "おうちワーク",
    # 2026-05-01 追加分: 案件/スカウト
    "スカウト募集", "代理店探してます",
    "業務委託案件", "案件募集", "案件探してます",
    # 2026-05-01 追加分: ライバー憧れ層 (A2)
    "配信者になりたい", "ライブ配信始めたい",
    "ライバー目指す", "ライバーデビュー", "ライバー始めたい",
    "配信デビュー", "配信始めたい", "ライブ配信興味あり",
})

# 旧: 単一共有パスワード。互換のため残す（owner ユーザの token として登録される）
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()
AUTH_COOKIE = "liver_auth"
PWA_PUBLIC_PATHS = {"/manifest.webmanifest", "/sw.js", "/icon-192.png", "/icon-512.png", "/logo.jpg", "/login", "/login.html", "/logout"}

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
    # （LINE等の in-app browser はリダイレクト越しに Set-Cookie を保持しないことがあるため）
    # /w/TOKEN はパス形式。クエリと違ってLINE等のURL自動検出で末尾が落ちるリスクが少ない。
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


def _pick_template(templates_for_type, lead_id: str) -> tuple[str, int]:
    """templates_for_type は str / list[str] / 空 のいずれか。
    lead_id を seed にして deterministic に選択（同じリードは常に同じバリエーション）。
    Pythonの組み込み hash() はプロセスごとに seed が変わるため md5 を使う。
    空のときは DB ではなくコード側の現行デフォルト文言にフォールバックする
    （DBの単数形 template キーは 2026-08-02 に廃止）"""
    if isinstance(templates_for_type, list) and templates_for_type:
        import hashlib
        h = int(hashlib.md5(lead_id.encode("utf-8")).hexdigest()[:8], 16)
        idx = h % len(templates_for_type)
        return templates_for_type[idx], idx
    if isinstance(templates_for_type, str) and templates_for_type:
        return templates_for_type, 0
    return db.FALLBACK_TEMPLATE, 0


@app.get("/api/queue")
def api_queue():
    templates = db.get_setting("templates", {}) or {}
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
        tpl, var_idx = _pick_template(templates.get(ttype), lead["id"])
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
        lead["profile_url"] = f"https://www.instagram.com/{lead['username']}/"
        lead["app_url"] = f"instagram://user?username={lead['username']}"
        lead["qualified_reasons"] = json.loads(lead.get("qualified_reasons") or "[]")
    return jsonify({"count": len(leads), "leads": leads})


@app.post("/api/leads/<lead_id>/mark-sent")
def api_mark_sent(lead_id):
    if not db.get_lead(lead_id):
        return jsonify({"error": "not_found"}), 404
    user = getattr(g, "user", None)
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
def _run_research(tag_specs: list[dict], max_candidates_per_tag: int = 30, mode: str = "api"):
    """tag_specs: [{"tag": "渋谷カフェ", "target_type": "beginner"}, ...]
    mode: "api" = web_profile_info（bio取得可・rate limit対象）
          "html" = og:description scrape（bio無し・rate limit低リスク）"""
    with _research_lock:
        if _research_state["running"]:
            return
        _research_state.update({"running": True, "stage": "開始", "fetched": 0, "added": 0, "log": [], "error": None})

    run_id = db.log_research_start()
    cfg = db.all_settings()
    manual_cookie = cfg.get("ig_cookie_raw") or ""

    total_fetched = 0
    total_added = 0
    log = []

    try:
        # 1. タグからユーザー抽出
        all_candidates: dict[str, dict] = {}
        for spec in tag_specs:
            tag = spec["tag"]
            ttype_hint = spec.get("target_type", "beginner")
            _research_state["stage"] = f"#{tag} 取得中"
            try:
                users = ig_api.fetch_hashtag_users(tag, manual_cookie=manual_cookie)
                for u in users:
                    if u["username"] not in all_candidates:
                        all_candidates[u["username"]] = {**u, "source_tag": tag, "target_type_hint": ttype_hint}
                log.append({"tag": tag, "type": ttype_hint, "found": len(users)})
                _research_state["log"] = log.copy()
            except Exception as e:
                log.append({"tag": tag, "error": str(e)})
                _research_state["log"] = log.copy()
            time.sleep(0.8)

        # 2. 既存ユーザー除外
        from db import get_conn
        with get_conn() as conn:
            existing = {r["username"] for r in conn.execute("SELECT username FROM leads").fetchall()}
        new_candidates = [c for c in all_candidates.values() if c["username"] not in existing]
        # 非公開アカは即除外
        new_candidates = [c for c in new_candidates if not c.get("is_private")]
        new_candidates = new_candidates[: max_candidates_per_tag * len(tag_specs)]

        _research_state["stage"] = f"{len(new_candidates)}件 プロフィール取得中"
        _research_state["log"] = log.copy()

        # 3. 各プロフィール取得 + qualify
        html_failures = 0
        html_failure_reasons: list[str] = []
        effective_mode = mode
        for i, cand in enumerate(new_candidates, 1):
            _research_state["stage"] = f"{i}/{len(new_candidates)}件目 プロフィール取得 ({effective_mode})"
            try:
                if effective_mode == "html":
                    profile = ig_api.fetch_profile_html(cand["username"])
                    if not profile:
                        html_failures += 1
                        reason = ig_api._html_last_error.get("reason") or "unknown"
                        if len(html_failure_reasons) < 5:
                            html_failure_reasons.append(f"{cand['username']}:{reason}")
                        # 連続失敗が多ければ api モードへフォールバック（cookie必要）
                        if html_failures >= 5 and total_fetched == 0 and manual_cookie:
                            effective_mode = "api"
                            log.append({"fallback": "html→api", "reason": "html_5連続失敗", "samples": html_failure_reasons})
                            _research_state["log"] = log.copy()
                            try:
                                profile = ig_api.fetch_profile(cand["username"], manual_cookie=manual_cookie)
                            except Exception as e:
                                log.append({"username": cand["username"], "error": f"api_fallback:{e}"})
                                _research_state["log"] = log.copy()
                                continue
                else:
                    profile = ig_api.fetch_profile(cand["username"], manual_cookie=manual_cookie)
            except Exception as e:
                log.append({"username": cand["username"], "error": str(e)})
                _research_state["log"] = log.copy()
                continue
            if not profile:
                continue
            total_fetched += 1
            ttype = detect_target_type(profile)
            # tag-hint適用:
            # - existing_liver タグは17LIVE等プラットフォーム名→配信者率高いので hint OK
            # - 強信頼agency タグ（代理店希望/副業希望等）は明示意図→ hint OK
            # - 弱agencyタグ（推し活/カフェ経営等）は誤検知多いので detect=beginner なら維持
            tag_hint = cand.get("target_type_hint")
            source_tag = cand.get("source_tag", "")
            if ttype == "beginner":
                if tag_hint == "existing_liver":
                    ttype = "existing_liver"
                elif source_tag in STRONG_AGENCY_TAGS:
                    ttype = "agency"
            passed, reasons = qualify_profile(profile, cfg, target_type=ttype)

            lead_id = "ig_" + cand["username"].replace(".", "_").replace("-", "_")
            db.upsert_lead({
                "id": lead_id,
                "username": cand["username"],
                "name": profile.get("full_name") or cand.get("full_name") or cand["username"],
                "bio": (profile.get("biography") or "")[:500],
                "followers": profile.get("followers"),
                "following": profile.get("following"),
                "source_tag": cand.get("source_tag", ""),
                "target_type": ttype,
                "qualified": passed,
                "qualified_reasons": reasons,
                "notes": f"#{cand.get('source_tag','')} API自動精査",
            })
            if passed:
                total_added += 1
            _research_state["fetched"] = total_fetched
            _research_state["added"] = total_added
            time.sleep(0.4)

        if mode == "html" and html_failures > 0:
            log.append({
                "html_diagnostic": True,
                "failures": html_failures,
                "samples": html_failure_reasons,
                "fallback_used": effective_mode == "api",
            })
            _research_state["log"] = log.copy()
        _research_state["stage"] = "完了"
        db.log_research_finish(run_id, total_fetched, total_added)

    except ig_api.IGAuthError as e:
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
    # source_tag から existing_liver を復元（detect-onlyだとbio空のlivers消えるため）
    EL_TAGS = ('17LIVE','イチナナライブ','IRIAM','イリアム','ふわっち','BIGOLIVE',
               'ミクチャ','ツイキャス','SHOWROOM','ライブ配信','配信者','ライバーさんと繋がりたい')
    with db.get_conn() as conn:
        conn.execute(
            f"UPDATE leads SET target_type='existing_liver' WHERE source_tag IN ({','.join(['?']*len(EL_TAGS))}) AND target_type='beginner' AND status='未接触'",
            EL_TAGS,
        )
        # 強信頼 agency タグも source_tag から昇格
        sa_tags = tuple(STRONG_AGENCY_TAGS)
        conn.execute(
            f"UPDATE leads SET target_type='agency' WHERE source_tag IN ({','.join(['?']*len(sa_tags))}) AND target_type='beginner' AND status='未接触'",
            sa_tags,
        )
        conn.commit()
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, username, name, bio, followers, following, post_count, target_type, source_tag FROM leads WHERE status='未接触'"
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
                "post_count": r["post_count"],
                "is_private": False,
                "is_verified": False,
                "is_business": False,
                "category": None,
            }
            # 種別ラベルの再判定:
            # - detect が agency / existing_liver を返せばそれを採用（強い証拠）
            # - detect=beginner で既存ラベルが existing_liver なら維持（17LIVE等のtag-hintは信頼OK）
            # - detect=beginner で既存ラベルが agency ならタグフォース由来→ beginner にデモート（誤検知多い）
            current = r["target_type"]
            src_tag = r["source_tag"] or ""
            detected = detect_target_type(profile)
            if detected in ("agency", "existing_liver"):
                ttype = detected
            elif current == "existing_liver":
                ttype = "existing_liver"
            elif src_tag in STRONG_AGENCY_TAGS:
                ttype = "agency"
            else:
                ttype = "beginner"
            if not profile["biography"] or len(profile["biography"]) < 5:
                # bio 未取得 → 名前/username ベースの NG だけ先に弾く
                from qualify import (
                    _guess_foreign, NAIL_SALON_RE, ESTABLISHED_AGENCY_RE, FOREIGN_PERSON_RE,
                    BEAUTY_PRO_RE, NAME_BUSINESS_RE,
                    _is_pet_account, _is_food_guide,
                )
                _fn = profile.get("full_name", "") or ""
                _un = profile.get("username", "") or ""
                _name_text = _fn + " " + _un
                name_ng_reason = None
                if _guess_foreign("", _fn) or FOREIGN_PERSON_RE.search(_fn):
                    name_ng_reason = "外国籍疑い（bio未取得）"
                elif NAIL_SALON_RE.search(_name_text):
                    name_ng_reason = "ネイル系（bio未取得）"
                elif BEAUTY_PRO_RE.search(_name_text):
                    name_ng_reason = "美容師系（bio未取得）"
                elif ESTABLISHED_AGENCY_RE.search(_name_text):
                    name_ng_reason = "既存代理店疑い（bio未取得）"
                elif _is_pet_account(profile):
                    name_ng_reason = "ペット/犬猫アカ（bio未取得）"
                elif _is_food_guide(profile):
                    name_ng_reason = "グルメ/カフェ紹介アカ（bio未取得）"
                elif ttype == "beginner" and NAME_BUSINESS_RE.search(_fn):
                    name_ng_reason = "事業者肩書（bio未取得）"
                if name_ng_reason:
                    conn.execute(
                        "UPDATE leads SET qualified=0, qualified_reasons=?, target_type=? WHERE id=?",
                        (json.dumps([name_ng_reason], ensure_ascii=False), ttype, r["id"]),
                    )
                    changed += 1
                    continue
                # bio 空でも fl/fw があれば数値ベースで qualify（overnight_enrich が後で bio を補完）
                ok, reasons = qualify_profile(profile, cfg, target_type=ttype)
                conn.execute(
                    "UPDATE leads SET qualified=?, qualified_reasons=?, target_type=? WHERE id=?",
                    (1 if ok else 0, json.dumps(reasons, ensure_ascii=False), ttype, r["id"]),
                )
                if ok:
                    passed += 1
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
            "post_count": p.get("pc") if "pc" in p else p.get("post_count"),
            "is_private": p.get("pv") or p.get("is_private", False),
            "is_verified": p.get("vf") or p.get("is_verified", False),
            "is_business": p.get("bz") or p.get("is_business", False),
            "category": p.get("c") or p.get("category"),
        }
        ttype = detect_target_type(profile)
        # ingest 経由も同じ方針:
        # - existing_liver hint 信頼
        # - 強信頼agencyタグ（代理店希望/副業希望等）も信頼
        # - 弱agencyタグ（推し活等）は detect 結果優先（誤検知多）
        hint = p.get("target_type_hint") or p.get("target_type")
        tag = p.get("tag", "")
        if ttype == "beginner":
            if hint == "existing_liver":
                ttype = "existing_liver"
            elif tag in STRONG_AGENCY_TAGS:
                ttype = "agency"
        passed, reasons = qualify_profile(profile, cfg, target_type=ttype)
        with db.get_conn() as conn:
            existing = conn.execute("SELECT id FROM leads WHERE username=?", (username,)).fetchone()
            if existing:
                conn.execute(
                    """UPDATE leads SET bio=?, followers=?, following=?, post_count=?,
                               qualified=?, qualified_reasons=?, target_type=?
                       WHERE username=?""",
                    (profile["biography"][:500], profile["followers"], profile["following"],
                     profile.get("post_count"),
                     1 if passed else 0, json.dumps(reasons, ensure_ascii=False), ttype, username),
                )
                updated += 1
            else:
                lead_id = "ig_" + username.replace(".", "_").replace("-", "_")
                db.upsert_lead({
                    "id": lead_id, "username": username,
                    "name": profile["full_name"], "bio": profile["biography"][:500],
                    "followers": profile["followers"], "following": profile["following"],
                    "post_count": profile.get("post_count"),
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


def _run_research_from_accounts(account_specs: list[dict], max_per_account: int = 100,
                                source_kind: str = "followers"):
    """account_specs: [{"username": "competitor_ig", "target_type": "existing_liver"}, ...]
    source_kind: "followers" | "likers"
    取得した候補を upsert_lead → qualify する流れは hashtag版と共通。"""
    with _research_lock:
        if _research_state["running"]:
            return
        _research_state.update({"running": True, "stage": "開始", "fetched": 0, "added": 0, "log": [], "error": None})

    run_id = db.log_research_start()
    cfg = db.all_settings()
    manual_cookie = cfg.get("ig_cookie_raw") or ""
    total_fetched = 0
    total_added = 0
    log = []

    try:
        all_candidates: dict[str, dict] = {}
        for spec in account_specs:
            tgt = spec["username"].lstrip("@").strip()
            if not tgt:
                continue
            ttype_hint = spec.get("target_type", "beginner")
            label = f"@{tgt} ({source_kind})"
            _research_state["stage"] = f"{label} 取得中"
            try:
                if source_kind == "likers":
                    users = ig_api.fetch_likers(tgt, max_count=max_per_account, manual_cookie=manual_cookie)
                else:
                    users = ig_api.fetch_followers(tgt, max_count=max_per_account, manual_cookie=manual_cookie)
                for u in users:
                    if u["username"] not in all_candidates:
                        all_candidates[u["username"]] = {
                            **u,
                            "source_tag": f"{source_kind}:{tgt}",
                            "target_type_hint": ttype_hint,
                        }
                log.append({"account": tgt, "source": source_kind, "type": ttype_hint, "found": len(users)})
                _research_state["log"] = log.copy()
            except Exception as e:
                log.append({"account": tgt, "source": source_kind, "error": str(e)})
                _research_state["log"] = log.copy()
            time.sleep(1.0)

        from db import get_conn
        with get_conn() as conn:
            existing = {r["username"] for r in conn.execute("SELECT username FROM leads").fetchall()}
        new_candidates = [c for c in all_candidates.values() if c["username"] not in existing]
        new_candidates = [c for c in new_candidates if not c.get("is_private")]

        _research_state["stage"] = f"{len(new_candidates)}件 プロフィール取得中"
        _research_state["log"] = log.copy()

        for i, cand in enumerate(new_candidates, 1):
            _research_state["stage"] = f"{i}/{len(new_candidates)}件目 プロフィール取得"
            try:
                profile = ig_api.fetch_profile(cand["username"], manual_cookie=manual_cookie)
            except Exception as e:
                log.append({"username": cand["username"], "error": str(e)})
                _research_state["log"] = log.copy()
                continue
            if not profile:
                continue
            total_fetched += 1
            ttype = detect_target_type(profile)
            tag_hint = cand.get("target_type_hint")
            if ttype == "beginner" and tag_hint == "existing_liver":
                ttype = "existing_liver"
            passed, reasons = qualify_profile(profile, cfg, target_type=ttype)

            lead_id = "ig_" + cand["username"].replace(".", "_").replace("-", "_")
            db.upsert_lead({
                "id": lead_id,
                "username": cand["username"],
                "name": profile.get("full_name") or cand.get("full_name") or cand["username"],
                "bio": (profile.get("biography") or "")[:500],
                "followers": profile.get("followers"),
                "following": profile.get("following"),
                "source_tag": cand.get("source_tag", ""),
                "target_type": ttype,
                "qualified": passed,
                "qualified_reasons": reasons,
                "notes": f"{cand.get('source_tag','')} 自動精査",
            })
            if passed:
                total_added += 1
            _research_state["fetched"] = total_fetched
            _research_state["added"] = total_added
            time.sleep(0.4)

        _research_state["stage"] = "完了"
        db.log_research_finish(run_id, total_fetched, total_added)
    except ig_api.IGAuthError as e:
        _research_state["error"] = f"認証エラー: {e}"
        _research_state["stage"] = "エラー"
        db.log_research_finish(run_id, total_fetched, total_added, error=str(e))
    except Exception as e:
        _research_state["error"] = str(e)
        _research_state["stage"] = "エラー"
        db.log_research_finish(run_id, total_fetched, total_added, error=str(e))
    finally:
        _research_state["running"] = False


@app.post("/api/research")
@require_owner
def api_research():
    """body.target_types で対象タイプを限定可（["beginner","existing_liver"] 等）。
    body.hashtags で従来通りタグ配列も受け付ける（target_type=beginner として扱う）。
    省略時は settings.hashtags_by_type 全部から取得"""
    if _research_state["running"]:
        return jsonify({"error": "already_running", "state": _research_state}), 409
    cfg = db.all_settings()
    body = request.json or {}

    tag_specs: list[dict] = []
    explicit_tags = body.get("hashtags")
    if explicit_tags:
        forced_type = body.get("target_type", "beginner")
        tag_specs = [{"tag": t, "target_type": forced_type} for t in explicit_tags]
    else:
        target_types = body.get("target_types") or ["beginner", "agency", "existing_liver"]
        hbt = cfg.get("hashtags_by_type") or {}
        for tt in target_types:
            for tag in hbt.get(tt, []):
                tag_specs.append({"tag": tag, "target_type": tt})

    if not tag_specs:
        return jsonify({"error": "no_hashtags"}), 400
    per_tag = int(body.get("per_tag", 30))
    mode = body.get("mode", "api")  # "api" | "html"
    t = threading.Thread(target=_run_research, args=(tag_specs, per_tag, mode), daemon=True)
    t.start()
    return jsonify({"ok": True, "started": True, "tag_specs": tag_specs, "mode": mode})


@app.post("/api/research-account")
@require_owner
def api_research_account():
    """body.accounts: ["@user1","user2"], body.source: "followers"|"likers",
    body.target_type: "beginner"|"existing_liver"|"agency", body.per_account: int"""
    if _research_state["running"]:
        return jsonify({"error": "already_running", "state": _research_state}), 409
    body = request.json or {}
    accounts = [a.lstrip("@").strip() for a in (body.get("accounts") or []) if a and a.strip()]
    if not accounts:
        return jsonify({"error": "no_accounts"}), 400
    source = body.get("source", "followers")
    if source not in ("followers", "likers"):
        return jsonify({"error": "invalid_source"}), 400
    target_type = body.get("target_type", "existing_liver")
    if target_type not in ("beginner", "existing_liver", "agency"):
        return jsonify({"error": "invalid_target_type"}), 400
    per_account = max(10, min(int(body.get("per_account", 100)), 500))
    account_specs = [{"username": a, "target_type": target_type} for a in accounts]
    t = threading.Thread(target=_run_research_from_accounts,
                         args=(account_specs, per_account, source), daemon=True)
    t.start()
    return jsonify({"ok": True, "started": True, "accounts": accounts,
                    "source": source, "target_type": target_type, "per_account": per_account})


# ---------- 起動 ----------
db.init_db()  # gunicorn worker 起動時にも実行されるよう module レベルに


def main():
    port = int(os.environ.get("PORT", 5050))
    host = os.environ.get("HOST", "0.0.0.0")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
