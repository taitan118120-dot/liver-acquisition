#!/usr/bin/env python3
"""x_purge_violations.py — 公開済みXポストから確定ファクト違反を探して消す
========================================================================
2026-08-09。x_post_guard.py で生成側・投稿側の両方を塞いだが、
**すでに公開されてしまった分**は残っている。2026-08-08 の実測で確認できたのは:
    「結論から言うと、9割の副業ライバーはフリーで十分。」        (evo_413 由来)
    「20代女性が…成功する奴は10人に1人もいない。」               (evo_283 由来)
キューを走査した限り同型は47本あり、うち25本は今の周回で投稿済みだった。

cloud_post.py は tweet_id をどこにも保存していない（data/recent_post_ids.txt に
入るのはキュー側のIDだけ）ので、消すにはタイムラインを引いて本文照合するしかない。

安全側の設計:
  - 既定は **dry-run**。--delete を明示したときだけ実際に消す
  - 既定の対象は **割合統計だけ**（--reasons all で全違反に広げられる）。
    「リスナー」の呼び捨て等まで一括削除すると数ヶ月分のポストが消えるので、
    削除は「事実として誤っているもの」に限る
  - 削除は取り消せないので、消す前に必ず data/x_purge_report.json に全文を残す

X API の認証情報は GitHub Secrets にしか無いため、実行は Actions 経由
（.github/workflows/x_purge_violations.yml を workflow_dispatch）。

使い方:
  python3 x_purge_violations.py                      # dry-run（割合統計のみ）
  python3 x_purge_violations.py --reasons all        # dry-run（全違反）
  python3 x_purge_violations.py --delete             # 実削除（割合統計のみ）
"""

import argparse
import json
import os
import sys

import tweepy

from x_post_guard import details

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_FILE = os.path.join(BASE_DIR, "data", "x_purge_report.json")

# 1回の実行で取りに行くツイート数の上限。読み取り枠を食い潰さないよう抑える。
MAX_TWEETS = 800
PAGE_SIZE = 100


def build_client():
    return tweepy.Client(
        bearer_token=os.environ.get("TWITTER_BEARER_TOKEN", ""),
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )


def fetch_timeline(client):
    """自分のツイートを新しい順に取得する。取得できた分だけ返す。"""
    me = client.get_me()
    uid = me.data.id
    out, token = [], None
    while len(out) < MAX_TWEETS:
        resp = client.get_users_tweets(
            id=uid,
            max_results=PAGE_SIZE,
            tweet_fields=["text", "created_at"],
            pagination_token=token,
        )
        if not resp.data:
            break
        out += [{"id": str(t.id), "text": t.text,
                 "created_at": str(t.created_at)} for t in resp.data]
        token = (resp.meta or {}).get("next_token")
        if not token:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delete", action="store_true", help="実際に削除する")
    ap.add_argument("--reasons", choices=["ratio", "all"], default="ratio",
                    help="ratio=出典なしの割合統計のみ（既定） / all=全違反")
    args = ap.parse_args()

    client = build_client()
    tweets = fetch_timeline(client)
    print(f"タイムライン取得: {len(tweets)}件"
          + (f"（{tweets[-1]['created_at'][:10]} 〜 {tweets[0]['created_at'][:10]}）"
             if tweets else ""))

    targets = []
    for t in tweets:
        d = details(t["text"])
        if args.reasons == "ratio":
            d = [x for x in d if "割合統計" in x[0]]
        if d:
            targets.append({**t, "reasons": [{"reason": r, "hit": h} for r, h in d]})

    print(f"該当: {len(targets)}件（対象={args.reasons}）")
    for t in targets:
        print(f"  {t['id']} {t['created_at'][:10]} "
              f":: {', '.join(r['reason'] for r in t['reasons'])}")
        print(f"     {t['text'][:70]}".replace("\n", " "))

    # 削除は取り消せない。消す前に必ず全文を残す。
    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump({"scanned": len(tweets), "reasons": args.reasons,
                   "deleted": args.delete, "targets": targets},
                  f, ensure_ascii=False, indent=1)
    print(f"→ {os.path.relpath(REPORT_FILE, BASE_DIR)} に保存")

    if not args.delete:
        print("\n[dry-run] 削除はしていません。--delete で実行されます。")
        return 0

    ok = 0
    for t in targets:
        try:
            client.delete_tweet(t["id"])
            ok += 1
            print(f"  🗑 削除: {t['id']}")
        except Exception as e:
            print(f"  ⚠️ 削除失敗 {t['id']}: {type(e).__name__}: {e}")
    print(f"\n{ok}/{len(targets)}件を削除しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
