#!/usr/bin/env python3
"""
shorts動画用のフリー素材を自動ダウンロードするスクリプト

BGM: 甘茶の音楽工房 (商用利用OK・クレジット不要)
   https://amachamusic.chagasi.com/
SE:  効果音ラボ (商用利用OK・クレジット不要)
   https://soundeffect-lab.info/

立ち絵: 商用OKの素材サイト探索中。未対応のため手動配置を推奨。

使い方:
  python3 download_assets.py           # 全部DL
  python3 download_assets.py --bgm     # BGMのみ
  python3 download_assets.py --se      # SEのみ
"""

import os
import sys
import argparse
import requests
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
BGM_DIR = BASE_DIR / "shorts" / "bgm"
SE_DIR = BASE_DIR / "shorts" / "se"
ASSETS_DIR = BASE_DIR / "shorts" / "assets"

# 素材マッピング（内部名 → 本家URL, Refererが必要なら合わせて指定）
BGM_SOURCES = [
    {
        "filename": "main.mp3",
        "url": "https://amachamusic.chagasi.com/mp3/happytime.mp3",
        "title": "ハッピータイム (甘茶の音楽工房)",
        "referer": "https://amachamusic.chagasi.com/music_happytime.html",
    },
]

SE_SOURCES = [
    {
        "filename": "whoosh.mp3",
        "url": "https://soundeffect-lab.info/sound/anime/mp3/hyun1.mp3",
        "title": "ヒューン (効果音ラボ)",
        "referer": "https://soundeffect-lab.info/sound/anime/",
    },
    {
        "filename": "pop.mp3",
        "url": "https://soundeffect-lab.info/sound/anime/mp3/pafu1.mp3",
        "title": "パフ (効果音ラボ)",
        "referer": "https://soundeffect-lab.info/sound/anime/",
    },
    {
        "filename": "tada.mp3",
        "url": "https://soundeffect-lab.info/sound/anime/mp3/jajean1.mp3",
        "title": "ジャジャーン (効果音ラボ)",
        "referer": "https://soundeffect-lab.info/sound/anime/",
    },
]


def download_one(url, dest_path, referer=None, label=""):
    """1ファイルDL"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }
    if referer:
        headers["Referer"] = referer
    try:
        resp = requests.get(url, headers=headers, timeout=30, stream=True)
        resp.raise_for_status()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        size_kb = dest_path.stat().st_size / 1024
        print(f"  ✅ {label}  →  {dest_path.name} ({size_kb:.0f}KB)")
        return True
    except Exception as e:
        print(f"  ❌ {label}  FAILED: {e}")
        return False


def download_bgm():
    print("── BGM (甘茶の音楽工房) ─────────────────────")
    BGM_DIR.mkdir(parents=True, exist_ok=True)
    for src in BGM_SOURCES:
        dest = BGM_DIR / src["filename"]
        if dest.exists():
            print(f"  ⏭️  {src['title']}  →  既に存在")
            continue
        download_one(src["url"], dest, src.get("referer"), src["title"])
    print()


def download_se():
    print("── SE (効果音ラボ) ──────────────────────────")
    SE_DIR.mkdir(parents=True, exist_ok=True)
    for src in SE_SOURCES:
        dest = SE_DIR / src["filename"]
        if dest.exists():
            print(f"  ⏭️  {src['title']}  →  既に存在")
            continue
        download_one(src["url"], dest, src.get("referer"), src["title"])
    print()


def print_character_instructions():
    print("── 立ち絵 (手動配置) ───────────────────────")
    print("  商用OKかつ自動DLできる決定打が見つからず、")
    print("  一旦 立ち絵なしで動画生成します。")
    print("  手動配置したい場合は以下のいずれかから:")
    print()
    print("  • AOmaterial (商用可・無償)")
    print("    https://aomaterial.com/")
    print("  • イラストAC (商用可・要会員登録・無料)")
    print("    https://www.ac-illust.com/")
    print("  • 素材屋あいりす (商用可・報告不要)")
    print("    https://sozai-irisu.com/")
    print()
    print(f"  DLしたPNGを {ASSETS_DIR}/zundamon.png に配置すると")
    print("  再生成時に自動で右下に表示されます。")
    print()
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def main():
    parser = argparse.ArgumentParser(description="shorts動画用のフリー素材を自動DL")
    parser.add_argument("--bgm", action="store_true", help="BGMのみ")
    parser.add_argument("--se", action="store_true", help="SEのみ")
    args = parser.parse_args()

    print("=" * 55)
    print("  shorts動画用フリー素材 自動ダウンロード")
    print("=" * 55)
    print()

    any_flag = args.bgm or args.se
    if not any_flag or args.bgm:
        download_bgm()
    if not any_flag or args.se:
        download_se()
    if not any_flag:
        print_character_instructions()

    print("完了. shorts/bgm/, shorts/se/ を確認してください")


if __name__ == "__main__":
    main()
