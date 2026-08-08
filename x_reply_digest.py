#!/usr/bin/env python3
"""毎朝「今日リプすべきX投稿」を10件抽出して Markdown ダイジェストを出力する。

なぜ必要か（2026-08-08 の健康診断より）:
  @taitan_LIVER は783投稿してフォロワー16人。シャドウバンではなく（リーチ率153%）、
  単に「投稿するだけ」ではXでフォロワーが増えないだけ。
  Xでフォロワーを増やす手段はリプライ・引用しかないが、リプライ自動化はBAN対象。
  → 自動化するのは「誰にリプすべきかの選定」までにして、送信は必ず人間がやる。

2種類を混ぜて出す:
  A. 共感リプ（フォロワー獲得狙い）… 小規模なターゲット層の新鮮な投稿。
     相手に確実に読まれるのでフォロバ・認知につながる。
  B. 露出リプ（インプ獲得狙い）… フォロワーの多いアカウントの投稿直後に付けるリプ。
     相手のリプ欄に人が集まるので、自分の投稿24インプとは桁違いの露出になる。

出力: data/x_reply_digest.md（ワークフローがこれをGitHub Issue本文にする）
重複防止: data/x_reply_seen.json に出した tweet_id を保存

送信は絶対に自動化しないこと（メモリ feedback_no_reply.md）。
"""

import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import tweepy

from cloud_engage import is_ng

JST = timezone(timedelta(hours=9))

SEEN_FILE = "data/x_reply_seen.json"
OUT_FILE = "data/x_reply_digest.md"
SEEN_KEEP = 3000  # 肥大化防止

# ─── A. 共感リプ用（ターゲット層本人を探す）───
# 「今まさに始めた／悩んでる」人。こちらが一言かけると刺さる瞬間の投稿を狙う。
EMPATHY_QUERIES = [
    "初配信 緊張",
    "配信 誰も来ない",
    "リスナー 増えない",
    "Pococha 始めた",
    "ライバー 始めたい",
    "配信 続かない",
    "副業 始めたい 在宅",
    "配信 楽しかった",
]

# ─── B. 露出リプ用（人が集まっている場所を探す）───
# ニッチの中で反応が付いている投稿。リプ欄に第三者の目がある。
REACH_QUERIES = [
    "ライブ配信 ライバー",
    "Pococha ランク",
    "ライバー 事務所",
    "TikTok LIVE 配信",
    "配信者 悩み",
]

# リプの書き出しヒント（そのままコピペせず、必ず1文は自分の言葉に直すこと）
# 同じ文面を繰り返すとスパム判定される。あくまで「書き出しの型」。
EMPATHY_HINTS = [
    "同じ状況だった子の実例を1つだけ添えて共感する",
    "「それ最初は全員そうです」＋具体的に何日くらいで変わるかを添える",
    "相手の言葉を1つ拾って復唱してから、自分の失敗談を短く",
    "質問で返す（どのアプリ？何時に配信してる？）— 会話が続くと露出が伸びる",
    "褒めるポイントを1つだけ具体的に指定して伝える",
]
REACH_HINTS = [
    "本文に対して自分の立場を1つ足す（賛成でも反対でもいい、曖昧にしない）",
    "4年見てきた側の一次情報を1つだけ置く（数字は確定ファクトのみ）",
    "元の投稿に無い視点を1つ足す（例: リスナー側から見るとどうか）",
    "自分の現場で実際にあったケースを1行で",
]

# リプに入れてはいけないもの（入れると宣伝アカ判定されてリーチが落ちる）
FORBIDDEN_IN_REPLY = ["リンク", "LINE", "特典PDF", "事務所への勧誘", "DMください"]


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return []
    try:
        with open(SEEN_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_seen(seen):
    os.makedirs("data", exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump(seen[-SEEN_KEEP:], f)


def search(client, query, max_results=30):
    """検索して (tweet, user) のリストを返す。失敗しても止めない。"""
    try:
        resp = client.search_recent_tweets(
            query=f"{query} -is:retweet -is:reply lang:ja",
            max_results=max_results,
            tweet_fields=["author_id", "created_at", "public_metrics", "text"],
            user_fields=["username", "name", "description", "public_metrics"],
            expansions=["author_id"],
        )
    except Exception as e:  # レート制限含め、1クエリ失敗で全体を落とさない
        print(f"  [WARN] 検索失敗 ({query}): {e}")
        return []

    if not resp or not resp.data:
        return []
    users = {u.id: u for u in (resp.includes or {}).get("users", [])}
    return [(t, users[t.author_id]) for t in resp.data if t.author_id in users]


def hours_ago(created_at):
    return (datetime.now(timezone.utc) - created_at).total_seconds() / 3600


def collect(client, queries, seen, my_id, keep, mode):
    """mode='empathy' or 'reach' で採点基準を変えて候補を集める"""
    cands = []
    picked_authors = set()
    for q in queries:
        for t, u in search(client, q):
            if str(t.id) in seen or u.id == my_id:
                continue
            if is_ng(u.description, tweet_text=t.text):
                continue

            fol = (u.public_metrics or {}).get("followers_count", 0)
            pm = t.public_metrics or {}
            age = hours_ago(t.created_at)

            if mode == "empathy":
                # 小〜中規模の生身の人。大きすぎる＝業者/インフルで反応が返らない
                if not (20 <= fol <= 3000):
                    continue
                if age > 18:  # 古い投稿にリプしても本人が見ない
                    continue
                # 新しくて、まだリプが少ない＝自分のリプが埋もれない
                score = 100 - age * 3 - pm.get("reply_count", 0) * 5
            else:
                # 人が集まっている投稿。ただし投稿直後でないとリプが埋もれる
                if fol < 1000:
                    continue
                if age > 6:
                    continue
                score = (
                    pm.get("like_count", 0) * 2
                    + pm.get("reply_count", 0)
                    + fol / 500
                    - age * 8
                )

            cands.append({
                "id": str(t.id),
                "url": f"https://x.com/{u.username}/status/{t.id}",
                "username": u.username,
                "name": u.name,
                "followers": fol,
                "age_h": round(age, 1),
                "likes": pm.get("like_count", 0),
                "replies": pm.get("reply_count", 0),
                "text": t.text.replace("\n", " ")[:140],
                "query": q,
                "score": round(score, 1),
            })

    cands.sort(key=lambda c: -c["score"])
    # 同じ人に何件もリプしない
    out = []
    for c in cands:
        if c["username"] in picked_authors:
            continue
        picked_authors.add(c["username"])
        out.append(c)
        if len(out) >= keep:
            break
    return out


def render(empathy, reach):
    today = datetime.now(JST).strftime("%Y-%m-%d (%a)")
    lines = [
        f"# 今日のXリプ候補 — {today}",
        "",
        "**所要10分。上から順にリンクを開いて、一言返すだけ。**",
        "",
        "ルール（これを守らないと逆効果になります）:",
        "- リンク・LINE・特典・事務所の話は**リプに書かない**。宣伝アカ判定されてリーチが落ちます。",
        "- ヒントはそのままコピペしない。**最低1文は自分の言葉**に直す（同一文の連投はスパム判定）。",
        "- 相手のプロフに飛んでもらうのが目的。売り込みは固定ポストとプロフ欄に任せる。",
        "- 返信が来たらもう一往復する。会話が伸びるほどリプ欄の表示時間が伸びます。",
        "",
    ]

    def block(title, note, items, hints):
        lines.append(f"## {title}")
        lines.append(f"_{note}_")
        lines.append("")
        if not items:
            lines.append("該当なし（検索がレート制限に当たったか、条件に合う投稿が無かった）")
            lines.append("")
            return
        for i, c in enumerate(items, 1):
            lines.append(
                f"### {i}. [@{c['username']}]({c['url']}) "
                f"（{c['followers']}フォロワー / {c['age_h']}時間前 / ♥{c['likes']} 💬{c['replies']}）"
            )
            lines.append(f"> {c['text']}")
            lines.append("")
            lines.append(f"**書き出しの型**: {random.choice(hints)}")
            lines.append("")

    block(
        "A. 共感リプ（フォロワーを増やす）",
        "始めたて・悩んでる本人。ここは相手に確実に読まれるので、フォロバと将来の応募につながる。",
        empathy,
        EMPATHY_HINTS,
    )
    block(
        "B. 露出リプ（インプを稼ぐ）",
        "人が集まっている投稿。ここのリプ欄は自分の投稿(中央値24インプ)より桁違いに見られる。早い者勝ち。",
        reach,
        REACH_HINTS,
    )

    lines += [
        "---",
        "",
        "終わったらこのIssueを閉じてください。",
        "生成: `x_reply_digest.py`（送信は自動化しません。リプライ自動化はBAN対象）",
    ]
    return "\n".join(lines)


def main() -> int:
    client = tweepy.Client(
        bearer_token=os.environ["TWITTER_BEARER_TOKEN"],
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )

    try:
        me = client.get_me()
        my_id = me.data.id if me and me.data else None
    except Exception as e:
        print(f"[WARN] get_me 失敗（自分の投稿の除外だけ効かなくなる）: {e}")
        my_id = None

    seen = load_seen()
    seen_set = set(seen)

    # レート制限を避けるため各モード3クエリまで
    empathy = collect(client, random.sample(EMPATHY_QUERIES, 3), seen_set, my_id, 5, "empathy")
    reach = collect(client, random.sample(REACH_QUERIES, 3), seen_set, my_id, 5, "reach")

    if not empathy and not reach:
        print("[ERROR] 候補が0件。検索が全滅した可能性が高い（レート制限/権限）")
        return 1

    body = render(empathy, reach)
    os.makedirs("data", exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(body)

    save_seen(seen + [c["id"] for c in empathy + reach])
    print(body)
    print(f"\n→ {OUT_FILE} に出力（共感{len(empathy)}件 / 露出{len(reach)}件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
