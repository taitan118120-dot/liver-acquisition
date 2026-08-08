#!/usr/bin/env python3
"""X(@taitan_LIVER) の健康診断。

なぜ必要か:
  cloud_analyze.py は「投稿ごとのスコア」しか出さないので、
  「インプが伸びない」のがコンテンツのせいなのかアカウントのせいなのか切り分けられない。
  フォロワー数が分かって初めて「1投稿あたりのリーチ率」が計算でき、
  リーチ率が極端に低ければコンテンツ改善より先にアカウント側の問題を疑える。

GitHub Secrets にしかトークンが無いので x_health_check.yml から workflow_dispatch で回す。

出力:
  - フォロワー/フォロー/総投稿数
  - 直近投稿のインプ中央値、フォロワー比リーチ率
  - 本体投稿 vs リプライ(CTA)別の内訳
  - ハッシュタグ数 / 画像有無 / 文字数 別のインプ中央値
"""

import os
import statistics
from collections import defaultdict

import tweepy


def med(values):
    return statistics.median(values) if values else 0


def main() -> int:
    client = tweepy.Client(
        bearer_token=os.environ["TWITTER_BEARER_TOKEN"],
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )

    me = client.get_me(user_fields=["public_metrics", "description", "url", "created_at"])
    if not me or not me.data:
        print("[ERROR] ユーザー情報を取得できませんでした")
        return 1

    u = me.data
    pm = u.public_metrics or {}
    followers = pm.get("followers_count", 0)
    print("=" * 60)
    print(f"  @{u.username} 健康診断")
    print("=" * 60)
    print(f"フォロワー   : {followers}")
    print(f"フォロー中   : {pm.get('following_count', 0)}")
    print(f"総投稿数     : {pm.get('tweet_count', 0)}")
    print(f"リスト登録数 : {pm.get('listed_count', 0)}")
    print(f"アカウント作成: {getattr(u, 'created_at', None)}")
    print(f"URL欄        : {getattr(u, 'url', None) or '(未設定)'}")
    print()

    tweets = client.get_users_tweets(
        id=u.id,
        max_results=100,
        tweet_fields=["created_at", "public_metrics", "text", "referenced_tweets", "attachments"],
        expansions=["attachments.media_keys"],
    )
    if not tweets or not tweets.data:
        print("[ERROR] 投稿を取得できませんでした")
        return 1

    main_posts, replies = [], []
    for t in tweets.data:
        refs = t.referenced_tweets or []
        (replies if any(r.type == "replied_to" for r in refs) else main_posts).append(t)

    def imps(ts):
        return [t.public_metrics["impression_count"] for t in ts]

    all_imps = imps(tweets.data)
    main_imps = imps(main_posts)
    print(f"取得投稿数   : {len(tweets.data)} 件（本体 {len(main_posts)} / リプライ {len(replies)}）")
    print(f"インプ中央値 : 全体 {med(all_imps)} / 本体 {med(main_imps)} / リプ {med(imps(replies))}")
    print(f"インプ最大   : {max(all_imps) if all_imps else 0}")
    if followers:
        print(f"リーチ率     : 本体中央値 {med(main_imps)} ÷ フォロワー {followers} = "
              f"{med(main_imps) / followers * 100:.1f}%")
        print("  ※健全な小規模アカウントの目安は 30〜100%。10%未満なら配信が抑制されている疑い。")
    print()

    tot = defaultdict(int)
    for t in tweets.data:
        for k in ("like_count", "retweet_count", "reply_count", "quote_count"):
            tot[k] += t.public_metrics[k]
    print(f"直近合計     : いいね {tot['like_count']} / RT {tot['retweet_count']} / "
          f"リプ {tot['reply_count']} / 引用 {tot['quote_count']}")
    print()

    media_keys = set()
    inc = tweets.includes or {}
    for m in inc.get("media", []):
        media_keys.add(m.media_key)

    def group(label, keyfn, ts):
        buckets = defaultdict(list)
        for t in ts:
            buckets[keyfn(t)].append(t.public_metrics["impression_count"])
        print(f"[{label}]")
        for k in sorted(buckets, key=str):
            v = buckets[k]
            print(f"  {k}: n={len(v)} 中央値={med(v)}")
        print()

    group("ハッシュタグ数（本体のみ）", lambda t: t.text.count("#"), main_posts)
    group("画像添付（本体のみ）",
          lambda t: "あり" if (t.attachments or {}).get("media_keys") else "なし", main_posts)
    group("文字数帯（本体のみ）",
          lambda t: f"{len(t.text) // 50 * 50}〜", main_posts)
    group("投稿時刻JST（本体のみ）",
          lambda t: f"{(t.created_at.hour + 9) % 24:02d}時", main_posts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
