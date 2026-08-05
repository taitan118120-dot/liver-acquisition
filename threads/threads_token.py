"""
Threads アクセストークン管理

Threadsの長期トークンは60日で失効するが、有効なうちに /refresh_access_token を
叩けば再延長できる。GitHub Actions から月1回 --refresh を回して
Secrets(THREADS_ACCESS_TOKEN) を自動更新する想定。

使い方:
  # 初回: 短期トークン -> 長期トークンに交換（SETUP_GUIDE参照）
  THREADS_SHORT_TOKEN=xxx python threads/threads_token.py --exchange

  # 確認: 残り有効期限を表示
  python threads/threads_token.py --check

  # 更新: 長期トークンを再延長し、GitHub Secretを書き換える
  python threads/threads_token.py --refresh
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

import requests

GRAPH_BASE = "https://graph.threads.net"
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "threads_token_info.json")


def _save_info(token, expires_in, secret_updated=None):
    info = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "expires_at": (datetime.now() + timedelta(seconds=int(expires_in))).isoformat(timespec="seconds"),
        "remaining_days": int(expires_in) // 86400,
        "token_prefix": token[:10] + "...",
    }
    if secret_updated is not None:
        # ここがFalseのまま残っている = Secretは古いトークンのまま。要手動対応。
        info["secret_updated"] = bool(secret_updated)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"[INFO] {TOKEN_FILE} 更新: 残り{info['remaining_days']}日 (期限 {info['expires_at']})")


def _on_actions():
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def _mask(token):
    """ログに残しても安全な形（先頭数文字＋長さ）に丸める。"""
    return f"{token[:8]}...(長さ{len(token)})"


def exchange():
    """短期トークン -> 長期トークン（初回のみ）。
    THREADS_SHORT_TOKEN と META_APP_SECRET(=Thredays appのclient secret) が必要。
    """
    short = os.environ.get("THREADS_SHORT_TOKEN", "").strip()
    secret = os.environ.get("THREADS_APP_SECRET", os.environ.get("META_APP_SECRET", "")).strip()
    if not short or not secret:
        print("[ERROR] THREADS_SHORT_TOKEN と THREADS_APP_SECRET(またはMETA_APP_SECRET) が必要です。")
        sys.exit(2)
    r = requests.get(
        f"{GRAPH_BASE}/access_token",
        params={
            "grant_type": "th_exchange_token",
            "client_secret": secret,
            "access_token": short,
        },
        timeout=30,
    )
    data = r.json()
    token = data.get("access_token")
    if not token:
        print(f"[ERROR] 交換失敗: {data}")
        sys.exit(1)
    expires_in = data.get("expires_in", 5184000)  # 既定60日
    print("=== 長期トークン取得成功 ===")
    print(token)
    print("\n↑これを GitHub Secret THREADS_ACCESS_TOKEN に登録してください。")
    print("  gh secret set THREADS_ACCESS_TOKEN")
    _save_info(token, expires_in)
    return token


def refresh():
    """長期トークンを再延長。成功したらGitHub Secretを書き換える（gh CLIが必要）。"""
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        print("[ERROR] THREADS_ACCESS_TOKEN が未設定です。")
        sys.exit(2)
    r = requests.get(
        f"{GRAPH_BASE}/refresh_access_token",
        params={"grant_type": "th_refresh_token", "access_token": token},
        timeout=30,
    )
    data = r.json()
    new_token = data.get("access_token")
    if not new_token:
        print(f"[ERROR] 更新失敗: {data}")
        # 失効が近いと失敗する場合あり。手動再認証が必要なケース。
        sys.exit(1)
    expires_in = data.get("expires_in", 5184000)

    on_actions = _on_actions()
    if on_actions:
        # 以降どこかでトークンが出力されても伏せ字になるよう登録しておく
        print(f"::add-mask::{new_token}")

    # GitHub Secretを更新（gh CLI / GH_TOKEN 経由）。
    # ここが失敗すると Secret は古いトークンのまま = 60日で Threads 投稿が全停止する。
    # 緑のまま見逃すのが一番まずいので、失敗したら必ず非ゼロで落とす。
    has_gh_token = bool(os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
    if has_gh_token:
        try:
            subprocess.run(
                ["gh", "secret", "set", "THREADS_ACCESS_TOKEN"],
                input=new_token.encode(),
                check=True,
            )
        except Exception as e:
            _save_info(new_token, expires_in, secret_updated=False)
            print(f"[ERROR] gh secret set 失敗: {e}")
            print("[ERROR] Secret THREADS_ACCESS_TOKEN は未更新のままです。手動対応が必要。")
            print(f"        Metaの再延長自体は成功（新トークン {_mask(new_token)}）")
            if on_actions:
                print("::error::Threads: gh secret set 失敗。Secret THREADS_ACCESS_TOKEN が未更新（GH_PATの期限切れ/権限不足を確認）")
            else:
                print("新トークン（手動でSecret更新してください）:")
                print(new_token)
            sys.exit(1)
        _save_info(new_token, expires_in, secret_updated=True)
        print("[OK] GitHub Secret THREADS_ACCESS_TOKEN を更新しました。")
        return new_token

    # GH_TOKEN/GITHUB_TOKEN なし
    _save_info(new_token, expires_in, secret_updated=False)
    if on_actions:
        # Actions上でSecretを書けない = 自動更新が機能していない。緑で終わらせない。
        print("[ERROR] GH_TOKEN/GITHUB_TOKEN が未設定のため Secret を更新できません。")
        print("[ERROR] Secret THREADS_ACCESS_TOKEN は未更新のままです。手動対応が必要。")
        print(f"        Metaの再延長自体は成功（新トークン {_mask(new_token)}）")
        print("::error::Threads: GH_TOKEN未設定でSecret THREADS_ACCESS_TOKEN を更新できず（workflowのGH_PATを確認）")
        sys.exit(1)
    # ローカル手動実行: 従来どおり成功扱いで、コピペ用に全文を出す
    print("新トークン（手動でSecret更新してください）:")
    print(new_token)
    return new_token


def check():
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        print("[ERROR] THREADS_ACCESS_TOKEN が未設定です。")
        sys.exit(2)
    # /me が通れば有効。残り日数はローカル記録から。
    r = requests.get(
        f"{GRAPH_BASE}/v1.0/me",
        params={"fields": "id,username", "access_token": token},
        timeout=30,
    )
    data = r.json()
    if "id" in data:
        print(f"[OK] トークン有効: @{data.get('username','?')} (id={data['id']})")
    else:
        print(f"[NG] トークン無効/期限切れ: {data}")
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, encoding="utf-8") as f:
            info = json.load(f)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        if info.get("secret_updated") is False:
            print("[WARN] 前回の更新で Secret THREADS_ACCESS_TOKEN を書き換えられていません。手動更新が必要です。")


def main():
    ap = argparse.ArgumentParser(description="Threads トークン管理")
    ap.add_argument("--exchange", action="store_true", help="短期->長期トークン交換（初回）")
    ap.add_argument("--refresh", action="store_true", help="長期トークン再延長＋Secret更新")
    ap.add_argument("--check", action="store_true", help="有効期限確認")
    args = ap.parse_args()
    if args.exchange:
        exchange()
    elif args.refresh:
        refresh()
    elif args.check:
        check()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
