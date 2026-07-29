#!/usr/bin/env python3
"""note_tag_guard.py — Note記事のタグ付け忘れを構造的に防ぐガード
==================================================================
なぜ必要か
----------
note_auto_poster の公開PUT は `"hashtags"` フィールドでタグを送るが、
note.com はこの形式を**無視する**（タグが0個になる）。タグは publish ページ
UI 経由でしか確実に付かない（project_note_remote_update メモ参照）。
そのため自動投稿された記事は放置するとタグ0のまま公開され続ける。

このガードの役割
----------------
1. ensure_tags(key, ...): 公開直後に GET で検証し、タグ不足なら UI で付与（冪等）。
   → post_article / update_article の末尾から呼び、投稿時点でタグ抜けを塞ぐ。
2. audit_and_fix(): 全公開記事を走査し、タグ不足を自動修復（毎日の安全網 / cron用）。
   → 手動公開やガード漏れも含め、あらゆる経路のタグ抜けを事後的に回収する。

ネットワーク耐性（2026-07-29）
----------------------------
launchd は 23:10 に起動するが、Mac がスリープ中だと復帰直後に走り Wi-Fi 未接続で
note.com が名前解決できず落ちる（実測: 成功16回に対し DNS失敗14回＝約半分の夜は
監査自体が走っていなかった）。しかも失敗はログに落ちるだけで誰も気づけない。
そこで:
  - 全HTTP呼び出しに指数バックオフのリトライ（requests例外＝DNS失敗含む）
  - 起動時にネットワーク到達性を確認し、未到達なら数分間隔で再確認してから諦める
  - 最終的に失敗したら GitHub Issue を作成/更新（link_guard と同じ通知経路）し exit 1
plist 側も 23:10 / 09:10 の2回に増やしてある（片方がスリープでも翌朝拾える）。

CLI
---
  python3 note_tag_guard.py --audit          # 状態レポートのみ（変更なし）
  python3 note_tag_guard.py --fix            # タグ不足を全て修復
  python3 note_tag_guard.py --fix --recent 15  # 直近15本だけ対象
  python3 note_tag_guard.py --fix --no-notify  # 失敗してもIssueを立てない
  python3 note_tag_guard.py <note_key> ...   # 指定keyだけ修復
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
COOKIE_FILE = BASE / "note_cookies.json"
CREATOR = "taitan_118"
MIN_TAGS = 5          # これ未満なら「付け忘れ」とみなす
TARGET_TAGS = 10      # 付与する本数

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# ── ネットワークリトライ設定 ──
RETRY_ATTEMPTS = 5      # 1回のGETあたりの試行回数（待機合計 約30秒: 2+4+8+16）
RETRY_BASE = 2.0        # 指数バックオフの底
NET_WAIT_ROUNDS = 6     # 起動時の到達性チェック回数
NET_WAIT_SLEEP = 120    # その間隔（秒）→ 最大約10分、スリープ復帰後のWi-Fi再接続を待てる
ISSUE_TITLE = "Noteタグ番犬が実行できていない（note_tag_guard）"


class NetworkUnavailable(RuntimeError):
    """リトライを尽くしても note.com に到達できなかった（＝監査自体が走っていない）"""

# ── タイトルからトピックタグを引く辞書（記事番号が不明でも良いタグを組める）──
# key: タイトルに含まれる語 / value: 付けたい固有タグ列
TOPIC_TAGS = [
    ("Pococha",       ["Pococha", "ポコチャ"]),
    ("ポコチャ",       ["Pococha", "ポコチャ"]),
    ("TikTok",        ["TikTokLIVE", "TikTok"]),
    ("IRIAM",         ["IRIAM", "Vライバー"]),
    ("ふわっち",       ["ふわっち"]),
    ("17LIVE",        ["17LIVE"]),
    ("事務所",         ["ライバー事務所", "事務所選び"]),
    ("代理店",         ["ライバー代理店", "代理店"]),
    ("還元率",         ["還元率"]),
    ("フリー",         ["フリーライバー"]),
    ("未経験",         ["未経験"]),
    ("主婦",           ["主婦副業", "ママライバー"]),
    ("ママ",           ["ママライバー"]),
    ("大学生",         ["大学生", "学生副業"]),
    ("会社員",         ["会社員副業"]),
    ("会社バレ",       ["副業バレ"]),
    ("顔出し",         ["顔出しなし"]),
    ("確定申告",       ["確定申告", "副業税金"]),
    ("経費",           ["経費", "確定申告"]),
    ("投げ銭",         ["投げ銭", "応援される配信者"]),
    ("コアファン",     ["コアファン", "ファン作り"]),
    ("ファン",         ["ファンづくり"]),
    ("時間ダイヤ",     ["時間ダイヤ"]),
    ("イベント",       ["ライバーイベント"]),
    ("ランク",         ["ランクアップ"]),
    ("収益化",         ["収益化"]),
    ("換金",           ["ダイヤ換金"]),
    ("始め方",         ["始め方"]),
    ("メンタル",       ["メンタルケア"]),
    ("緊張",           ["初配信"]),
    ("男性",           ["男性ライバー"]),
    ("40代",           ["40代ライバー"]),
    ("50代",           ["50代ライバー"]),
    ("30代",           ["30代ライバー"]),
]
# 母集団の大きい汎用タグ（10本に満たない分を埋める）
BROAD_TAGS = ["ライブ配信", "ライバー", "副業", "初心者", "在宅ワーク",
              "スマホ副業", "配信のコツ", "リスナー", "お金の勉強", "働き方"]


def _env_cookies():
    """CI用: NOTE_COOKIES_JSON Secret のcookieリストを返す（無ければNone）。"""
    raw = os.environ.get("NOTE_COOKIES_JSON", "").strip()
    if not raw:
        return None
    try:
        cookies = json.loads(raw)
        return cookies if isinstance(cookies, list) and cookies else None
    except json.JSONDecodeError:
        return None


def refresh_cookies():
    """Chrome の note.com cookie を browser_cookie3 で読み、note_cookies.json を最新化。
    stale cookie による Playwright ログイン失敗（=更新できずタグ抜け）を防ぐ。
    CI（browser_cookie3なし）では NOTE_COOKIES_JSON Secret をそのまま使うためスキップ。"""
    if _env_cookies() is not None:
        return None
    import browser_cookie3
    cj = browser_cookie3.chrome(domain_name="note.com")
    out = []
    for c in cj:
        out.append({
            "name": c.name, "value": c.value, "domain": c.domain,
            "path": c.path or "/", "expires": int(c.expires) if c.expires else -1,
            "httpOnly": False, "secure": bool(c.secure), "sameSite": "Lax",
        })
    COOKIE_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def _log(msg):
    """launchd のログにリアルタイムで残す（バッファされると失敗時に何も見えない）"""
    print(msg)
    sys.stdout.flush()


def wait_for_network(rounds=NET_WAIT_ROUNDS, sleep_s=NET_WAIT_SLEEP):
    """note.com に到達できるまで数分間隔で再確認する。
    launchd の StartCalendarInterval は一度きりで再実行されないため、
    スリープ復帰直後にWi-Fiが繋がるのをここで待たないと1晩まるごと監査が飛ぶ。"""
    import requests
    for i in range(1, rounds + 1):
        try:
            requests.head("https://note.com/", headers={"User-Agent": UA},
                          timeout=15, allow_redirects=True)
            if i > 1:
                _log(f"[net] {i}回目で note.com に到達（復帰待ち成功）")
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
    - 5xx / 429 → リトライ（note.com 側の一時不調）
    - それ以外のステータス → そのまま Response を返す（呼び出し側が判断）
    尽きたら NetworkUnavailable を送出する（0タグと誤認させないため None は返さない）。
    """
    import requests
    last = None
    for i in range(attempts):
        try:
            r = session.get(url, timeout=timeout)
        except requests.RequestException as e:
            last = f"{type(e).__name__}"
        else:
            if r.status_code < 500 and r.status_code != 429:
                return r
            last = f"HTTP {r.status_code}"
        if i < attempts - 1:
            wait = RETRY_BASE ** (i + 1)
            _log(f"  [retry {i + 1}/{attempts - 1}] {label or url} ← {last} / {wait:.0f}s待機")
            time.sleep(wait)
    raise NetworkUnavailable(f"{label or url}: {attempts}回試行して失敗（最後: {last}）")


def notify_failure(reason, extra=""):
    """最終失敗を可視化する。link_guard と同じく GitHub Issue に集約（同題があればコメント）。
    黙って死ぬと『タグ抜けが起きた日に気づけない』という元の穴が残るため必須。"""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    body = "\n".join([
        "## Noteタグ番犬が実行できていない",
        "",
        f"- 発生: {stamp}",
        f"- 理由: {reason}",
        (f"- 詳細: {extra}" if extra else ""),
        "",
        "監査自体が走っていないため、**この日に公開された記事のタグ抜けは検知されていません**。",
        "",
        "## 対処",
        "1. Mac をオンラインにして `python3 note_tag_guard.py --audit` を手動実行",
        "2. タグ不足があれば `python3 note_tag_guard.py --fix`",
        "3. ログ: `data/note_tag_guard.log`",
        "",
        "---",
        "_このIssueは `note_tag_guard.py`（launchd `com.taitanpro.note-tag-guard`）が自動生成しました。_",
    ])
    try:
        listed = subprocess.run(
            ["gh", "issue", "list", "--state", "open", "--limit", "100",
             "--json", "number,title"],
            cwd=str(BASE), capture_output=True, text=True, timeout=60)
        if listed.returncode != 0:
            raise RuntimeError(listed.stderr.strip()[:200])
        match = next((i for i in json.loads(listed.stdout or "[]")
                      if i.get("title") == ISSUE_TITLE), None)
        if match:
            cmd = ["gh", "issue", "comment", str(match["number"]),
                   "--body", f"再発: {stamp}\n\n理由: {reason}\n{extra}"]
        else:
            cmd = ["gh", "issue", "create", "--title", ISSUE_TITLE, "--body", body]
        res = subprocess.run(cmd, cwd=str(BASE), capture_output=True,
                             text=True, timeout=90)
        if res.returncode != 0:
            raise RuntimeError(res.stderr.strip()[:200])
        _log(f"[notify] GitHub Issue 通知済み: {res.stdout.strip() or match}")
        return True
    except Exception as e:
        # 通知に失敗しても exit 1 は残るので launchd ログ＋終了コードで検知できる
        _log(f"[notify] Issue通知に失敗（exit 1 のみで可視化）: {e}")
        return False


def make_session():
    import requests
    s = requests.Session()
    env = _env_cookies()
    if env is not None:
        for c in env:
            s.cookies.set(c["name"], c["value"],
                          domain=c.get("domain", ".note.com"), path=c.get("path", "/"))
    else:
        import browser_cookie3
        s.cookies = browser_cookie3.chrome(domain_name="note.com")
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest", "Accept": "application/json",
    })
    return s


def get_note(session, key):
    """記事詳細。到達不能なら NetworkUnavailable（None＝記事側の問題と区別する）。"""
    r = _get_with_retry(session, f"https://note.com/api/v3/notes/{key}",
                        label=f"get_note {key}")
    if r.status_code != 200:
        return None
    d = r.json().get("data", {})
    tags = [t.get("hashtag", {}).get("name", "").lstrip("#")
            for t in (d.get("hashtag_notes") or [])]
    return {"key": key, "name": d.get("name"), "status": d.get("status"),
            "eyecatch": d.get("eyecatch"), "tags": [t for t in tags if t]}


def list_published(session, limit=None):
    """creator の公開note を新しい順で返す [{key,name,eyecatch}]。"""
    notes, page = [], 1
    while True:
        url = f"https://note.com/api/v2/creators/{CREATOR}/contents?kind=note&page={page}"
        r = _get_with_retry(session, url, label=f"list_published page={page}")
        if r.status_code != 200:
            break
        d = r.json().get("data", {})
        for it in d.get("contents", []):
            notes.append({"key": it.get("key"), "name": it.get("name"),
                          "eyecatch": it.get("eyecatch")})
            if limit and len(notes) >= limit:
                return notes
        if d.get("isLastPage", True) or not d.get("contents"):
            break
        page += 1
    return notes


def generate_hashtags(title, article_num=None):
    """タグを組み立てる。記事番号があれば poster の既定ロジックを優先し、
    無ければタイトルのトピック語から固有タグ＋汎用タグで10本埋める。空は返さない。"""
    tags = []
    if article_num is not None:
        try:
            from note_auto_poster import get_hashtags_for_article
            tags = list(get_hashtags_for_article(article_num) or [])
        except Exception:
            tags = []
    # タイトルのトピック語から固有タグを補強（先頭に寄せる）
    topic = []
    for kw, tg in TOPIC_TAGS:
        if kw in (title or ""):
            for t in tg:
                if t not in topic:
                    topic.append(t)
    merged = []
    for t in topic + tags:
        if t and t not in merged:
            merged.append(t)
    for t in BROAD_TAGS:
        if len(merged) >= TARGET_TAGS:
            break
        if t not in merged:
            merged.append(t)
    return merged[:TARGET_TAGS]


# ── Playwright UI でタグを付与（fetch-PUTは効かないため必須）──
def _load_pw_cookies():
    cookies = _env_cookies() or json.loads(COOKIE_FILE.read_text())
    out = []
    for c in cookies:
        out.append({
            "name": c["name"], "value": c["value"],
            "domain": c.get("domain", ".note.com"), "path": c.get("path", "/"),
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure": bool(c.get("secure", True)),
            "sameSite": (c.get("sameSite") or "Lax").capitalize(),
        })
    return out


def set_tags_via_ui(page, key, hashtags):
    page.goto(f"https://editor.note.com/notes/{key}/edit/",
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    btn = page.locator('button:has-text("公開に進む")').first
    if btn.count() == 0:
        return False, 0
    btn.click()
    page.wait_for_timeout(5000)
    tag_input = page.locator('input[placeholder="ハッシュタグを追加する"]').first
    if tag_input.count() == 0:
        return False, 0
    added = 0
    for tag in hashtags[:TARGET_TAGS]:
        try:
            tag_input.click()
            page.wait_for_timeout(300)
            tag_input.fill(tag)
            page.wait_for_timeout(500)
            tag_input.press("Enter")
            page.wait_for_timeout(800)
            added += 1
        except Exception:
            pass
    page.wait_for_timeout(1500)
    for sel in ['button:has-text("更新する")', 'button:has-text("投稿する")',
                'button:has-text("公開する")']:
        loc = page.locator(sel).first
        if loc.count() > 0 and loc.is_visible():
            loc.click()
            page.wait_for_timeout(6000)
            return True, added
    return False, added


def _fix_keys(jobs):
    """jobs: [(key, hashtags)] を UI で一括修復。戻り値 {key: added}。"""
    from playwright.sync_api import sync_playwright
    refresh_cookies()  # Playwright前に必ず最新cookieへ
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="ja-JP", viewport={"width": 1280, "height": 1400})
        ctx.add_cookies(_load_pw_cookies())
        page = ctx.new_page()
        for key, tags in jobs:
            try:
                ok, n = set_tags_via_ui(page, key, tags)
                results[key] = n if ok else 0
            except Exception as e:
                print(f"  [ERR] {key}: {e}")
                results[key] = 0
            time.sleep(2)
        browser.close()
    return results


def ensure_tags(key, hashtags=None, article_num=None, title=None, min_tags=MIN_TAGS):
    """公開後の検証＋修復（冪等）。post_article/update_article から呼ぶ。
    既にタグが十分あれば何もしない。"""
    session = make_session()
    try:
        note = get_note(session, key)
    except NetworkUnavailable as e:
        # 呼び出し元（poster等）は dict を期待しているので例外は外へ出さない
        return {"key": key, "ok": False, "reason": f"note取得失敗: {e}"}
    if note is None:
        return {"key": key, "ok": False, "reason": "note取得失敗"}
    if len(note["tags"]) >= min_tags:
        return {"key": key, "ok": True, "already": len(note["tags"])}
    if not hashtags:
        hashtags = generate_hashtags(title or note["name"], article_num)
    # UI付与は「公開に進む」ボタン未表示等で単発失敗しうるため最大2ラウンド試行。
    # 検証も公開APIへの反映ラグで直後は0に見えることがあるためリトライする。
    after_cnt = len(note["tags"])
    for round_no in range(1, 3):
        _fix_keys([(key, hashtags)])
        for _ in range(3):
            time.sleep(8)
            try:
                after = get_note(session, key)
            except NetworkUnavailable as e:
                print(f"  [tag-guard] 検証GET失敗: {e}")
                after = None
            after_cnt = len(after["tags"]) if after else 0
            if after_cnt >= min_tags:
                return {"key": key, "ok": True, "before": len(note["tags"]),
                        "after": after_cnt, "rounds": round_no}
        print(f"  [tag-guard] round {round_no} 後もタグ{after_cnt}個 → "
              f"{'再試行' if round_no < 2 else '断念'}")
    return {"key": key, "ok": False, "before": len(note["tags"]), "after": after_cnt}


def audit_and_fix(min_tags=MIN_TAGS, recent=None, dry_run=False):
    session = make_session()
    notes = list_published(session, limit=recent)
    _log(f"公開記事 {len(notes)}本を監査（閾値 {min_tags}タグ未満を修復対象）")
    need, unchecked = [], []
    for n in notes:
        try:
            det = get_note(session, n["key"])
        except NetworkUnavailable as e:
            # 取得できなかった記事を0タグ扱いすると無用なUI修復が走るので分離する
            _log(f"  [WARN] {n['key']} 取得失敗（未監査扱い）: {e}")
            unchecked.append(n["key"])
            continue
        cnt = len(det["tags"]) if det else 0
        if cnt < min_tags:
            need.append((n["key"], n["name"], cnt))
    if not need:
        _log("✅ タグ不足の記事はありません"
             + (f"（ただし {len(unchecked)}本は取得失敗で未監査）" if unchecked else ""))
        return {"checked": len(notes) - len(unchecked), "fixed": 0,
                "targets": [], "unchecked": unchecked}
    print(f"\n⚠️  タグ不足 {len(need)}本:")
    for key, name, cnt in need:
        print(f"  {key}  {cnt}tags  {(name or '')[:44]}")
    if dry_run:
        print("\n[dry-run] 修復はスキップ")
        return {"checked": len(notes) - len(unchecked), "fixed": 0,
                "targets": [k for k, _, _ in need], "unchecked": unchecked}
    jobs = [(key, generate_hashtags(name)) for key, name, _ in need]
    res = _fix_keys(jobs)
    # 検証
    fixed = 0
    print("\n── 結果 ──")
    for key, name, _ in need:
        try:
            det = get_note(session, key)
        except NetworkUnavailable as e:
            print(f"  ❓ {key}  検証GET失敗: {e}")
            unchecked.append(key)
            continue
        cnt = len(det["tags"]) if det else 0
        ok = cnt >= min_tags
        fixed += 1 if ok else 0
        print(f"  {'✅' if ok else '❌'} {key}  {cnt}tags  {(name or '')[:40]}")
    _log(f"\n完了: {fixed}/{len(need)} 修復")
    return {"checked": len(notes) - len(unchecked), "fixed": fixed,
            "targets": [k for k, _, _ in need], "unchecked": unchecked}


def _run_audit(dry_run, recent, notify):
    """監査を実行し、実行できなかった/やり残しがあれば通知して exit code を返す。"""
    _log(f"=== note_tag_guard {'--audit' if dry_run else '--fix'} "
         f"{time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    if not wait_for_network():
        reason = ("note.com に到達できず監査を実行できませんでした"
                  f"（{NET_WAIT_ROUNDS}回 × {NET_WAIT_SLEEP}秒の再確認後も未到達。"
                  "Mac がスリープ/オフラインの可能性）")
        _log(f"\n❌ {reason}")
        if notify:
            notify_failure(reason)
        return 1
    try:
        res = audit_and_fix(dry_run=dry_run, recent=recent)
    except NetworkUnavailable as e:
        reason = f"監査中にネットワークが切れて中断: {e}"
        _log(f"\n❌ {reason}")
        if notify:
            notify_failure(reason)
        return 1
    unchecked = res.get("unchecked") or []
    if unchecked:
        reason = f"{len(unchecked)}本の記事を取得できず未監査のまま終了しました"
        _log(f"\n⚠️ {reason}: {', '.join(unchecked[:10])}")
        if notify:
            notify_failure(reason, extra=f"未監査key: {', '.join(unchecked[:20])}")
        return 1
    return 0


def main():
    args = sys.argv[1:]
    if not args or "--help" in args or "-h" in args:
        print(__doc__)
        return 0
    # 通知は launchd 経路（--fix）だけ。手動の --audit ではIssueを立てない。
    notify = "--fix" in args and "--no-notify" not in args
    if "--audit" in args:
        return _run_audit(dry_run=True, recent=None, notify=False)
    if "--fix" in args:
        recent = None
        if "--recent" in args:
            i = args.index("--recent")
            recent = int(args[i + 1])
        return _run_audit(dry_run=False, recent=recent, notify=notify)
    # 明示key指定
    keys = [a for a in args if not a.startswith("-")]
    if keys:
        session = make_session()
        jobs = []
        for key in keys:
            det = get_note(session, key)
            jobs.append((key, generate_hashtags(det["name"] if det else "")))
        _fix_keys(jobs)
        for key in keys:
            det = get_note(session, key)
            print(f"  {key}: {len(det['tags']) if det else 0}tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
