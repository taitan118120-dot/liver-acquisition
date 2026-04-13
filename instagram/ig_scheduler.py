"""
Instagram自動投稿スケジューラ

GitHub Actionsから実行される。
1. トークンの有効性を事前チェック（期限切れなら自動リフレッシュ）
2. 未投稿のコンテンツがなければGeminiで自動生成（ブログ/X投稿/リミックス）
3. 次の未投稿コンテンツをInstagram Graph APIで投稿
4. 一時エラー（タイムアウト等）は同一実行内でリトライ

使い方:
  python ig_scheduler.py                          # 次の1件を投稿（未投稿なければスキップ）
  python ig_scheduler.py --generate               # 自動生成 + 投稿
  python ig_scheduler.py --generate --source blog  # ブログから生成 + 投稿
  python ig_scheduler.py --generate --source twitter  # X投稿から生成 + 投稿
  python ig_scheduler.py --generate --source auto  # 自動選択（デフォルト）
  python ig_scheduler.py --test                   # テスト投稿（dry-run）
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: F401 - configを先にimportしてキャッシュに載せる

from ig_content_generator import generate_posts, load_posts
from ig_poster import post_next


MAX_RETRY = 3          # 永続エラーでスキップする回数
TRANSIENT_RETRIES = 2  # 一時エラーの同一実行内リトライ回数
RETRY_WAIT = 30        # リトライ間隔（秒）


def check_and_refresh_token():
    """トークンの有効性を確認し、期限切れなら自動リフレッシュを試みる。
    Returns: True=OK or リフレッシュ成功, False=リフレッシュ不可
    """
    token = config.INSTAGRAM_ACCESS_TOKEN
    if not token:
        print("[ERROR] INSTAGRAM_ACCESS_TOKEN が未設定")
        return False

    # debug_token APIでチェック
    try:
        import requests
        url = "https://graph.facebook.com/v21.0/debug_token"
        resp = requests.get(url, params={
            "input_token": token,
            "access_token": token,
        }, timeout=10)
        data = resp.json().get("data", {})
    except Exception as e:
        print(f"[WARNING] トークンチェック失敗（ネットワークエラー、続行）: {e}")
        return True  # チェック失敗は一時エラー扱いで続行

    if data.get("is_valid", False):
        expires_at = data.get("expires_at", 0)
        if expires_at > 0:
            import datetime
            remaining = datetime.datetime.fromtimestamp(expires_at) - datetime.datetime.now()
            print(f"[TOKEN] 有効 — 残り{remaining.days}日{remaining.seconds // 3600}時間")
            if remaining.days < 7:
                print("[TOKEN] 残り7日以内 → 自動リフレッシュ試行")
                return _try_refresh(token)
        else:
            print("[TOKEN] 有効（無期限）")
        return True

    # トークンが無効
    print("[TOKEN] 無効または期限切れ → 自動リフレッシュ試行")
    return _try_refresh(token)


def _try_refresh(current_token):
    """トークンリフレッシュを試みる。成功すればconfig更新+GitHub Secret更新。"""
    app_id = os.environ.get("META_APP_ID", "")
    app_secret = os.environ.get("META_APP_SECRET", "")

    if not app_id or not app_secret:
        print("[ERROR] META_APP_ID/META_APP_SECRET が未設定 → 自動リフレッシュ不可")
        print("  手動で ig_token_refresh.py --force-refresh を実行してください")
        return False

    try:
        from ig_token_refresh import refresh_long_token, update_github_secret
        new_token = refresh_long_token(current_token)
        if new_token:
            # ランタイムのconfig更新
            config.INSTAGRAM_ACCESS_TOKEN = new_token
            os.environ["INSTAGRAM_ACCESS_TOKEN"] = new_token
            print("[TOKEN] リフレッシュ成功 → ランタイム更新済み")
            # GitHub Secret更新
            update_github_secret("INSTAGRAM_ACCESS_TOKEN", new_token)
            return True
        else:
            print("[ERROR] リフレッシュ失敗 → 新しいトークンの再取得が必要")
            return False
    except Exception as e:
        print(f"[ERROR] リフレッシュ例外: {e}")
        return False


def run(generate_if_empty=False, source_type="auto", dry_run=False):
    """スケジュール実行のメイン処理。(success, has_content) を返す。"""

    # トークン事前チェック（dry-runでは不要）
    if not dry_run:
        if not check_and_refresh_token():
            print("[ABORT] トークンが無効で自動リフレッシュできませんでした。")
            return False, True  # 永続エラー

    posts = load_posts()

    # 失敗回数が上限に達した投稿をスキップ対象にする
    unposted = [
        p for p in posts
        if not p["posted"] and p.get("image_path") and p.get("fail_count", 0) < MAX_RETRY
    ]
    failed = [p for p in posts if not p["posted"] and p.get("fail_count", 0) >= MAX_RETRY]

    print(f"投稿キュー: 全{len(posts)}件 / 未投稿{len(unposted)}件 / スキップ済{len(failed)}件\n")
    for fp in failed:
        print(f"  [SKIP] {fp['id']}: {fp.get('fail_count', 0)}回失敗 - {fp.get('last_error', '不明')}")

    # 未投稿がなければ生成（スキップ済みは数えない）
    if not unposted and generate_if_empty:
        print("未投稿コンテンツがないため、新規生成します...\n")
        generate_posts(source_type=source_type, count=1, dry_run=dry_run)
        # 再読み込み
        posts = load_posts()
        unposted = [
            p for p in posts
            if not p["posted"] and p.get("image_path") and p.get("fail_count", 0) < MAX_RETRY
        ]

    if not unposted:
        print("[INFO] 投稿するコンテンツがありません。")
        print("  `python ig_content_generator.py --generate` でコンテンツを生成してください。")
        return False, False

    # 一時エラー時のリトライループ
    for attempt in range(TRANSIENT_RETRIES + 1):
        if attempt > 0:
            print(f"\n[RETRY] 一時エラー → {RETRY_WAIT}秒後にリトライ ({attempt}/{TRANSIENT_RETRIES})")
            time.sleep(RETRY_WAIT)

        success, is_transient = post_next(dry_run=dry_run)

        if success:
            return True, True

        if not is_transient:
            # 永続エラー → リトライしても意味がない
            print("[ABORT] 永続エラーのためリトライせず終了")
            return False, True

    # 全リトライ失敗（一時エラー）
    print(f"\n[WARNING] {TRANSIENT_RETRIES + 1}回試行したが一時エラーが継続")
    print("  次回スケジュール実行で再試行されます（fail_countは増加していません）")
    return False, True


def main():
    parser = argparse.ArgumentParser(description="Instagram自動投稿スケジューラ")
    parser.add_argument("--generate", action="store_true",
                        help="未投稿がなければ自動生成してから投稿")
    parser.add_argument("--source", choices=["blog", "twitter", "auto"], default="auto",
                        help="コンテンツソース（default: auto）")
    parser.add_argument("--test", action="store_true",
                        help="テスト実行（投稿しない）")
    args = parser.parse_args()

    dry_run = args.test
    success, had_content = run(
        generate_if_empty=args.generate,
        source_type=args.source,
        dry_run=dry_run,
    )

    if success:
        print("\n投稿完了!")
    elif not had_content:
        print("\n投稿対象がありませんでした。")
        # 投稿対象なしは正常終了（ワークフローを失敗にしない）
    elif not dry_run:
        print("\n投稿に失敗しました。ログを確認してください。")
        sys.exit(1)


if __name__ == "__main__":
    main()
