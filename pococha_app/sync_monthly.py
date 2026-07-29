"""Pococha 運営の月次レポートを自動同期 → SQLite → ダッシュボード再生成.

Chrome のセッションCookieを browser_cookie3 で読み、organizer-ope に HTTP GET。
ブラウザを開かずに完結する。launchd で毎日叩く想定。

使い方:
    python3 sync_monthly.py                # 今月分を同期 → dashboard.html 再生成
    python3 sync_monthly.py --month 2026-04  # 過去月を指定（前月遷移ボタン相当）
    python3 sync_monthly.py --no-dashboard   # ダッシュボード再生成を省略
    python3 sync_monthly.py --no-notify      # 失敗してもGitHub Issueを立てない（手動実行用）

launchd（com.taitanpro.pococha-sync, 1日5回）が スリープ復帰直後に発火すると
Wi-Fi 未接続で DNS が引けず落ちる。起動時のネット到達性待ち＋指数バックオフの
リトライでそれを吸収し、最終的に失敗したら黙って死なずに exit 1 ＋ Issue 通知する。

organizer-ope のログインCookieは5日で切れ、切れると403しか返らない（人間が
Chrome でログインし直すまで自動復旧しない）。切れる前に事前通知し、切れていたら
HTTPを撃つ前に理由を確定させる。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

import requests

sys.path.insert(0, os.path.dirname(__file__))
from db import connect

JST = timezone(timedelta(hours=9))
BASE = "https://organizer-ope.pococha.com"
DOMAIN = "organizer-ope.pococha.com"

# ── ネットワークリトライ設定（note_tag_guard.py と同じ思想）──
RETRY_ATTEMPTS = 5      # 1回のGETあたりの試行回数（待機合計 約30秒: 2+4+8+16）
RETRY_BASE = 2.0        # 指数バックオフの底
NET_WAIT_ROUNDS = 6     # 起動時の到達性チェック回数
NET_WAIT_SLEEP = 120    # その間隔（秒）→ 最大約10分、スリープ復帰後のWi-Fi再接続を待てる

STATE_FILE = os.path.join(os.path.dirname(__file__), "data", "sync_state.json")
ISSUE_TITLE = "Pococha月次同期が実行できていない（pococha-sync）"
ISSUE_TITLE_COOKIE = "Pococha運営のログインがもうすぐ切れる（pococha-sync）"

# organizer-ope のセッションCookieは「ログインから5日」で失効する（実測）。
# 切れると403しか返らず、復旧には人間が Chrome でログインし直すしかない。
# 切れてから気づくと最大5日ぶんのデータが欠測するので、切れる前に通知する。
SESSION_COOKIE = "_pokota_organizer_ope_session"
COOKIE_WARN_HOURS = 24

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")


class NetworkUnavailable(RuntimeError):
    """リトライを尽くしても organizer-ope に到達できなかった（＝同期自体が走っていない）"""


class AuthExpired(RuntimeError):
    """到達はできたが認証が切れている（Cookie切れ／ログアウト）。リトライしても直らない。"""

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


def _log(msg):
    """launchd のログにリアルタイムで残す（バッファされると失敗時に何も見えない）"""
    print(msg)
    sys.stdout.flush()


def _today():
    return datetime.now(JST).strftime("%Y-%m-%d")


def _load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(**kv):
    state = _load_state()
    state.update(kv)
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError as e:
        _log(f"[state] 保存できず（通知の重複抑止が効かない可能性）: {e}")
    return state


def _succeeded_today():
    """今日すでに同期が成功しているか。1日5回走るので、
    朝に成功していれば夕方の1回が落ちても通知しない（スパム防止）。
    state ファイルが消えていても DB の captured_at で判定できるようにしておく。"""
    today = _today()
    if _load_state().get("last_success_date") == today:
        return True
    try:
        conn = connect()
        row = conn.execute(
            "SELECT 1 FROM monthly_reports WHERE date(captured_at) = ? LIMIT 1",
            (today,),
        ).fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False


def wait_for_network(rounds=NET_WAIT_ROUNDS, sleep_s=NET_WAIT_SLEEP):
    """organizer-ope に到達できるまで数分間隔で再確認する。
    launchd の StartCalendarInterval は一度きりで再実行されないため、
    スリープ復帰直後にWi-Fiが繋がるのをここで待たないとその回の同期がまるごと飛ぶ。
    認証は見ない（403が返ってきても「到達できた」＝OK）。"""
    for i in range(1, rounds + 1):
        try:
            requests.head(BASE + "/", headers={"User-Agent": UA},
                          timeout=15, allow_redirects=True)
            if i > 1:
                _log(f"[net] {i}回目で {DOMAIN} に到達（復帰待ち成功）")
            return True
        except requests.RequestException as e:
            _log(f"[net] 到達不可 {i}/{rounds}: {type(e).__name__}"
                 + (f" → {sleep_s}秒待機" if i < rounds else " → 断念"))
            if i < rounds:
                time.sleep(sleep_s)
    return False


def _get_with_retry(session, url, timeout=30, attempts=RETRY_ATTEMPTS, label=""):
    """GET を指数バックオフでリトライする。

    - requests の例外（DNS失敗＝NameResolutionError/ConnectionError、タイムアウト等）→ リトライ
    - 5xx / 429 → リトライ（pococha 側の一時不調）
    - 401 / 403 → AuthExpired（Cookie切れ。何度やっても直らないので即中断）
    - それ以外のステータス → そのまま Response を返す
    尽きたら NetworkUnavailable を送出する（空データと誤認させないため None は返さない）。
    """
    last = None
    for i in range(attempts):
        try:
            r = session.get(url, timeout=timeout)
        except requests.RequestException as e:
            last = f"{type(e).__name__}"
        else:
            if r.status_code in (401, 403):
                raise AuthExpired(f"{label or url}: HTTP {r.status_code}（Cookie切れ／ログアウト）")
            if r.status_code < 500 and r.status_code != 429:
                return r
            last = f"HTTP {r.status_code}"
        if i < attempts - 1:
            wait = RETRY_BASE ** (i + 1)
            _log(f"  [retry {i + 1}/{attempts - 1}] {label or url} ← {last} / {wait:.0f}s待機")
            time.sleep(wait)
    raise NetworkUnavailable(f"{label or url}: {attempts}回試行して失敗（最後: {last}）")


def _post_issue(title, body, comment):
    """GitHub Issue に集約（同題があればコメント）。note_tag_guard / link_guard と同じ思想。"""
    here = os.path.dirname(os.path.abspath(__file__))
    listed = subprocess.run(
        ["gh", "issue", "list", "--state", "open", "--limit", "100",
         "--json", "number,title"],
        cwd=here, capture_output=True, text=True, timeout=60)
    if listed.returncode != 0:
        raise RuntimeError(listed.stderr.strip()[:200])
    match = next((i for i in json.loads(listed.stdout or "[]")
                  if i.get("title") == title), None)
    if match:
        cmd = ["gh", "issue", "comment", str(match["number"]), "--body", comment]
    else:
        cmd = ["gh", "issue", "create", "--title", title, "--body", body]
    res = subprocess.run(cmd, cwd=here, capture_output=True, text=True, timeout=90)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip()[:200])
    return res.stdout.strip() or f"#{match['number']} にコメント"


def notify_cookie_expiring(expires_at):
    """Cookieが切れる前に知らせる。切れてから通知しても、気づくまでの数日は必ず欠測する。
    同期自体は成功しているので notify_failure の抑止条件（今日成功したら黙る）には乗せられない。
    1日1通に絞る（1日5回走るため）。"""
    today = _today()
    if _load_state().get("last_cookie_warn_date") == today:
        return False
    stamp = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    exp = expires_at.strftime("%Y-%m-%d %H:%M")
    body = "\n".join([
        "## Pococha運営のログインがもうすぐ切れます",
        "",
        f"- 検知: {stamp}",
        f"- 失効予定: **{exp}**（Cookie `{SESSION_COOKIE}`）",
        "",
        "失効すると同期は403で止まり、**ダッシュボードの月間ダイヤが古いまま**になります。",
        "自動では復旧できません（ログインは人間しかできない）。",
        "",
        "## 対処（30秒）",
        "1. Chrome で https://organizer-ope.pococha.com を開いてログインし直す",
        "2. それだけ。次の同期（1日5回）が新しいCookieを拾います",
        "",
        "---",
        "_このIssueは `sync_monthly.py`（launchd `com.taitanpro.pococha-sync`）が自動生成しました。_",
    ])
    try:
        out = _post_issue(ISSUE_TITLE_COOKIE, body,
                          f"再通知: {stamp}\n\n失効予定: {exp}\n"
                          "Chrome で https://organizer-ope.pococha.com にログインし直してください。")
        _save_state(last_cookie_warn_date=today, cookie_expires_at=expires_at.isoformat())
        _log(f"[notify] ログイン失効の事前通知を送信: {out}")
        return True
    except Exception as e:
        _log(f"[notify] 事前通知に失敗: {e}")
        return False


def notify_failure(reason, extra=""):
    """最終失敗を可視化する。黙って死ぬと『数値が古いまま気づかない』穴が残る。

    1日5回走るジョブなので通知条件を絞る:
      - 今日すでに成功した同期がある → 通知しない（次回リトライで足りている）
      - 今日すでに通知済み → 通知しない（1日1通まで）
    """
    if _succeeded_today():
        _log("[notify] 今日は既に同期成功済みのため通知しない")
        return False
    today = _today()
    if _load_state().get("last_notify_date") == today:
        _log("[notify] 今日は通知済みのためスキップ（1日1通）")
        return False

    stamp = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    body = "\n".join([
        "## Pococha月次同期が実行できていない",
        "",
        f"- 発生: {stamp}",
        f"- 理由: {reason}",
        (f"- 詳細: {extra}" if extra else ""),
        "",
        "同期が走っていないため、**ダッシュボードの月間ダイヤ等が古いままです**。",
        "",
        "## 対処",
        "1. Mac をオンラインにする",
        "2. Chrome で https://organizer-ope.pococha.com にログインし直す（403＝Cookie切れの場合）",
        "3. `python3 pococha_app/sync_monthly.py` を手動実行",
        "4. ログ: `pococha_app/data/sync.log`",
        "",
        "---",
        "_このIssueは `sync_monthly.py`（launchd `com.taitanpro.pococha-sync`）が自動生成しました。_",
    ])
    try:
        out = _post_issue(ISSUE_TITLE, body,
                          f"再発: {stamp}\n\n理由: {reason}\n{extra}")
        _save_state(last_notify_date=today, last_notify_reason=reason)
        _log(f"[notify] GitHub Issue 通知済み: {out}")
        return True
    except Exception as e:
        # 通知に失敗しても exit 1 は残るので launchd ログ＋終了コードで検知できる
        _log(f"[notify] Issue通知に失敗（exit 1 のみで可視化）: {e}")
        return False


def chrome_cookies():
    """Chromeから pococha.com 系のCookieを取得（macOS Keychainパスフレーズ自動解決）.
    domain_name='organizer-ope.pococha.com' だと .pococha.com で登録されてる Cookie が
    マッチしないので、全体取得して pococha が含まれるものだけ返す."""
    import http.cookiejar

    import browser_cookie3
    full = browser_cookie3.chrome()
    out = http.cookiejar.CookieJar()
    for c in full:
        if "pococha" in (c.domain or "").lower():
            out.set_cookie(c)
    return out


def session_expiry(jar):
    """ログインCookieの失効時刻を返す（無ければ None）。

    browser_cookie3 は失効済みのCookieもそのまま返すので、値があること＝有効ではない。
    実際 2026-06-04 に失効した Cookie を 8週間ぶん送り続けて 403 を食らっていた。
    """
    for c in jar:
        if c.name == SESSION_COOKIE and c.expires:
            return datetime.fromtimestamp(c.expires, JST)
    return None


def check_session_cookie(jar):
    """同期前にCookieの生死を判定する。
    切れていれば HTTP を撃つ前に AuthExpired（403を5回食うより原因が明確に残る）。
    生きていれば失効時刻を返す（呼び出し側が事前通知の要否を判断する）。"""
    exp = session_expiry(jar)
    if exp is None:
        if not any(c.name == SESSION_COOKIE for c in jar):
            raise AuthExpired(
                f"Chrome に {SESSION_COOKIE} が無い"
                "（organizer-ope にログインしていない／別プロファイルで見ている）")
        return None  # セッションCookie（期限なし）＝ブラウザを閉じるまで有効
    left = exp - datetime.now(JST)
    if left.total_seconds() <= 0:
        raise AuthExpired(
            f"ログインCookieが {exp:%Y-%m-%d %H:%M} に失効している"
            f"（{-left.days}日前）。Chrome でログインし直すまで復旧しません")
    _log(f"  ログイン有効期限: {exp:%Y-%m-%d %H:%M}（残り {left.days}日{left.seconds // 3600}時間）")
    return exp


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
    r = _get_with_retry(session, f"{BASE}/publishers?max_display=1000",
                        timeout=20, label="publishers")
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
    r = _get_with_retry(session, url, timeout=20, label=f"monthly:{user_id}")
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


def sync(args):
    """同期本体。(成功件数, Cookie失効時刻) を返す。到達不能/認証切れは例外で上に投げる。"""
    _log("Chrome Cookieを読み込み中...")
    jar = chrome_cookies()
    cookie_exp = check_session_cookie(jar)
    session = requests.Session()
    session.cookies = jar
    session.headers.update({
        "User-Agent": UA,
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    before = next((c.value for c in jar if c.name == SESSION_COOKIE), None)

    _log("ライバー一覧取得中...")
    livers = fetch_publishers(session)
    if not livers:
        raise AuthExpired("ライバーが取れなかった。Cookie切れ or ログアウトの可能性")
    _log(f"  {len(livers)}名")

    # サーバがアクセスのたびにセッションを延長するタイプなら、Set-Cookie を保存し直す
    # だけで5日ごとの手動ログインを無くせる。判定材料をログに残しておく。
    after = next((c.value for c in session.cookies if c.name == SESSION_COOKIE), None)
    if before and after:
        _log(f"  [session] Set-Cookieで更新された: {'はい' if after != before else 'いいえ（絶対期限）'}")

    conn = connect()
    n_ok, n_fail = 0, 0
    try:
        for lv in livers:
            try:
                rec = fetch_monthly(session, lv["id"], args.month)
                if args.month and rec.get("month") != args.month:
                    # &month= が効いていない（当月が返っている）。書くと「埋め戻せた」と
                    # 誤認するので書かない。過去月の取り方が判明するまで --month は使えない。
                    _log(f"  ❌ {lv['name']} ({lv['id']}): --month {args.month} を指定したが "
                         f"{rec.get('month')} が返った（過去月クエリ未対応）→ 書き込まない")
                    n_fail += 1
                elif upsert(conn, rec):
                    _log(f"  ✅ {lv['name']} ({lv['id']}) {rec.get('month')}: "
                         f"月間ダイヤ {rec.get('total_dia')}")
                    n_ok += 1
                else:
                    _log(f"  ⚠️  {lv['name']} ({lv['id']}): month/user_id 取得失敗")
                    n_fail += 1
            except (NetworkUnavailable, AuthExpired):
                # 途中でネットが切れた/Cookieが切れた → 残りを回しても無駄。
                # ここまでの成功分は commit してから上に投げる。
                raise
            except Exception as e:
                _log(f"  ❌ {lv['name']} ({lv['id']}): {e}")
                n_fail += 1
    finally:
        conn.commit()
        conn.close()

    _log(f"\n完了: 成功{n_ok} 失敗{n_fail}")
    if n_ok == 0:
        raise RuntimeError(f"1件も取得できなかった（失敗{n_fail}件）")

    if not args.no_dashboard:
        _log("\nダッシュボード再生成...")
        subprocess.run([sys.executable, "dashboard.py"],
                       cwd=os.path.dirname(__file__), check=False)
    return n_ok, cookie_exp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM 過去月指定（既定: 今月）")
    ap.add_argument("--no-dashboard", action="store_true")
    ap.add_argument("--no-notify", action="store_true",
                    help="失敗してもGitHub Issueを立てない（手動実行用）")
    args = ap.parse_args()

    _log(f"=== pococha-sync {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')} ===")

    def fail(reason, extra=""):
        _log(f"\n❌ {reason}")
        if not args.no_notify:
            notify_failure(reason, extra)
        return 1

    if not wait_for_network():
        return fail(
            f"{DOMAIN} に到達できず同期を実行できませんでした"
            f"（{NET_WAIT_ROUNDS}回 × {NET_WAIT_SLEEP}秒の再確認後も未到達。"
            "Mac がスリープ/オフラインの可能性）")

    try:
        n_ok, cookie_exp = sync(args)
    except NetworkUnavailable as e:
        return fail(f"同期中にネットワークが切れて中断: {e}")
    except AuthExpired as e:
        return fail(f"Cookie切れで同期できません: {e}",
                    extra="Chrome で organizer-ope.pococha.com にログインし直してください。")
    except Exception as e:
        return fail(f"同期に失敗: {type(e).__name__}: {e}")

    _save_state(last_success_date=_today(),
                last_success_at=datetime.now(JST).isoformat(),
                last_success_count=n_ok)

    # 成功していても、Cookieの寿命が尽きかけていれば今のうちに知らせる。
    # 失効を待って通知すると、気づくまでの日数はそのまま欠測になる。
    if cookie_exp and not args.no_notify:
        left_h = (cookie_exp - datetime.now(JST)).total_seconds() / 3600
        if left_h <= COOKIE_WARN_HOURS:
            _log(f"\n⚠️  ログインCookieの残り {left_h:.0f}時間 → 事前通知")
            notify_cookie_expiring(cookie_exp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
