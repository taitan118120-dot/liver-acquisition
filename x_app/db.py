"""SQLite DB管理 (X版): leadsテーブルとsettingsテーブル"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.environ.get(
    "X_APP_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.sqlite"),
)

# ============================================================
# DM テンプレート（X版）
# - X DM は最大10000字だが、長すぎは敬遠されるので IG と同等の長さに維持
# - {name} {username} 置換可
# ============================================================
_DEFAULT_BEGINNER_TEMPLATE = (
    "✨スマホ1台で月10万円超のライバー育成中✨\n"
    "TAITAN PROのたいたんと申します！\n\n"
    "投稿拝見してご連絡しました🙏\n"
    "未経験〜経験者まで、毎月20〜30名のライバーを育成しているライバー事務所です。\n\n"
    "🎁所属メリット🎁\n"
    "・専属マネージャーが1on1で配信戦略コンサル\n"
    "・未経験でも稼げる「初動加速プログラム」完備\n"
    "・大型イベント時のリスナー集客サポート\n"
    "・案件・コラボ配信の優先紹介\n\n"
    "📱スマホ1台でOK／全国どこでも所属可能\n"
    "📝所属費用は一切かかりません\n\n"
    "「ちょっと気になるかも…」と思っていただけたら、\n"
    "『興味あり』とだけご返信ください♪\n"
    "詳細を即お送りします！\n\n"
    "→ https://taitan-pro-lp.netlify.app/#apply"
)

_DEFAULT_AGENCY_TEMPLATE_SIDEJOB = (
    "✨副業/独立志向の方へ：ライバースカウト事業のご紹介✨\n"
    "TAITAN PROのたいたんと申します！\n\n"
    "副業・独立に興味あるとのこと、ご連絡しました🙏\n"
    "SNSで集客できる方なら相性◎の事業をご紹介しています。\n\n"
    "🎯1人スカウトで月3〜10万の継続収益（既存スキルそのまま活かせる）\n"
    "🎯完全在宅・スマホ完結\n"
    "🎯弊社が育成サポート全部代行（手間ゼロ）\n"
    "🎯初期費用なし／低リスクで始められる\n\n"
    "「興味あり」とご返信いただければ詳細お送りします💌\n\n"
    "→ https://taitan-pro-lp.netlify.app/#apply"
)

_DEFAULT_AGENCY_TEMPLATE_OWNER = (
    "✨経営者さま向け：追加収益のご紹介✨\n"
    "TAITAN PROのたいたんと申します！\n\n"
    "ご自身でも事業されてるとのこと、頑張られてて尊敬です🙏\n"
    "既存事業の追加収益として、ライバースカウト事業のご紹介です。\n\n"
    "🎯既存スタッフ・お客様をライバー化→月10万〜の副収入\n"
    "🎯店舗/事業の集客にもなる（SNS流入）\n"
    "🎯弊社が育成・配信ノウハウ全部代行（手間ゼロ）\n"
    "🎯既存事業との相性◎・初期費用なし\n\n"
    "「興味あり」とご返信いただければ詳細お送りします💌\n\n"
    "→ https://taitan-pro-lp.netlify.app/#apply"
)

_DEFAULT_AGENCY_TEMPLATE_LIVER_FAN = (
    "✨ライバー興味ある方へ：別ルートのご紹介✨\n"
    "TAITAN PROのたいたんと申します！\n\n"
    "ライバー興味あるとのこと、ご連絡しました🙏\n"
    "実は「ライバーをスカウトする側」も参入しやすい副業で\n\n"
    "🎯顔出しせず月3〜10万の継続収益\n"
    "🎯既にライバーやってる方の中継役として\n"
    "🎯弊社サポートで未経験でも初月から成果\n"
    "🎯ご自身がライバーになるルートもサポート可能\n\n"
    "「興味あり」とご返信いただければ詳細お送りします💌\n\n"
    "→ https://taitan-pro-lp.netlify.app/#apply"
)

_DEFAULT_EXISTING_LIVER_TEMPLATE = (
    "✨他事務所からの移籍/個人勢の所属サポート✨\n"
    "TAITAN PROのたいたんと申します！\n\n"
    "配信されているのを拝見してご連絡しました🙏\n"
    "未経験〜経験者まで幅広くサポートしている、毎月20〜30名所属のライバー事務所です。\n\n"
    "🎁所属メリット🎁\n"
    "・イベント時のリスナーブースト・集客支援\n"
    "・専属マネージャーによる配信戦略コンサル\n"
    "・案件・コラボ配信の優先紹介\n"
    "・他事務所の縛りや待遇でお悩みの方の相談もOK\n\n"
    "📱現プラットフォーム継続OK\n"
    "📝所属費用は一切かかりません\n\n"
    "「ちょっと話聞いてみたい」と思っていただけたら、\n"
    "『興味あり』とだけご返信ください♪\n"
    "具体的な所属条件をすぐにお送りします！\n\n"
    "→ https://taitan-pro-lp.netlify.app/#apply"
)

_DEFAULT_EXISTING_LIVER_TEMPLATE_2 = (
    "✨ポコチャ以外のライバーさん向け 特別キャンペーンのご案内✨\n"
    "ライバー事務所TAITAN PROのたいたんと申します！\n\n"
    "配信されているのを拝見してご連絡しました🙏\n"
    "現在ご活動中のライバーさん向けに、収益アップをサポートする\n"
    "【特別マネジメントプラン】をご案内しています。\n\n"
    "🎁プランの内容🎁\n"
    "✨ 達成条件に応じて時給上乗せ報酬（最大5,000円/h）\n"
    "✨ 過去には90日で月収100万円超を達成したライバーも在籍\n"
    "✨ いま活動中のアプリと並行配信OK\n"
    "✨ 案件・コラボ配信の優先紹介\n\n"
    "📱現プラットフォーム継続OK／全国どこでも所属可能\n"
    "📝所属費用は一切かかりません\n\n"
    "少しでも「気になる」「話だけ聞いてみたい」でも大歓迎です！\n"
    "『興味あり』とだけご返信ください🙏\n"
    "詳細をすぐにお送りします。\n\n"
    "→ https://taitan-pro-lp.netlify.app/#apply"
)

# ============================================================
# 検索キーワード プリセット（X用）
# X はタグより本文キーワード検索が主流。 `lang:ja -is:retweet -is:reply` は x_api 側で付与
# ============================================================
_DEFAULT_KEYWORDS_BEGINNER = [
    "ライブ配信 興味", "配信者になりたい", "ライバー始めたい", "ライバーやってみたい",
    "副業 ライブ配信", "在宅 ライブ配信",
    "在宅ワーク 始めたい", "スマホで稼ぎたい", "副業 月10万",
    "シフト終わり", "派遣 辞めたい", "OL 疲れた", "アルバイト 辞めたい",
    "コミュ症 在宅", "人見知り 在宅",
]

_DEFAULT_KEYWORDS_EXISTING_LIVER = [
    "17LIVE 配信", "イチナナ ライバー", "IRIAM 配信", "イリアム ライバー",
    "ふわっち 配信", "BIGO LIVE", "ミクチャ 配信", "ツイキャス 配信",
    "SHOWROOM 配信", "個人勢 ライバー", "事務所移籍 ライバー",
    "ライバーさんと繋がりたい", "配信者と繋がりたい",
]

_DEFAULT_KEYWORDS_AGENCY = [
    "副業 始めたい", "副業 興味あり", "ストック収入", "脱サラ したい",
    "起業 準備中", "フリーランス 駆け出し", "営業職 副業",
    "経営者 副業", "オーナー 追加収益",
    "ライバーになりたい", "配信 憧れ",
]

DEFAULT_SETTINGS = {
    # 旧key（互換維持・実体は templates / keywords_by_type）
    "keywords": _DEFAULT_KEYWORDS_BEGINNER,
    "template": _DEFAULT_BEGINNER_TEMPLATE,
    "templates": {
        "beginner": [_DEFAULT_BEGINNER_TEMPLATE],
        "agency": [
            _DEFAULT_AGENCY_TEMPLATE_SIDEJOB,
            _DEFAULT_AGENCY_TEMPLATE_OWNER,
            _DEFAULT_AGENCY_TEMPLATE_LIVER_FAN,
        ],
        "existing_liver": [_DEFAULT_EXISTING_LIVER_TEMPLATE, _DEFAULT_EXISTING_LIVER_TEMPLATE_2],
    },
    "keywords_by_type": {
        "beginner": _DEFAULT_KEYWORDS_BEGINNER,
        "agency": _DEFAULT_KEYWORDS_AGENCY,
        "existing_liver": _DEFAULT_KEYWORDS_EXISTING_LIVER,
    },
    "max_followers": 10000,
    "max_followers_existing": 5000,
    "max_followers_agency": 30000,
    "min_followers": 1,
    "max_ratio": 5.0,
    "daily_limit": 20,
    "age_min": 18,
    "age_max": 40,
    "x_bearer_token": "",  # 環境変数 TWITTER_BEARER_TOKEN が優先。手動上書き用
}


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                name TEXT,
                bio TEXT,
                followers INTEGER,
                following INTEGER,
                source_tag TEXT,
                target_type TEXT DEFAULT 'beginner',
                status TEXT DEFAULT '未接触',
                qualified INTEGER DEFAULT 0,
                qualified_reasons TEXT DEFAULT '[]',
                auto_qualified INTEGER DEFAULT 1,
                found_date TEXT,
                dm_sent_date TEXT,
                notes TEXT DEFAULT '',
                skip_reason TEXT DEFAULT '',
                sent_by TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
            CREATE INDEX IF NOT EXISTS idx_leads_qualified ON leads(qualified);

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS research_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT,
                finished_at TEXT,
                candidates_fetched INTEGER DEFAULT 0,
                qualified_added INTEGER DEFAULT 0,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'worker',
                auth_token TEXT UNIQUE NOT NULL,
                daily_limit INTEGER DEFAULT 20,
                rate_per_lead INTEGER DEFAULT 60,
                active INTEGER DEFAULT 1,
                created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_users_token ON users(auth_token);
            """
        )
        try:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(leads)").fetchall()]
            if "skip_reason" not in cols:
                conn.execute("ALTER TABLE leads ADD COLUMN skip_reason TEXT DEFAULT ''")
            if "sent_by" not in cols:
                conn.execute("ALTER TABLE leads ADD COLUMN sent_by TEXT")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_sent_by ON leads(sent_by)")
        except Exception:
            pass
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (k, json.dumps(v, ensure_ascii=False)),
            )
        try:
            tpl_row = conn.execute("SELECT value FROM settings WHERE key='templates'").fetchone()
            if tpl_row:
                templates = json.loads(tpl_row["value"])
                if isinstance(templates, dict):
                    changed = False
                    for k in list(templates.keys()):
                        v = templates[k]
                        if isinstance(v, str):
                            templates[k] = [v] if v else []
                            changed = True
                        elif not isinstance(v, list):
                            templates[k] = []
                            changed = True
                    if changed:
                        conn.execute(
                            "UPDATE settings SET value=? WHERE key='templates'",
                            (json.dumps(templates, ensure_ascii=False),),
                        )
        except Exception:
            pass
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_setting(key, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])


def set_setting(key, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        conn.commit()


def all_settings():
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: json.loads(r["value"]) for r in rows}


def upsert_lead(lead):
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, status FROM leads WHERE username = ?", (lead["username"],)
        ).fetchone()
        if existing:
            return existing["id"], False
        conn.execute(
            """
            INSERT INTO leads (id, username, name, bio, followers, following,
                               source_tag, target_type, status, qualified,
                               qualified_reasons, auto_qualified, found_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '未接触', ?, ?, 1, ?, ?)
            """,
            (
                lead["id"],
                lead["username"],
                lead.get("name", ""),
                lead.get("bio", ""),
                lead.get("followers"),
                lead.get("following"),
                lead.get("source_tag", ""),
                lead.get("target_type", "beginner"),
                1 if lead.get("qualified") else 0,
                json.dumps(lead.get("qualified_reasons", []), ensure_ascii=False),
                datetime.now().strftime("%Y-%m-%d"),
                lead.get("notes", ""),
            ),
        )
        conn.commit()
    return lead["id"], True


def update_lead_target_type(lead_id, target_type):
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET target_type=? WHERE id=?", (target_type, lead_id)
        )
        conn.commit()


def get_queue():
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM leads
            WHERE status = '未接触' AND qualified = 1 AND (dm_sent_date IS NULL OR dm_sent_date = '')
            ORDER BY found_date DESC, id ASC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_lead(lead_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return dict(row) if row else None


def mark_sent(lead_id, sent_by=None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET status = 'DM送信済', dm_sent_date = ?, sent_by = ? WHERE id = ?",
            (datetime.now().strftime("%Y-%m-%d"), sent_by, lead_id),
        )
        conn.commit()


# ---------- users ----------
def _gen_token() -> str:
    """LINE等のURL自動リンク化で末尾が切れるのを防ぐため、末尾に -/_ を含めない。"""
    import secrets
    while True:
        t = secrets.token_urlsafe(18)
        if t[-1] not in "-_":
            return t


def create_user(name, role="worker", daily_limit=20, rate_per_lead=60):
    import secrets
    token = _gen_token()
    user_id = f"u_{secrets.token_hex(4)}"
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO users(id, name, role, auth_token, daily_limit, rate_per_lead, active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
            (user_id, name, role, token, daily_limit, rate_per_lead,
             datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    return get_user(user_id)


def get_user(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_token(token):
    if not token:
        return None
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE auth_token = ?", (token,)).fetchone()
    return dict(row) if row else None


def list_users(include_inactive=True):
    with get_conn() as conn:
        if include_inactive:
            rows = conn.execute("SELECT * FROM users ORDER BY role DESC, created_at ASC").fetchall()
        else:
            rows = conn.execute("SELECT * FROM users WHERE active = 1 ORDER BY role DESC, created_at ASC").fetchall()
    return [dict(r) for r in rows]


def update_user(user_id, **fields):
    allowed = {"name", "daily_limit", "rate_per_lead", "active"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return get_user(user_id)
    cols = ", ".join(f"{k}=?" for k in sets)
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET {cols} WHERE id=?", (*sets.values(), user_id))
        conn.commit()
    return get_user(user_id)


def rotate_user_token(user_id):
    token = _gen_token()
    with get_conn() as conn:
        conn.execute("UPDATE users SET auth_token=? WHERE id=?", (token, user_id))
        conn.commit()
    return get_user(user_id)


def has_any_users():
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    return row["c"] > 0


def ensure_owner_seeded(token):
    """APP_PASSWORD を auth_token に持つ owner ユーザがいなければ作成。冪等。"""
    if not token:
        return None
    u = get_user_by_token(token)
    if u:
        return u
    user_id = "u_owner"
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if existing:
            conn.execute("UPDATE users SET auth_token=?, active=1 WHERE id=?", (token, user_id))
        else:
            conn.execute(
                """INSERT INTO users(id, name, role, auth_token, daily_limit, rate_per_lead, active, created_at)
                   VALUES (?, ?, 'owner', ?, 9999, 0, 1, ?)""",
                (user_id, "オーナー", token, datetime.now().isoformat(timespec="seconds")),
            )
        conn.commit()
    return get_user(user_id)


def stats_for_user(user_id):
    """指定ユーザの送信統計（本日 / 今月 / 累計）"""
    today = datetime.now().strftime("%Y-%m-%d")
    month_prefix = datetime.now().strftime("%Y-%m")
    with get_conn() as conn:
        today_c = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE sent_by=? AND dm_sent_date=?",
            (user_id, today),
        ).fetchone()["c"]
        month_c = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE sent_by=? AND dm_sent_date LIKE ?",
            (user_id, month_prefix + "%"),
        ).fetchone()["c"]
        total_c = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE sent_by=? AND status='DM送信済'",
            (user_id,),
        ).fetchone()["c"]
    return {"sent_today": today_c, "sent_month": month_c, "sent_total": total_c}


def stats_by_worker():
    """全 worker の送信統計（owner ダッシュボード用）"""
    today = datetime.now().strftime("%Y-%m-%d")
    month_prefix = datetime.now().strftime("%Y-%m")
    out = []
    for u in list_users():
        s = stats_for_user(u["id"])
        s.update({
            "id": u["id"],
            "name": u["name"],
            "role": u["role"],
            "active": u["active"],
            "daily_limit": u["daily_limit"],
            "rate_per_lead": u["rate_per_lead"],
            "payout_month": s["sent_month"] * (u["rate_per_lead"] or 0),
            "payout_total": s["sent_total"] * (u["rate_per_lead"] or 0),
            "auth_token": u["auth_token"],
            "created_at": u.get("created_at"),
        })
        out.append(s)
    return {"users": out, "today": today, "month": month_prefix}


def _extract_tokens(text: str) -> list[str]:
    import re as _re
    if not text:
        return []
    tokens = set()
    parts = _re.split(r"[\s_./|｜・\-、,，:：;；()（）【】\[\]<>\!?！？★☆♪♥♡🌟✨💎👑🌸🌷🌹🌺🌻🌼🍀🍒🍑🍎🍇🐶🐱🐭🐰🐻🦄🦋🐧🐤🐣🐔🦅🦉🦆🐦]+", text)
    for p in parts:
        if not p:
            continue
        if _re.search(r"[A-Za-z0-9]", p) and len(p) >= 3:
            tokens.add(p.lower())
    cjk = "".join(_re.findall(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]", text))
    for n in (2, 3):
        for i in range(len(cjk) - n + 1):
            tokens.add(cjk[i:i+n])
    return list(tokens)


_SKIP_TOKEN_STOPWORDS = {
    "official", "japan", "tokyo", "love", "channel", "studio", "team",
    "ちゃん", "さん", "くん", "です", "ます", "して", "から", "まで",
    "私の", "あなた", "毎日", "今日", "明日", "昨日",
    "love", "life", "work", "shop", "good", "best", "happy",
}


def get_skip_blocklist(min_count: int = 3) -> dict:
    from collections import Counter
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT username, name, source_tag, skip_reason FROM leads WHERE status='見送り' AND skip_reason IS NOT NULL AND skip_reason != ''"
        ).fetchall()
    by_reason: dict[str, Counter] = {}
    for r in rows:
        reason = r["skip_reason"]
        text = " ".join([(r["username"] or ""), (r["name"] or "")])
        tokens = _extract_tokens(text)
        c = by_reason.setdefault(reason, Counter())
        for t in tokens:
            if t in _SKIP_TOKEN_STOPWORDS:
                continue
            c[t] += 1
    out = {}
    for reason, cnt in by_reason.items():
        out[reason] = {t: n for t, n in cnt.items() if n >= min_count}
    return out


def get_skip_stats() -> dict:
    from collections import Counter
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT skip_reason, source_tag FROM leads WHERE status='見送り' AND skip_reason IS NOT NULL AND skip_reason != ''"
        ).fetchall()
    reason_count = Counter()
    reason_tags: dict[str, Counter] = {}
    for r in rows:
        reason = r["skip_reason"]
        reason_count[reason] += 1
        if r["source_tag"]:
            reason_tags.setdefault(reason, Counter())[r["source_tag"]] += 1
    return {
        "total": sum(reason_count.values()),
        "by_reason": dict(reason_count),
        "top_tags_by_reason": {r: dict(c.most_common(5)) for r, c in reason_tags.items()},
        "blocklist": get_skip_blocklist(),
    }


def mark_skip(lead_id, reason):
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE leads SET status = '見送り',
                             skip_reason = ?,
                             notes = COALESCE(notes, '') || ' | skip:' || ?
            WHERE id = ?
            """,
            (reason, reason, lead_id),
        )
        conn.commit()


def stats(user=None):
    """user が worker のときは self の本日送信数 / 自分の daily_limit を返す。
    owner / None のときは全体集計 + 全体 daily_limit。"""
    today = datetime.now().strftime("%Y-%m-%d")
    is_worker = bool(user) and user.get("role") == "worker"
    if is_worker:
        daily_limit = user.get("daily_limit") or 20
    else:
        daily_limit = get_setting("daily_limit", 20)
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
        queue = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE status='未接触' AND qualified=1"
        ).fetchone()["c"]
        if is_worker:
            sent_today = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE dm_sent_date=? AND sent_by=?",
                (today, user["id"]),
            ).fetchone()["c"]
            sent_total = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE status='DM送信済' AND sent_by=?",
                (user["id"],),
            ).fetchone()["c"]
        else:
            sent_today = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE dm_sent_date = ?", (today,)
            ).fetchone()["c"]
            sent_total = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE status='DM送信済'"
            ).fetchone()["c"]
        disqualified = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE qualified=0"
        ).fetchone()["c"]
    return {
        "total": total,
        "queue": queue,
        "sent_today": sent_today,
        "sent_total": sent_total,
        "disqualified": disqualified,
        "daily_limit": daily_limit,
        "remaining": max(0, daily_limit - sent_today),
    }


def recent_sent(limit=20, sent_by=None):
    with get_conn() as conn:
        if sent_by:
            rows = conn.execute(
                "SELECT * FROM leads WHERE status='DM送信済' AND sent_by=? ORDER BY dm_sent_date DESC, id DESC LIMIT ?",
                (sent_by, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM leads WHERE status='DM送信済' ORDER BY dm_sent_date DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def log_research_start():
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO research_runs(started_at) VALUES (?)",
            (datetime.now().isoformat(timespec="seconds"),),
        )
        conn.commit()
        return cur.lastrowid


def log_research_finish(run_id, fetched, added, error=None):
    with get_conn() as conn:
        conn.execute(
            """UPDATE research_runs
               SET finished_at=?, candidates_fetched=?, qualified_added=?, error=?
               WHERE id=?""",
            (
                datetime.now().isoformat(timespec="seconds"),
                fetched,
                added,
                error,
                run_id,
            ),
        )
        conn.commit()


def recent_runs(limit=5):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM research_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
