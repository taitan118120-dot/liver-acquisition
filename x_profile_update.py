#!/usr/bin/env python3
"""X（Twitter）@taitan_LIVER のプロフィール（表示名・bio・URL欄）を更新する。

なぜスクリプト＋GitHub Actions なのか:
  bio 更新には OAuth1.0a のユーザーコンテキストが要る（Bearer では不可）。
  TWITTER_API_KEY / SECRET / ACCESS_TOKEN / SECRET はローカルには無く、
  GitHub Secrets にだけ登録されている（cloud_post.py と同じ4本）。
  → ワークフロー x_profile_update.yml から workflow_dispatch で回す。

正本は marketing/social_profiles.md の「X（Twitter）」節。
文面を変えるときは **必ず両方**を直すこと（片方だけだと次回の一括更新で戻る）。

使い方:
  python x_profile_update.py            # 反映
  python x_profile_update.py --dry-run  # 送信せず内容と文字数だけ確認
"""

import argparse
import os
import sys

import tweepy

# marketing/social_profiles.md の X 節と一致させること（2026-08-01 ユーザー承認済み）
NAME = "たいたん｜元Pococha S帯／ライバー事務所代表"

DESCRIPTION = """元Pococha S帯｜石川発・ライバー事務所「TAITAN PRO」代表
Pococha・TikTokで200名が所属／11の配信代理店と提携／還元率100%
甘い言葉は言えません。配信4年で見てきた現実だけを毎日。
始め方・悩み相談はLINEへ→"""

URL = "https://lin.ee/xchCfdn"

# X の上限
NAME_LIMIT = 50
DESCRIPTION_LIMIT = 160


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="送信せず内容だけ表示")
    args = parser.parse_args()

    print(f"[name] {len(NAME)}/{NAME_LIMIT}字\n{NAME}\n")
    print(f"[description] {len(DESCRIPTION)}/{DESCRIPTION_LIMIT}字\n{DESCRIPTION}\n")
    print(f"[url] {URL}\n")

    if len(NAME) > NAME_LIMIT or len(DESCRIPTION) > DESCRIPTION_LIMIT:
        print("[ERROR] 文字数制限を超えています")
        return 1

    if args.dry_run:
        print("[dry-run] 送信しませんでした")
        return 0

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
