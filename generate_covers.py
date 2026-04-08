#!/usr/bin/env python3
"""
Note記事用 アイキャッチ画像生成（Pillow版）
テキスト+グラデーション背景でシンプルなカバー画像を生成
"""

import os
from PIL import Image, ImageDraw, ImageFont

IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blog", "images")
os.makedirs(IMAGES_DIR, exist_ok=True)

# 画像サイズ（16:9）
WIDTH, HEIGHT = 1280, 720

# 記事ごとの設定: (ファイル名, タイトル短縮版, グラデーション色1, グラデーション色2, アクセント絵文字)
ARTICLES = [
    ("27_ライバー事務所おすすめランキング", "ライバー事務所\nおすすめランキング\nTOP10", (220, 50, 50), (180, 30, 80)),
    ("28_ライバー1日スケジュール", "ライバーの\n1日スケジュール\n専業・副業別", (50, 120, 200), (30, 80, 180)),
    ("29_ライバー事務所怪しい見分け方", "怪しい\nライバー事務所の\n見分け方", (180, 40, 40), (120, 20, 60)),
    ("30_ライバーファン増やし方", "ライバーの\nファンの増やし方\n0→100人戦略", (200, 80, 160), (160, 40, 140)),
    ("31_ライバーメンタルケア", "ライバーの\nメンタルケア\n病む原因と対処法", (80, 160, 120), (40, 120, 100)),
    ("32_ライバー事務所移籍", "ライバー事務所\n移籍・変更方法\n円満退所ガイド", (50, 140, 180), (30, 100, 160)),
    ("33_ライブ配信アプリ比較", "ライブ配信アプリ\n徹底比較10選\n2026年版", (180, 100, 50), (140, 70, 30)),
    ("34_ライバー容姿関係ない", "ライバーに\n容姿は関係ない？\n稼げる理由と戦略", (200, 140, 60), (170, 100, 40)),
    ("35_ライバー事務所契約書注意点", "事務所の契約書\nチェックすべき\n10項目", (40, 60, 120), (20, 40, 100)),
    ("36_ライバーコラボ配信", "コラボ配信の\nやり方ガイド\nファンを一気に増やす", (220, 120, 50), (180, 80, 30)),
]


def create_gradient(width, height, color1, color2):
    """縦グラデーション画像を生成"""
    img = Image.new("RGB", (width, height))
    for y in range(height):
        ratio = y / height
        r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
        g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
        b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
        for x in range(width):
            img.putpixel((x, y), (r, g, b))
    return img


def create_gradient_fast(width, height, color1, color2):
    """高速版: numpy不要でも行単位で描画"""
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        ratio = y / height
        r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
        g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
        b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    return img


def find_font(size):
    """使えるフォントを探す"""
    # macOS日本語フォント候補
    font_paths = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def generate_cover(filename, title_text, color1, color2):
    """1枚のカバー画像を生成"""
    output_path = os.path.join(IMAGES_DIR, f"{filename}.png")
    if os.path.exists(output_path):
        print(f"  ⏭️ 既に存在: {filename}")
        return

    # グラデーション背景
    img = create_gradient_fast(WIDTH, HEIGHT, color1, color2)
    draw = ImageDraw.Draw(img)

    # 半透明オーバーレイ（白い丸を装飾として追加）
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    # 右上に大きな半透明の円
    overlay_draw.ellipse([WIDTH - 350, -100, WIDTH + 100, 350], fill=(255, 255, 255, 25))
    # 左下に小さな半透明の円
    overlay_draw.ellipse([-100, HEIGHT - 250, 250, HEIGHT + 100], fill=(255, 255, 255, 20))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # 「TAITAN PRO」ラベル（左上）
    label_font = find_font(28)
    draw.text((60, 40), "TAITAN PRO", fill=(255, 255, 255, 200), font=label_font)
    # 下線
    draw.line([(60, 75), (240, 75)], fill=(255, 255, 255, 150), width=2)

    # メインタイトル
    title_font = find_font(72)
    lines = title_text.split("\n")
    total_height = len(lines) * 90
    start_y = (HEIGHT - total_height) // 2 + 20

    for i, line in enumerate(lines):
        y = start_y + i * 90
        # テキスト影
        draw.text((62, y + 2), line, fill=(0, 0, 0, 80), font=title_font)
        # メインテキスト
        draw.text((60, y), line, fill=(255, 255, 255), font=title_font)

    # 下部のタグライン
    tag_font = find_font(24)
    draw.text((60, HEIGHT - 60), "現役事務所運営者が本音で解説", fill=(255, 255, 255, 180), font=tag_font)

    img.save(output_path, "PNG", quality=95)
    print(f"  ✅ 生成: {filename}")


def main():
    print("=" * 60)
    print("  Note記事 カバー画像生成（Pillow版）")
    print(f"  対象: {len(ARTICLES)}記事")
    print("=" * 60)

    for filename, title, c1, c2 in ARTICLES:
        generate_cover(filename, title, c1, c2)

    print()
    print(f"  完了！画像保存先: {IMAGES_DIR}/")


if __name__ == "__main__":
    main()
