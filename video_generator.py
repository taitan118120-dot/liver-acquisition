#!/usr/bin/env python3
"""
TikTokショート動画 自動生成スクリプト v2
=========================================
shorts/capcut/*.json → AI音声 + Pexels背景動画 + テキストアニメ + BGM → MP4

使い方:
  python3 video_generator.py                          # 全113本生成
  python3 video_generator.py --file 01_xxx.json       # 1本だけ
  python3 video_generator.py --limit 5                # 最初の5本
  python3 video_generator.py --list                   # 生成状況一覧
  python3 video_generator.py --no-pexels              # Pexelsなしで生成（グラデ背景）

初回セットアップ:
  export PEXELS_API_KEY="YOUR_KEY_HERE"
  pip3 install edge-tts moviepy pillow numpy requests
"""

import os
import re
import sys
import json
import glob
import argparse
import asyncio
import hashlib
import textwrap
import random
import math
from pathlib import Path

import numpy as np
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import (
    ImageClip,
    VideoFileClip,
    AudioFileClip,
    CompositeVideoClip,
    CompositeAudioClip,
    concatenate_videoclips,
    vfx,
)

# tzunda-v1 演出モジュール
from video_layout import (
    build_bg as tz_build_bg,
    render_caption as tz_render_caption,
    build_speaker_clips as tz_build_speaker_clips,
    build_end_card as tz_build_end_card,
    build_progress_bar as tz_build_progress_bar,
)
from video_karaoke import fetch_mora_timing, build_karaoke_clip

# ─── 設定 ───────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
CAPCUT_DIR = BASE_DIR / "shorts" / "capcut"
VIDEO_DIR = BASE_DIR / "shorts" / "videos"
AUDIO_DIR = BASE_DIR / "shorts" / "audio"
BG_DIR = BASE_DIR / "shorts" / "backgrounds"
BGM_DIR = BASE_DIR / "shorts" / "bgm"
SE_DIR = BASE_DIR / "shorts" / "se"
ASSETS_DIR = BASE_DIR / "shorts" / "assets"

WIDTH = 1080
HEIGHT = 1920
FPS = 30  # 30fpsに上げて滑らかに

VOICE = "ja-JP-NanamiNeural"
RATE = "+10%"

# VOICEVOX (ローカルサーバ http://localhost:50021)
VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://localhost:50021")
VOICEVOX_SPEAKERS = {
    "zundamon":        3,   # ずんだもん ノーマル
    "zundamon_ama":    1,   # ずんだもん あまあま
    "zundamon_tsun":   7,   # ずんだもん ツンツン
    "zundamon_sexy":   5,   # ずんだもん セクシー
    "metan":           2,   # 四国めたん ノーマル
    "metan_ama":       0,   # 四国めたん あまあま
    "tsumugi":         8,   # 春日部つむぎ
    "ryusei":          13,  # 青山龍星 ノーマル
}

# 対話モード: 話者別設定 (shorts_generator.py の SPEAKER_COLORS と連動)
DIALOGUE_SPEAKER_CONFIG = {
    "zundamon": {
        "voicevox_id": 3,
        "asset_pattern": "zundamon*.png",
        "position": "left",   # 画面左下
        "box_color": (46, 125, 50),    # 深緑
        "accent_color": (129, 199, 132),
    },
    "metan": {
        "voicevox_id": 2,
        "asset_pattern": "metan*.png",
        "position": "right",  # 画面右下
        "box_color": (194, 24, 91),    # ピンク
        "accent_color": (244, 143, 177),
    },
}

FONT_PATH = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
FALLBACK_FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

# スライドtypeごとのPexels検索キーワード
PEXELS_KEYWORDS = {
    "hook": ["smartphone social media", "live streaming neon", "young woman phone"],
    "point": ["technology abstract", "neon light dark", "digital network"],
    "number": ["money success", "gold coins", "statistics graph"],
    "compare": ["versus comparison", "balance scale", "split screen"],
    "cta": ["thumbs up success", "happy celebration", "smartphone tap"],
}

# ─── フォント ────────────────────────────────────────

def get_font(size):
    for path in [FONT_PATH, FALLBACK_FONT_PATH]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ─── Pexels背景動画 ──────────────────────────────────

def search_pexels_video(query, orientation="portrait"):
    """Pexels APIで動画を検索"""
    if not PEXELS_API_KEY:
        return None
    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": query, "orientation": orientation, "size": "medium", "per_page": 15}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        videos = resp.json().get("videos", [])
        if not videos:
            return None
        video = random.choice(videos[:5])
        # HDまたはSDの縦動画ファイルを取得
        for vf in video["video_files"]:
            if vf.get("height", 0) >= 720 and vf.get("width", 0) < vf.get("height", 0):
                return vf["link"]
        # 縦動画がなければ最初のファイル
        for vf in video["video_files"]:
            if vf.get("height", 0) >= 720:
                return vf["link"]
        return video["video_files"][0]["link"] if video["video_files"] else None
    except Exception:
        return None


def download_pexels_video(query, slide_type="hook"):
    """背景動画をダウンロード（キャッシュ付き）"""
    cache_key = hashlib.md5(query.encode()).hexdigest()[:10]
    cache_path = BG_DIR / f"{cache_key}.mp4"
    if cache_path.exists():
        return str(cache_path)

    keywords = PEXELS_KEYWORDS.get(slide_type, PEXELS_KEYWORDS["point"])
    for kw in keywords:
        url = search_pexels_video(kw)
        if url:
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                cache_path.write_bytes(resp.content)
                return str(cache_path)
            except Exception:
                continue
    return None


# ─── 放射集中線背景（転職ずんだ風）──────────────────

def create_sunburst_background(center_color=(255, 230, 80), ray_color=(255, 150, 30),
                                num_rays=40, rotation=0.0):
    """放射状集中線背景 (転職ずんだ風 強化版)

    - 40レイ (密度UP)
    - 鮮やかなイエロー中心 → ビビッドオレンジレイ
    - 中央にスパーク光(白ハイライト) を大きめに
    - レイのエッジにわずかなフェード
    """
    import math as _math
    # 中心が明るい黄色、周辺が若干暗めのオレンジ寄り
    img = Image.new("RGB", (WIDTH, HEIGHT), center_color)
    draw = ImageDraw.Draw(img)

    cx = WIDTH // 2
    cy = HEIGHT // 2 - 150  # 少し上寄り
    radius = int(_math.hypot(WIDTH, HEIGHT)) + 200

    # レイを描画
    angle_step = 360.0 / num_rays
    for i in range(num_rays):
        angle1 = i * angle_step + rotation
        angle2 = (i + 0.45) * angle_step + rotation  # レイを少し細め
        p1 = (cx + radius * _math.cos(_math.radians(angle1)),
              cy + radius * _math.sin(_math.radians(angle1)))
        p2 = (cx + radius * _math.cos(_math.radians(angle2)),
              cy + radius * _math.sin(_math.radians(angle2)))
        draw.polygon([(cx, cy), p1, p2], fill=ray_color)

    # 画面端を若干暗くする (ビネット) → レイが引き締まる
    vignette = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    max_r = int(_math.hypot(WIDTH / 2, HEIGHT / 2)) + 100
    step = 30
    for r in range(max_r, 0, -step):
        alpha = int(80 * (r / max_r) ** 2)
        vd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 0, 0, 0))
        # 外側に広がるほど濃い黒フィルタ
    # 簡易ビネットは色減らして無効化、別途中央ハイライトで対応

    # 中央のスパーク (大きい白ハイライト)
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    highlight_r = 580
    for i in range(highlight_r, 0, -10):
        alpha = int(120 * (1 - i / highlight_r) ** 2)
        odraw.ellipse(
            [cx - i, cy - i, cx + i, cy + i],
            fill=(255, 250, 200, alpha),
        )
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    # 軽くブラーを加えてなめらかに (Pillowの組込みフィルタ)
    img = img.filter(ImageFilter.GaussianBlur(radius=1.5))
    return np.array(img)


# ─── グラデーション背景（Pexelsフォールバック）──────────

def create_gradient_background(bg_color, slide_type, duration):
    """アニメーション付きグラデーション背景を生成"""
    rgb = hex_to_rgb(bg_color)

    # タイプに応じてグラデーション方向と色を変える
    if slide_type == "hook":
        color_top = tuple(min(255, c + 40) for c in rgb)
        color_bot = tuple(max(0, c - 60) for c in rgb)
    elif slide_type == "number":
        color_top = (30, 20, 60)
        color_bot = (10, 10, 30)
    elif slide_type == "cta":
        color_top = tuple(min(255, c + 30) for c in rgb)
        color_bot = tuple(max(0, c - 40) for c in rgb)
    else:
        color_top = tuple(min(255, c + 20) for c in rgb)
        color_bot = tuple(max(0, c - 30) for c in rgb)

    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(color_top[0] + (color_bot[0] - color_top[0]) * ratio)
        g = int(color_top[1] + (color_bot[1] - color_top[1]) * ratio)
        b = int(color_top[2] + (color_bot[2] - color_top[2]) * ratio)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

    # 装飾パーティクル（光の粒）を追加
    for _ in range(15):
        px = random.randint(0, WIDTH)
        py = random.randint(0, HEIGHT)
        pr = random.randint(2, 8)
        alpha_val = random.randint(30, 80)
        overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.ellipse(
            [px - pr, py - pr, px + pr, py + pr],
            fill=(255, 255, 255, alpha_val),
        )
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    return np.array(img)


# ─── 背景動画クリップ生成 ──────────────────────────────

def get_background_clip(bg_color, slide_type, duration, keyword, use_pexels=True, style="sunburst"):
    """背景クリップを取得（Pexels動画 or 集中線 or グラデーション）

    style: "sunburst" (転職ずんだ風集中線) | "gradient" (グラデ)
    """
    # 集中線モード (転職ずんだ風)
    if style == "sunburst" and not (use_pexels and PEXELS_API_KEY):
        sun_img = create_sunburst_background()
        # 緩やかに回転させる
        base_clip = ImageClip(sun_img).with_duration(duration)
        try:
            # 30度/durationで回転。vfx.Rotate は moviepy 2.x で時間関数可
            def rot_at(t):
                return (t / max(duration, 0.01)) * 15  # 最大15度回転
            base_clip = base_clip.with_effects([vfx.Rotate(rot_at)])
        except Exception:
            pass
        return base_clip

    if use_pexels and PEXELS_API_KEY:
        video_path = download_pexels_video(keyword, slide_type)
        if video_path:
            try:
                bg_clip = VideoFileClip(video_path)
                # 1080×1920にリサイズ＆クロップ
                # アスペクト比を維持してリサイズ
                clip_ratio = bg_clip.w / bg_clip.h
                target_ratio = WIDTH / HEIGHT

                if clip_ratio > target_ratio:
                    # 横長 → 高さに合わせてリサイズ、横をクロップ
                    bg_clip = bg_clip.resized(height=HEIGHT)
                    x_center = bg_clip.w // 2
                    bg_clip = bg_clip.cropped(
                        x1=x_center - WIDTH // 2,
                        y1=0,
                        x2=x_center + WIDTH // 2,
                        y2=HEIGHT,
                    )
                else:
                    # 縦長 → 幅に合わせてリサイズ、縦をクロップ
                    bg_clip = bg_clip.resized(width=WIDTH)
                    y_center = bg_clip.h // 2
                    bg_clip = bg_clip.cropped(
                        x1=0,
                        y1=y_center - HEIGHT // 2,
                        x2=WIDTH,
                        y2=y_center + HEIGHT // 2,
                    )

                # 動画を必要な長さにループ or カット
                if bg_clip.duration < duration:
                    bg_clip = bg_clip.with_effects([vfx.Loop(duration=duration)])
                else:
                    bg_clip = bg_clip.subclipped(0, duration)

                # 暗くする（テキスト視認性向上）
                bg_clip = bg_clip.with_effects([vfx.MultiplyColor(0.4)])

                return bg_clip
            except Exception:
                pass

    # フォールバック: グラデーション背景
    gradient_img = create_gradient_background(bg_color, slide_type, duration)
    return ImageClip(gradient_img).with_duration(duration)


# ─── 転職ずんだ風 ランキングタイトル画像生成 ───────────

def _draw_outlined_text(draw, xy, text, font, fill, outlines):
    """複数レイヤーの縁取りを描画するヘルパー

    outlines: [(color, radius), ...] 外側から内側への順
    """
    x, y = xy
    for color, radius in outlines:
        for ox in range(-radius, radius + 1):
            for oy in range(-radius, radius + 1):
                if ox * ox + oy * oy <= radius * radius:
                    draw.text((x + ox, y + oy), text, fill=color, font=font)
    draw.text((x, y), text, fill=fill, font=font)


def _draw_gradient_text(base_img, xy, text, font, top_color, bottom_color):
    """上→下のグラデーションで塗りつぶすテキスト"""
    x, y = xy
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1] + bbox[1]  # descender分
    # 文字マスクを描く
    mask = Image.new("L", (tw + 20, th + 40), 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.text((10, 0), text, fill=255, font=font)
    # グラデーション画像を作る
    grad = Image.new("RGBA", (tw + 20, th + 40), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(grad)
    for i in range(th + 40):
        ratio = i / max(th + 40, 1)
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * ratio)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * ratio)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * ratio)
        gdraw.line([(0, i), (tw + 20, i)], fill=(r, g, b, 255))
    # マスクを適用
    grad.putalpha(mask)
    # 本画像に合成
    base_img.paste(grad, (x - 10, y), grad)


def generate_ranking_title_image(rank_num, topic, width=WIDTH, height=HEIGHT):
    """上部に「第N位」+「項目名」の大きな2段タイトルを描画 (転職ずんだ風強化版)

    「第N位」: 白縁+グレー黒メタリック＋大きい黒影 (立体感)
    「項目名」: 黄色グラデ塗り + 濃赤太縁 + 黒細縁 + オレンジ影
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    rank_font = get_font(220)
    topic_font = get_font(150)

    # === 第N位 ===
    rank_text = f"第{rank_num}位"
    rank_bbox = rank_font.getbbox(rank_text)
    rank_w = rank_bbox[2] - rank_bbox[0]
    rank_h = rank_bbox[3] - rank_bbox[1]
    rank_x = (width - rank_w) // 2
    rank_y = 150

    # 影 (黒、右下に大きくずらす)
    for ox, oy in [(16, 20), (14, 18), (12, 16)]:
        draw.text((rank_x + ox, rank_y + oy), rank_text,
                  fill=(0, 0, 0, 180 - (abs(ox - 16)) * 20),
                  font=rank_font)

    # 多層縁取り: 黒外縁 → 白太縁 → 本体
    _draw_outlined_text(
        draw, (rank_x, rank_y), rank_text, rank_font,
        fill=(60, 60, 75, 255),  # 本体はグレー黒 (メタリック下地)
        outlines=[
            ((0, 0, 0, 255), 14),    # 黒外縁
            ((255, 255, 255, 255), 10),  # 白太縁
        ],
    )
    # メタリックグラデをマスクで重ねる (白→グレー)
    _draw_gradient_text(
        img, (rank_x, rank_y), rank_text, rank_font,
        top_color=(220, 220, 230),
        bottom_color=(60, 60, 80),
    )

    # === 項目名 ===
    topic_bbox = topic_font.getbbox(topic)
    topic_w = topic_bbox[2] - topic_bbox[0]
    topic_x = (width - topic_w) // 2
    topic_y = rank_y + rank_h + 100

    draw2 = ImageDraw.Draw(img)
    # 影 (オレンジ)
    for ox, oy in [(10, 14), (8, 12), (6, 10)]:
        draw2.text((topic_x + ox, topic_y + oy), topic,
                   fill=(200, 100, 20, 160), font=topic_font)
    # 多層縁取り: 黒外縁 → 赤濃縁 → 本体(黄色)
    _draw_outlined_text(
        draw2, (topic_x, topic_y), topic, topic_font,
        fill=(255, 220, 50, 255),
        outlines=[
            ((0, 0, 0, 255), 13),      # 黒外縁
            ((200, 30, 45, 255), 9),    # 赤太縁
        ],
    )
    # 黄色グラデ (明黄→濃黄)
    _draw_gradient_text(
        img, (topic_x, topic_y), topic, topic_font,
        top_color=(255, 245, 100),
        bottom_color=(245, 180, 30),
    )

    return np.array(img)


# ─── 転職ずんだ風 字幕カード (白背景+黄色枠) ────────────

def generate_card_subtitle_image(text, font_size=56, y_offset_ratio=0.55):
    """白背景+黄色太枠+赤文字の字幕カード (転職ずんだ風 強化版)

    - 大きい影 (下方向20px)
    - 黄色枠を20pxに増強
    - 内側にゴールド→白のグラデ風ハイライト
    - 文字サイズアップ、縁太め
    """
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    scaled_size = int(font_size * 1.5)
    font = get_font(scaled_size)

    padding = 70
    max_width = WIDTH - padding * 2
    lines = wrap_text(text, font, max_width)

    line_height = int(scaled_size * 1.35)
    total_text_height = line_height * len(lines)

    card_center_y = int(HEIGHT * y_offset_ratio)
    card_padding_v = 60
    card_h = total_text_height + card_padding_v * 2
    card_top = card_center_y - card_h // 2
    card_bottom = card_top + card_h
    card_left = 50
    card_right = WIDTH - 50

    # 大きい影 (下方向にずらし、ぼかし)
    shadow_pad = 20
    draw.rounded_rectangle(
        [card_left + shadow_pad, card_top + shadow_pad,
         card_right + shadow_pad, card_bottom + shadow_pad],
        radius=36, fill=(0, 0, 0, 180),
    )

    # 太い黄色枠
    border_w = 20
    draw.rounded_rectangle(
        [card_left, card_top, card_right, card_bottom],
        radius=36, fill=(255, 210, 50, 255),
    )
    # 黄色枠の上縁に明るいハイライト (ゴールド感)
    highlight_img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    hd = ImageDraw.Draw(highlight_img)
    hd.rounded_rectangle(
        [card_left + 4, card_top + 4, card_right - 4, card_top + 30],
        radius=30, fill=(255, 250, 180, 180),
    )
    img = Image.alpha_composite(img, highlight_img)
    draw = ImageDraw.Draw(img)

    # 白背景 (内側)
    draw.rounded_rectangle(
        [card_left + border_w, card_top + border_w,
         card_right - border_w, card_bottom - border_w],
        radius=22, fill=(255, 255, 255, 255),
    )

    # テキスト (赤文字+黒太縁)
    text_y_start = card_top + card_padding_v
    for i, line in enumerate(lines):
        bbox = font.getbbox(line)
        lw = bbox[2] - bbox[0]
        x = (WIDTH - lw) // 2
        y = text_y_start + i * line_height
        # 黒太縁
        _draw_outlined_text(
            draw, (x, y), line, font,
            fill=(215, 25, 55, 255),
            outlines=[((0, 0, 0, 255), 4)],
        )

    return np.array(img)


# ─── テキスト画像生成（縁取り付き）─────────────────────

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def wrap_text(text, font, max_width):
    chars_per_line = max(1, int(max_width / (font.size * 0.9)))
    lines = textwrap.wrap(text, width=chars_per_line)
    result = []
    for line in lines:
        bbox = font.getbbox(line)
        line_width = bbox[2] - bbox[0]
        if line_width <= max_width:
            result.append(line)
        else:
            mid = len(line) // 2
            result.append(line[:mid])
            result.append(line[mid:])
    return result


def generate_text_image(text, font_size, color, position="center"):
    """縁取り付きテキスト画像を生成（透明背景）"""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    scaled_size = int(font_size * 1.5)
    font = get_font(scaled_size)

    padding = 80
    max_width = WIDTH - padding * 2
    lines = wrap_text(text, font, max_width)

    line_height = int(scaled_size * 1.4)
    total_text_height = line_height * len(lines)

    if position == "bottom":
        y_start = HEIGHT - total_text_height - 350
    else:
        y_start = (HEIGHT - total_text_height) // 2

    text_color = hex_to_rgb(color)

    # 半透明の背景帯
    band_padding = 30
    band_top = y_start - band_padding
    band_bottom = y_start + total_text_height + band_padding
    draw.rounded_rectangle(
        [40, band_top, WIDTH - 40, band_bottom],
        radius=20,
        fill=(0, 0, 0, 140),
    )

    for i, line in enumerate(lines):
        bbox = font.getbbox(line)
        line_width = bbox[2] - bbox[0]
        x = (WIDTH - line_width) // 2
        y = y_start + i * line_height

        # 縁取り（太め）
        outline_color = (0, 0, 0, 255)
        for ox, oy in [(-3, -3), (-3, 3), (3, -3), (3, 3), (-3, 0), (3, 0), (0, -3), (0, 3)]:
            draw.text((x + ox, y + oy), line, fill=outline_color, font=font)

        # 本文
        draw.text((x, y), line, fill=(*text_color, 255), font=font)

    return np.array(img)


# ─── TTS ──────────────────────────────────────────────

async def generate_tts_async(text, output_path, rate=RATE):
    communicate = edge_tts.Communicate(text, VOICE, rate=rate)
    await communicate.save(output_path)


def generate_tts_edge(text, output_path, rate=RATE):
    asyncio.run(generate_tts_async(text, output_path, rate=rate))


def generate_tts_voicevox(text, output_path, speaker_id=3, speed=1.15):
    """VOICEVOXローカルサーバでTTS生成 (デフォルト: ずんだもん ノーマル)"""
    # Step 1: audio_query
    q = requests.post(
        f"{VOICEVOX_URL}/audio_query",
        params={"text": text, "speaker": speaker_id},
        timeout=30,
    )
    q.raise_for_status()
    query = q.json()
    # スピード調整 (1.0=通常, 1.15=少し速く, viralモード用)
    query["speedScale"] = speed
    # 音量と抑揚もブースト
    query["volumeScale"] = 1.0
    query["intonationScale"] = 1.2
    # Step 2: synthesis
    s = requests.post(
        f"{VOICEVOX_URL}/synthesis",
        params={"speaker": speaker_id},
        json=query,
        timeout=60,
    )
    s.raise_for_status()
    # VOICEVOXはWAVを返すので一旦WAV保存→MP3変換ではなくWAV直接使用
    wav_path = str(output_path).replace(".mp3", ".wav")
    with open(wav_path, "wb") as f:
        f.write(s.content)
    # MoviePyはWAV/MP3両対応なのでWAVパスを返す
    return wav_path


def generate_tts(text, output_path, rate=RATE, voice_provider="edge", voicevox_speaker=3, voicevox_speed=1.15):
    """統合TTSエントリ。voice_provider: 'edge' or 'voicevox'"""
    if voice_provider == "voicevox":
        try:
            return generate_tts_voicevox(text, output_path, speaker_id=voicevox_speaker, speed=voicevox_speed)
        except Exception as e:
            print(f"  ⚠️ VOICEVOX失敗、Edge-TTSにフォールバック: {e}")
            generate_tts_edge(text, output_path, rate=rate)
            return str(output_path)
    else:
        generate_tts_edge(text, output_path, rate=rate)
        return str(output_path)


# ─── Viralモード用エフェクト ─────────────────────────────

def apply_ken_burns(bg_clip, duration, start_scale=1.0, end_scale=1.18):
    """背景に緩やかなズーム(Ken Burns)を適用してダイナミックに"""
    try:
        def scale_at(t):
            ratio = min(1.0, t / max(duration, 0.01))
            return start_scale + (end_scale - start_scale) * ratio

        # MoviePy 2.x: vfx.Resize は時間関数を受け取れる
        return bg_clip.with_effects([vfx.Resize(scale_at)])
    except Exception:
        return bg_clip


def apply_text_popin(text_clip, duration, pop_duration=0.35):
    """テキストをオーバーシュート付きポップイン (スケール 0 → 1.15 → 1.0)"""
    try:
        def scale_at(t):
            if t >= pop_duration:
                return 1.0
            ratio = t / pop_duration
            # イージング: エラスティック風 (オーバーシュート)
            if ratio < 0.6:
                return ratio / 0.6 * 1.15  # 0 → 1.15
            else:
                # 1.15 → 1.0
                remaining = (ratio - 0.6) / 0.4
                return 1.15 - 0.15 * remaining
        return text_clip.with_effects([vfx.Resize(scale_at)])
    except Exception:
        return text_clip


def apply_text_pulse(text_clip, duration, beats=2, amplitude=0.08):
    """テキストに鼓動パルス (sin波で1.0〜1.08をbeats回)"""
    try:
        def scale_at(t):
            phase = (t / max(duration, 0.01)) * beats * 2 * math.pi
            return 1.0 + amplitude * abs(math.sin(phase))

        return text_clip.with_effects([vfx.Resize(scale_at)])
    except Exception:
        return text_clip


def generate_progress_bar_image(progress_ratio, height_px=10, color=(255, 225, 53)):
    """上部に配置する進捗バー画像を生成（透明背景）"""
    img = Image.new("RGBA", (WIDTH, 40), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 背景バー（半透明黒）
    draw.rounded_rectangle(
        [20, 15, WIDTH - 20, 15 + height_px],
        radius=height_px // 2,
        fill=(0, 0, 0, 140),
    )
    # 進捗（アクセントカラー）
    filled_w = int((WIDTH - 40) * max(0.0, min(1.0, progress_ratio)))
    if filled_w > 0:
        draw.rounded_rectangle(
            [20, 15, 20 + filled_w, 15 + height_px],
            radius=height_px // 2,
            fill=(*color, 255),
        )
    return np.array(img)


def build_progress_clip(total_duration, segment_starts, segment_durations):
    """動画全体の進捗バーを、複数の静止画を切り替えて表現（20ステップ）"""
    steps = 20
    step_duration = total_duration / steps
    clips = []
    for i in range(steps):
        ratio = (i + 1) / steps
        img = generate_progress_bar_image(ratio)
        clip = (
            ImageClip(img, transparent=True)
            .with_duration(step_duration)
            .with_start(i * step_duration)
            .with_position(("center", 0))
        )
        clips.append(clip)
    return clips


def get_audio_duration(audio_path):
    clip = AudioFileClip(audio_path)
    duration = clip.duration
    clip.close()
    return duration


# ─── 対話モード用レイアウト ────────────────────────────

def get_dialogue_character_clip(speaker, duration, start_time, active=True, viral=False):
    """対話モード: speaker毎のキャラ立ち絵 (active=False時は暗め)"""
    config = DIALOGUE_SPEAKER_CONFIG.get(speaker)
    if not config:
        return None
    assets = list(ASSETS_DIR.glob(config["asset_pattern"]))
    if not assets:
        return None
    try:
        clip = ImageClip(str(assets[0]), transparent=True).with_duration(duration).with_start(start_time)
        # サイズ調整
        target_h = 820 if viral else 760
        scale = target_h / clip.h
        target_w = int(clip.w * scale)
        clip = clip.resized((target_w, target_h))

        # 左右配置
        margin = 20
        if config["position"] == "left":
            x_pos = margin
        else:
            x_pos = WIDTH - target_w - margin
        y_pos = HEIGHT - target_h - 100  # 下から少し浮かせる

        # active (発話中) は通常、非activeは半透明暗く
        if not active:
            clip = clip.with_effects([vfx.MultiplyColor(0.55)])

        # 発話中は軽くバウンス
        if active and viral:
            def bounce_y(t):
                return y_pos + int(math.sin(t * 3 * math.pi) * 6)
            clip = clip.with_position(lambda t: (x_pos, bounce_y(t)))
        else:
            clip = clip.with_position((x_pos, y_pos))

        return clip
    except Exception as e:
        print(f"  ⚠️ {speaker} 立ち絵読込失敗: {e}")
        return None


def generate_dialogue_subtitle_image(text, speaker, font_size=54):
    """対話用: 話者色別の字幕ボックス画像"""
    config = DIALOGUE_SPEAKER_CONFIG.get(speaker, {})
    box_rgb = config.get("box_color", (10, 14, 39))

    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    scaled_size = int(font_size * 1.5)
    font = get_font(scaled_size)

    padding = 60
    max_width = WIDTH - padding * 2
    lines = wrap_text(text, font, max_width)

    line_height = int(scaled_size * 1.35)
    total_text_height = line_height * len(lines)

    # 画面中央やや上寄りに配置 (立ち絵の上)
    y_start = int(HEIGHT * 0.35) - total_text_height // 2

    # 話者色の角丸ボックス (不透明感を出す)
    band_padding = 40
    band_top = y_start - band_padding
    band_bottom = y_start + total_text_height + band_padding
    # 外枠（濃い色）
    draw.rounded_rectangle(
        [50, band_top, WIDTH - 50, band_bottom],
        radius=30,
        fill=(*box_rgb, 230),
    )
    # 内側ハイライト (上部明るく)
    inner_margin = 6
    highlight_h = (band_bottom - band_top) // 3
    draw.rounded_rectangle(
        [50 + inner_margin, band_top + inner_margin,
         WIDTH - 50 - inner_margin, band_top + highlight_h],
        radius=24,
        fill=(min(255, box_rgb[0] + 30),
              min(255, box_rgb[1] + 30),
              min(255, box_rgb[2] + 30), 80),
    )

    # 話者名ラベル (左上小さく)
    name_label = "ずんだもん" if speaker == "zundamon" else "四国めたん"
    name_font = get_font(int(font_size * 0.6))
    name_y = band_top - 50
    # 小さい名前バッジ
    name_bbox = name_font.getbbox(name_label)
    name_w = name_bbox[2] - name_bbox[0]
    name_h = name_bbox[3] - name_bbox[1]
    draw.rounded_rectangle(
        [50, name_y, 50 + name_w + 40, name_y + name_h + 20],
        radius=16,
        fill=(*box_rgb, 255),
    )
    draw.text((70, name_y + 6), name_label, fill=(255, 255, 255, 255), font=name_font)

    # テキスト本体
    for i, line in enumerate(lines):
        bbox = font.getbbox(line)
        line_width = bbox[2] - bbox[0]
        x = (WIDTH - line_width) // 2
        y = y_start + i * line_height
        # 縁取り (薄め - ボックス上なので不要に近い)
        for ox, oy in [(-2, -2), (2, -2), (-2, 2), (2, 2)]:
            draw.text((x + ox, y + oy), line, fill=(0, 0, 0, 200), font=font)
        draw.text((x, y), line, fill=(255, 255, 255, 255), font=font)

    return np.array(img)


# ─── 立ち絵オーバーレイ ───────────────────────────────

def get_character_overlay_clip(duration, viral=False, ranking_mode=False):
    """立ち絵PNGを配置。ranking_mode=True なら中央下に大きく、それ以外は右下"""
    asset_candidates = list(ASSETS_DIR.glob("zundamon*.png")) + list(ASSETS_DIR.glob("character*.png"))
    if not asset_candidates:
        return None
    try:
        char_path = str(asset_candidates[0])
        clip = ImageClip(char_path, transparent=True).with_duration(duration)

        if ranking_mode:
            # 転職ずんだ風: 中央下に大きく
            target_h = 1000
            scale = target_h / clip.h
            target_w = int(clip.w * scale)
            clip = clip.resized((target_w, target_h))
            x_pos = (WIDTH - target_w) // 2
            y_pos = HEIGHT - target_h - 20
        else:
            target_h = 720
            scale = target_h / clip.h
            target_w = int(clip.w * scale)
            clip = clip.resized((target_w, target_h))
            x_pos = WIDTH - target_w - 40
            y_pos = HEIGHT - target_h - 40

        # viralモード: 上下に軽くバウンス
        if viral:
            def bounce_y(t):
                return y_pos + int(math.sin(t * 2 * math.pi) * 6)
            clip = clip.with_position(lambda t: (x_pos, bounce_y(t)))
        else:
            clip = clip.with_position((x_pos, y_pos))

        return clip
    except Exception as e:
        print(f"  ⚠️ 立ち絵読み込み失敗: {e}")
        return None


# ─── SE (効果音) ──────────────────────────────────────

def get_se_clip(se_name, start_time):
    """効果音を指定時間にトリガー"""
    se_path = SE_DIR / f"{se_name}.mp3"
    if not se_path.exists():
        se_path = SE_DIR / f"{se_name}.wav"
    if not se_path.exists():
        return None
    try:
        se = AudioFileClip(str(se_path))
        # 最大2秒まで
        if se.duration > 2.0:
            se = se.subclipped(0, 2.0)
        se = se.with_volume_scaled(0.5).with_start(start_time)
        return se
    except Exception:
        return None


def build_se_track(segments_info):
    """セグメント情報から効果音トラックを生成

    segments_info: [(slide_type, start_time, duration), ...]
    """
    se_clips = []
    for slide_type, start, duration in segments_info:
        # slide_typeごとにSEを割当
        se_name = {
            "hook": "whoosh",
            "point": "pop",
            "number": "tada",
            "compare": "whoosh",
            "cta": "pop",
        }.get(slide_type)
        if se_name:
            clip = get_se_clip(se_name, start)
            if clip:
                se_clips.append(clip)
    return se_clips


# ─── BGM ──────────────────────────────────────────────

def get_bgm_clip(duration):
    """BGMクリップを取得（あれば）"""
    bgm_files = list(BGM_DIR.glob("*.mp3")) + list(BGM_DIR.glob("*.wav"))
    if not bgm_files:
        return None
    bgm_path = bgm_files[0]
    try:
        bgm = AudioFileClip(str(bgm_path))
        if bgm.duration < duration:
            bgm = bgm.with_effects([vfx.Loop(duration=duration)])
        else:
            bgm = bgm.subclipped(0, duration)
        # 音量を20%に
        bgm = bgm.with_volume_scaled(0.15)
        # フェードアウト
        bgm = bgm.audio_fadeout(2.0)
        return bgm
    except Exception:
        return None


# ─── 動画ビルド ───────────────────────────────────────

def _tz_voicevox_id(speaker: str) -> int:
    return {"zunda": 3, "metan": 2}.get(speaker, 3)


def build_video_tzunda(capcut_json_path, output_path):
    """tzunda-v1 スキーマ用の新レンダラ (@tensyokuzunda 風)"""
    with open(capcut_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    segments = data["segments"]
    keyword = data.get("keyword", "video")
    pattern = data.get("pattern", "")
    print(f"  tzunda-v1 レンダ: {len(segments)}セグメント / {keyword} / {pattern}")

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    clips = []
    segment_metas = []  # (duration, speaker, is_end_card)
    for idx, seg in enumerate(segments):
        text = seg.get("text", "")
        speaker = seg.get("speaker", "zunda")
        emphasis = seg.get("emphasis", []) or []
        bg_preset = seg.get("bg_preset", "navy")
        is_end_card = bool(seg.get("is_end_card", False))
        font_size = int(seg.get("font_size", 82))

        print(f"  [{idx+1}/{len(segments)}] [{speaker:5}] {text[:22]}…", end=" ", flush=True)

        # 1. TTS (VOICEVOX mora timing を取りつつ WAV 保存)
        wav_path = str(AUDIO_DIR / f"seg_{keyword}_{idx}.wav")
        vvox_speed = 1.10
        actual_wav, mora_timing = fetch_mora_timing(
            text, _tz_voicevox_id(speaker), wav_path, speed=vvox_speed
        )
        if not actual_wav:
            # Edge-TTS フォールバック
            mp3_path = str(AUDIO_DIR / f"seg_{keyword}_{idx}.mp3")
            generate_tts_edge(text, mp3_path, rate=RATE)
            actual_wav = mp3_path
            mora_timing = []
            print("(edge fallback)", end=" ")

        audio_duration = get_audio_duration(actual_wav)
        duration = max(audio_duration + 0.25, 1.8)

        # 2. 背景
        bg_clip = tz_build_bg(bg_preset, duration, seed=idx)

        # 3. 立ち絵 L/R
        char_clips = tz_build_speaker_clips(speaker, duration, ASSETS_DIR, pulse=True)

        # 4. 静的キャプション（大型・中央上）
        if is_end_card:
            caption_clip = tz_build_end_card(text, duration)
            karaoke_clip = None
        else:
            caption_clip = tz_render_caption(text, emphasis, duration, font_size=font_size)
            # 5. カラオケ層（VOICEVOX mora があるときだけ）
            karaoke_clip = build_karaoke_clip(
                text, emphasis, mora_timing, duration, font_size=font_size
            )

        # 6. 合成
        layers = [bg_clip]
        layers.extend(char_clips)
        layers.append(caption_clip)
        if karaoke_clip is not None:
            layers.append(karaoke_clip)

        composite = CompositeVideoClip(layers, size=(WIDTH, HEIGHT)).with_duration(duration)
        composite = composite.with_audio(AudioFileClip(actual_wav))

        clips.append(composite)
        segment_metas.append((duration, speaker, is_end_card))
        print(f"✅ ({duration:.1f}s)")

    # 7. ハードカット連結
    print("  ハードカット連結…", end=" ", flush=True)
    final_clips = []
    t_cursor = 0.0
    segment_starts = []
    for c in clips:
        segment_starts.append(t_cursor)
        final_clips.append(c.with_start(t_cursor))
        t_cursor += c.duration
    total_duration = t_cursor

    # 8. 常時プログレスバー
    progress_clips = tz_build_progress_bar(total_duration, steps=40)

    composite_layers = list(final_clips) + progress_clips

    final = CompositeVideoClip(composite_layers, size=(WIDTH, HEIGHT)).with_duration(total_duration)

    # 9. 音声合成: 各セグメント音声 + pop SE + BGM
    audio_clips = []
    for c, start in zip(clips, segment_starts):
        if c.audio:
            audio_clips.append(c.audio.with_start(start))

    # 冒頭 pop SE（無ければスキップ）
    for start, (_, _, is_end) in zip(segment_starts, segment_metas):
        se_name = "ding" if is_end else "pop"
        se = get_se_clip(se_name, start)
        if se:
            audio_clips.append(se)

    bgm = get_bgm_clip(total_duration)
    if bgm:
        audio_clips.append(bgm)

    if audio_clips:
        final = final.with_audio(CompositeAudioClip(audio_clips))

    # 10. 出力
    final.write_videofile(
        str(output_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        bitrate="8000k",
        ffmpeg_params=["-crf", "19", "-pix_fmt", "yuv420p"],
        logger=None,
    )
    final.close()
    for c in clips:
        c.close()
    print("✅")
    return output_path


def build_video(capcut_json_path, output_path, use_pexels=True, viral=False,
                voice_provider="edge", voicevox_speaker=3):
    """CapCut JSONから高品質動画を生成 (tzunda-v1 自動判定)"""
    with open(capcut_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # tzunda-v1 スキーマなら新レンダラへ
    if data.get("style_version") == "tzunda-v1":
        return build_video_tzunda(capcut_json_path, output_path)

    segments = data["segments"]
    keyword = data.get("keyword", "video")
    pattern = data.get("pattern", "")

    # 対話モード検出
    is_dialogue = any("speaker" in seg for seg in segments)
    # ランキング/転職ずんだ風モード (TOP3等)
    is_ranking = ("TOP" in pattern or "TOP3" in pattern) and not is_dialogue

    mode_label = "🔥 VIRAL" if viral else "通常"
    if is_dialogue:
        mode_label += " 💬対話"
    if is_ranking:
        mode_label += " 🏆ランキング"
    voice_label = f"VOICEVOX(sp={voicevox_speaker})" if voice_provider == "voicevox" else "Edge-TTS"
    print(f"  セグメント数: {len(segments)}  モード: {mode_label}  音声: {voice_label}")

    clips = []
    transition_duration = 0.2 if viral else 0.3  # viralモードは詰める

    # viralモード用のTTSレート (デフォルト+10%→+20%)
    tts_rate = "+20%" if viral else RATE
    # セグメント間の余白 (デフォルト+0.5s→+0.15s)
    padding = 0.15 if viral else 0.5
    min_seg = 1.8 if viral else 2.5

    for idx, seg in enumerate(segments):
        text = seg["text"]
        font_size = seg["font_size"]
        color = seg["color"]
        bg_color = seg["bg_color"]
        position = seg.get("position", "center")
        slide_type = seg.get("type", "point")

        # 対話モード: speakerがあればVOICEVOX speakerを上書き
        seg_speaker = seg.get("speaker")
        seg_voicevox_id = voicevox_speaker
        if is_dialogue and seg_speaker:
            spk_config = DIALOGUE_SPEAKER_CONFIG.get(seg_speaker, {})
            seg_voicevox_id = spk_config.get("voicevox_id", voicevox_speaker)

        # viralモード: フォントサイズを1.15倍、hookはさらに1.2倍
        if viral:
            font_size = int(font_size * 1.15)
            if slide_type == "hook":
                font_size = int(font_size * 1.15)

        print(f"  [{idx + 1}/{len(segments)}] [{seg_speaker or slide_type:9}] {text[:18]}...", end=" ", flush=True)

        # 1. TTS音声生成
        audio_path = AUDIO_DIR / f"seg_{keyword}_{idx}.mp3"
        # VOICEVOXはスピードをサーバ側で指定するのでrateは使わない
        vvox_speed = 1.25 if viral else 1.10
        # 対話モードは話者ごとに speaker_id を切替
        actual_audio = generate_tts(
            text, str(audio_path), rate=tts_rate,
            voice_provider=voice_provider,
            voicevox_speaker=seg_voicevox_id,
            voicevox_speed=vvox_speed,
        )
        audio_duration = get_audio_duration(actual_audio)
        duration = max(audio_duration + padding, min_seg)

        # 2. 背景クリップ（集中線/Pexels/グラデーション）
        bg_style = "sunburst" if is_ranking else "gradient"
        bg_clip = get_background_clip(bg_color, slide_type, duration, keyword, use_pexels, style=bg_style)

        # viralモード: Ken Burns ズームで背景を動かす (sunburstは既に回転してるのでスキップ)
        if viral and not is_ranking:
            bg_clip = apply_ken_burns(bg_clip, duration)

        # 3. テキストクリップ（ranking/対話/通常の3モード）
        if is_ranking:
            # ランキング解析: "第1位：スマホ" → ("1", "スマホ")、それ以外はそのまま字幕カード
            m = re.match(r"第(\d+)位[：:]?\s*(.+)", text)
            top_title_img = None
            if m:
                rank_num = m.group(1)
                topic = m.group(2).strip()
                # 上部タイトル画像生成
                top_title_img = generate_ranking_title_image(rank_num, topic)
            # 下部字幕カード (メインの説明文があれば、なければ空)
            # ランキング項目では上部タイトルのみ、説明はないので空カードは出さない
            text_img = None
            if slide_type == "hook" or slide_type == "cta" or not m:
                text_img = generate_card_subtitle_image(text, font_size=font_size)
        elif is_dialogue and seg_speaker:
            text_img = generate_dialogue_subtitle_image(text, seg_speaker, font_size=font_size)
            top_title_img = None
        else:
            text_img = generate_text_image(text, font_size, color, position)
            top_title_img = None

        # テキストクリップ (text_img があれば作成)
        text_clip = None
        if text_img is not None:
            text_clip = (
                ImageClip(text_img, is_mask=False, transparent=True)
                .with_duration(duration)
                .with_start(0)
                .with_position(("center", "center"))
                .with_effects([vfx.CrossFadeIn(0.15 if is_dialogue else (0.2 if viral else 0.3))])
            )
            # viralモード: ポップイン + hook/numberにはパルス (ranking時はポップインのみ)
            if viral:
                text_clip = apply_text_popin(text_clip, duration, pop_duration=0.28 if is_dialogue else 0.35)
                if slide_type in ("hook", "number") and not is_dialogue and not is_ranking:
                    text_clip = apply_text_pulse(text_clip, duration, beats=2, amplitude=0.09)

        # 上部ランキングタイトル (rankingモード時)
        top_title_clip = None
        if top_title_img is not None:
            top_title_clip = (
                ImageClip(top_title_img, is_mask=False, transparent=True)
                .with_duration(duration)
                .with_start(0)
                .with_position(("center", "center"))
                .with_effects([vfx.CrossFadeIn(0.15)])
            )
            # ランキングタイトルにはポップインと軽いパルス
            top_title_clip = apply_text_popin(top_title_clip, duration, pop_duration=0.4)
            top_title_clip = apply_text_pulse(top_title_clip, duration, beats=1, amplitude=0.06)

        # 4. 合成
        layers = [bg_clip]
        if top_title_clip is not None:
            layers.append(top_title_clip)
        if text_clip is not None:
            layers.append(text_clip)
        composite = CompositeVideoClip(layers, size=(WIDTH, HEIGHT)).with_duration(duration)

        # 音声を追加
        composite = composite.with_audio(AudioFileClip(actual_audio))

        clips.append(composite)
        print(f"✅ ({duration:.1f}s)")

    # 5. クロスフェードで連結
    print(f"  動画を連結中...", end=" ", flush=True)

    if len(clips) > 1:
        # クロスフェード付き連結
        final_clips = [clips[0]]
        current_start = clips[0].duration - transition_duration
        for i in range(1, len(clips)):
            clip = clips[i].with_start(current_start).with_effects(
                [vfx.CrossFadeIn(transition_duration)]
            )
            final_clips.append(clip)
            current_start += clips[i].duration - transition_duration

        total_duration = current_start + transition_duration

        # viralモード: 上部プログレスバーを重ねる
        composite_layers = list(final_clips)
        if viral:
            progress_clips = build_progress_clip(total_duration, None, None)
            composite_layers.extend(progress_clips)

        # 対話モードは両キャラの立ち絵を発話タイミングで配置、それ以外は単独立ち絵
        if is_dialogue:
            # 各セグメントの開始時刻を計算
            seg_start = 0.0
            for i, seg in enumerate(segments):
                clip_dur = clips[i].duration
                spk = seg.get("speaker")
                # ずんだもん・めたん 両方表示。active は現在の話者
                for candidate in ("zundamon", "metan"):
                    char = get_dialogue_character_clip(
                        candidate, clip_dur, seg_start,
                        active=(candidate == spk), viral=viral,
                    )
                    if char:
                        composite_layers.append(char)
                seg_start += clip_dur - (transition_duration if i < len(clips) - 1 else 0)
            print(f"  💬 対話モード: 両キャラ配置 完了")
        else:
            char_clip = get_character_overlay_clip(total_duration, viral=viral, ranking_mode=is_ranking)
            if char_clip:
                composite_layers.append(char_clip)
                label = "中央下大" if is_ranking else "右下"
                print(f"  👤 立ち絵オーバーレイ 追加 ({label})")

        final = CompositeVideoClip(composite_layers, size=(WIDTH, HEIGHT)).with_duration(total_duration)

        # 各セグメントの音声もずらして合成
        audio_clips = []
        audio_start = 0
        # SEトリガー情報収集用
        seg_timing_info = []
        for i, clip in enumerate(clips):
            if clip.audio:
                audio_clips.append(clip.audio.with_start(audio_start))
            # viralモード: SE挿入タイミング記録
            seg_type = segments[i].get("type", "point")
            seg_timing_info.append((seg_type, audio_start, clip.duration))
            audio_start += clip.duration - (transition_duration if i < len(clips) - 1 else 0)

        # SE追加
        if viral:
            se_clips = build_se_track(seg_timing_info)
            if se_clips:
                audio_clips.extend(se_clips)
                print(f"  🔊 SE {len(se_clips)}個 追加")

        if audio_clips:
            final_audio = CompositeAudioClip(audio_clips)
            bgm = get_bgm_clip(total_duration)
            if bgm:
                final_audio = CompositeAudioClip([final_audio, bgm])
            final = final.with_audio(final_audio)
    else:
        final = clips[0]
        bgm = get_bgm_clip(final.duration)
        if bgm and final.audio:
            final = final.with_audio(CompositeAudioClip([final.audio, bgm]))

    # 6. MP4出力 (高画質設定)
    final.write_videofile(
        str(output_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="slow",     # slow: 画質優先 (少し遅くなるがキレイ)
        bitrate="8000k",   # 8Mbps: TikTok推奨帯
        ffmpeg_params=["-crf", "18", "-pix_fmt", "yuv420p"],
        logger=None,
    )

    final.close()
    for clip in clips:
        clip.close()

    print(f"✅")
    return output_path


# ─── メイン ───────────────────────────────────────────

def get_capcut_files():
    return sorted(glob.glob(str(CAPCUT_DIR / "*.json")))


def list_status():
    files = get_capcut_files()
    generated = 0
    print(f"\n全{len(files)}本のCapCut JSON:\n")
    for f in files:
        basename = os.path.basename(f)
        video_name = basename.replace(".json", ".mp4")
        video_path = VIDEO_DIR / video_name
        status = "✅" if video_path.exists() else "⬜"
        if video_path.exists():
            generated += 1
        with open(f, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        print(f"  {status} {basename}  ({data['duration']:.0f}秒 / {data['slides']}スライド)")
    print(f"\n生成済み: {generated}/{len(files)}本")


def main():
    parser = argparse.ArgumentParser(description="TikTokショート動画 自動生成 v2")
    parser.add_argument("--file", type=str, help="特定のCapCut JSONファイルのみ生成")
    parser.add_argument("--limit", type=int, help="最初のN本だけ生成")
    parser.add_argument("--list", action="store_true", help="生成状況一覧を表示")
    parser.add_argument("--no-pexels", action="store_true", help="Pexels背景なし（グラデーション背景）")
    parser.add_argument("--regenerate", action="store_true", help="生成済みも再生成")
    parser.add_argument("--viral", action="store_true", help="バズ動画風モード (パルス+KenBurns+プログレスバー+テンポUP)")
    parser.add_argument("--voice", choices=["edge", "zundamon", "zundamon_ama", "zundamon_tsun", "zundamon_sexy", "metan", "tsumugi", "ryusei"],
                        default="edge", help="TTS音声: edge=Azure Nanami, zundamon=VOICEVOX ずんだもん, 他")

    args = parser.parse_args()

    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    BG_DIR.mkdir(parents=True, exist_ok=True)
    BGM_DIR.mkdir(parents=True, exist_ok=True)

    if args.list:
        list_status()
        return

    use_pexels = not args.no_pexels
    if use_pexels and not PEXELS_API_KEY:
        print("⚠️  PEXELS_API_KEY が未設定です。グラデーション背景で生成します。")
        print("   設定方法: export PEXELS_API_KEY='YOUR_KEY'")
        print()
        use_pexels = False

    if args.file:
        target_path = CAPCUT_DIR / args.file
        if not target_path.exists():
            matches = [f for f in get_capcut_files() if args.file in f]
            if matches:
                files = matches[:1]
            else:
                print(f"❌ ファイルが見つかりません: {args.file}")
                return
        else:
            files = [str(target_path)]
    else:
        files = get_capcut_files()

    if args.limit:
        files = files[:args.limit]

    # VOICEVOX設定
    if args.voice == "edge":
        voice_provider = "edge"
        voicevox_speaker = 0
    else:
        voice_provider = "voicevox"
        voicevox_speaker = VOICEVOX_SPEAKERS.get(args.voice, 3)
        # 起動確認
        try:
            requests.get(f"{VOICEVOX_URL}/version", timeout=3)
        except Exception:
            print(f"⚠️  VOICEVOXに接続できません ({VOICEVOX_URL})")
            print(f"   voicevox.hiroshiba.jp からDL→起動してから再実行してください")
            print(f"   Edge-TTSで続行します")
            voice_provider = "edge"

    print("=" * 60)
    print(f"  TikTokショート動画 自動生成 v2 {'🔥VIRAL' if args.viral else ''}")
    print(f"  対象: {len(files)}本")
    voice_desc = f"VOICEVOX {args.voice} (sp={voicevox_speaker})" if voice_provider == "voicevox" else f"{VOICE} ({'+20%' if args.viral else RATE})"
    print(f"  音声: {voice_desc}")
    print(f"  背景: {'Pexels動画' if use_pexels else 'グラデーション'}")
    print(f"  BGM:  {'あり' if list(BGM_DIR.glob('*.*')) else 'なし（shorts/bgm/にMP3を配置）'}")
    print(f"  出力: {VIDEO_DIR}/")
    print("=" * 60)
    print()

    success = 0
    errors = []

    for i, filepath in enumerate(files, 1):
        basename = os.path.basename(filepath)
        video_name = basename.replace(".json", ".mp4")
        output_path = VIDEO_DIR / video_name

        if not args.regenerate and output_path.exists():
            print(f"[{i}/{len(files)}] {basename} → スキップ（生成済み）")
            success += 1
            continue

        print(f"[{i}/{len(files)}] {basename}")
        try:
            build_video(filepath, output_path, use_pexels=use_pexels, viral=args.viral,
                        voice_provider=voice_provider, voicevox_speaker=voicevox_speaker)
            success += 1
            print()
        except Exception as e:
            print(f"  ❌ エラー: {e}")
            errors.append((basename, str(e)))
            print()

    print("=" * 60)
    print(f"  完了: {success}/{len(files)}本")
    if errors:
        print(f"  エラー: {len(errors)}本")
        for name, err in errors:
            print(f"    - {name}: {err}")
    print(f"  出力先: {VIDEO_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
