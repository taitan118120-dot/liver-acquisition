"""X (Twitter) 内部API薄ラッパー（Chrome Cookie 経由 / 認証必須・無料）

Bearer Token (有料 API) ではなく、Chrome の auth_token + ct0 Cookie で
x.com の内部 GraphQL を叩く。@taitan_LIVER でログイン済みの Chrome 前提。

このモジュールはMac側でしか使わない（Fly上ではChrome Cookieが無いので動かない）。
local_research.py から呼ばれて /api/ingest に流す。

注意: GraphQL の queryId は X が更新するたびに変わる。
壊れたら https://x.com を Chrome DevTools で開き、検索リクエストを観察して
SearchTimeline / UserByScreenName の queryId を更新する。
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from typing import Optional

import httpx

# x.com 公式Web の Bearer Token（数年安定。アプリのSPA bundle に埋め込まれている公開値）
WEB_BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

# GraphQL queryId デフォルト（main.js から動的に解決できなかった場合のフォールバック）
# 2026-04-28 時点の値。X が更新するたびに古くなるが、_resolve_query_ids() が
# 失敗時のみここを使う。
DEFAULT_QUERY_IDS = {
    "SearchTimeline": "XN_HccZ9SU-miQVvwTAlFQ",
    "UserByScreenName": "IGgvgiOx4QZndDHuD3x9TQ",
}

# プロセス内キャッシュ（main.js を毎回取りに行かない）
_QID_CACHE: dict[str, str] = {}
_QID_CACHE_AT: float = 0.0
_QID_CACHE_TTL = 6 * 3600  # 6時間

# SearchTimeline の features フラグ（X が増減するたびに 'unknown feature' エラーになる）
SEARCH_FEATURES = {
    "rweb_video_screen_enabled": False,
    "payments_enabled": False,
    "rweb_xchat_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": True,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "responsive_web_grok_show_grok_translated_post": False,
    "responsive_web_grok_analysis_button_from_backend": True,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_grok_imagine_annotation_enabled": True,
    "responsive_web_grok_community_note_auto_translation_is_enabled": False,
    "responsive_web_enhance_cards_enabled": False,
}

USER_FEATURES = {
    "responsive_web_grok_bio_auto_translation_is_enabled": False,
    "hidden_profile_subscriptions_enabled": True,
    "payments_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "verified_phone_label_enabled": False,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": True,
    "subscriptions_feature_can_gift_premium": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
}

USER_FIELD_TOGGLES = {
    "withAuxiliaryUserLabels": True,
}

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


class XAuthError(RuntimeError):
    pass


def _load_cookies_from_chrome() -> Optional[dict]:
    """browser-cookie3 で Chrome Keychain から x.com / twitter.com の Cookie を取得"""
    try:
        import browser_cookie3  # type: ignore
    except ImportError:
        return None
    cookies: dict[str, str] = {}
    for domain in (".x.com", ".twitter.com"):
        try:
            cj = browser_cookie3.chrome(domain_name=domain)
            for c in cj:
                if c.value:
                    cookies[c.name] = c.value
        except Exception:
            continue
    return cookies or None


def _ensure_auth(manual_cookies: Optional[dict] = None) -> dict:
    """auth_token + ct0 が揃った Cookie 辞書を返す"""
    c = _load_cookies_from_chrome() or {}
    if manual_cookies:
        c.update(manual_cookies)
    if "auth_token" not in c or "ct0" not in c:
        raise XAuthError(
            "X (.x.com) の Cookie (auth_token + ct0) が見つかりません。"
            "Chrome で x.com にログイン済みか確認してください。"
        )
    return c


def _headers(cookies: dict, lang: str = "ja") -> dict:
    return {
        "authorization": f"Bearer {WEB_BEARER}",
        "x-csrf-token": cookies["ct0"],
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": lang,
        "User-Agent": UA,
        "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
        "Accept": "*/*",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Referer": "https://x.com/",
        "Origin": "https://x.com",
        "x-twitter-client-language": "ja",
    }


_OP_BLOCK_RE = re.compile(
    r'queryId:"([^"]+)",operationName:"([^"]+)",operationType:"[^"]*",metadata:\{'
    r'featureSwitches:\[([^\]]*)\](?:,fieldToggles:\[([^\]]*)\])?',
)


def _parse_op_blocks(js: str) -> dict:
    """main.js から {operationName: {queryId, featureSwitches, fieldToggles}} を抽出"""
    out: dict[str, dict] = {}
    for m in _OP_BLOCK_RE.finditer(js):
        op = m.group(2)
        fs = re.findall(r'"([^"]+)"', m.group(3) or "")
        ft = re.findall(r'"([^"]+)"', m.group(4) or "")
        out[op] = {"queryId": m.group(1), "featureSwitches": fs, "fieldToggles": ft}
    return out


# 各 featureSwitch のデフォルト値を「主に True」にする。明示的に False が必要なものだけ列挙。
_FEATURE_FALSE_KEYS = {
    "rweb_video_screen_enabled",
    "rweb_cashtags_enabled",
    "responsive_web_profile_redirect_enabled",
    "verified_phone_label_enabled",
    "premium_content_api_read_enabled",
    "responsive_web_grok_analyze_button_fetch_trends_enabled",
    "tweet_awards_web_tipping_enabled",
    "responsive_web_grok_show_grok_translated_post",
    "creator_subscriptions_quote_tweet_preview_enabled",
    "responsive_web_grok_community_note_auto_translation_is_enabled",
    "responsive_web_enhance_cards_enabled",
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled",
    "rweb_xchat_enabled",
    "payments_enabled",
    "hidden_profile_likes_enabled",
    "responsive_web_grok_bio_auto_translation_is_enabled",
    "subscriptions_feature_can_gift_premium",
}


def _build_features(switches: list[str]) -> dict:
    return {k: (k not in _FEATURE_FALSE_KEYS) for k in switches}


def _build_field_toggles(toggles: list[str]) -> dict:
    return {k: True for k in toggles}


def _resolve_query_meta() -> dict:
    """x.com のトップHTMLから main.js を辿り、SearchTimeline / UserByScreenName の
    queryId + featureSwitches + fieldToggles を抽出。プロセス内に TTL キャッシュ。"""
    global _QID_CACHE, _QID_CACHE_AT
    now = time.time()
    if _QID_CACHE and (now - _QID_CACHE_AT) < _QID_CACHE_TTL:
        return _QID_CACHE
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            html = client.get("https://x.com/", headers={"User-Agent": UA}).text
            js_urls = list(set(re.findall(
                r'(https://abs\.twimg\.com/responsive-web/client-web/main\.[a-f0-9]+\.js)', html
            )))
            meta: dict[str, dict] = {}
            wanted = ("SearchTimeline", "UserByScreenName", "Followers", "Following", "UserByRestId")
            for u in js_urls:
                js = client.get(u, headers={"User-Agent": UA}).text
                blocks = _parse_op_blocks(js)
                for op in wanted:
                    if op in blocks and op not in meta:
                        meta[op] = blocks[op]
                if all(op in meta for op in wanted):
                    break
            if meta:
                _QID_CACHE = meta
                _QID_CACHE_AT = now
                return _QID_CACHE
    except Exception:
        pass
    # フォールバック: ハードコード
    _QID_CACHE = {
        "SearchTimeline": {"queryId": DEFAULT_QUERY_IDS["SearchTimeline"], "featureSwitches": [], "fieldToggles": []},
        "UserByScreenName": {"queryId": DEFAULT_QUERY_IDS["UserByScreenName"], "featureSwitches": [], "fieldToggles": []},
    }
    _QID_CACHE_AT = now
    return _QID_CACHE


def _qid(name: str, override: Optional[dict] = None) -> str:
    if override and override.get(name):
        return override[name]
    return _resolve_query_meta().get(name, {}).get("queryId") or DEFAULT_QUERY_IDS[name]


# ---------- 検索 ----------
def fetch_search_users(
    query: str,
    max_users: int = 30,
    manual_cookies: Optional[dict] = None,
    query_ids: Optional[dict] = None,
) -> list[dict]:
    """X 検索クエリ（Latest）から投稿者プロフィール込みで抽出。

    返り値: [{username, full_name, biography, followers, following,
              is_private, is_verified, is_business, category}, ...]
    """
    cookies = _ensure_auth(manual_cookies)
    raw_q = f"{query} lang:ja -is:retweet -is:reply"
    variables = {
        "rawQuery": raw_q,
        "count": min(max(20, max_users * 2), 50),  # 1ツイート = 1ユーザではないので多めに
        "querySource": "typed_query",
        "product": "Latest",
    }
    meta = _resolve_query_meta().get("SearchTimeline") or {}
    qid = (query_ids or {}).get("SearchTimeline") or meta.get("queryId") or DEFAULT_QUERY_IDS["SearchTimeline"]
    features = _build_features(meta.get("featureSwitches") or []) or SEARCH_FEATURES
    field_toggles = _build_field_toggles(meta.get("fieldToggles") or [])
    body = {"variables": variables, "features": features, "queryId": qid}
    if field_toggles:
        body["fieldToggles"] = field_toggles
    url = f"https://api.x.com/graphql/{qid}/SearchTimeline"
    headers = {**_headers(cookies), "content-type": "application/json"}
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        r = client.post(url, headers=headers, content=json.dumps(body, separators=(',', ':')))
    if r.status_code in (401, 403):
        raise XAuthError(f"X 認証失敗 ({r.status_code}): Cookie 期限切れか queryId 古い可能性。本文先頭: {r.text[:200]}")
    if r.status_code == 429:
        raise XAuthError("X rate limit (429): しばらく待つ")
    if r.status_code != 200:
        raise XAuthError(f"SearchTimeline {r.status_code}: {r.text[:200]}")
    try:
        data = r.json()
    except Exception:
        raise XAuthError(f"JSON parse 失敗: {r.text[:200]}")
    if "errors" in data and not data.get("data"):
        raise XAuthError(f"GraphQL errors: {data['errors']}")
    return _extract_users_from_search(data, limit=max_users)


def _extract_users_from_search(data: dict, limit: int = 30) -> list[dict]:
    users: dict[str, dict] = {}
    timeline = (
        data.get("data", {})
        .get("search_by_raw_query", {})
        .get("search_timeline", {})
        .get("timeline", {})
    )
    for inst in timeline.get("instructions", []) or []:
        for entry in inst.get("entries", []) or []:
            content = entry.get("content") or {}
            ic = content.get("itemContent")
            if ic and ic.get("__typename") == "TimelineTweet":
                tweet = (ic.get("tweet_results") or {}).get("result") or {}
                # promoted/quoted の場合は ".tweet" にネスト
                if tweet.get("__typename") == "TweetWithVisibilityResults":
                    tweet = tweet.get("tweet") or {}
                ur = ((tweet.get("core") or {}).get("user_results") or {}).get("result") or {}
                _absorb_user(ur, users)
            # items 配列（"users" モジュールが返ることも）
            items = (content.get("items") or [])
            for it in items:
                ic2 = (it.get("item") or {}).get("itemContent") or {}
                ur2 = (ic2.get("user_results") or {}).get("result") or {}
                _absorb_user(ur2, users)
            if len(users) >= limit:
                return list(users.values())[:limit]
    return list(users.values())[:limit]


def _absorb_user(ur: dict, sink: dict):
    if not ur:
        return
    legacy = ur.get("legacy") or {}
    # __typename "User" or "UserUnavailable"
    uname = legacy.get("screen_name") or ur.get("rest_id_screen_name")
    if not uname:
        # 一部経路では core 側に screen_name が退避される
        core = ur.get("core") or {}
        uname = core.get("screen_name")
    if not uname or uname in sink:
        return
    sink[uname] = {
        "username": uname,
        "full_name": (ur.get("core") or {}).get("name") or legacy.get("name") or "",
        "biography": legacy.get("description", "") or "",
        "followers": legacy.get("followers_count"),
        "following": legacy.get("friends_count"),
        "is_private": bool(legacy.get("protected")),
        "is_verified": bool(ur.get("is_blue_verified")),
        "is_business": bool(legacy.get("verified_type") == "Business"),
        "category": legacy.get("verified_type") or None,
    }


# ---------- プロフィール ----------
def fetch_profile(
    username: str,
    manual_cookies: Optional[dict] = None,
    query_ids: Optional[dict] = None,
) -> Optional[dict]:
    """単一 username のプロフィール取得（UserByScreenName GraphQL）"""
    cookies = _ensure_auth(manual_cookies)
    variables = {"screen_name": username}
    meta = _resolve_query_meta().get("UserByScreenName") or {}
    qid = (query_ids or {}).get("UserByScreenName") or meta.get("queryId") or DEFAULT_QUERY_IDS["UserByScreenName"]
    features = _build_features(meta.get("featureSwitches") or []) or USER_FEATURES
    field_toggles = _build_field_toggles(meta.get("fieldToggles") or []) or USER_FIELD_TOGGLES
    url = (
        f"https://api.x.com/graphql/{qid}/UserByScreenName"
        f"?variables={urllib.parse.quote(json.dumps(variables, separators=(',', ':')))}"
        f"&features={urllib.parse.quote(json.dumps(features, separators=(',', ':')))}"
        f"&fieldToggles={urllib.parse.quote(json.dumps(field_toggles, separators=(',', ':')))}"
    )
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        r = client.get(url, headers=_headers(cookies))
    if r.status_code in (401, 403):
        raise XAuthError(f"X 認証失敗 ({r.status_code})")
    if r.status_code == 429:
        raise XAuthError("X rate limit (429)")
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:
        return None
    ur = ((data.get("data") or {}).get("user") or {}).get("result") or {}
    if not ur or ur.get("__typename") == "UserUnavailable":
        return None
    legacy = ur.get("legacy") or {}
    return {
        "username": username,
        "rest_id": ur.get("rest_id"),
        "full_name": (ur.get("core") or {}).get("name") or legacy.get("name") or "",
        "biography": legacy.get("description", "") or "",
        "followers": legacy.get("followers_count"),
        "following": legacy.get("friends_count"),
        "is_private": bool(legacy.get("protected")),
        "is_verified": bool(ur.get("is_blue_verified")),
        "is_business": bool(legacy.get("verified_type") == "Business"),
        "category": legacy.get("verified_type") or None,
    }


# ---------- フォロワー取得 ----------
def fetch_followers(
    username: str,
    max_count: int = 200,
    manual_cookies: Optional[dict] = None,
    query_ids: Optional[dict] = None,
) -> list[dict]:
    """指定ユーザのフォロワー一覧をプロフィール込みで取得。

    例: fetch_followers("17liveJP", 200) → 17LIVE JP公式の最新フォロワー200人。
    1リクエスト=20人前後。max_count に達するまでカーソル送りで繰り返す。
    """
    cookies = _ensure_auth(manual_cookies)
    prof = fetch_profile(username, manual_cookies=cookies, query_ids=query_ids)
    if not prof or not prof.get("rest_id"):
        # 存在しない/Suspended/タイポ等。AUTHエラーではないので呼出側でスキップさせるため空配列
        return []
    rest_id = prof["rest_id"]

    meta = _resolve_query_meta().get("Followers") or {}
    qid = (query_ids or {}).get("Followers") or meta.get("queryId")
    if not qid:
        raise XAuthError("Followers の queryId が解決できません（main.js 解析失敗）")
    features = _build_features(meta.get("featureSwitches") or [])
    field_toggles = _build_field_toggles(meta.get("fieldToggles") or [])

    out: dict[str, dict] = {}
    cursor: Optional[str] = None
    headers = {**_headers(cookies), "content-type": "application/json"}
    url = f"https://api.x.com/graphql/{qid}/Followers"

    while len(out) < max_count:
        variables = {"userId": rest_id, "count": 20, "includePromotedContent": False}
        if cursor:
            variables["cursor"] = cursor
        body = {"variables": variables, "features": features, "queryId": qid}
        if field_toggles:
            body["fieldToggles"] = field_toggles
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            r = client.post(url, headers=headers, content=json.dumps(body, separators=(',', ':')))
        if r.status_code == 429:
            raise XAuthError("X rate limit (429)")
        if r.status_code != 200:
            raise XAuthError(f"Followers {r.status_code}: {r.text[:200]}")
        data = r.json()
        instructions = (
            data.get("data", {})
            .get("user", {})
            .get("result", {})
            .get("timeline", {})
            .get("timeline", {})
            .get("instructions", []) or []
        )
        new_cursor = None
        added_in_page = 0
        for inst in instructions:
            for entry in inst.get("entries", []) or []:
                eid = entry.get("entryId", "")
                content = entry.get("content") or {}
                if eid.startswith("cursor-bottom-"):
                    new_cursor = content.get("value")
                    continue
                ic = content.get("itemContent") or {}
                if ic.get("__typename") != "TimelineUser":
                    continue
                ur = (ic.get("user_results") or {}).get("result") or {}
                before = len(out)
                _absorb_user(ur, out)
                if len(out) > before:
                    added_in_page += 1
                if len(out) >= max_count:
                    break
            if len(out) >= max_count:
                break
        if not new_cursor or added_in_page == 0:
            break
        cursor = new_cursor
        time.sleep(1.2)
    return list(out.values())[:max_count]


def fetch_profiles(
    usernames: list[str],
    manual_cookies: Optional[dict] = None,
    delay: float = 0.6,
    query_ids: Optional[dict] = None,
) -> list[dict]:
    out: list[dict] = []
    for u in usernames:
        try:
            p = fetch_profile(u, manual_cookies=manual_cookies, query_ids=query_ids)
            if p:
                out.append(p)
        except XAuthError:
            raise
        except Exception as e:
            out.append({"username": u, "error": str(e)})
        time.sleep(delay)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="x_internal の動作確認")
    ap.add_argument("--query", help="検索キーワード")
    ap.add_argument("--profile", help="ユーザ名")
    ap.add_argument("--followers", help="ユーザ名のフォロワーを取得")
    ap.add_argument("--max", type=int, default=10)
    args = ap.parse_args()
    if args.query:
        users = fetch_search_users(args.query, max_users=args.max)
        print(f"=== {args.query}: {len(users)}件 ===")
        for u in users:
            print(f"@{u['username']:20s} fl={u['followers']} fw={u['following']} | {u['full_name']}")
    if args.profile:
        p = fetch_profile(args.profile)
        print(json.dumps(p, ensure_ascii=False, indent=2))
    if args.followers:
        users = fetch_followers(args.followers, max_count=args.max)
        print(f"=== @{args.followers} のフォロワー {len(users)}件 ===")
        for u in users:
            print(f"@{u['username']:20s} fl={u['followers']} fw={u['following']} | {u['full_name'][:30]}")
