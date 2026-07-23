"""X (Twitter) 投稿スクリプト — x_content/x_posts.json のキューから投稿する。

認証は x_internal.py を流用（Chrome の auth_token + ct0 Cookie 経由 / 無料・有料API不要）。
投稿は GraphQL CreateTweet。queryId は main.js から動的解決し、失敗時はフォールバック。

使い方:
  python x_app/x_poster.py --next --dry-run   # 次の1本を投稿せず確認
  python x_app/x_poster.py --next             # 次の未投稿1本を投稿
  python x_app/x_poster.py --text "本文"       # 任意テキストを直接投稿
  python x_app/x_poster.py --list             # キュー状況を表示

注意: 内部API投稿はアカウント保護のため 1回1本・自然な間隔で。連投しない。
"""
import os, sys, json, argparse, datetime, re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

import httpx  # x_internal も使用
import x_internal as xi

POSTS_FILE = os.path.join(ROOT, "x_content", "x_posts.json")
LOG_FILE = os.path.join(ROOT, "x_content", "x_post_log.csv")

# main.js から解決できなかった場合のフォールバック（queryId は時々変わる）
FALLBACK_CREATETWEET_QID = "DQIp0b4mKIciCAZ3bfrwAA"  # 解決失敗時のみ使用（2026-06時点の実値）


def _resolve_createtweet():
    """main.js を辿って CreateTweet の queryId / featureSwitches / fieldToggles を取得。"""
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            html = client.get("https://x.com/", headers={"User-Agent": xi.UA}).text
            js_urls = list(set(re.findall(
                r'(https://abs\.twimg\.com/responsive-web/client-web/main\.[a-f0-9]+\.js)', html)))
            for u in js_urls:
                js = client.get(u, headers={"User-Agent": xi.UA}).text
                blocks = xi._parse_op_blocks(js)
                if "CreateTweet" in blocks:
                    return blocks["CreateTweet"]
    except Exception as e:
        print(f"[warn] CreateTweet 解決失敗: {e}")
    return {"queryId": FALLBACK_CREATETWEET_QID, "featureSwitches": [], "fieldToggles": []}


# CreateTweet で最低限必要な features（main.js から取れなかった時の保険）
_FALLBACK_FEATURES = {
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}


def create_tweet(text, cookies=None, dry_run=False):
    cookies = xi._ensure_auth(cookies)
    meta = _resolve_createtweet()
    qid = meta.get("queryId") or FALLBACK_CREATETWEET_QID
    features = xi._build_features(meta["featureSwitches"]) if meta.get("featureSwitches") else dict(_FALLBACK_FEATURES)
    variables = {
        "tweet_text": text,
        "dark_request": False,
        "media": {"media_entities": [], "possibly_sensitive": False},
        "semantic_annotation_ids": [],
    }
    payload = {"variables": variables, "features": features, "queryId": qid}
    if meta.get("fieldToggles"):
        payload["fieldToggles"] = xi._build_field_toggles(meta["fieldToggles"])

    if dry_run:
        print("---- DRY RUN (X) ----")
        print(text)
        print(f"[len] {len(text)}  [queryId] {qid}")
        return None

    headers = xi._headers(cookies)
    headers["content-type"] = "application/json"
    url = f"https://api.x.com/graphql/{qid}/CreateTweet"
    r = httpx.post(url, headers=headers, json=payload, timeout=25.0)
    if r.status_code != 200:
        raise RuntimeError(f"投稿失敗 HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(f"投稿エラー: {data['errors']}")
    try:
        rest_id = data["data"]["create_tweet"]["tweet_results"]["result"]["rest_id"]
    except Exception:
        rest_id = "?"
    return rest_id


def _load():
    with open(POSTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save(posts):
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def _log(pid, status, rest_id, note=""):
    new = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        if new:
            f.write("posted_at,id,status,rest_id,note\n")
        ts = datetime.datetime.now().isoformat()
        f.write(f"{ts},{pid},{status},{rest_id},{note}\n")


def cmd_next(dry_run=False):
    posts = _load()
    target = next((p for p in posts if not p.get("posted")), None)
    if not target:
        print("未投稿の投稿がありません。"); return
    print(f"[next] id={target.get('id')} cat={target.get('category','')}")
    try:
        rest_id = create_tweet(target["text"], dry_run=dry_run)
    except Exception as e:
        print(f"[ERROR] {e}")
        if not dry_run:
            _log(target.get("id"), "error", "", str(e)[:80].replace(",", " "))
        return
    if dry_run:
        return
    target["posted"] = True
    target["posted_at"] = datetime.datetime.now().isoformat()
    target["rest_id"] = rest_id
    _save(posts)
    _log(target.get("id"), "posted", rest_id)
    print(f"[OK] 投稿しました rest_id={rest_id}  https://x.com/i/status/{rest_id}")


def cmd_list():
    posts = _load()
    done = sum(1 for p in posts if p.get("posted"))
    print(f"合計{len(posts)}本 / 投稿済{done} / 残り{len(posts)-done}")
    nxt = next((p for p in posts if not p.get("posted")), None)
    if nxt:
        print(f"次: [{nxt.get('category','')}] {nxt['text'][:38].replace(chr(10),' ')}...")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--next", action="store_true", help="キューから次の1本を投稿")
    ap.add_argument("--text", help="任意テキストを直接投稿")
    ap.add_argument("--list", action="store_true", help="キュー状況を表示")
    ap.add_argument("--dry-run", action="store_true", help="投稿せず確認")
    a = ap.parse_args()
    if a.list:
        cmd_list()
    elif a.text:
        rid = create_tweet(a.text, dry_run=a.dry_run)
        if rid:
            print(f"[OK] rest_id={rid}  https://x.com/i/status/{rid}")
    elif a.next:
        cmd_next(dry_run=a.dry_run)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
