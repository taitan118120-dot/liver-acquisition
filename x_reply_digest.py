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
# 「今まさに始めた／悩んでる」本人。こちらが一言かけると刺さる瞬間の投稿を狙う。
# OR で束ねて1リクエストに詰める（検索のレート制限を節約するため）。
EMPATHY_QUERIES = [
    '("ライバー 始めたい" OR "ライバー やってみたい" OR "配信 始めたい" OR "Pococha 始め" OR "初配信")',
    '("リスナー 増えない" OR "配信 誰も来ない" OR "配信 伸びない" OR "配信 続かない")',
    '("ライバー事務所" OR "ライバー 事務所") (迷 OR 不安 OR どこ OR おすすめ OR 怪しい)',
    '("副業 始めたい" OR "在宅ワーク 探し" OR "副業 何がいい") (スマホ OR 在宅 OR 夜)',
]

# ─── B. 露出リプ用（人が集まっている場所を探す）───
# ニッチの中で反応が付いている投稿。リプ欄に第三者の目がある。
REACH_QUERIES = [
    '(ライバー OR ライブ配信) (稼 OR 収入 OR 現実 OR 事務所)',
    '(Pococha OR ぽこちゃ) (ランク OR ダイヤ OR イベント OR 応援)',
    '(配信者 OR ライバー) (悩み OR しんどい OR メンタル OR 辞め)',
    '("TikTok LIVE" OR 17LIVE OR イチナナ) (配信 OR ライバー)',
]

# ─── ドメイン判定 ───
# これが本文にもプロフにも無い投稿は、こちらの土俵の外（怪談・バンド・パチンコ等）。
# 4年分の一次情報で語れないところにリプしても会話にならないので落とす。

# 獲得ターゲットのプラットフォーム（メモリ feedback_note_target_platforms）。重み高め。
PRIMARY_PLATFORMS = [
    "pococha", "ぽこちゃ", "ポコチャ", "ポコチャ",
    "tiktok live", "tiktoklive", "ティックトックライブ", "tiktokライブ",
    "17live", "イチナナ", "17ライブ",
]
# 隣接プラットフォーム・一般語。ターゲットではないが会話は成立する。
DOMAIN_LIVER = PRIMARY_PLATFORMS + [
    "ライバー", "ライブ配信", "配信者", "配信アプリ", "投げ銭",
    "iriam", "イリアム", "ふわっち", "showroom", "ミクチャ", "ツイキャス",
]
# 副業層。共感リプでは拾うが、露出リプでは使わない
# （副業タグの大型アカウントは情報商材・AI副業・物販ばかりでリプ欄に居るのが客層違い）。
DOMAIN_SIDEJOB = ["副業", "在宅ワーク", "スマホ副業", "おうちワーク"]

# 界隈が違うので落とす。B枠が稼ぐ系・ギャンブル系に流れるのを防ぐ。
OFF_TOPIC_WORDS = [
    "パチンコ", "パチスロ", "スロット", "競馬", "ボートレース", "競艇", "遊技",
    "uber", "ウーバー", "出前館", "配達員",
    "fx", "バイナリー", "仮想通貨", "ビットコイン", "投資",
    "ai副業", "コンテンツ販売", "物販", "せどり", "転売", "アフィリ", "brain",
]

# 「〇〇の配信を #IRIAM で視聴中！」等の自動シェア。投稿者はリスナーなので拾わない。
VIEWER_SHARE_WORDS = [
    "視聴中", "の配信を", "みんなで見よう", "見てます", "観てます", "配信見に",
]

# アプリが自動生成する配信開始通知。中身が無いのでリプしても会話にならない。
AUTO_SHARE_WORDS = [
    "がライブ配信中", "今すぐ遊びにいこう", "ライブ配信中！", "配信中！",
    "配信スタート", "枠あけました", "枠開けました", "配信はじめました",
]

# 「これから／始めたて／伸び悩み」の一人称サイン。共感リプはここが本体。
INTENT_WORDS = [
    "始めたい", "はじめたい", "やってみたい", "気になってる", "興味ある",
    "始めた", "はじめた", "始めます", "なりたい", "デビュー", "初配信", "初めて",
    "準備中", "新人", "駆け出し", "初心者",
    "不安", "緊張", "こわい", "怖い",
    "伸びない", "増えない", "来ない", "続かない", "わからない", "分からない",
    "迷って", "悩んで", "どうすれば", "教えて", "アドバイス",
]

# リスナー側の投稿を落とすためのサイン。
# 「配信 楽しかった」等はリスナーが配信者へ送る言葉で、拾ってもこちらの客にならない。
LISTENER_WORDS = [
    "お疲れ様でした", "おつかれさまでした", "おつかれさま", "おつかれ", "おつ！",
    "ありがとうございました", "ありがとうございます", "楽しかったです", "楽しかったよ",
    "楽しみにしてる", "楽しみにしています", "応援してる", "応援します", "おめでとう",
    "来てくれて", "参加ありがとう", "見に来て", "遊びに来て", "推し",
    "記念配信", "凸待ち", "アーカイブ",
]


def hits(text, words):
    low = (text or "").lower()
    return sum(1 for w in words if w.lower() in low)

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
            bio = u.description or ""

            both = f"{t.text}\n{bio}"
            if hits(both, OFF_TOPIC_WORDS):
                continue
            if hits(t.text, AUTO_SHARE_WORDS):
                continue

            # ターゲットのプラットフォーム名が出ていれば重く見る
            domain = (
                hits(both, DOMAIN_LIVER)
                + hits(both, PRIMARY_PLATFORMS) * 2
                + (hits(both, DOMAIN_SIDEJOB) if mode == "empathy" else 0)
            )
            if domain == 0:
                continue
            listener = hits(t.text, LISTENER_WORDS)

            if mode == "empathy":
                if hits(t.text, VIEWER_SHARE_WORDS):
                    continue
                # 小〜中規模の生身の人。大きすぎる＝業者/インフルで反応が返らない
                if not (10 <= fol <= 5000):
                    continue
                if age > 24:  # 古い投稿にリプしても本人が見ない
                    continue
                intent = hits(t.text, INTENT_WORDS)
                # 検索結果はほぼ全部「数分前」なので鮮度では差が付かない。
                # 「本人が悩みを書いているか」で並べる。リスナーの労い投稿は落とす。
                if intent == 0 or listener >= 2:
                    continue
                score = intent * 10 + domain * 5 - listener * 20 - pm.get("reply_count", 0) * 3
                if score <= 0:
                    continue
            else:
                # 人が集まっている投稿。ただし投稿直後でないとリプが埋もれる
                if fol < 1000:
                    continue
                if age > 6:
                    continue
                # リプ欄に入る価値があるのは、こちらが一次情報で語れる話題のときだけ。
                # プロフに配信ドメイン語がある＝その人のフォロワーもこの界隈、を重視する。
                if hits(bio, DOMAIN_LIVER) == 0:
                    continue
                # 中身のある投稿だけ。短文＝配信告知で、リプ欄に会話が起きない。
                if len(t.text) < 60:
                    continue
                # 誰も反応していない投稿のリプ欄には人が来ない
                if pm.get("like_count", 0) + pm.get("reply_count", 0) * 2 < 3:
                    continue
                score = (
                    pm.get("like_count", 0) * 2
                    + pm.get("reply_count", 0)
                    + fol / 500
                    - age * 8
                    - listener * 10
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

    # 1日1回の実行なので全クエリ回して構わない（8リクエスト）
    empathy = collect(client, EMPATHY_QUERIES, seen_set, my_id, 5, "empathy")
    reach = collect(client, REACH_QUERIES, seen_set, my_id, 5, "reach")

    if not empathy and not reach:
        # 空のIssueを毎朝送ると開かなくなるので、その日は黙って見送る。
        # 失敗(1)ではなく2を返し、ワークフロー側でIssue作成だけスキップする。
        print("[INFO] 条件を満たす候補が0件でした。今日はIssueを作りません。")
        return 2

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
