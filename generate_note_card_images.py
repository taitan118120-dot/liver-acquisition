#!/usr/bin/env python3
"""
Note記事用 アイキャッチ画像生成（Pillow ローカル版・APIコスト0）
================================================================
Geminiを使わず、Pillowでテーマカラー＋テキストオーバーレイ型の
1280x670（Note推奨16:9相当）アイキャッチ画像を生成する。

使い方:
  python3 generate_note_card_images.py 61 62 63 ...
  python3 generate_note_card_images.py --range 61 76
  python3 generate_note_card_images.py --all-missing
"""

import os
import sys
import glob
import re
import argparse
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTICLES_DIR = os.path.join(BASE_DIR, "blog", "articles_note")
IMAGES_DIR = os.path.join(BASE_DIR, "blog", "images")

FONT_BOLD = "/Users/mitataisei/ライバー獲得/video_pipeline/assets/NotoSansJP-Bold.ttf"
FONT_REG  = "/Users/mitataisei/ライバー獲得/instagram/fonts/NotoSansJP-VF.ttf"

WIDTH, HEIGHT = 1280, 670

# 記事番号 → カラーパレット（top, bottom, accent）
PALETTES = {
    61: ((255, 121, 121), (157, 80, 187), (255, 230, 100)),   # P×TT 比較・赤紫
    62: ((255, 56, 92),   (40, 40, 60),   (255, 230, 100)),   # TikTok 始め方・赤黒
    63: ((10, 132, 255),  (94, 92, 230),  (255, 214, 102)),   # フォロワー1000・青系
    64: ((255, 99, 71),   (45, 45, 80),   (255, 220, 100)),   # 稼げない原因・赤黒
    65: ((59, 130, 246),  (139, 92, 246), (251, 191, 36)),    # 事務所選び・青紫
    66: ((251, 191, 36),  (217, 119, 6),  (255, 240, 200)),   # ギフト換金・金
    67: ((255, 138, 101), (244, 81, 30),  (255, 224, 130)),   # 17LIVE・オレンジ
    68: ((236, 64, 122),  (142, 36, 170), (255, 213, 79)),    # SHOWROOM・ピンク紫
    69: ((38, 198, 218),  (3, 155, 229),  (255, 235, 59)),    # 始める前10・水色
    70: ((121, 134, 203), (63, 81, 181),  (255, 213, 79)),    # リスナー0・落ち着き
    71: ((255, 138, 128), (244, 67, 54),  (255, 235, 59)),    # コアファン・赤
    72: ((129, 199, 132), (76, 175, 80),  (255, 235, 59)),    # 雑談ネタ・緑
    73: ((84, 110, 122),  (38, 50, 56),   (255, 193, 7)),     # 顔バレ・グレー
    74: ((255, 167, 38),  (255, 87, 34),  (255, 235, 59)),    # ゴールデンタイム
    75: ((124, 77, 255),  (98, 0, 234),   (255, 213, 79)),    # 親バレ・紫
    76: ((255, 215, 0),   (218, 165, 32), (50, 50, 80)),      # 月100万・ゴールド
    90: ((38, 70, 83),    (42, 157, 143), (233, 196, 106)),   # 出口戦略・ティール×金
    91: ((6, 95, 70),     (16, 185, 129), (250, 204, 21)),    # NISA全世界株・グリーン×金
    92: ((30, 58, 138),   (109, 40, 217), (244, 114, 182)),   # セカンドキャリア・青紫×桃
}

DEFAULT_PALETTE = ((100, 100, 200), (50, 50, 100), (255, 220, 100))


def get_article_title_and_subtitle(article_num):
    pat = os.path.join(ARTICLES_DIR, f"{article_num:02d}_*.md")
    files = glob.glob(pat)
    if not files:
        return None, None
    with open(files[0], encoding="utf-8") as f:
        content = f.read()
    m = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    if not m:
        return None, None
    raw = m.group(1).strip()
    # タイトルを「主タイトル」と「サブ」に分離（｜で分割）
    if "｜" in raw:
        main, sub = raw.split("｜", 1)
    elif "|" in raw:
        main, sub = raw.split("|", 1)
    else:
        main, sub = raw, ""
    return main.strip(), sub.strip()


def get_basename(article_num):
    pat = os.path.join(ARTICLES_DIR, f"{article_num:02d}_*.md")
    files = glob.glob(pat)
    if not files:
        return None
    return os.path.splitext(os.path.basename(files[0]))[0]


def make_gradient(top_rgb, bottom_rgb, w, h):
    base = Image.new("RGB", (w, h), top_rgb)
    top = Image.new("RGB", (w, h), top_rgb)
    bot = Image.new("RGB", (w, h), bottom_rgb)
    mask = Image.new("L", (w, h))
    for y in range(h):
        v = int(255 * (y / h))
        for x in range(w):
            mask.putpixel((x, y), v)
    base = Image.composite(bot, top, mask)
    return base


def add_decorations(img, accent_rgb):
    """背景にぼかし円や帯で装飾"""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    # 大きめの半透明円
    for _ in range(4):
        cx = random.randint(0, WIDTH)
        cy = random.randint(0, HEIGHT)
        r = random.randint(150, 350)
        alpha = random.randint(20, 50)
        od.ellipse((cx - r, cy - r, cx + r, cy + r),
                   fill=(*accent_rgb, alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(40))
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, overlay)
    return img.convert("RGB")


def wrap_text(text, font, max_width, draw):
    """日本語テキストを max_width に収まるように行折り返し"""
    lines = []
    cur = ""
    for ch in text:
        test = cur + ch
        bbox = draw.textbbox((0, 0), test, font=font)
        w = bbox[2] - bbox[0]
        if w > max_width and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


def render_card(article_num, output_path):
    main, sub = get_article_title_and_subtitle(article_num)
    if not main:
        print(f"  ❌ #{article_num} 記事が見つかりません")
        return False

    palette = PALETTES.get(article_num, DEFAULT_PALETTE)
    top, bottom, accent = palette

    random.seed(article_num)

    img = make_gradient(top, bottom, WIDTH, HEIGHT)
    img = add_decorations(img, accent)

    draw = ImageDraw.Draw(img)

    # フォントサイズ調整
    title_font_size = 78
    sub_font_size   = 32
    brand_font_size = 28

    title_font = ImageFont.truetype(FONT_BOLD, title_font_size)
    sub_font   = ImageFont.truetype(FONT_BOLD, sub_font_size)
    brand_font = ImageFont.truetype(FONT_BOLD, brand_font_size)

    # 主タイトルの折り返し（左右マージン80px）
    margin = 80
    max_w = WIDTH - margin * 2

    # タイトルが長すぎる場合フォント縮小
    title_lines = wrap_text(main, title_font, max_w, draw)
    while len(title_lines) > 3 and title_font_size > 50:
        title_font_size -= 6
        title_font = ImageFont.truetype(FONT_BOLD, title_font_size)
        title_lines = wrap_text(main, title_font, max_w, draw)

    # 全体のテキストブロック高さ
    line_h = title_font_size + 14
    total_h = line_h * len(title_lines)
    if sub:
        total_h += 60

    start_y = (HEIGHT - total_h) // 2 - 40

    # 影付きで描画
    for i, line in enumerate(title_lines):
        bbox = draw.textbbox((0, 0), line, font=title_font)
        w = bbox[2] - bbox[0]
        x = (WIDTH - w) // 2
        y = start_y + i * line_h
        # 影
        draw.text((x + 3, y + 3), line, fill=(0, 0, 0, 120), font=title_font)
        # 本体
        draw.text((x, y), line, fill=(255, 255, 255), font=title_font)

    # サブタイトル
    if sub:
        # 短くする（先頭40字）
        sub_short = sub[:40]
        bbox = draw.textbbox((0, 0), sub_short, font=sub_font)
        w = bbox[2] - bbox[0]
        x = (WIDTH - w) // 2
        y = start_y + len(title_lines) * line_h + 20
        draw.text((x + 2, y + 2), sub_short, fill=(0, 0, 0, 120), font=sub_font)
        draw.text((x, y), sub_short, fill=accent, font=sub_font)

    # ブランドフッター
    brand_text = "TAITAN PRO  |  元Pococha S Rank"
    bbox = draw.textbbox((0, 0), brand_text, font=brand_font)
    w = bbox[2] - bbox[0]
    x = (WIDTH - w) // 2
    y = HEIGHT - 60
    draw.text((x + 2, y + 2), brand_text, fill=(0, 0, 0, 100), font=brand_font)
    draw.text((x, y), brand_text, fill=(255, 255, 255), font=brand_font)

    # 上下の細ライン
    draw.rectangle((0, 0, WIDTH, 8), fill=accent)
    draw.rectangle((0, HEIGHT - 8, WIDTH, HEIGHT), fill=accent)

    img.save(output_path, "PNG", optimize=True)
    print(f"  ✅ #{article_num}: {os.path.basename(output_path)}")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("nums", nargs="*", type=int, help="記事番号")
    parser.add_argument("--range", nargs=2, type=int, help="範囲指定 start end")
    parser.add_argument("--all-missing", action="store_true",
                        help="画像未生成の記事を全て対象に")
    args = parser.parse_args()

    targets = []
    if args.range:
        targets = list(range(args.range[0], args.range[1] + 1))
    elif args.nums:
        targets = args.nums
    elif args.all_missing:
        for f in sorted(glob.glob(os.path.join(ARTICLES_DIR, "*.md"))):
            m = re.match(r'(\d+)_', os.path.basename(f))
            if not m:
                continue
            num = int(m.group(1))
            base = os.path.splitext(os.path.basename(f))[0]
            img_path = os.path.join(IMAGES_DIR, f"{base}.png")
            if not os.path.exists(img_path):
                targets.append(num)

    if not targets:
        print("対象の記事番号を指定してください")
        sys.exit(1)

    os.makedirs(IMAGES_DIR, exist_ok=True)

    for num in targets:
        base = get_basename(num)
        if not base:
            print(f"  ❌ #{num} 記事ファイルが見つかりません")
            continue
        out_path = os.path.join(IMAGES_DIR, f"{base}.png")
        try:
            render_card(num, out_path)
        except Exception as e:
            print(f"  ❌ #{num} エラー: {e}")


if __name__ == "__main__":
    main()
