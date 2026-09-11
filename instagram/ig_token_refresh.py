"""
Instagram Graph API トークン自動更新

Meta Graph APIのアクセストークンは60日で期限切れになる。
このスクリプトは短期トークンを長期トークンに交換し、
期限切れ前に自動で更新する。

GitHub Actionsから月1回実行して、Secretsを自動更新する。

使い方:
  python ig_token_refresh.py --check     # トークンの有効期限を確認
  python ig_token_refresh.py --refresh   # トークンを更新
  python ig_token_refresh.py --exchange  # 短期→長期トークンに交換（初回）
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "token_info.json")


def debug_token(access_token):
    """トークンの有効期限・権限を確認"""
    url = f"{GRAPH_API_BASE}/debug_token"
    params = {
        "input_token": access_token,
        "access_token": access_token,
    }
    try:
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] トークン情報取得リクエスト失敗: {e}")
        return None

    if "data" not in data:
        print(f"[ERROR] トークン情報取得失敗: {data}")
        return None

    info = data["data"]
    expires_at = info.get("expires_at", 0)
    if expires_at == 0:
        print("トークン種別: 無期限トークン")
        return {"expires_at": 0, "is_valid": info.get("is_valid", False)}

    expires_dt = datetime.fromtimestamp(expires_at)
    remaining = expires_dt - datetime.now()

    print(f"トークン有効: {info.get('is_valid', False)}")
    print(f"有効期限: {expires_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"残り: {remaining.days}日 {remaining.seconds // 3600}時間")
    print(f"スコープ: {', '.join(info.get('scopes', []))}")

    return {
        "expires_at": expires_at,
        "expires_dt": expires_dt.isoformat(),
        "remaining_days": remaining.days,
        "is_valid": info.get("is_valid", False),
        "scopes": info.get("scopes", []),
    }


def exchange_short_to_long(short_token, app_id, app_secret):
    """短期トークン → 長期トークン（60日）に交換（初回セットアップ用）"""
    url = f"{GRAPH_API_BASE}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_token,
    }
    try:
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] トークン交換リクエスト失敗: {e}")
        return None

    if "access_token" in data:
        new_token = data["access_token"]
        expires_in = data.get("expires_in", 5184000)  # デフォルト60日
        expires_dt = datetime.now() + timedelta(seconds=expires_in)

        print(f"長期トークン取得成功!")
        print(f"有効期限: {expires_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"トークン（先頭20文字）: {new_token[:20]}...")

        save_token_info(new_token, expires_dt)
        return new_token

    print(f"[ERROR] トークン交換失敗: {data}")
    return None


def refresh_long_token(current_token):
    """長期トークンを新しい長期トークンに更新（期限延長）"""
    app_id = os.environ.get("META_APP_ID", "")
    app_secret = os.environ.get("META_APP_SECRET", "")

    if not app_id or not app_secret:
        print("[ERROR] META_APP_ID と META_APP_SECRET が必要です。")
        return None

    url = f"{GRAPH_API_BASE}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": current_token,
    }
    try:
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] トークン更新リクエスト失敗: {e}")
        return None

    if "access_token" in data:
        new_token = data["access_token"]
        expires_in = data.get("expires_in", 5184000)
        expires_dt = datetime.now() + timedelta(seconds=expires_in)

        print(f"トークン更新成功!")
        print(f"新しい有効期限: {expires_dt.strftime('%Y-%m-%d %H:%M:%S')}")

        save_token_info(new_token, expires_dt)
        return new_token

    print(f"[ERROR] トークン更新失敗: {data}")
    return None


def update_github_secret(secret_name, secret_value):
    """GitHub Secretを更新（gh CLIを使用）"""
    import subprocess

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        # ローカル実行時はgit remoteから取得
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True, text=True,
                cwd=os.path.dirname(os.path.dirname(__file__)),
            )
            remote_url = result.stdout.strip()
            # https://github.com/user/repo.git or git@github.com:user/repo.git
            if "github.com" in remote_url:
                repo = remote_url.split("github.com")[-1].strip(":/").replace(".git", "")
        except Exception:
            pass

    if not repo:
        print(f"[WARNING] リポジトリ特定不可。手動でSecretを更新してください:")
        print(f"  gh secret set {secret_name}")
        return False

    try:
        result = subprocess.run(
            ["gh", "secret", "set", secret_name, "--repo", repo],
            input=secret_value,
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"GitHub Secret '{secret_name}' を更新しました。")
            return True
        else:
            print(f"[ERROR] Secret更新失敗: {result.stderr}")
            return False
    except FileNotFoundError:
        print("[WARNING] gh CLI が見つかりません。手動でSecretを更新してください:")
        print(f"  gh secret set {secret_name}")
        return False


def save_token_info(token, expires_dt):
    """トークン情報をファイルに保存（トークン本体は保存しない）"""
    info = {
        "updated_at": datetime.now().isoformat(),
        "expires_at": expires_dt.isoformat(),
        "remaining_days": (expires_dt - datetime.now()).days,
        "token_prefix": token[:10] + "...",
    }
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"トークン情報を保存: {TOKEN_FILE}")


def auto_refresh():
    """トークンを確認し、期限が近ければ自動更新 + GitHub Secret更新"""
    token = config.INSTAGRAM_ACCESS_TOKEN
    if not token:
        token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")

    if not token:
        print("[ERROR] INSTAGRAM_ACCESS_TOKEN が設定されていません。")
        return False

    print("=== トークン有効期限チェック ===")
    info = debug_token(token)

    if not info:
        return False

    if not info["is_valid"]:
        print("\n[ERROR] トークンが無効です。再取得が必要です。")
        return False

    if info["expires_at"] == 0:
        print("\n無期限トークンです。更新不要。")
        return True

    remaining = info.get("remaining_days", 0)

    if remaining > 30:
        print(f"\n残り{remaining}日。更新不要です（30日以内になったら自動更新）。")
        return True

    print(f"\n残り{remaining}日。トークンを更新します...")
    new_token = refresh_long_token(token)

    if not new_token:
        return False

    # GitHub Secretを更新（期限が延びていなくても、新しい文字列自体は有効なので先に入れる）
    print("\n=== GitHub Secret 更新 ===")
    update_github_secret("INSTAGRAM_ACCESS_TOKEN", new_token)

    # 「更新成功」と言いながら期限が1ミリも延びていないことがある。
    # 2026-08-10〜09-07 は毎日ここを通って毎回 success だったのに、有効期限は
    # ずっと 2026-09-08 15:38:25 のままで、そのまま失効してIG投稿が止まった。
    # fb_exchange_token は「すでに長期トークン」を渡しても新しい文字列は返すが、
    # 期限は延ばさないことがあるため。expires_in の自己申告ではなく、
    # 新トークンを debug_token に掛け直して実際の期限を確かめる。
    print("\n=== 更新後の期限を実測 ===")
    after = debug_token(new_token)
    if not after:
        print("[ERROR] 更新後のトークンを確認できませんでした。")
        return False
    if after["expires_at"] == 0:
        print("更新後は無期限トークンです。")
        return True
    # 1日以上延びていなければ「延長できていない」とみなす
    if after["expires_at"] <= info["expires_at"] + 86400:
        print("[ERROR] トークン文字列は入れ替わりましたが、有効期限が延びていません")
        print(f"  更新前: {datetime.fromtimestamp(info['expires_at'])}")
        print(f"  更新後: {datetime.fromtimestamp(after['expires_at'])}")
        print("  このまま放置すると期限日にIG投稿が止まります。")
        print("  Meta for Developers で長期トークンを再発行し、")
        print("  GitHub Secrets の INSTAGRAM_ACCESS_TOKEN を差し替えてください。")
        return False

    return True


def main():
    parser = argparse.ArgumentParser(description="Instagram Graph API トークン管理")
    parser.add_argument("--check", action="store_true",
                        help="トークンの有効期限を確認")
    parser.add_argument("--refresh", action="store_true",
                        help="トークンを自動更新（期限14日以内なら更新）")
    parser.add_argument("--exchange", action="store_true",
                        help="短期トークン→長期トークンに交換（初回セットアップ）")
    parser.add_argument("--force-refresh", action="store_true",
                        help="期限に関係なく強制更新")
    args = parser.parse_args()

    if args.check:
        token = config.INSTAGRAM_ACCESS_TOKEN or os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
        if not token:
            print("[ERROR] INSTAGRAM_ACCESS_TOKEN が設定されていません。")
            sys.exit(1)
        debug_token(token)

    elif args.exchange:
        short_token = os.environ.get("META_SHORT_TOKEN", "")
        app_id = os.environ.get("META_APP_ID", "")
        app_secret = os.environ.get("META_APP_SECRET", "")

        if not all([short_token, app_id, app_secret]):
            print("初回セットアップに必要な環境変数:")
            print("  META_SHORT_TOKEN  — Graph APIエクスプローラーで取得した短期トークン")
            print("  META_APP_ID       — MetaアプリのApp ID")
            print("  META_APP_SECRET   — MetaアプリのApp Secret")
            sys.exit(1)

        new_token = exchange_short_to_long(short_token, app_id, app_secret)
        if not new_token:
            sys.exit(1)
        print(f"\n以下をGitHub Secretに設定してください:")
        print(f"  gh secret set INSTAGRAM_ACCESS_TOKEN")
        update_github_secret("INSTAGRAM_ACCESS_TOKEN", new_token)

    elif args.refresh or args.force_refresh:
        # 失敗したら必ず非ゼロで落とす。
        # 2026-09-08 に INSTAGRAM_ACCESS_TOKEN が失効したとき、ここが戻り値を
        # 捨てていたので instagram_token_refresh.yml は毎日 success のままで、
        # 9/9(水)のIG投稿が丸ごと落ちていたのに気づけなかった（発覚は9/11）。
        # トークンが死んだら投稿も止まる＝赤で気づける状態にしておく
        # （[[feedback_keep_failure_notifications]]）。
        if args.force_refresh:
            token = config.INSTAGRAM_ACCESS_TOKEN or os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
            new_token = refresh_long_token(token)
            if not new_token:
                print("[ERROR] トークンの強制更新に失敗しました。")
                sys.exit(1)
            update_github_secret("INSTAGRAM_ACCESS_TOKEN", new_token)
        elif not auto_refresh():
            print("[ERROR] トークンの確認/更新に失敗しました。"
                  "Meta for Developers で長期トークンを再発行し、"
                  "GitHub Secrets の INSTAGRAM_ACCESS_TOKEN を更新してください。")
            sys.exit(1)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
