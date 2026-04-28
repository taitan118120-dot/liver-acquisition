"""X (Twitter) API 薄ラッパー

データ取得経路は2つ:
  1. tweepy + Bearer Token (X API v2) — クラウドOK
     - 環境変数 TWITTER_BEARER_TOKEN または settings.x_bearer_token
     - 検索: tweets/search/recent (Basicプラン以上推奨。Free枠は100reads/月)
     - プロフィール: users/by/username (公開メトリクスのみ)
  2. claude-in-chrome 経由で x.com 内部API → /api/ingest にPOST
     - クラウドFlask自体はscrapingしない。Macからオフラインで流し込む
     - メモリ「X自動化システム構成」の @taitan_LIVER ログイン済みChromeを利用

Bearerが無い/エラーの場合は XAuthError を投げる。呼出側 (app.py) で握りつぶす。
"""
from __future__ import annotations

import os
import time
from typing import Optional


class XAuthError(RuntimeError):
    pass


def _bearer_token(manual: str = "") -> str:
    tok = (manual or "").strip() or os.environ.get("TWITTER_BEARER_TOKEN", "").strip()
    if not tok:
        raise XAuthError(
            "TWITTER_BEARER_TOKEN が未設定です。"
            "Bearer無しの場合はクラウドでのリサーチは出来ないため、"
            "Macのclaude-in-chrome経由で取得して /api/ingest に投げてください。"
        )
    return tok


def _client(bearer: str):
    """tweepy client (lazy import)"""
    try:
        import tweepy  # type: ignore
    except ImportError as e:
        raise XAuthError(f"tweepy が入っていません: {e}")
    return tweepy.Client(bearer_token=bearer, wait_on_rate_limit=False)


def fetch_search_users(query: str, max_users: int = 20, manual_bearer: str = "") -> list[dict]:
    """X検索クエリから投稿者ユーザーを抽出。
    日本語ツイート、リツイート/リプライ除外。"""
    client = _client(_bearer_token(manual_bearer))
    full_q = f"{query} -is:retweet -is:reply lang:ja"
    try:
        resp = client.search_recent_tweets(
            query=full_q,
            max_results=min(max(10, max_users), 100),
            tweet_fields=["author_id", "created_at"],
            expansions=["author_id"],
            user_fields=["name", "username", "description", "public_metrics", "verified", "protected"],
        )
    except Exception as e:
        raise XAuthError(f"search_recent_tweets エラー: {e}")

    if not resp or not resp.data:
        return []
    users_by_id = {u.id: u for u in (resp.includes.get("users") or [])}
    out: dict[str, dict] = {}
    for t in resp.data:
        u = users_by_id.get(t.author_id)
        if not u:
            continue
        if u.username in out:
            continue
        pm = u.public_metrics or {}
        out[u.username] = {
            "username": u.username,
            "full_name": u.name or "",
            "biography": u.description or "",
            "followers": pm.get("followers_count"),
            "following": pm.get("following_count"),
            "is_private": bool(getattr(u, "protected", False)),
            "is_verified": bool(getattr(u, "verified", False)),
            "is_business": False,
            "category": None,
        }
    return list(out.values())


def fetch_profile(username: str, manual_bearer: str = "") -> Optional[dict]:
    """単一ユーザーのプロフィール取得"""
    client = _client(_bearer_token(manual_bearer))
    try:
        resp = client.get_user(
            username=username,
            user_fields=["name", "username", "description", "public_metrics", "verified", "protected", "location"],
        )
    except Exception as e:
        raise XAuthError(f"get_user エラー: {e}")
    u = getattr(resp, "data", None)
    if not u:
        return None
    pm = u.public_metrics or {}
    return {
        "username": u.username,
        "full_name": u.name or "",
        "biography": u.description or "",
        "followers": pm.get("followers_count"),
        "following": pm.get("following_count"),
        "is_private": bool(getattr(u, "protected", False)),
        "is_verified": bool(getattr(u, "verified", False)),
        "is_business": False,
        "category": None,
    }


def fetch_profiles(usernames: list[str], manual_bearer: str = "", delay: float = 0.4) -> list[dict]:
    out = []
    for u in usernames:
        try:
            p = fetch_profile(u, manual_bearer=manual_bearer)
            if p:
                out.append(p)
        except XAuthError:
            raise
        except Exception as e:
            out.append({"username": u, "error": str(e)})
        time.sleep(delay)
    return out
