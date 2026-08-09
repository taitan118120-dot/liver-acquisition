#!/usr/bin/env python3
"""X（Twitter）@taitan_LIVER のプロフィール（表示名・bio・URL欄）を更新する。

なぜスクリプト＋GitHub Actions なのか:
  bio 更新には OAuth1.0a のユーザーコンテキストが要る（Bearer では不可）。
  TWITTER_API_KEY / SECRET / ACCESS_TOKEN / SECRET はローカルには無く、
  GitHub Secrets にだけ登録されている（cloud_post.py と同じ4本）。
  → ワークフロー x_profile_update.yml から workflow_dispatch で回す。

文面の出所（2026-08-09 変更）:
  **正本 marketing/social_profiles.md の ```canonical:x.* フェンスから直接読む。**
  以前はここに同じ文字列を手書きでコピーしていて、担保は docstring の
  「必ず両方を直すこと」だけだった。機械的な照合が無いので、片方だけ直しても
  CI は緑のまま＝黙ってズレる。直すのは正本1箇所でよくなった
  （ig_profile_update.py と同じ形）。
  埋め込みに戻すと social_profile_guard.py の audit_consumers() が赤くする。

使い方:
  python x_profile_update.py            # 反映
  python x_profile_update.py --dry-run  # 送信せず内容と文字数だけ確認
"""

import argparse
import os
import sys

from social_profile_guard import parse_canonical

CANON_KEY = "x"

# 正本 marketing/social_profiles.md の X 節（2026-08-01 ユーザー承認済みの文面）。
# ここに文字列リテラルを書き戻さないこと（番犬が弾く）。
_CANON = parse_canonical().get(CANON_KEY, {})
NAME = _CANON.get("name")
DESCRIPTION = _CANON.get("bio")
URL = _CANON.get("link")

# X の上限
NAME_LIMIT = 50
DESCRIPTION_LIMIT = 160


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="送信せず内容だけ表示")
    args = parser.parse_args()

    missing = [k for k, v in (("name", NAME), ("bio", DESCRIPTION), ("link", URL)) if not v]
    if missing:
        print(f"[ERROR] 正本 marketing/social_profiles.md から {missing} を読めませんでした")
        print("        ```canonical:x.<項目> の印が付いているか確認してください")
        print("        （python3 social_profile_guard.py --local で全項目を確認できます）")
        return 1

    print(f"[name] {len(NAME)}/{NAME_LIMIT}字\n{NAME}\n")
    print(f"[description] {len(DESCRIPTION)}/{DESCRIPTION_LIMIT}字\n{DESCRIPTION}\n")
    print(f"[url] {URL}\n")

    if len(NAME) > NAME_LIMIT or len(DESCRIPTION) > DESCRIPTION_LIMIT:
        print("[ERROR] 文字数制限を超えています")
        return 1

    if args.dry_run:
        print("[dry-run] 送信しませんでした")
        return 0

    # tweepy は送信時にしか要らない。番犬（social_profile_guard.audit_consumers）は
    # この定数を読むためにモジュールを import するので、トップレベルに置かない
    import tweepy

    try:
        auth = tweepy.OAuth1UserHandler(
            os.environ["TWITTER_API_KEY"],
            os.environ["TWITTER_API_SECRET"],
            os.environ["TWITTER_ACCESS_TOKEN"],
            os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
        )
    except KeyError as e:
        print(f"[ERROR] 環境変数 {e} が未設定です（GitHub Secrets から注入されます）")
        return 1

    api = tweepy.API(auth)

    try:
        user = api.update_profile(name=NAME, description=DESCRIPTION, url=URL)
    except tweepy.TweepyException as e:
        # account/update_profile は v1.1。プラン次第で 403 になりうるので理由を残す
        print(f"[ERROR] update_profile 失敗: {e}")
        return 1

    print("[OK] 更新リクエスト成功（API応答）")
    print(f"  name: {user.name}")
    print(f"  description: {user.description}")
    print(f"  url: {getattr(user, 'url', None)}")
    print("\n※ API応答だけで完了と判断しないこと。")
    print("  https://api.fxtwitter.com/taitan_LIVER で実際の反映を必ず検証する。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
