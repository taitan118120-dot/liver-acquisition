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

# ─── 設定 ───────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
CAPCUT_DIR = BASE_DIR / "shorts" / "capcut"
VIDEO_DIR = BASE_DIR / "shorts" / "videos"
AUDIO_DIR = BASE_DIR / "shorts" / "audio"
BG_DIR = BASE_DIR / "shorts" / "backgrounds"
BGM_DIR = BASE_DIR / "shorts" / "bgm"

WIDTH = 1080
HEIGHT = 1920
FPS = 24

VOICE = "ja-JP-NanamiNeural"
RATE = "+10%"

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

def get_background_clip(bg_color, slide_type, duration, keyword, use_pexels=True):
    """背景クリップを取得（Pexels動画 or グラデーション）"""
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

async def generate_tts_async(text, output_path):
    communicate = edge_tts.Communicate(text, VOICE, rate=RATE)
    await communicate.save(output_path)


def generate_tts(text, output_path):
    asyncio.run(generate_tts_async(text, output_path))


def get_audio_duration(audio_path):
    clip = AudioFileClip(audio_path)
    duration = clip.duration
    clip.close()
    return duration


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

def build_video(capcut_json_path, output_path, use_pexels=True):
    """CapCut JSONから高品質動画を生成"""
    with open(capcut_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    segments = data["segments"]
    keyword = data.get("keyword", "video")

    print(f"  セグメント数: {len(segments)}")

    clips = []
    transition_duration = 0.3  # クロスフェード秒数

    for idx, seg in enumerate(segments):
        text = seg["text"]
        font_size = seg["font_size"]
        color = seg["color"]
        bg_color = seg["bg_color"]
        position = seg.get("position", "center")
        slide_type = seg.get("type", "point")

        print(f"  [{idx + 1}/{len(segments)}] {text[:20]}...", end=" ", flush=True)

        # 1. TTS音声生成
        audio_path = AUDIO_DIR / f"seg_{keyword}_{idx}.mp3"
        generate_tts(text, str(audio_path))
        audio_duration = get_audio_duration(str(audio_path))
        duration = max(audio_duration + 0.5, 2.5)

        # 2. 背景クリップ（Pexels or グラデーション）
        bg_clip = get_background_clip(bg_color, slide_type, duration, keyword, use_pexels)

        # 3. テキストクリップ（フェードインアニメーション）
        text_img = generate_text_image(text, font_size, color, position)
        text_clip = (
            ImageClip(text_img, is_mask=False, transparent=True)
            .with_duration(duration)
            .with_start(0)
            .with_position(("center", "center"))
            .with_effects([vfx.CrossFadeIn(0.3)])
        )

        # 4. 合成
        composite = CompositeVideoClip(
            [bg_clip, text_clip],
            size=(WIDTH, HEIGHT),
        ).with_duration(duration)

        # 音声を追加
        composite = composite.with_audio(AudioFileClip(str(audio_path)))

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
        final = CompositeVideoClip(final_clips, size=(WIDTH, HEIGHT)).with_duration(total_duration)

        # 各セグメントの音声もずらして合成
        audio_clips = []
        audio_start = 0
        for i, clip in enumerate(clips):
            if clip.audio:
                audio_clips.append(clip.audio.with_start(audio_start))
            audio_start += clip.duration - (transition_duration if i < len(clips) - 1 else 0)

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

    # 6. MP4出力
    final.write_videofile(
        str(output_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        bitrate="4000k",
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

    print("=" * 60)
    print(f"  TikTokショート動画 自動生成 v2")
    print(f"  対象: {len(files)}本")
    print(f"  音声: {VOICE}")
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
            build_video(filepath, output_path, use_pexels=use_pexels)
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
