#!/usr/bin/env python3
"""
caption_preview_v2.py
=====================
@tensyokuzunda 風の高品質デザイン試作:
- 集中線/サンバースト背景
- 白ピル + 黒文字 + 赤縁取りの強調見出し
- 巨大ランキングヘッダー (第X位)
- 下段の白箱キャプション (黒文字、影付き)
"""
from __future__ import annotations
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

WIDTH = 1080
HEIGHT = 1920

FONT_CANDIDATES = [
    Path("/Users/mitataisei/ライバー獲得/shorts/assets/fonts/NotoSansJP-Black.otf"),
    Path("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    return ImageFont.load_default()


# ─── sunburst 背景 ──────────────────────────────

def build_sunburst_bg(
    cx: int = WIDTH // 2,
    cy: int = int(HEIGHT * 0.35),
    center_color=(255, 231, 92),
    ray_color_a=(255, 195, 37),
    ray_color_b=(255, 150, 20),
    rim_color=(255, 120, 10),
    num_rays: int = 24,
    seed: int = 0,
) -> Image.Image:
    """@tensyokuzunda 風の放射線背景 (黄→オレンジ)。"""
    img = Image.new("RGB", (WIDTH, HEIGHT), rim_color)
    # 半径方向グラデ（外縁はオレンジ、中心は黄色）
    pixels = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    yy, xx = np.ogrid[:HEIGHT, :WIDTH]
    dx = xx - cx
    dy = yy - cy
    dist = np.sqrt(dx * dx + dy * dy)
    r_max = math.hypot(max(cx, WIDTH - cx), max(cy, HEIGHT - cy))
    t = np.clip(dist / r_max, 0.0, 1.0)
    for i, (ca, cb) in enumerate(zip(center_color, rim_color)):
        pixels[..., i] = (ca * (1 - t) + cb * t).astype(np.uint8)
    img = Image.fromarray(pixels, "RGB")

    # 放射線（交互色）
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    angle_step = 360 / num_rays
    # 三角形polygonで放射
    for i in range(num_rays):
        a0 = math.radians(i * angle_step)
        a1 = math.radians((i + 1) * angle_step)
        half = math.radians(angle_step / 2)
        color = ray_color_a if i % 2 == 0 else ray_color_b
        length = r_max * 1.4
        # 各放射線は厚み half のくさび
        p1 = (cx, cy)
        p2 = (cx + length * math.cos(a0 + half * 0.1), cy + length * math.sin(a0 + half * 0.1))
        p3 = (cx + length * math.cos(a1 - half * 0.1), cy + length * math.sin(a1 - half * 0.1))
        draw.polygon([p1, p2, p3], fill=(*color, 200 if i % 2 == 0 else 120))
    img = Image.alpha_composite(img.convert("RGBA"), overlay)
    # 中央に黄色グロー
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r, a in [(520, 60), (360, 90), (220, 130), (120, 170)]:
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 240, 140, a))
    glow = glow.filter(ImageFilter.GaussianBlur(30))
    img = Image.alpha_composite(img, glow)
    # 端を少し暗く
    vignette = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    vd.rectangle([0, HEIGHT - 200, WIDTH, HEIGHT], fill=(0, 0, 0, 70))
    vd.rectangle([0, 0, WIDTH, 80], fill=(0, 0, 0, 60))
    img = Image.alpha_composite(img, vignette)
    return img.convert("RGB")


# ─── 巨大ヘッダー (第X位 / キーワード) ──────────────

def render_rank_header(
    rank_text: str | None,
    keyword_text: str | None,
    y_rank: int = 140,
    y_keyword: int = 360,
) -> Image.Image:
    """白角丸パネルに黒文字（赤ストローク付き）で巨大ヘッダーを描画"""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def draw_box_text(text, y_top, font_size, text_color, box_fill=(255, 255, 255), box_stroke=(0, 0, 0), stroke_w=8, padding=(60, 26)):
        font = _font(font_size)
        bb = font.getbbox(text)
        tw = bb[2] - bb[0]
        th = bb[3] - bb[1]
        px, py = padding
        bw = tw + px * 2
        bh = th + py * 2
        bx = (WIDTH - bw) // 2
        by = y_top
        # shadow
        shadow = Image.new("RGBA", (bw + 40, bh + 40), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle([0, 0, bw, bh], radius=bh // 3, fill=(0, 0, 0, 140))
        shadow = shadow.filter(ImageFilter.GaussianBlur(14))
        img.paste(shadow, (bx - 5, by + 10), shadow)
        # box
        draw.rounded_rectangle(
            [bx, by, bx + bw, by + bh],
            radius=bh // 3,
            fill=(*box_fill, 255),
            outline=(*box_stroke, 255),
            width=stroke_w,
        )
        # text with optional outline
        tx = bx + px - bb[0]
        ty = by + py - bb[1]
        draw.text((tx, ty), text, fill=(*text_color, 255), font=font)

    if rank_text:
        draw_box_text(rank_text, y_rank, 180, text_color=(20, 20, 20), stroke_w=10)
    if keyword_text:
        draw_box_text(keyword_text, y_keyword, 200, text_color=(220, 35, 35), stroke_w=12)

    return img


# ─── キャプション（下段 白箱 + 黒文字 + 赤強調） ──────────────

def _wrap_chars(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    if not text:
        return [""]
    lines, buf = [], ""
    for ch in text:
        test = buf + ch
        bb = font.getbbox(test)
        if bb[2] - bb[0] > max_w and buf:
            lines.append(buf)
            buf = ch
        else:
            buf = test
    if buf:
        lines.append(buf)
    return lines


def render_bottom_caption(
    text: str,
    emphasis: list[str] | None = None,
    font_size: int = 70,
    y_center_ratio: float = 0.62,
) -> Image.Image:
    """@tensyokuzunda の下段キャプション風: 白の角丸パネル + 黒文字、強調は赤"""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _font(font_size)

    max_w = int(WIDTH * 0.82) - 120
    lines = _wrap_chars(text, font, max_w)
    line_h = int(font_size * 1.35)
    block_h = line_h * len(lines)
    box_pad_x, box_pad_y = 60, 32
    # 最大行幅
    max_line_w = 0
    for l in lines:
        bb = font.getbbox(l)
        max_line_w = max(max_line_w, bb[2] - bb[0])
    box_w = max_line_w + box_pad_x * 2
    box_h = block_h + box_pad_y * 2
    box_x = (WIDTH - box_w) // 2
    box_y = int(HEIGHT * y_center_ratio) - box_h // 2

    # shadow
    shadow = Image.new("RGBA", (box_w + 60, box_h + 60), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle([0, 0, box_w, box_h], radius=40, fill=(0, 0, 0, 160))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    img.paste(shadow, (box_x - 8, box_y + 14), shadow)

    # box
    draw.rounded_rectangle(
        [box_x, box_y, box_x + box_w, box_y + box_h],
        radius=36,
        fill=(255, 255, 255, 248),
        outline=(0, 0, 0, 255),
        width=6,
    )

    # emphasis char indices
    emph_chars: set[int] = set()
    for e in emphasis or []:
        start = 0
        while True:
            idx = text.find(e, start)
            if idx < 0:
                break
            for k in range(idx, idx + len(e)):
                emph_chars.add(k)
            start = idx + len(e)

    # render per line, per char (emphasis → red)
    cursor_global = 0
    for li, line in enumerate(lines):
        bb = font.getbbox(line)
        lw = bb[2] - bb[0]
        x = box_x + (box_w - lw) // 2
        y = box_y + box_pad_y + li * line_h
        for ch in line:
            cb = font.getbbox(ch)
            cw = cb[2] - cb[0]
            color = (220, 35, 35) if cursor_global in emph_chars else (20, 20, 20)
            # 軽いストローク（赤文字のみ白縁で読みやすく）
            if cursor_global in emph_chars:
                for dx in (-2, 0, 2):
                    for dy in (-2, 0, 2):
                        if dx or dy:
                            draw.text((x + dx, y + dy), ch, fill=(255, 255, 255, 255), font=font)
            draw.text((x, y), ch, fill=color, font=font)
            x += cw
            cursor_global += 1
        # 改行ぶんはカウントアップなし（wrapは元テキストの連続部分）

    return img


# ─── ビルド & 保存 ─────────────────────────────

def build_scene(rank, keyword, caption, emphasis):
    bg = build_sunburst_bg()
    header = render_rank_header(rank, keyword)
    cap = render_bottom_caption(caption, emphasis=emphasis)
    result = bg.convert("RGBA")
    result = Image.alpha_composite(result, header)
    result = Image.alpha_composite(result, cap)
    return result.convert("RGB")


def main():
    out_dir = Path(__file__).resolve().parent / "outputs" / "caption_previews_v2"
    out_dir.mkdir(parents=True, exist_ok=True)

    scenes = [
        {
            "rank": "第1位",
            "keyword": "顔出しNG",
            "caption": "実は顔出しなしでも月30万円稼げるのだ",
            "emphasis": ["月30万円"],
        },
        {
            "rank": "第3位",
            "keyword": "初日収益化",
            "caption": "登録者0人からでも 収益化まで最短即日可能なのだ",
            "emphasis": ["最短即日"],
        },
        {
            "rank": None,
            "keyword": "ライバー始め方",
            "caption": "知らないと損する 3つのコツを紹介するのだ",
            "emphasis": ["3つ"],
        },
        {
            "rank": "第7位",
            "keyword": "雑談配信",
            "caption": "初心者は雑談よりASMRの方が稼げるのだ",
            "emphasis": ["ASMR"],
        },
    ]

    for i, s in enumerate(scenes):
        img = build_scene(s["rank"], s["keyword"], s["caption"], s["emphasis"])
        out = out_dir / f"v2_{i+1}.jpg"
        img.save(out, quality=90)
        print(f"saved: {out}")


if __name__ == "__main__":
    main()
