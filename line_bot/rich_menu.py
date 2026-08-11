"""
リッチメニュー作成スクリプト
LINE Developers APIを使ってリッチメニューをプログラムで作成する

メニューは2種類ある（2026-08-11〜）:
  liver  … デフォルト。全員に出る。ライバー向け5枠＋「代理店」への入口1枠
  agency … intent が "agency" のユーザーだけに差し替える代理店パートナー向け

差し替えは app.py の link_rich_menu() が LINE の richmenu/link API を叩いて行う。
そのために agency のリッチメニューIDを環境変数 RICH_MENU_ID_AGENCY に入れること
（このスクリプトが作成後に表示する）。

使い方:
    python3 rich_menu_images.py      # 画像を2枚生成
    python3 rich_menu.py             # 2枚とも作成＋アップロード＋liverをデフォルト化
    python3 rich_menu.py --list      # 既存のリッチメニュー一覧
    python3 rich_menu.py --delete-old  # 既存を消してから作り直す
"""

import argparse
import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from config import LINE_CHANNEL_ACCESS_TOKEN

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

LP_BASE = "https://taitan-pro-lp.netlify.app"
UTM = "utm_source=line&utm_medium=richmenu"

# --- タップ判定の座標（正本）---
# 画像は 3列×2段 のカード＋最下部の横長バー。カード間の余白も取りこぼさないよう、
# 境界は「見た目の隙間の中央」に置いて画像全体を隙間なく覆っている。
_COLS = [(0, 847), (847, 1652), (1652, 2500)]
_ROWS = [(0, 629), (629, 1216)]
_BAR = (1216, 1686)


def _grid_bounds():
    """カード6枚ぶんの bounds を左上から順に返す"""
    out = []
    for y0, y1 in _ROWS:
        for x0, x1 in _COLS:
            out.append({"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0})
    return out


BAR_BOUNDS = {"x": 0, "y": _BAR[0], "width": 2500, "height": _BAR[1] - _BAR[0]}


# --- メニューの中身（画像の文言とタップ動作を1か所で持つ）---
# label はそのまま送信されるキーワードなので、messages.py の
# AUTO_REPLIES / AGENCY_REPLIES のキー（「面談」は app.py 側の面談フロー）と必ず揃えること。
RICH_MENU_IMAGES = {
    "liver": {
        "name": "TAITAN PRO メニュー（ライバー）",
        "chatBarText": "メニューを開く",
        "cells": [
            {"icon": "💰", "label": "収入", "sub": "どれくらい稼げる？"},
            {"icon": "🚀", "label": "始め方", "sub": "デビューまでの流れ"},
            {"icon": "📅", "label": "面談", "sub": "個別に相談する"},
            {"icon": "🙈", "label": "顔出し", "sub": "顔出しなしでもOK？"},
            {"icon": "🧾", "label": "費用", "sub": "初期費用・月額費用"},
            {"icon": "🤝", "label": "代理店", "sub": "紹介する側で稼ぐ"},
        ],
        "bar": {
            "title": "はじめての方へ",
            "sub": "事務所のことを詳しく見る",
            "accent": (6, 199, 85),  # LINEグリーン
            "uri": f"{LP_BASE}/beginner/?{UTM}&utm_campaign=line_richmenu",
        },
    },
    "agency": {
        "name": "TAITAN PRO メニュー（代理店）",
        "chatBarText": "メニューを開く",
        "cells": [
            {"icon": "🤝", "label": "代理店", "sub": "お仕事の内容"},
            {"icon": "💰", "label": "報酬", "sub": "報酬が生まれる仕組み"},
            {"icon": "📈", "label": "収入", "sub": "収入の目安"},
            {"icon": "🔰", "label": "未経験", "sub": "営業未経験でも大丈夫？"},
            {"icon": "🛠", "label": "サポート", "sub": "研修・ツール・相談窓口"},
            {"icon": "📅", "label": "面談", "sub": "個別に相談する"},
        ],
        "bar": {
            "title": "代理店パートナー募集",
            "sub": "仕組みと条件を詳しく見る",
            "accent": (165, 148, 184),  # --lav
            "uri": f"{LP_BASE}/agency/?{UTM}&utm_campaign=line_richmenu_agency",
        },
    },
}


def _areas(menu):
    spec = RICH_MENU_IMAGES[menu]
    areas = [
        {"bounds": bounds, "action": {"type": "message", "text": cell["label"]}}
        for bounds, cell in zip(_grid_bounds(), spec["cells"])
    ]
    areas.append({"bounds": BAR_BOUNDS, "action": {"type": "uri", "uri": spec["bar"]["uri"]}})
    return areas


LAYOUT = {menu: _areas(menu) for menu in RICH_MENU_IMAGES}


def rich_menu_body(menu):
    spec = RICH_MENU_IMAGES[menu]
    return {
        "size": {"width": 2500, "height": 1686},
        "selected": True,
        "name": spec["name"],
        "chatBarText": spec["chatBarText"],
        "areas": LAYOUT[menu],
    }


# 旧コードとの互換（デフォルトメニュー）
RICH_MENU_BODY = rich_menu_body("liver")


# --- LINE API ---
def _auth(extra=None):
    headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
    if extra:
        headers.update(extra)
    return headers


def create_rich_menu(menu):
    """リッチメニューを作成してIDを返す"""
    url = "https://api.line.me/v2/bot/richmenu"
    body = json.dumps(rich_menu_body(menu)).encode("utf-8")
    req = Request(url, data=body, headers=_auth({"Content-Type": "application/json"}), method="POST")

    try:
        res = urlopen(req)
        rich_menu_id = json.loads(res.read().decode())["richMenuId"]
        print(f"作成成功 [{menu}]: {rich_menu_id}")
        return rich_menu_id
    except HTTPError as e:
        print(f"エラー: {e.code} {e.read().decode()}")
        return None


def upload_image(rich_menu_id, image_path):
    """リッチメニュー画像をアップロード"""
    url = f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content"
    with open(image_path, "rb") as f:
        data = f.read()
    req = Request(url, data=data, headers=_auth({"Content-Type": "image/png"}), method="POST")

    try:
        urlopen(req)
        print(f"画像アップロード成功: {os.path.basename(image_path)} ({len(data) // 1024}KB)")
        return True
    except HTTPError as e:
        print(f"エラー: {e.code} {e.read().decode()}")
        return False


def set_default_rich_menu(rich_menu_id):
    """デフォルトリッチメニューに設定（全員に出る）"""
    url = f"https://api.line.me/v2/bot/user/all/richmenu/{rich_menu_id}"
    req = Request(url, headers=_auth(), method="POST")

    try:
        urlopen(req)
        print("デフォルトリッチメニューに設定しました")
        return True
    except HTTPError as e:
        print(f"エラー: {e.code} {e.read().decode()}")
        return False


def list_rich_menus():
    """作成済みリッチメニューの一覧"""
    req = Request("https://api.line.me/v2/bot/richmenu/list", headers=_auth())
    try:
        with urlopen(req) as res:
            return json.loads(res.read().decode()).get("richmenus", [])
    except HTTPError as e:
        print(f"エラー: {e.code} {e.read().decode()}")
        return []


def delete_rich_menu(rich_menu_id):
    url = f"https://api.line.me/v2/bot/richmenu/{rich_menu_id}"
    req = Request(url, headers=_auth(), method="DELETE")
    try:
        urlopen(req)
        print(f"削除: {rich_menu_id}")
        return True
    except HTTPError as e:
        print(f"エラー: {e.code} {e.read().decode()}")
        return False


def _ensure_image(menu, rebuild=False):
    """画像が無ければ生成する（rich_menu_images.py と同じ出力先）"""
    path = os.path.join(ASSETS_DIR, f"rich_menu_{menu}.png")
    if rebuild or not os.path.exists(path):
        from rich_menu_images import build  # 循環importを避けてここで読む
        path = build(menu)
        print(f"画像を生成しました: {path}")
    return path


def deploy(menus, rebuild_image=False):
    """作成 → 画像アップロード → liver をデフォルト化 まで一気に行う"""
    created = {}
    for menu in menus:
        image_path = _ensure_image(menu, rebuild_image)
        rich_menu_id = create_rich_menu(menu)
        if not rich_menu_id:
            continue
        if not upload_image(rich_menu_id, image_path):
            print(f"⚠️ [{menu}] 画像なしのメニューが残った。--list で確認して削除すること")
            continue
        created[menu] = rich_menu_id

    if "liver" in created:
        set_default_rich_menu(created["liver"])

    print()
    if "agency" in created:
        print("=" * 60)
        print("代理店メニューを有効にするには、Renderの環境変数に次を登録して再デプロイ:")
        print(f"  RICH_MENU_ID_AGENCY={created['agency']}")
        print("（未設定のあいだ、代理店希望者にもデフォルトのライバー向けメニューが出る）")
        print("=" * 60)
    return created


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--menu", choices=["liver", "agency", "both"], default="both")
    ap.add_argument("--list", action="store_true", help="既存メニューの一覧だけ表示")
    ap.add_argument("--delete-old", action="store_true", help="既存メニューを削除してから作成")
    ap.add_argument("--rebuild-image", action="store_true", help="画像があっても作り直す")
    args = ap.parse_args()

    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
        print("  export LINE_CHANNEL_ACCESS_TOKEN='...' してから再実行してください")
        return

    existing = list_rich_menus()
    if args.list:
        if not existing:
            print("リッチメニューはまだありません")
        for m in existing:
            print(f"{m['richMenuId']}  {m.get('name')}  areas={len(m.get('areas', []))}")
        return

    if existing:
        print(f"既存のリッチメニューが {len(existing)} 件あります:")
        for m in existing:
            print(f"  {m['richMenuId']}  {m.get('name')}")
        if args.delete_old:
            print("\nこれらを削除します。よろしいですか？ (yes/n)")
            if input("> ").strip().lower() == "yes":
                for m in existing:
                    delete_rich_menu(m["richMenuId"])
            else:
                print("削除せず続行します")
        else:
            print("（消さずに新規作成します。不要なら --delete-old）")
        print()

    menus = ["liver", "agency"] if args.menu == "both" else [args.menu]
    deploy(menus, rebuild_image=args.rebuild_image)


if __name__ == "__main__":
    main()
