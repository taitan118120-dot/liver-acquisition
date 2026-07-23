#!/usr/bin/env python3
"""
ショート動画用のVTuber風キャラ立ち絵を自動生成

Pollinations.ai (無料・無制限・商用OK) で画像生成
→ rembg で背景透過
→ shorts/assets/character.png に保存

使い方:
  python3 generate_character.py                        # デフォルトプロンプトで生成
  python3 generate_character.py --prompt "..."         # カスタムプロンプト
  python3 generate_character.py --seed 42              # シード指定（再現性）
"""
import os
import argparse
import urllib.parse
import requests
from pathlib import Path
from PIL import Image
from io import BytesIO

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "shorts" / "assets"

DEFAULT_PROMPT = (
    "flat vector illustration, cute japanese streamer mascot character, "
    "simple cel-shaded cartoon style, thick clean bold black outlines, "
    "flat solid colors no gradient, adobe illustrator style, "
    "cheerful young woman with ponytail, pink headphones around neck, "
    "holding smartphone doing live streaming pose, casual t-shirt, "
    "bust up portrait facing viewer, "
    "solid pure white background, minimal shading, "
    "kawaii corporate mascot, friendly smile, "
    "NOT photorealistic, NOT 3D render, NOT realistic skin, "
    "japanese illustration style like irasutoya or soco-st, "
    "pastel pink and light blue accent colors"
)

def generate_from_pollinations(prompt, width=768, height=1152, seed=7):
    """Pollinations.ai で画像生成"""
    encoded = urllib.parse.quote(prompt)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={width}&height={height}&model=flux&nologo=true&seed={seed}"
    )
    print(f"  📡 Pollinations.ai に問い合わせ中... (512KB程度、30秒前後)")
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    img = Image.open(BytesIO(resp.content)).convert("RGB")
    print(f"  ✅ 生成完了: {img.size[0]}x{img.size[1]}px")
    return img


def remove_background(img):
    """rembgで背景透過"""
    try:
        from rembg import remove
    except ImportError:
        print("  ⚠️ rembg未インストール。pip install rembg してください")
        return None
    print(f"  🎨 背景透過処理中...")
    output = remove(img)
    print(f"  ✅ 透過完了")
    return output


def main():
    parser = argparse.ArgumentParser(description="VTuber風キャラ立ち絵 自動生成")
    parser.add_argument("--prompt", type=str, default=DEFAULT_PROMPT, help="生成プロンプト (英語推奨)")
    parser.add_argument("--seed", type=int, default=7, help="シード値（再現性制御）")
    parser.add_argument("--output", type=str, default="character.png", help="出力ファイル名")
    parser.add_argument("--no-rembg", action="store_true", help="背景透過処理をスキップ")
    args = parser.parse_args()

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = ASSETS_DIR / args.output

    print("=" * 60)
    print("  VTuber風立ち絵 自動生成")
    print("=" * 60)
    print(f"  プロンプト: {args.prompt[:80]}...")
    print(f"  seed: {args.seed}")
    print()

    # 1. 生成
    img = generate_from_pollinations(args.prompt, seed=args.seed)

    # 2. 背景透過 (skipなら元のまま)
    if not args.no_rembg:
        transparent = remove_background(img)
        if transparent:
            img = transparent

    # 3. 保存
    img.save(str(output_path), "PNG")
    size_kb = output_path.stat().st_size / 1024
    print()
    print(f"💾 保存完了: {output_path} ({size_kb:.0f}KB)")
    print(f"   video_generator.py 実行時に自動で右下に表示されます")


if __name__ == "__main__":
    main()
