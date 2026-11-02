#!/usr/bin/env python3
"""social_pinned_publish.py — Threads の固定用投稿を確定ファクト準拠版で投稿する

2026-11-02: X 側（--post-x / --delete-x）は撤去した。X自動化を全部撤去したため
（x_content/RETIRED.md）。以下の背景は X で起きた事故の記録として残している。

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
  投稿には Threads の長期トークンが要り、ローカルには無く GitHub Secrets にだけある。

固定操作そのものはAPIに存在しない:
  Threads には「ピン留め/固定」の公開APIが無い。**投稿までがスクリプトの仕事**で、
  固定の差し替えはアプリ/Web UI から手動で行う。

使い方:
  python social_pinned_publish.py --post-threads  --dry-run

文面の出所（2026-08-09 変更）:
  **正本 marketing/social_profiles.md の ```canonical:threads.pinned
  フェンスから直接読む。** 以前はここに同じ文字列を手書きでコピーしていて、担保は
  docstring の「必ず両方を直すこと」だけだった。機械的な照合が無いので、片方だけ直しても
  CI は緑のまま＝黙ってズレる。直すのは正本1箇所でよくなった。
  埋め込みに戻すと social_profile_guard.py の audit_consumers() が赤くする。
"""

import argparse
import os
import sys

from social_profile_guard import parse_canonical

# ── 文面（正本 marketing/social_profiles.md から読む）────────────────
# 2026-08-01 設計・2026-08-08 ユーザー承認。
# ここに文字列リテラルを書き戻さないこと（番犬が弾く）。
_CANON = parse_canonical()
THREADS_PINNED_TEXT = _CANON.get("threads", {}).get("pinned")

THREADS_LIMIT = 500      # Threads の本文上限


def _missing(text, key):
    """正本から文面を読めていなければ理由を出して True を返す。"""
    if text:
        return False
    print(f"[ERROR] 正本 marketing/social_profiles.md から {key} を読めませんでした")
    print(f"        ```canonical:{key} の印が付いているか確認してください")
    print("        （python3 social_profile_guard.py --local で全項目を確認できます）")
    return True


def post_threads(dry_run):
    if _missing(THREADS_PINNED_TEXT, "threads.pinned"):
        return 1
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
    p.add_argument("--post-threads", action="store_true", help="Threads の固定用投稿を投稿する")
    p.add_argument("--dry-run", action="store_true", help="送信せず内容と文字数だけ確認")
    args = p.parse_args()

    if not args.post_threads:
        p.error("--post-threads を指定してください")

    return post_threads(args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
