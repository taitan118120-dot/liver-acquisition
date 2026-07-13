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

CLI
---
  python3 note_tag_guard.py --audit          # 状態レポートのみ（変更なし）
  python3 note_tag_guard.py --fix            # タグ不足を全て修復
  python3 note_tag_guard.py --fix --recent 15  # 直近15本だけ対象
  python3 note_tag_guard.py <note_key> ...   # 指定keyだけ修復
"""
import json
import os
import re
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
COOKIE_FILE = BASE / "note_cookies.json"
CREATOR = "taitan_118"
MIN_TAGS = 5          # これ未満なら「付け忘れ」とみなす
TARGET_TAGS = 10      # 付与する本数

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
    r = session.get(f"https://note.com/api/v3/notes/{key}", timeout=30)
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
        r = session.get(url, timeout=30)
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
    note = get_note(session, key)
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
            after = get_note(session, key)
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
    print(f"公開記事 {len(notes)}本を監査（閾値 {min_tags}タグ未満を修復対象）")
    need = []
    for n in notes:
        det = get_note(session, n["key"])
        cnt = len(det["tags"]) if det else 0
        if cnt < min_tags:
            need.append((n["key"], n["name"], cnt))
    if not need:
        print("✅ タグ不足の記事はありません")
        return {"checked": len(notes), "fixed": 0, "targets": []}
    print(f"\n⚠️  タグ不足 {len(need)}本:")
    for key, name, cnt in need:
        print(f"  {key}  {cnt}tags  {(name or '')[:44]}")
    if dry_run:
        print("\n[dry-run] 修復はスキップ")
        return {"checked": len(notes), "fixed": 0, "targets": [k for k, _, _ in need]}
    jobs = [(key, generate_hashtags(name)) for key, name, _ in need]
    res = _fix_keys(jobs)
    # 検証
    fixed = 0
    print("\n── 結果 ──")
    for key, name, _ in need:
        det = get_note(session, key)
        cnt = len(det["tags"]) if det else 0
        ok = cnt >= min_tags
        fixed += 1 if ok else 0
        print(f"  {'✅' if ok else '❌'} {key}  {cnt}tags  {(name or '')[:40]}")
    print(f"\n完了: {fixed}/{len(need)} 修復")
    return {"checked": len(notes), "fixed": fixed, "targets": [k for k, _, _ in need]}


def main():
    args = sys.argv[1:]
    if not args or "--help" in args or "-h" in args:
        print(__doc__)
        return
    if "--audit" in args:
        audit_and_fix(dry_run=True)
        return
    if "--fix" in args:
        recent = None
        if "--recent" in args:
            i = args.index("--recent")
            recent = int(args[i + 1])
        audit_and_fix(dry_run=False, recent=recent)
        return
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


if __name__ == "__main__":
    main()
