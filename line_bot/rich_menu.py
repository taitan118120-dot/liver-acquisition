"""
リッチメニュー作成スクリプト
LINE Developers APIを使ってリッチメニューをプログラムで作成

使い方: python rich_menu.py
"""

import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from config import LINE_CHANNEL_ACCESS_TOKEN

RICH_MENU_BODY = {
    "size": {"width": 2500, "height": 1686},
    "selected": True,
    "name": "TAITAN PRO メニュー",
    "chatBarText": "メニューを開く",
    "areas": [
        {
            "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
            "action": {"type": "message", "text": "収入"},
        },
        {
            "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
            "action": {"type": "message", "text": "始め方"},
        },
        {
            "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
            "action": {"type": "message", "text": "面談"},
        },
        {
            "bounds": {"x": 0, "y": 843, "width": 833, "height": 843},
            "action": {"type": "message", "text": "顔出し"},
        },
        {
            "bounds": {"x": 833, "y": 843, "width": 834, "height": 843},
            "action": {"type": "message", "text": "費用"},
        },
        {
            "bounds": {"x": 1667, "y": 843, "width": 833, "height": 843},
            "action": {
                "type": "uri",
                "uri": "https://taitan-pro-lp.netlify.app/#apply",
            },
        },
    ],
}


def create_rich_menu():
    """リッチメニューを作成"""
    url = "https://api.line.me/v2/bot/richmenu"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    body = json.dumps(RICH_MENU_BODY).encode("utf-8")
    req = Request(url, data=body, headers=headers, method="POST")

    try:
        res = urlopen(req)
        data = json.loads(res.read().decode())
        rich_menu_id = data["richMenuId"]
        print(f"リッチメニュー作成成功: {rich_menu_id}")
        return rich_menu_id
    except HTTPError as e:
        print(f"エラー: {e.code} {e.read().decode()}")
        return None


def set_default_rich_menu(rich_menu_id):
    """デフォルトリッチメニューに設定"""
    url = f"https://api.line.me/v2/bot/user/all/richmenu/{rich_menu_id}"
    headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
    req = Request(url, headers=headers, method="POST")

    try:
        urlopen(req)
        print("デフォルトリッチメニューに設定しました")
    except HTTPError as e:
        print(f"エラー: {e.code} {e.read().decode()}")


def main():
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
        print("環境変数を設定してから再実行してください")
        return

    print("リッチメニューを作成しています...")
    rich_menu_id = create_rich_menu()

    if rich_menu_id:
        print()
        print("次のステップ:")
        print(f"1. リッチメニュー画像（2500x1686px）を用意")
        print(f"   6分割: 収入 | 始め方 | 面談予約")
        print(f"           顔出し | 費用 | Web応募")
        print()
        print(f"2. 画像をアップロード:")
        print(f"   curl -v -X POST https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content \\")
        print(f'     -H "Authorization: Bearer $LINE_CHANNEL_ACCESS_TOKEN" \\')
        print(f'     -H "Content-Type: image/png" \\')
        print(f"     -T rich_menu.png")
        print()
        print("3. デフォルトに設定しますか？ (y/n)")

        answer = input("> ").strip().lower()
        if answer == "y":
            set_default_rich_menu(rich_menu_id)


if __name__ == "__main__":
    main()
