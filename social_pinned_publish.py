#!/usr/bin/env python3
"""social_pinned_publish.py — 固定ポスト（X / Threads）を確定ファクト準拠版に差し替える

背景（2026-08-08）:
  X @taitan_LIVER の固定ポスト（tweet id 2037849449498837271・2026-03-28 の初投稿）に
  確定ファクト違反が4点残っていた。
    ①「累計150名」→ 確定は200名
    ②「傘下11代理店を統括」→ 確定表記は「11の配信代理店と提携」
    ③ CTAがDM → 全媒体は特典PDF経由のLINE登録に統一済み
    ④「私は現役プレイヤー」→ 確定は「元Pococha S帯」（同アカウントのbioと自己矛盾）

  原因は、これまでの一括ファクト更新が **本文だけを対象にしていて
  固定ポスト／プロフィールを走査対象に含めていなかった** こと。
  プロフィール側は 2026-07-31〜08-01 に是正済みだったが、固定ポストだけ取り残された。

なぜスクリプト＋GitHub Actions なのか:
  投稿・削除には OAuth1.0a のユーザーコンテキスト（X）と長期トークン（Threads）が要る。
  どちらもローカルには無く GitHub Secrets にだけある（x_profile_update.py と同じ事情）。

固定操作そのものはAPIに存在しない:
  X も Threads も「ピン留め/固定」の公開APIが無い。**投稿までがスクリプトの仕事**で、
  固定の差し替えはアプリ/Web UI から手動で行う。

使い方:
  python social_pinned_publish.py --post-x        --dry-run
  python social_pinned_publish.py --post-threads  --dry-run
  python social_pinned_publish.py --delete-x 2037849449498837271 --dry-run

正本は marketing/social_profiles.md。文面を変えるときは **必ず両方**を直すこと。
"""

import argparse
import os
import sys

# ── 文面（marketing/social_profiles.md と一致させること）──────────────

# X「固定ツイート」節（2026-08-01 設計・2026-08-08 ユーザー承認）
X_PINNED_TEXT = """4年前、0人の枠で2時間ひとり喋ってた僕が、いま200名のライバー事務所の代表をやってます。

元Pococha S帯。最初は誰より震えてた。

「始めたいけど自分なんて」って人の背中を押したくて、配信の本音をここに書きます。

還元率100%+α・初配信から僕が伴走。新人ガイドはプロフのLINEで配布中。"""

# Threads「固定投稿」節（2026-08-01 設計・2026-08-08 ユーザー承認）
THREADS_PINNED_TEXT = """はじめまして、たいたんです☕️

元Pococha S帯。ミクチャでは8,000人の中からミスターコン1位をとりました。Pocochaを4年見続けて、いまはライバー事務所「TAITAN PRO」をやっています。Pococha・TikTok LIVE・17LIVEで200名が一緒に配信中です。

最初に正直に言うと——配信は「始め方」さえ間違えなければ、未経験でも十分に伸ばせます。逆に、そこを独学でつまずいて静かに消えていく人を、何百人も見てきました。

このアカウントでは、
・Pococha / TikTok LIVEで伸びる人の共通点
・未経験がつまずく「最初の30日」の落とし穴
・元S帯が実際にやっていた運用

を、毎日リアルに発信していきます。

TAITAN PROは還元率100%+α。初配信から代表の僕が直接伴走します。

その「最初の30日」でやることをまとめた『ライバー新人期スタートダッシュガイド』を、公式LINEの友だち追加で無料で配っています。配信の悩みも、始め方の相談も、そのまま送ってください👇
https://lin.ee/xchCfdn"""

# 差し替え対象の旧固定ポスト（削除は --delete-x で明示指定したときだけ実行する）
X_OLD_PINNED_ID = "2037849449498837271"

X_WEIGHTED_LIMIT = 280   # X の重み付き文字数上限
THREADS_LIMIT = 500      # Threads の本文上限


def x_weighted_len(text):
    """X の重み付き文字数。CJK等は2、ラテン・記号は1として数える。

    参考: https://developer.x.com/en/docs/counting-characters
    """
    weight = 0
    for ch in text:
        o = ord(ch)
        if (0x0000 <= o <= 0x10FF or 0x2000 <= o <= 0x200D
                or 0x2010 <= o <= 0x201F or 0x2032 <= o <= 0x2037):
            weight += 1
        else:
            weight += 2
    return weight


def _x_client():
    import tweepy
    try:
        return tweepy.Client(
            consumer_key=os.environ["TWITTER_API_KEY"],
            consumer_secret=os.environ["TWITTER_API_SECRET"],
            access_token=os.environ["TWITTER_ACCESS_TOKEN"],
            access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
        )
    except KeyError as e:
        print(f"[ERROR] 環境変数 {e} が未設定です（GitHub Secrets から注入されます）")
        sys.exit(1)


def post_x(dry_run):
    weighted = x_weighted_len(X_PINNED_TEXT)
    print(f"[X 固定用ポスト] {len(X_PINNED_TEXT)}字 / 重み付き {weighted}/{X_WEIGHTED_LIMIT}")
    print("-" * 60)
    print(X_PINNED_TEXT)
    print("-" * 60)
    if weighted > X_WEIGHTED_LIMIT:
        print("[ERROR] 重み付き文字数が上限を超えています")
        return 1
    if dry_run:
        print("[dry-run] 投稿しませんでした")
        return 0

    resp = _x_client().create_tweet(text=X_PINNED_TEXT)
    tweet_id = resp.data["id"]
    print(f"[OK] 投稿しました: https://x.com/taitan_LIVER/status/{tweet_id}")
    print("\n次にやること（APIに固定機能が無いので手動）:")
    print("  1. Xアプリ/Webでこのポストを「プロフィールに固定する」")
    print(f"  2. 固定が新ポストに移ったのを確認してから、旧ポストを削除:")
    print(f"     python social_pinned_publish.py --delete-x {X_OLD_PINNED_ID}")
    return 0


def delete_x(tweet_id, dry_run):
    print(f"[X ポスト削除] id={tweet_id}")
    print("  ※削除は取り消せません。固定が新ポストに移ったのを確認してから実行してください。")
    if dry_run:
        print("[dry-run] 削除しませんでした")
        return 0
    client = _x_client()
    resp = client.delete_tweet(tweet_id)
    deleted = bool(resp.data and resp.data.get("deleted"))
    print(f"[{'OK' if deleted else 'ERROR'}] delete_tweet -> {resp.data}")
    return 0 if deleted else 1


def post_threads(dry_run):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "threads"))
    import threads_poster

    n = len(THREADS_PINNED_TEXT)
    print(f"[Threads 固定用投稿] {n}/{THREADS_LIMIT}字")
    print("-" * 60)
    print(THREADS_PINNED_TEXT)
    print("-" * 60)
    if n > THREADS_LIMIT:
        print("[ERROR] 本文が上限を超えています")
        return 1
    if dry_run:
        print("[dry-run] 投稿しませんでした")
        return 0

    token = threads_poster._token()
    user_id = threads_poster._user_id(token)
    media_id = threads_poster.post_text(token, user_id, THREADS_PINNED_TEXT)
    if not media_id:
        print("[ERROR] 投稿に失敗しました")
        return 1
    print(f"[OK] 投稿しました media_id={media_id}")
    print("\n次にやること（APIに固定機能が無いので手動）:")
    print("  Threadsアプリでこの投稿の「…」→「固定する」を選ぶ")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--post-x", action="store_true", help="X の固定用ポストを投稿する")
    p.add_argument("--post-threads", action="store_true", help="Threads の固定用投稿を投稿する")
    p.add_argument("--delete-x", metavar="TWEET_ID", help="指定IDのXポストを削除する")
    p.add_argument("--dry-run", action="store_true", help="送信せず内容と文字数だけ確認")
    args = p.parse_args()

    if not (args.post_x or args.post_threads or args.delete_x):
        p.error("--post-x / --post-threads / --delete-x のいずれかを指定してください")

    rc = 0
    if args.post_x:
        rc |= post_x(args.dry_run)
    if args.post_threads:
        rc |= post_threads(args.dry_run)
    if args.delete_x:
        rc |= delete_x(args.delete_x, args.dry_run)
    return rc


if __name__ == "__main__":
    sys.exit(main())
