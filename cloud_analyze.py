"""
投稿分析スクリプト
過去の投稿のエンゲージメントを取得し、
伸びた投稿と伸びなかった投稿を分析する。
週1回実行して改善に活かす。
"""

import os
import json
import tweepy


def main():
    client = tweepy.Client(
        bearer_token=os.environ["TWITTER_BEARER_TOKEN"],
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )

    # 自分のツイートを取得（直近50件）
    try:
        me = client.get_me()
        if not me or not me.data:
            print("[ERROR] ユーザー情報を取得できませんでした")
            return
        user_id = me.data.id
    except (tweepy.errors.TweepyException, Exception) as e:
        print(f"[ERROR] ユーザー情報取得失敗: {e}")
        return

    try:
        tweets = client.get_users_tweets(
            id=user_id,
            max_results=50,
            tweet_fields=["created_at", "public_metrics", "text"],
        )
    except tweepy.errors.TooManyRequests:
        print("[ERROR] レート制限。次回の実行まで待機。")
        return
    except (tweepy.errors.TweepyException, Exception) as e:
        print(f"[ERROR] ツイート取得失敗: {e}")
        return

    if not tweets.data:
        print("ツイートなし")
        return

    # 分析
    results = []
    for t in tweets.data:
        metrics = t.public_metrics
        score = (
            metrics["like_count"] * 1
            + metrics["retweet_count"] * 3
            + metrics["reply_count"] * 2
            + metrics["quote_count"] * 4
            + metrics["impression_count"] * 0.001
        )
        results.append({
            "id": t.id,
            "text": t.text[:80],
            "created_at": str(t.created_at),
            "likes": metrics["like_count"],
            "retweets": metrics["retweet_count"],
            "replies": metrics["reply_count"],
            "quotes": metrics["quote_count"],
            "impressions": metrics["impression_count"],
            "score": round(score, 2),
        })

    # スコア順にソート
    results.sort(key=lambda x: x["score"], reverse=True)

    # レポート出力
    print("=" * 60)
    print("  投稿パフォーマンス分析レポート")
    print("=" * 60)

    print("\n🏆 TOP5（伸びた投稿）")
    for i, r in enumerate(results[:5], 1):
        print(f"\n  [{i}位] スコア: {r['score']}")
        print(f"  📊 いいね:{r['likes']} RT:{r['retweets']} リプ:{r['replies']} 表示:{r['impressions']}")
        print(f"  📝 {r['text']}...")

    print("\n\n📉 WORST3（伸びなかった投稿）")
    for i, r in enumerate(results[-3:], 1):
        print(f"\n  [{i}] スコア: {r['score']}")
        print(f"  📊 いいね:{r['likes']} RT:{r['retweets']} リプ:{r['replies']} 表示:{r['impressions']}")
        print(f"  📝 {r['text']}...")

    # 傾向分析
    print("\n\n📈 傾向分析")
    avg_score = sum(r["score"] for r in results) / len(results)
    print(f"  平均スコア: {round(avg_score, 2)}")

    # 伸びた投稿の共通パターン
    top5_texts = [r["text"] for r in results[:5]]
    patterns = {
        "質問系": sum(1 for t in top5_texts if "？" in t),
        "あるある系": sum(1 for t in top5_texts if "あるある" in t),
        "リスト系": sum(1 for t in top5_texts if "→" in t or "・" in t),
        "ストーリー系": sum(1 for t in top5_texts if "ヶ月" in t),
        "ぶっちゃけ系": sum(1 for t in top5_texts if "ぶっちゃけ" in t or "正直" in t or "リアル" in t),
    }

    print("\n  伸びた投稿のパターン:")
    for pattern, count in sorted(patterns.items(), key=lambda x: -x[1]):
        if count > 0:
            bar = "█" * count
            print(f"    {pattern}: {count}件 {bar}")

    print("\n\n💡 改善ヒント")
    best = results[0]
    if "？" in best["text"]:
        print("  → 質問系が伸びてる！もっと質問形式の投稿を増やそう")
    if "あるある" in best["text"]:
        print("  → あるある系がウケてる！共感ネタを深掘りしよう")
    if "→" in best["text"]:
        print("  → リスト・比較系が人気！「○○ vs △△」形式を増やそう")

    # JSON保存
    os.makedirs("data", exist_ok=True)
    with open("data/analysis_report.json", "w", encoding="utf-8") as f:
        json.dump({
            "results": results,
            "avg_score": avg_score,
            "patterns": patterns,
        }, f, ensure_ascii=False, indent=2)

    print("\n\nレポートを data/analysis_report.json に保存しました")


if __name__ == "__main__":
    main()
