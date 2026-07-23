"""フレーム描画: グラデ背景 + モーションタイポ + 強調色 + big_number 演出."""
from __future__ import annotations
import math
import random
from pathlib import Path
from typing import List, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from ..config import (
    WIDTH, HEIGHT, FONT_PATH, FONT_FALLBACK, PALETTE,
)

_FONT_CACHE: dict = {}


def _font(size: int) -> ImageFont.FreeTypeFont:
    key = size
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    try:
        f = ImageFont.truetype(str(FONT_PATH), size)
    except Exception:
        f = ImageFont.truetype(str(FONT_FALLBACK), size)
    _FONT_CACHE[key] = f
    return f


def _hex_rgb(hex_color: str) -> Tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _emph_color(name: str) -> Tuple[int, int, int]:
    key = {
        "yellow": "emph_yellow",
        "red":    "emph_red",
        "cyan":   "emph_cyan",
        "pink":   "emph_pink",
        "green":  "emph_green",
    }.get(name, "emph_yellow")
    return _hex_rgb(PALETTE[key])


# ───── 背景 ──────────────────────────────────────
def _radial_gradient(width: int, height: int, t: float, seed: int = 0) -> Image.Image:
    """紺メインのラジアルグラデ + わずかに揺れる光点."""
    base = Image.new("RGB", (width, height), _hex_rgb(PALETTE["bg_dark"]))
    # ラジアル光点（中央やや上）をオーバーレイ
    glow = Image.new("RGB", (width, height), (0, 0, 0))
    d = ImageDraw.Draw(glow)
    cx = width // 2 + int(20 * math.sin(t * 0.6 + seed))
    cy = int(height * 0.35) + int(15 * math.cos(t * 0.5 + seed))
    radius = int(width * 0.8)
    # 同心円グラデ
    for i in range(24):
        r = radius - i * 26
        if r <= 0:
            break
        alpha = int(14 + i * 3)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(alpha, alpha + 6, alpha + 20))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=40))
    return Image.blend(base, glow, alpha=0.55)


def _grain(img: Image.Image, strength: float = 4.0) -> Image.Image:
    arr = np.asarray(img).astype(np.int16)
    noise = (np.random.default_rng(42).integers(-int(strength), int(strength) + 1,
                                                size=arr.shape)).astype(np.int16)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


# ───── テキストレイアウト ─────────────────────
def _wrap_by_width(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> List[str]:
    """自動改行 (\\n は強制改行)."""
    lines_out: List[str] = []
    for forced in text.split("\n"):
        if not forced:
            lines_out.append("")
            continue
        line = ""
        for ch in forced:
            test = line + ch
            w = draw.textlength(test, font=font)
            if w > max_w and line:
                lines_out.append(line)
                line = ch
            else:
                line = test
        if line:
            lines_out.append(line)
    return lines_out


def _find_emph_spans(line: str, emphs: List[str]) -> List[Tuple[int, int]]:
    spans = []
    lo = line
    offset = 0
    for e in sorted(emphs, key=len, reverse=True):
        s = lo.find(e)
        if s >= 0:
            spans.append((offset + s, offset + s + len(e)))
    # 重複マージ
    spans.sort()
    merged = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _draw_caption_line(
    draw: ImageDraw.ImageDraw,
    line: str,
    font: ImageFont.FreeTypeFont,
    cx: int,
    y: int,
    color: Tuple[int, int, int],
    emph_spans: List[Tuple[int, int]],
    emph_color: Tuple[int, int, int],
    stroke: int = 6,
    stroke_fill=(0, 0, 0),
):
    """1行を中央揃えで描画、強調区間は色違い."""
    total_w = draw.textlength(line, font=font)
    x = cx - total_w // 2
    cur = 0
    # 文字単位でspan判定しつつバッチ描画
    for i, ch in enumerate(line):
        in_emph = any(s <= i < e for s, e in emph_spans)
        c = emph_color if in_emph else color
        w = draw.textlength(ch, font=font)
        draw.text((x, y), ch, font=font, fill=c,
                  stroke_width=stroke, stroke_fill=stroke_fill)
        x += w
        cur += 1


# ───── ビートフレーム描画 ──────────────────
def render_beat_frame(
    caption: str,
    emphasis: List[str],
    emph_color_name: str,
    big_number: str | None,
    visual_hint: str,
    progress: float,       # 0.0 〜 1.0 動画全体の進行
    beat_t: float,         # ビート内の経過秒
    beat_dur: float,       # ビートの長さ
    role: str = "payoff",
) -> np.ndarray:
    """1フレーム分の 1080×1920 画像を numpy array で返す."""
    # 背景
    bg = _radial_gradient(WIDTH, HEIGHT, progress * 6.0)

    # zoom_in: 1.0 → 1.08
    if visual_hint == "zoom_in":
        scale = 1.0 + 0.08 * min(1.0, beat_t / max(0.01, beat_dur))
        nw, nh = int(WIDTH * scale), int(HEIGHT * scale)
        bg = bg.resize((nw, nh), Image.LANCZOS)
        bg = bg.crop(((nw - WIDTH) // 2, (nh - HEIGHT) // 2,
                     (nw - WIDTH) // 2 + WIDTH, (nh - HEIGHT) // 2 + HEIGHT))
    elif visual_hint == "pan_left":
        shift = int(-40 * min(1.0, beat_t / max(0.01, beat_dur)))
        nw = WIDTH + 40
        bg = bg.resize((nw, HEIGHT), Image.LANCZOS)
        bg = bg.crop((20 + shift, 0, 20 + shift + WIDTH, HEIGHT))
    elif visual_hint == "pulse":
        s = 1.0 + 0.015 * math.sin(beat_t * 6.0)
        nw, nh = int(WIDTH * s), int(HEIGHT * s)
        bg = bg.resize((nw, nh), Image.LANCZOS)
        bg = bg.crop(((nw - WIDTH) // 2, (nh - HEIGHT) // 2,
                     (nw - WIDTH) // 2 + WIDTH, (nh - HEIGHT) // 2 + HEIGHT))

    bg = _grain(bg, strength=3.0)
    draw = ImageDraw.Draw(bg)

    # ───── プログレスバー (上部) ─────
    bar_y = 24
    bar_h = 8
    draw.rectangle([60, bar_y, WIDTH - 60, bar_y + bar_h], fill=(255, 255, 255, 60))
    filled = int((WIDTH - 120) * max(0.0, min(1.0, progress)))
    draw.rectangle([60, bar_y, 60 + filled, bar_y + bar_h], fill=_emph_color(emph_color_name))

    # ───── role 別レイアウト ─────
    is_hook = role == "hook"
    is_cta  = role == "cta"

    # big_number があれば上半分に巨大表示、キャプションは下
    if big_number and role == "payoff":
        _draw_big_number(draw, big_number, emph_color_name, beat_t, beat_dur)
        _draw_caption_block(draw, caption, emphasis, emph_color_name,
                            y_center=int(HEIGHT * 0.78), max_w=WIDTH - 160,
                            font_size=78, t=beat_t)
    elif is_hook:
        _draw_caption_block(draw, caption, emphasis, emph_color_name,
                            y_center=int(HEIGHT * 0.50), max_w=WIDTH - 140,
                            font_size=110, t=beat_t, hook=True)
    elif is_cta:
        # CTAはピンク帯にして目立たせる
        _draw_cta(draw, caption, beat_t)
    else:
        _draw_caption_block(draw, caption, emphasis, emph_color_name,
                            y_center=int(HEIGHT * 0.50), max_w=WIDTH - 140,
                            font_size=92, t=beat_t)

    # ───── 右下ブランドバッジ (CTA以外) ─────
    if not is_cta:
        _draw_brand(draw)

    return np.asarray(bg)


def _draw_caption_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    emphasis: List[str],
    emph_color_name: str,
    y_center: int,
    max_w: int,
    font_size: int,
    t: float,
    hook: bool = False,
):
    # 冒頭0.18s pop-in: スケール小→大
    pop_dur = 0.18
    if t < pop_dur:
        scale = 0.85 + 0.15 * (t / pop_dur)
    else:
        scale = 1.0
    fs = max(36, int(font_size * scale))
    font = _font(fs)

    lines = _wrap_by_width(draw, text, font, max_w)
    line_h = int(fs * 1.22)
    total_h = line_h * len(lines)
    top = y_center - total_h // 2

    emph_c = _emph_color(emph_color_name)
    text_c = _hex_rgb(PALETTE["text"])

    for i, line in enumerate(lines):
        spans = _find_emph_spans(line, emphasis)
        _draw_caption_line(
            draw, line, font, WIDTH // 2, top + i * line_h,
            color=text_c, emph_spans=spans, emph_color=emph_c,
            stroke=9 if hook else 7,
        )


def _draw_big_number(
    draw: ImageDraw.ImageDraw, text: str, emph_color_name: str,
    t: float, dur: float,
):
    # 数字をバーン! と出す演出
    pop = min(1.0, t / 0.28)
    scale = 0.6 + 0.4 * pop
    fs = int(220 * scale)
    font = _font(fs)
    w = draw.textlength(text, font=font)
    x = WIDTH // 2 - w // 2
    y = int(HEIGHT * 0.30)
    # グロー (ずらして同色薄く)
    c = _emph_color(emph_color_name)
    for dx, dy in [(-6, 0), (6, 0), (0, -6), (0, 6), (-4, -4), (4, 4)]:
        draw.text((x + dx, y + dy), text, font=font,
                  fill=(c[0] // 2, c[1] // 2, c[2] // 2))
    draw.text((x, y), text, font=font, fill=c,
              stroke_width=12, stroke_fill=(0, 0, 0))


def _draw_cta(draw: ImageDraw.ImageDraw, text: str, t: float):
    # ピンク帯
    bar_top = int(HEIGHT * 0.38)
    bar_bot = int(HEIGHT * 0.62)
    c = _hex_rgb(PALETTE["cta_pink"])
    draw.rectangle([0, bar_top, WIDTH, bar_bot], fill=c)
    # 上下にアクセント線
    draw.rectangle([0, bar_top - 6, WIDTH, bar_top], fill=_hex_rgb(PALETTE["emph_yellow"]))
    draw.rectangle([0, bar_bot, WIDTH, bar_bot + 6], fill=_hex_rgb(PALETTE["emph_yellow"]))
    # テキスト
    fs = 96
    font = _font(fs)
    lines = _wrap_by_width(draw, text, font, WIDTH - 80)
    line_h = int(fs * 1.25)
    total = line_h * len(lines)
    top = (bar_top + bar_bot) // 2 - total // 2
    for i, ln in enumerate(lines):
        w = draw.textlength(ln, font=font)
        draw.text((WIDTH // 2 - w // 2, top + i * line_h), ln,
                  font=font, fill=(255, 255, 255),
                  stroke_width=8, stroke_fill=(0, 0, 0))

    # 矢印↓
    pulse = 1.0 + 0.08 * math.sin(t * 8)
    arrow_fs = int(110 * pulse)
    af = _font(arrow_fs)
    arr = "↓"
    aw = draw.textlength(arr, font=af)
    draw.text((WIDTH // 2 - aw // 2, bar_bot + 30), arr, font=af,
              fill=(255, 255, 255), stroke_width=6, stroke_fill=(0, 0, 0))


def _draw_brand(draw: ImageDraw.ImageDraw):
    from ..config import AGENCY_NAME
    font = _font(34)
    txt = f"@{AGENCY_NAME}"
    w = draw.textlength(txt, font=font)
    pad = 16
    # 半透明黒背景
    x = WIDTH - w - 60
    y = HEIGHT - 80
    draw.rounded_rectangle([x - pad, y - pad // 2, x + w + pad, y + 48],
                           radius=14, fill=(0, 0, 0, 140))
    draw.text((x, y), txt, font=font, fill=(230, 230, 230))
