"""IG内部API薄ラッパー（Chrome Cookie自動吸出 + hashtag/profileエンドポイント）

セキュリティ警告対応（2026-05-17〜）:
  - 環境変数 IG_SCRAPING_DISABLED=1 で内部API系の呼び出しを即座にエラー化（kill switch）
  - 環境変数 IG_DISPOSABLE_COOKIE に捨て垢Cookie文字列を入れると、Chrome本垢Cookieを一切吸わずに
    それを使う（本垢Chrome残留対策）
  - 引数 manual_cookie はChrome本垢Cookieより優先される（バグ修正: 旧実装はChromeを先に試していた）

2026-05-11 に taitan_pro7 へIGからサイバーセキュリティ違反警告。最低4週間（〜2026-06-14頃）は
IG_SCRAPING_DISABLED=1 を入れた状態で運用する想定。
"""
import os
import re
import time
from typing import Optional

import httpx

APP_ID = "936619743392459"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


class IGAuthError(RuntimeError):
    pass


def _load_cookies_from_chrome() -> Optional[str]:
    """browser-cookie3でChrome Keychainからinstagram.comのCookieを取得"""
    try:
        import browser_cookie3  # type: ignore
    except ImportError:
        return None
    try:
        cj = browser_cookie3.chrome(domain_name=".instagram.com")
        parts = [f"{c.name}={c.value}" for c in cj]
        if not parts:
            return None
        return "; ".join(parts)
    except Exception:
        return None


def _cookie_header(manual_cookie: str = "") -> str:
    # Kill switch: 警告解除待ち期間中は内部API系を一切叩かない
    if os.environ.get("IG_SCRAPING_DISABLED") == "1":
        raise IGAuthError(
            "IG内部APIのscrapingは現在無効化されています "
            "(IG_SCRAPING_DISABLED=1)。警告解除後に解除してください。"
        )

    # 優先順位: manual_cookie > IG_DISPOSABLE_COOKIE(env) > Chrome本垢
    # （旧実装はChromeを先に試していたため、捨て垢に切り替えても本垢が使われる重大バグだった）
    if manual_cookie.strip():
        return manual_cookie.strip()

    disposable = os.environ.get("IG_DISPOSABLE_COOKIE", "").strip()
    if disposable:
        return disposable

    # Chrome本垢Cookie吸出は明示的に許可された場合のみ
    if os.environ.get("IG_ALLOW_CHROME_COOKIE") == "1":
        c = _load_cookies_from_chrome()
        if c:
            return c

    raise IGAuthError(
        "IG Cookieが取得できません。IG_DISPOSABLE_COOKIE 環境変数に捨て垢Cookieを入れるか、"
        "manual_cookie引数で渡してください。Chrome本垢Cookieを使う場合は IG_ALLOW_CHROME_COOKIE=1 "
        "を明示する必要があります（警告再発防止）。"
    )


def _headers(manual_cookie: str = "") -> dict:
    return {
        "x-ig-app-id": APP_ID,
        "User-Agent": UA,
        "Accept": "*/*",
        "Referer": "https://www.instagram.com/",
        "Cookie": _cookie_header(manual_cookie),
    }


def fetch_hashtag_users(tag: str, manual_cookie: str = "") -> list[dict]:
    """ハッシュタグから投稿者ユーザーを抽出"""
    url = f"https://www.instagram.com/api/v1/tags/web_info/?tag_name={tag}"
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        r = client.get(url, headers=_headers(manual_cookie))
        r.raise_for_status()
        data = r.json()

    users = {}
    secs = (data.get("data", {}).get("recent", {}).get("sections", []) or []) + (
        data.get("data", {}).get("top", {}).get("sections", []) or []
    )
    for s in secs:
        medias = (s.get("layout_content") or {}).get("medias") or []
        for m in medias:
            u = (m.get("media") or {}).get("user") or {}
            uname = u.get("username")
            if uname and uname not in users:
                users[uname] = {
                    "username": uname,
                    "full_name": u.get("full_name", ""),
                    "is_private": u.get("is_private", False),
                }
    return list(users.values())


def fetch_profile(username: str, manual_cookie: str = "") -> Optional[dict]:
    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        r = client.get(url, headers=_headers(manual_cookie))
        if r.status_code != 200:
            return None
        data = r.json()
    user = (data.get("data") or {}).get("user")
    if not user:
        return None
    return {
        "username": username,
        "full_name": user.get("full_name", ""),
        "biography": user.get("biography", ""),
        "followers": (user.get("edge_followed_by") or {}).get("count"),
        "following": (user.get("edge_follow") or {}).get("count"),
        "post_count": (user.get("edge_owner_to_timeline_media") or {}).get("count"),
        "is_private": user.get("is_private", False),
        "is_verified": user.get("is_verified", False),
        "is_business": user.get("is_business_account", False),
        "is_professional": user.get("is_professional_account", False),
        "business_contact_method": user.get("business_contact_method"),
        "category": user.get("category_name"),
        "external_url": user.get("external_url") or "",
    }


_OG_DESC_RE = re.compile(r'<meta property="og:description" content="([^"]+)"')
_OG_TITLE_RE = re.compile(r'<meta property="og:title" content="([^"]+)"')
_NUM_RE = re.compile(r"([\d,\.]+[KMB]?)")


def _parse_count(s: str) -> Optional[int]:
    s = s.replace(",", "").strip()
    if not s:
        return None
    mult = 1
    if s.endswith("K"):
        mult, s = 1000, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000, s[:-1]
    elif s.endswith("B"):
        mult, s = 1_000_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


_html_last_error: dict = {"status": None, "reason": None, "html_len": 0}


def fetch_profile_html(username: str) -> Optional[dict]:
    """IG プロフィールページHTMLから og:description を解析して fl/fw 取得。
    認証/Cookie不要。レート制限対象外（推定）。bio は取れない。
    失敗理由は _html_last_error に格納される（呼び出し側がログに使える）。
    """
    url = f"https://www.instagram.com/{username}/"
    # Googlebot UA で og: メタタグ取得（一般UAだとSPA shellのみで og なし）
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(url, headers=headers)
            _html_last_error.update({"status": r.status_code, "html_len": len(r.text), "reason": None})
            if r.status_code != 200:
                _html_last_error["reason"] = f"http_{r.status_code}"
                return None
            html = r.text
    except Exception as e:
        _html_last_error.update({"status": None, "html_len": 0, "reason": f"exc:{type(e).__name__}"})
        return None

    desc_m = _OG_DESC_RE.search(html)
    title_m = _OG_TITLE_RE.search(html)
    if not desc_m:
        # SPA shell が返ってきた（Googlebot 認識されず）か login redirect
        is_login = "/accounts/login" in html or "loginForm" in html
        _html_last_error["reason"] = "login_redirect" if is_login else "no_og_desc"
        return None
    desc = desc_m.group(1)

    # JA: "フォロワー1,234人、フォロー中567人、89件の投稿 - @usernameのInstagram..."
    # EN: "123 Followers, 456 Following, 78 Posts - See Instagram photos..."
    fl = fw = None
    m = re.search(r"フォロワー\s*([\d,]+)\s*人", desc)
    if m:
        fl = _parse_count(m.group(1))
    else:
        m = re.search(r"([\d,\.]+[KMB]?)\s*Followers", desc)
        if m:
            fl = _parse_count(m.group(1))
    m = re.search(r"フォロー中\s*([\d,]+)\s*人", desc)
    if m:
        fw = _parse_count(m.group(1))
    else:
        m = re.search(r"([\d,\.]+[KMB]?)\s*Following", desc)
        if m:
            fw = _parse_count(m.group(1))
    post_count = None
    m = re.search(r"([\d,]+)\s*件の投稿", desc)
    if m:
        post_count = _parse_count(m.group(1))
    else:
        m = re.search(r"([\d,\.]+[KMB]?)\s*Posts?", desc)
        if m:
            post_count = _parse_count(m.group(1))

    full_name = ""
    if title_m:
        import html as _html
        # "Full Name (&#064;username) &#x2022; Instagram photos and videos"
        title = _html.unescape(title_m.group(1))
        full_name = re.sub(r"\s*\(@[^)]+\)\s*.*$", "", title).strip()

    is_private = "isPrivate&q;:true" in html or '"is_private":true' in html

    return {
        "username": username,
        "full_name": full_name,
        "biography": "",  # HTML scrape では取得不可
        "followers": fl,
        "following": fw,
        "post_count": post_count,
        "is_private": is_private,
        "is_verified": False,
        "is_business": False,
        "category": None,
    }


def fetch_profiles(usernames: list[str], manual_cookie: str = "", delay: float = 0.4) -> list[dict]:
    out = []
    for u in usernames:
        try:
            p = fetch_profile(u, manual_cookie)
            if p:
                out.append(p)
        except Exception as e:
            out.append({"username": u, "error": str(e)})
        time.sleep(delay)
    return out


def fetch_user_id(username: str, manual_cookie: str = "") -> Optional[str]:
    """username -> 数値user_id（フォロワー/いいねAPI用）"""
    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        r = client.get(url, headers=_headers(manual_cookie))
        if r.status_code != 200:
            return None
        data = r.json()
    user = (data.get("data") or {}).get("user") or {}
    return user.get("id")


def fetch_followers(target_username: str, max_count: int = 200,
                    manual_cookie: str = "") -> list[dict]:
    """指定アカウントのフォロワー一覧を取得（最新登録順、認証必須）"""
    user_id = fetch_user_id(target_username, manual_cookie)
    if not user_id:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    next_max_id = ""
    while len(out) < max_count:
        url = f"https://www.instagram.com/api/v1/friendships/{user_id}/followers/?count=50"
        if next_max_id:
            url += f"&max_id={next_max_id}"
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(url, headers=_headers(manual_cookie))
            if r.status_code != 200:
                break
            data = r.json()
        users = data.get("users") or []
        if not users:
            break
        for u in users:
            uname = u.get("username")
            if not uname or uname in seen:
                continue
            seen.add(uname)
            out.append({
                "username": uname,
                "full_name": u.get("full_name", ""),
                "is_private": u.get("is_private", False),
            })
            if len(out) >= max_count:
                break
        next_max_id = data.get("next_max_id")
        if not next_max_id:
            break
        time.sleep(0.6)
    return out


def fetch_following(target_username: str, max_count: int = 200,
                    manual_cookie: str = "") -> list[dict]:
    """指定アカウントのフォロー中一覧を取得（認証必須）"""
    user_id = fetch_user_id(target_username, manual_cookie)
    if not user_id:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    next_max_id = ""
    while len(out) < max_count:
        url = f"https://www.instagram.com/api/v1/friendships/{user_id}/following/?count=50"
        if next_max_id:
            url += f"&max_id={next_max_id}"
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(url, headers=_headers(manual_cookie))
            if r.status_code != 200:
                break
            data = r.json()
        users = data.get("users") or []
        if not users:
            break
        for u in users:
            uname = u.get("username")
            if not uname or uname in seen:
                continue
            seen.add(uname)
            out.append({
                "username": uname,
                "full_name": u.get("full_name", ""),
                "is_private": u.get("is_private", False),
            })
            if len(out) >= max_count:
                break
        next_max_id = data.get("next_max_id")
        if not next_max_id:
            break
        time.sleep(0.8)
    return out


def fetch_user_recent_media(user_id: str, count: int = 12,
                            manual_cookie: str = "") -> list[str]:
    """user_id の最新投稿の media_id 一覧"""
    url = f"https://www.instagram.com/api/v1/feed/user/{user_id}/?count={count}"
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        r = client.get(url, headers=_headers(manual_cookie))
        if r.status_code != 200:
            return []
        data = r.json()
    return [m.get("pk") for m in (data.get("items") or []) if m.get("pk")]


def fetch_likers(target_username: str, max_count: int = 200, posts: int = 6,
                 manual_cookie: str = "") -> list[dict]:
    """指定アカウントの最新投稿群 から いいねしたユーザーを集約"""
    user_id = fetch_user_id(target_username, manual_cookie)
    if not user_id:
        return []
    media_ids = fetch_user_recent_media(user_id, count=posts, manual_cookie=manual_cookie)
    out: dict[str, dict] = {}
    for mid in media_ids:
        if len(out) >= max_count:
            break
        url = f"https://www.instagram.com/api/v1/media/{mid}/likers/"
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                r = client.get(url, headers=_headers(manual_cookie))
                if r.status_code != 200:
                    continue
                data = r.json()
        except Exception:
            continue
        for u in (data.get("users") or []):
            uname = u.get("username")
            if not uname or uname in out:
                continue
            out[uname] = {
                "username": uname,
                "full_name": u.get("full_name", ""),
                "is_private": u.get("is_private", False),
            }
            if len(out) >= max_count:
                break
        time.sleep(0.6)
    return list(out.values())
