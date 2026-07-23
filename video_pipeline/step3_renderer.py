"""step3_renderer.py (v2.5対応版)
=================================
EditPlan v2 (または v1) を読み、縦型ショート動画 1080×1920 を出力する。

v2 機能:
  - hook (冒頭3秒の全画面オーバーレイ banner/centered_huge/chat_bubble/scribble)
  - Subtitle.tokens の color / size_scale (マルチカラー強調・サイズ変更)
  - Subtitle.template ごとに位置・スタイル切替 (punchline/question/shock/whisper)
  - Clip.speed (vfx.speedx で速度ランプ)
  - se_cues (pop/tada/whoosh の任意時刻挿入)
  - broll_cues (ken_burns / blur_bg / color_block / split_screen)
  - bgm (BGM音源を低音量で全体に重ねる)

v2.5 追加:
  - **カラオケ風単語進行リビール** (Token.reveal_start を時刻に展開)
  - **Hook entrance アニメ** (slide_left/slide_right/slide_up/slide_down/pop/fade/shake)
  - **Subtitle punch-in アニメ** (出現時120ms scale 0.85→1.08→1.0)
  - **BGM ducking** (発話中はBGM音量を50%に)
  - **Outro CTA card** (末尾1.5sにチャンネル登録誘導)
  - **数値強調パルス** (数字を含むtokenは出現時に1.0→1.3→1.0でバウンド)

v1 は version フィールドが無い場合、起動時に v2 互換に昇格してから処理する。

Usage:
  python step3_renderer.py
  python step3_renderer.py --input temp/edit_plan.json --output outputs/final.mp4
  python step3_renderer.py --font assets/NotoSansJP-Bold.ttf --font-size 72
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from dotenv import load_dotenv
from loguru import logger
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Pillow 10+ 互換パッチ（moviepy 1.0.3用）
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS  # type: ignore[attr-defined]

from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)
from moviepy.audio.AudioClip import AudioClip
from moviepy.video.fx.all import resize, speedx

BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp"
OUTPUT_DIR = BASE_DIR / "outputs"
ASSETS_DIR = BASE_DIR / "assets"
LOG_DIR = BASE_DIR / "logs"
SHORTS_SE_DIR = BASE_DIR.parent / "shorts" / "se"
for d in (TEMP_DIR, OUTPUT_DIR, ASSETS_DIR, LOG_DIR):
    d.mkdir(exist_ok=True)

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}")
logger.add(LOG_DIR / "step3_{time:YYYYMMDD}.log", level="DEBUG", rotation="10 MB", retention="7 days")

# ========== 出力仕様 ==========
TARGET_W = 1080
TARGET_H = 1920
FPS = 30

# ========== テロップ仕様 ==========
DEFAULT_FONT_SIZE = 72
DEFAULT_FONT_COLOR = (255, 255, 255, 255)
STROKE_COLOR = (0, 0, 0, 255)
STROKE_WIDTH = 8
SHADOW_OFFSET = (4, 6)
SHADOW_COLOR = (0, 0, 0, 180)
SUBTITLE_MAX_WIDTH_RATIO = 0.88

FONT_CANDIDATES = [
    ASSETS_DIR / "NotoSansJP-Bold.ttf",
    BASE_DIR.parent / "shorts" / "fonts" / "NotoSansJP-Bold.ttf",
    Path("/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc"),
    Path("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
]

# ========== Template別 y_ratio ==========
TEMPLATE_Y_RATIO = {
    "default": 0.72,
    "punchline": 0.50,
    "question": 0.50,
    "shock": 0.45,
    "whisper": 0.78,
}


def _hex_to_rgba(h: str, alpha: int = 255) -> Tuple[int, int, int, int]:
    h = h.lstrip("#")
    if len(h) != 6:
        return (255, 255, 255, alpha)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def pick_font(override: Optional[Path], size: int) -> ImageFont.FreeTypeFont:
    candidates: List[Path] = []
    if override:
        candidates.append(Path(override))
    candidates.extend(FONT_CANDIDATES)
    for f in candidates:
        if f.exists():
            try:
                font = ImageFont.truetype(str(f), size=size)
                logger.debug(f"フォント使用: {f} size={size}")
                return font
            except Exception as e:
                logger.warning(f"フォントロード失敗 {f}: {e}")
    raise RuntimeError(
        "日本語対応フォントが無い。assets/NotoSansJP-Bold.ttf を配置するか --font 指定。"
    )


_FONT_CACHE: dict = {}


def font_at(font_path: Optional[Path], size: int) -> ImageFont.FreeTypeFont:
    key = (str(font_path) if font_path else "_", size)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = pick_font(font_path, size)
    return _FONT_CACHE[key]


# =====================================================================
#                     v1 → v2 in-memory 昇格
# =====================================================================
def upgrade_v1_to_v2(plan: dict) -> dict:
    """version フィールドが無いplanに最低限のv2/v2.5フィールドを補完する。"""
    if plan.get("version") == "2":
        # v2 でも v2.5 の追加フィールドが無ければ補完
        plan.setdefault("outro", None)
        plan.setdefault("bgm_duck_segments", [])
        for s in plan.get("subtitles", []):
            s.setdefault("entrance", "punch")
            s.setdefault("karaoke", True)
            for tok in s.get("tokens", []):
                tok.setdefault("reveal_start", None)
        if plan.get("hook"):
            plan["hook"].setdefault("entrance", "slide_left")
            plan["hook"].setdefault("entrance_dur", 0.35)
        return plan
    plan["version"] = "2"
    plan.setdefault("genre", "default")
    plan.setdefault("template", {"genre": "default"})
    plan.setdefault("hook", None)
    plan.setdefault("outro", None)
    plan.setdefault("se_cues", [])
    plan.setdefault("broll_cues", [])
    plan.setdefault("bgm", None)
    plan.setdefault("bgm_duck_segments", [])
    plan.setdefault("critic", None)
    for s in plan.get("subtitles", []):
        s.setdefault("template", "default")
        s.setdefault("y_ratio", None)
        s.setdefault("entrance", "punch")
        s.setdefault("karaoke", False)  # v1 plan は reveal_start 無いので OFF
        for tok in s.get("tokens", []):
            tok.setdefault("color", None)
            tok.setdefault("size_scale", 1.0)
            tok.setdefault("reveal_start", None)
    for c in plan.get("clips", []):
        c.setdefault("speed", 1.0)
    return plan


# =====================================================================
#                       Hook オーバーレイ生成
# =====================================================================
def render_hook_png(
    hook: dict,
    font_path: Optional[Path],
) -> np.ndarray:
    style = hook.get("style", "banner")
    text = hook.get("text", "")
    subtext = hook.get("subtext")
    text_color = _hex_to_rgba(hook.get("text_color", "#FFFFFF"))
    bg_color = _hex_to_rgba(hook.get("bg_color", "#FF3C3C"))
    font_size = int(hook.get("font_size", 120))
    y_ratio = float(hook.get("y_ratio", 0.38))

    img = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Hook テキスト auto-fit（指定 font_size から始めて、画面の84%以下になるまで縮小）
    max_text_w = int(TARGET_W * 0.84)
    fitted_size = font_size
    while fitted_size > 40:
        f = font_at(font_path, fitted_size)
        bb = draw.textbbox((0, 0), text, font=f, stroke_width=8)
        if bb[2] - bb[0] <= max_text_w:
            break
        fitted_size -= 6
    main_font = font_at(font_path, fitted_size)
    sub_font = font_at(font_path, max(40, int(fitted_size * 0.5))) if subtext else None
    if subtext and sub_font:
        # サブも収まるサイズに
        ss = max(40, int(fitted_size * 0.5))
        while ss > 28:
            sf = font_at(font_path, ss)
            sb = draw.textbbox((0, 0), subtext, font=sf, stroke_width=6)
            if sb[2] - sb[0] <= max_text_w:
                sub_font = sf
                break
            ss -= 4

    bbox = draw.textbbox((0, 0), text, font=main_font, stroke_width=8)
    main_w, main_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    sub_w, sub_h = (0, 0)
    if subtext and sub_font:
        sb = draw.textbbox((0, 0), subtext, font=sub_font, stroke_width=6)
        sub_w, sub_h = sb[2] - sb[0], sb[3] - sb[1]

    block_w = max(main_w, sub_w) + 80
    block_h = main_h + (sub_h + 20 if subtext else 0) + 60
    cx = TARGET_W // 2
    cy = int(TARGET_H * y_ratio)

    if style == "banner":
        # 横長バンドにテキストを乗せる
        band_h = block_h
        band_y = cy - band_h // 2
        draw.rectangle((0, band_y, TARGET_W, band_y + band_h), fill=bg_color)
        # メインテキスト中央
        tx = cx - main_w // 2
        ty = band_y + 30
        draw.text((tx, ty), text, font=main_font, fill=text_color, stroke_width=4, stroke_fill=(0, 0, 0, 200))
        if subtext and sub_font:
            stx = cx - sub_w // 2
            sty = ty + main_h + 20
            draw.text((stx, sty), subtext, font=sub_font, fill=text_color, stroke_width=3, stroke_fill=(0, 0, 0, 200))
    elif style == "centered_huge":
        # 巨大テキスト中央、背景は透明
        tx = cx - main_w // 2
        ty = cy - main_h // 2
        draw.text((tx, ty), text, font=main_font, fill=text_color, stroke_width=10, stroke_fill=(0, 0, 0, 255))
        if subtext and sub_font:
            stx = cx - sub_w // 2
            sty = ty + main_h + 20
            draw.text((stx, sty), subtext, font=sub_font, fill=text_color, stroke_width=6, stroke_fill=(0, 0, 0, 255))
    elif style == "chat_bubble":
        # 角丸の吹き出し風
        pad = 60
        bx1 = cx - block_w // 2
        by1 = cy - block_h // 2
        bx2 = bx1 + block_w
        by2 = by1 + block_h
        draw.rounded_rectangle((bx1, by1, bx2, by2), radius=40, fill=bg_color)
        tx = cx - main_w // 2
        ty = by1 + 30
        draw.text((tx, ty), text, font=main_font, fill=text_color, stroke_width=2, stroke_fill=(0, 0, 0, 160))
        if subtext and sub_font:
            stx = cx - sub_w // 2
            sty = ty + main_h + 20
            draw.text((stx, sty), subtext, font=sub_font, fill=text_color)
    elif style == "scribble":
        # 黄色マーカー風下線 + テキスト
        marker_color = _hex_to_rgba("#FFD60A")
        tx = cx - main_w // 2
        ty = cy - main_h // 2
        draw.rectangle((tx - 10, ty + main_h - 18, tx + main_w + 10, ty + main_h + 12), fill=marker_color)
        draw.text((tx, ty), text, font=main_font, fill=text_color, stroke_width=4, stroke_fill=(0, 0, 0, 255))
    return np.array(img)


# =====================================================================
#                      Subtitle 画像化（v2.5: カラオケ進行対応）
# =====================================================================
DIM_COLOR = (220, 220, 220, 230)   # カラオケで未到達の文字色


def render_subtitle_png_v2(
    tokens: List[dict],
    template_name: str,
    base_font_size: int,
    font_path: Optional[Path],
    canvas_w: int,
    canvas_h: int,
    y_ratio_override: Optional[float] = None,
    active_until_token: Optional[int] = None,  # この index 以下のtokenだけ active 色 (カラオケ用)
) -> np.ndarray:
    """tokens: [{"text": "...", "highlight": bool, "color": "#XXXX", "size_scale": float}]

    text に "\n" を含めば改行として扱う。
    各tokenごとにフォントサイズと色を変更可能。
    """
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # tokens を改行で分割して行列に展開
    lines: List[List[dict]] = [[]]
    for t in tokens:
        text = t.get("text", "")
        # "\n" でtoken内分割
        parts = text.split("\n")
        for pi, p in enumerate(parts):
            if p:
                lines[-1].append(
                    {
                        "text": p,
                        "highlight": t.get("highlight", False),
                        "color": t.get("color"),
                        "size_scale": float(t.get("size_scale", 1.0)),
                    }
                )
            if pi < len(parts) - 1:
                lines.append([])
    if not lines or all(not L for L in lines):
        return np.array(img)
    lines = [L for L in lines if L]

    # 各行で最大フォントサイズを使って高さ計算
    line_metrics: List[Tuple[int, int, List[Tuple[dict, int, int]]]] = []
    for line_tokens in lines:
        line_w = 0
        line_h = 0
        token_w_h = []
        for t in line_tokens:
            size = max(16, int(base_font_size * t["size_scale"]))
            font = font_at(font_path, size)
            bbox = draw.textbbox((0, 0), t["text"], font=font, stroke_width=STROKE_WIDTH)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            token_w_h.append((t, tw, th))
            line_w += tw
            line_h = max(line_h, th)
        line_metrics.append((line_w, line_h, token_w_h))

    total_h = sum(lh for _, lh, _ in line_metrics) + (len(line_metrics) - 1) * 16
    y_ratio = y_ratio_override if y_ratio_override is not None else TEMPLATE_Y_RATIO.get(
        template_name, 0.72
    )
    y0 = int(canvas_h * y_ratio) - total_h // 2

    # template別の背景演出（whisper はそのまま、shock は赤い帯）
    if template_name == "shock":
        band_color = _hex_to_rgba("#FF3C3C", 200)
        band_top = y0 - 20
        band_bot = y0 + total_h + 20
        draw.rectangle((0, band_top, canvas_w, band_bot), fill=band_color)
    elif template_name == "punchline":
        band_color = _hex_to_rgba("#000000", 150)
        band_top = y0 - 20
        band_bot = y0 + total_h + 20
        draw.rectangle((0, band_top, canvas_w, band_bot), fill=band_color)

    # token のグローバル index（行をまたいだ通し番号）を作る
    # active_until_token (None=全部active) より大きい index は DIM 色で描画
    global_token_idx = -1
    cur_y = y0
    for line_w, line_h, token_w_h in line_metrics:
        x = (canvas_w - line_w) // 2
        for t, tw, th in token_w_h:
            global_token_idx += 1
            is_active = active_until_token is None or global_token_idx <= active_until_token

            size = max(16, int(base_font_size * t["size_scale"]))
            font = font_at(font_path, size)
            base_color = (
                _hex_to_rgba(t["color"]) if t.get("color") else DEFAULT_FONT_COLOR
            )
            if not t.get("highlight"):
                base_color = DEFAULT_FONT_COLOR
            # カラオケ: 未到達なら DIM 色で描画
            if not is_active:
                draw_color = DIM_COLOR
            else:
                draw_color = base_color
            # シャドウ
            sx, sy = SHADOW_OFFSET
            draw.text(
                (x + sx, cur_y + sy),
                t["text"],
                font=font,
                fill=SHADOW_COLOR,
                stroke_width=STROKE_WIDTH,
                stroke_fill=SHADOW_COLOR,
            )
            # 本体
            draw.text(
                (x, cur_y),
                t["text"],
                font=font,
                fill=draw_color,
                stroke_width=STROKE_WIDTH,
                stroke_fill=STROKE_COLOR,
            )
            x += tw
        cur_y += line_h + 16

    return np.array(img)


# =====================================================================
#                       縦型フィット & クリップ構築
# =====================================================================
def fit_vertical(clip):
    scaled = resize(clip, height=TARGET_H)
    w, h = scaled.size
    if w >= TARGET_W:
        x_center = w / 2
        x1 = int(x_center - TARGET_W / 2)
        return scaled.crop(x1=x1, y1=0, x2=x1 + TARGET_W, y2=TARGET_H)
    else:
        scaled2 = resize(clip, width=TARGET_W)
        w2, h2 = scaled2.size
        if h2 >= TARGET_H:
            y_center = h2 / 2
            y1 = int(y_center - TARGET_H / 2)
            return scaled2.crop(x1=0, y1=y1, x2=TARGET_W, y2=y1 + TARGET_H)
        return resize(scaled2, newsize=(TARGET_W, TARGET_H))


def build_base_video(source_path: Path, clips_plan: List[dict]):
    if not source_path.exists():
        raise FileNotFoundError(f"元動画が無い: {source_path}")

    src = VideoFileClip(str(source_path))
    try:
        pieces = []
        for i, c in enumerate(clips_plan):
            start = float(c["start"])
            end = float(c["end"])
            scale = float(c.get("scale", 1.0))
            speed = float(c.get("speed", 1.0))
            if end > src.duration:
                logger.warning(f"clip[{i}] end={end} > duration={src.duration} → 切詰")
                end = src.duration
            if start >= end:
                logger.warning(f"clip[{i}] 無効 スキップ")
                continue
            sub = src.subclip(start, end)
            if abs(scale - 1.0) > 1e-3:
                sub = resize(sub, scale)
            if abs(speed - 1.0) > 1e-3:
                sub = speedx(sub, speed)
            vert = fit_vertical(sub)
            pieces.append(vert)
            logger.debug(f"clip[{i}] {start:.2f}-{end:.2f}s scale={scale} speed={speed}")
        if not pieces:
            raise RuntimeError("有効clipゼロ")
        combined = concatenate_videoclips(pieces, method="compose")
        return src, combined
    except Exception:
        src.close()
        raise


# =====================================================================
#                       時間マッピング
# =====================================================================
def build_time_mapping(clips_plan: List[dict]) -> List[Tuple[float, float, float, float]]:
    """各clipの (orig_start, orig_end, edit_offset, speed) を返す。"""
    mapping = []
    cum = 0.0
    for c in clips_plan:
        s = float(c["start"])
        e = float(c["end"])
        sp = float(c.get("speed", 1.0))
        dur = (e - s) / sp
        mapping.append((s, e, cum, sp))
        cum += dur
    return mapping


def map_orig_to_edit(t: float, mapping) -> Optional[float]:
    for s, e, offset, sp in mapping:
        if s <= t <= e:
            return offset + (t - s) / sp
    return None


# =====================================================================
#                       Subtitle Overlays
# =====================================================================
def _punch_resize_factor(t: float, dur: float = 0.16) -> float:
    """Subtitle出現時の punch-in: 0→0.16s で 0.85 → 1.08 → 1.0 のオーバーシュート。"""
    if t >= dur:
        return 1.0
    progress = t / dur
    # ease-out + overshoot
    if progress < 0.6:
        # 0.85 → 1.08
        p = progress / 0.6
        return 0.85 + 0.23 * (1 - (1 - p) ** 2)
    else:
        # 1.08 → 1.0
        p = (progress - 0.6) / 0.4
        return 1.08 - 0.08 * p


def _scale_pop_factor(t: float, dur: float = 0.22) -> float:
    """数値強調用 pop: 1.0 → 1.30 → 1.0 のバウンド (出現時)。"""
    if t >= dur:
        return 1.0
    progress = t / dur
    if progress < 0.45:
        p = progress / 0.45
        return 1.0 + 0.30 * (1 - (1 - p) ** 2)
    else:
        p = (progress - 0.45) / 0.55
        return 1.30 - 0.30 * p


def _build_one_subtitle_overlays(
    sub: dict,
    edit_start: float,
    edit_end: float,
    base_font_size: int,
    font_path: Optional[Path],
) -> List[ImageClip]:
    """1個のsubtitleからOverlay群（カラオケ進行 + entrance アニメ含む）を作る。

    karaoke=True かつ tokens に reveal_start があれば、tokenごとに状態切替の
    画像を生成して連続貼り。
    karaoke=False または reveal_start 全部 None なら、1枚のPNGをsubtitle時間全体貼る。
    出現直後は punch-in scale animation を適用（CompositeVideoClipの仕組みで resize lambda使用）。
    """
    tokens = sub.get("tokens", [])
    template_name = sub.get("template", "default")
    y_ratio = sub.get("y_ratio")
    karaoke = sub.get("karaoke", True)
    duration = max(0.05, edit_end - edit_start)

    # token フィルタ: 純粋な改行 (\n) tokenは描画には影響しないが、
    # active_until_token のカウントには含む（reveal_startの整合のため）
    n_tokens = len(tokens)

    overlays: List[ImageClip] = []

    # 各 token の active 開始時刻（subtitle.start基準）を集める
    reveal_times: List[Optional[float]] = []
    for t in tokens:
        rs = t.get("reveal_start")
        reveal_times.append(float(rs) if rs is not None else None)

    # karaoke モード判定
    do_karaoke = karaoke and any(rt is not None for rt in reveal_times)

    if not do_karaoke:
        # シンプル: 全token activeで1枚
        png = render_subtitle_png_v2(
            tokens=tokens,
            template_name=template_name,
            base_font_size=base_font_size,
            font_path=font_path,
            canvas_w=TARGET_W,
            canvas_h=TARGET_H,
            y_ratio_override=y_ratio,
            active_until_token=None,
        )
        clip = (
            ImageClip(png, transparent=True)
            .set_start(edit_start)
            .set_duration(duration)
            .set_position(("center", "center"))
        )
        # entrance アニメ
        clip = _apply_entrance(clip, sub.get("entrance", "punch"), duration)
        overlays.append(clip)
        return overlays

    # karaoke: token単位で reveal するため、状態切替境界を決める
    # 境界 = ユニークな reveal_start (None は 0 と同視) + duration終端
    boundaries: List[float] = []
    for rt in reveal_times:
        b = float(rt) if rt is not None else 0.0
        if 0 <= b < duration:
            boundaries.append(round(b, 3))
    boundaries.append(duration)
    boundaries = sorted(set(boundaries))

    for i, b in enumerate(boundaries[:-1]):
        seg_start = b
        seg_end = boundaries[i + 1]
        if seg_end <= seg_start:
            continue
        # この区間で active な最大 token index
        active_idx = -1
        for ti, rt in enumerate(reveal_times):
            r = rt if rt is not None else 0.0
            if r <= seg_start + 1e-3:
                active_idx = ti
        png = render_subtitle_png_v2(
            tokens=tokens,
            template_name=template_name,
            base_font_size=base_font_size,
            font_path=font_path,
            canvas_w=TARGET_W,
            canvas_h=TARGET_H,
            y_ratio_override=y_ratio,
            active_until_token=active_idx,
        )
        clip = (
            ImageClip(png, transparent=True)
            .set_start(edit_start + seg_start)
            .set_duration(seg_end - seg_start)
            .set_position(("center", "center"))
        )
        # 最初の区間にだけ entrance アニメ適用
        if i == 0:
            clip = _apply_entrance(clip, sub.get("entrance", "punch"), seg_end - seg_start)
        overlays.append(clip)
    return overlays


def _apply_entrance(clip, entrance: str, segment_duration: float):
    """ImageClip に entrance アニメーションを適用して返す。"""
    from moviepy.video.fx.all import resize as _resize
    if entrance == "none":
        return clip
    if entrance == "punch":
        # scale 0.85 → 1.08 → 1.0 over 0.16s
        return clip.fx(_resize, lambda t: _punch_resize_factor(t))
    if entrance == "scale_pop":
        return clip.fx(_resize, lambda t: _scale_pop_factor(t))
    if entrance == "fade":
        # 透明度はImageClipのset_opacityで対応（一定値だが、crossfadein使う）
        try:
            return clip.crossfadein(min(0.2, segment_duration / 2))
        except Exception:
            return clip
    if entrance in ("slide_up", "slide_left"):
        # 別途 set_position lambda で対応
        return clip
    return clip


def build_subtitle_overlays(
    subtitles_plan: List[dict],
    mapping,
    base_font_size: int,
    font_path: Optional[Path],
) -> List[ImageClip]:
    overlays = []
    for si, sub in enumerate(subtitles_plan):
        raw_s = float(sub["start"])
        raw_e = float(sub["end"])
        ms = map_orig_to_edit(raw_s, mapping)
        me = map_orig_to_edit(raw_e, mapping)
        if ms is None or me is None or me <= ms:
            continue
        overlays.extend(
            _build_one_subtitle_overlays(sub, ms, me, base_font_size, font_path)
        )
    logger.info(f"subtitle overlay: {len(overlays)}件 (karaoke展開後)")
    return overlays


# =====================================================================
#                       Hook Overlay
# =====================================================================
def _ease_out_cubic(p: float) -> float:
    return 1 - (1 - p) ** 3


def _ease_out_back(p: float) -> float:
    """軽い跳ねを含むイージング (overshoot 1.07)。"""
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2


def _hook_position_lambda(entrance: str, entrance_dur: float):
    """Hook entrance アニメに応じた set_position 用 lambda を返す。
    座標は (x, y) で全て (0,0) を基準とした PNG左上のオフセット。"""
    if entrance == "none":
        return ("center", "center")
    if entrance == "slide_left":
        # 画面右端外から左へスライドイン
        def _f(t):
            if t >= entrance_dur:
                return (0, 0)
            p = _ease_out_cubic(t / entrance_dur)
            return (int(TARGET_W * (1 - p)), 0)
        return _f
    if entrance == "slide_right":
        def _f(t):
            if t >= entrance_dur:
                return (0, 0)
            p = _ease_out_cubic(t / entrance_dur)
            return (int(-TARGET_W * (1 - p)), 0)
        return _f
    if entrance == "slide_up":
        def _f(t):
            if t >= entrance_dur:
                return (0, 0)
            p = _ease_out_cubic(t / entrance_dur)
            return (0, int(TARGET_H * (1 - p) * 0.4))
        return _f
    if entrance == "slide_down":
        def _f(t):
            if t >= entrance_dur:
                return (0, 0)
            p = _ease_out_cubic(t / entrance_dur)
            return (0, int(-TARGET_H * (1 - p) * 0.4))
        return _f
    if entrance == "shake":
        # 短時間 0.18s シェイク
        import math
        def _f(t):
            if t >= 0.18:
                return (0, 0)
            amp = 30 * (1 - t / 0.18)
            return (int(amp * math.sin(t * 80)), 0)
        return _f
    return (0, 0)


def _hook_resize_lambda(entrance: str, entrance_dur: float):
    if entrance == "pop":
        # 0 → 0.18s で 0.4 → 1.10 → 1.0 のバウンド
        def _f(t):
            if t >= entrance_dur:
                return 1.0
            p = t / entrance_dur
            if p < 0.65:
                pp = p / 0.65
                return 0.4 + 0.7 * _ease_out_back(pp)
            else:
                pp = (p - 0.65) / 0.35
                return 1.10 - 0.10 * pp
        return _f
    return None


def build_hook_overlay(hook: Optional[dict], font_path: Optional[Path]) -> Optional[ImageClip]:
    if not hook:
        return None
    png = render_hook_png(hook, font_path)
    start = float(hook.get("start", 0.0))
    end = float(hook.get("end", 3.0))
    duration = max(0.5, end - start)
    entrance = hook.get("entrance", "slide_left")
    entrance_dur = float(hook.get("entrance_dur", 0.35))
    clip = (
        ImageClip(png, transparent=True)
        .set_start(start)
        .set_duration(duration)
    )
    pos = _hook_position_lambda(entrance, entrance_dur)
    clip = clip.set_position(pos)
    rsz = _hook_resize_lambda(entrance, entrance_dur)
    if rsz is not None:
        from moviepy.video.fx.all import resize as _resize
        clip = clip.fx(_resize, rsz)
    if entrance == "fade":
        try:
            clip = clip.crossfadein(min(0.4, duration / 2))
        except Exception:
            pass
    logger.info(f"hook overlay: '{hook.get('text')}' entrance={entrance}")
    return clip


# =====================================================================
#                       B-roll Overlays
# =====================================================================
def render_broll_png(
    style: str,
    text_overlay: Optional[str],
    font_path: Optional[Path],
    base_font_size: int,
) -> np.ndarray:
    img = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if style == "color_block":
        draw.rectangle((0, 0, TARGET_W, TARGET_H), fill=_hex_to_rgba("#1a1a2e", 230))
    elif style == "blur_bg":
        draw.rectangle((0, 0, TARGET_W, TARGET_H), fill=(0, 0, 0, 120))
    elif style == "split_screen":
        draw.rectangle((0, TARGET_H // 2, TARGET_W, TARGET_W // 2 + 8), fill=(255, 255, 255, 255))
    # text_overlay
    if text_overlay:
        size = max(60, int(base_font_size * 1.6))
        font = font_at(font_path, size)
        bbox = draw.textbbox((0, 0), text_overlay, font=font, stroke_width=8)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (TARGET_W - tw) // 2
        y = (TARGET_H - th) // 2
        draw.text(
            (x, y),
            text_overlay,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=10,
            stroke_fill=(0, 0, 0, 255),
        )
    return np.array(img)


# =====================================================================
#                  Outro CTA カード
# =====================================================================
def render_outro_png(outro: dict, font_path: Optional[Path]) -> np.ndarray:
    """末尾エンドカード: bg一面 + 中央に大きなテキスト + アイコン記号 + サブテキスト。"""
    img = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    bg = _hex_to_rgba(outro.get("bg_color", "#0a0a14"), alpha=235)
    text_color = _hex_to_rgba(outro.get("text_color", "#FFFFFF"))
    accent = _hex_to_rgba(outro.get("accent_color", "#FFFF00"))
    icon = outro.get("icon")
    text = outro.get("text", "チャンネル登録してね")
    subtext = outro.get("subtext")

    # 全画面 bg
    draw.rectangle((0, 0, TARGET_W, TARGET_H), fill=bg)

    # アイコン (絵文字風: 記号で代用)
    icon_map = {"bell": "🔔", "heart": "♥", "follow": "▶", "subscribe": "★"}
    icon_str = icon_map.get(icon or "", "")

    # テキスト中央配置（フィット調整あり）
    icon_size = 200
    sub_size = 60
    max_text_w = int(TARGET_W * 0.86)
    # メインテキストを max_text_w に収まる最大サイズで描画
    main_size = 130
    while main_size > 50:
        f = font_at(font_path, main_size)
        bb = draw.textbbox((0, 0), text, font=f, stroke_width=8)
        if bb[2] - bb[0] <= max_text_w:
            break
        main_size -= 6
    main_font = font_at(font_path, main_size)
    sub_font = font_at(font_path, sub_size) if subtext else None

    bbox = draw.textbbox((0, 0), text, font=main_font, stroke_width=8)
    main_w, main_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    sub_w, sub_h = (0, 0)
    if subtext and sub_font:
        # サブも収まるサイズに微調整
        while sub_size > 28:
            sf = font_at(font_path, sub_size)
            sb = draw.textbbox((0, 0), subtext, font=sf, stroke_width=4)
            if sb[2] - sb[0] <= max_text_w:
                sub_font = sf
                break
            sub_size -= 4
        sb = draw.textbbox((0, 0), subtext, font=sub_font, stroke_width=4)
        sub_w, sub_h = sb[2] - sb[0], sb[3] - sb[1]

    cx = TARGET_W // 2
    total_h = main_h + (sub_h + 30 if subtext else 0) + (icon_size + 20 if icon_str else 0)
    cy_top = (TARGET_H - total_h) // 2

    # アイコン描画 (大きな丸アクセント色)
    if icon_str:
        ic_font = font_at(font_path, icon_size)
        ib = draw.textbbox((0, 0), icon_str, font=ic_font, stroke_width=2)
        ic_w = ib[2] - ib[0]
        ic_x = cx - ic_w // 2
        # アクセント色の丸背景
        circle_r = icon_size // 2 + 30
        draw.ellipse(
            (cx - circle_r, cy_top - 10, cx + circle_r, cy_top + 2 * circle_r - 10),
            fill=accent,
        )
        draw.text(
            (ic_x, cy_top - 30),
            icon_str,
            font=ic_font,
            fill=(20, 20, 20, 255),
        )
        cy_top += 2 * circle_r + 20

    # メインテキスト
    tx = cx - main_w // 2
    draw.text(
        (tx, cy_top),
        text,
        font=main_font,
        fill=text_color,
        stroke_width=8,
        stroke_fill=(0, 0, 0, 255),
    )
    cy_top += main_h + 30

    # サブ
    if subtext and sub_font:
        stx = cx - sub_w // 2
        draw.text(
            (stx, cy_top),
            subtext,
            font=sub_font,
            fill=accent,
            stroke_width=4,
            stroke_fill=(0, 0, 0, 255),
        )

    return np.array(img)


def build_outro_overlay(
    outro: Optional[dict], font_path: Optional[Path], video_total_duration: float
) -> Optional[ImageClip]:
    """末尾 outro.duration 秒の間、エンドカードを表示。fade in 0.2s."""
    if not outro:
        return None
    duration = float(outro.get("duration", 1.5))
    duration = min(duration, max(0.3, video_total_duration - 0.1))
    png = render_outro_png(outro, font_path)
    start = max(0.0, video_total_duration - duration)
    clip = (
        ImageClip(png, transparent=True)
        .set_start(start)
        .set_duration(duration)
        .set_position((0, 0))
    )
    try:
        clip = clip.crossfadein(min(0.25, duration / 3))
    except Exception:
        pass
    logger.info(f"outro overlay: '{outro.get('text')}' @ {start:.2f}s ({duration:.2f}s)")
    return clip


def build_broll_overlays(
    broll_plan: List[dict],
    font_path: Optional[Path],
    base_font_size: int,
) -> List[ImageClip]:
    overlays = []
    for cue in broll_plan:
        s = float(cue["start"])
        e = float(cue["end"])
        if e <= s:
            continue
        png = render_broll_png(
            style=cue.get("style", "blur_bg"),
            text_overlay=cue.get("text_overlay"),
            font_path=font_path,
            base_font_size=base_font_size,
        )
        clip = (
            ImageClip(png, transparent=True)
            .set_start(s)
            .set_duration(e - s)
            .set_position((0, 0))
        )
        overlays.append(clip)
    if overlays:
        logger.info(f"broll overlay: {len(overlays)}件")
    return overlays


# =====================================================================
#                       SE/BGM ミックス
# =====================================================================
def _resolve_se_path(sfx: str) -> Optional[Path]:
    candidates = [
        SHORTS_SE_DIR / f"{sfx}.mp3",
        ASSETS_DIR / "se" / f"{sfx}.mp3",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _ducked_bgm_segments(
    bgm_clip,
    base_volume: float,
    duck_volume: float,
    duck_segments_edit: List[Tuple[float, float]],
    total_duration: float,
):
    """BGMを発話区間ごとに音量を分けた小クリップに分解して返す。
    fade_in/out 0.15s を区間境界に適用してダッキングを滑らかに。
    """
    if not duck_segments_edit:
        return [bgm_clip.set_duration(total_duration).volumex(base_volume)]
    pieces = []
    cursor = 0.0
    fade = 0.15
    for ds, de in duck_segments_edit:
        ds = max(0.0, min(total_duration, ds))
        de = max(0.0, min(total_duration, de))
        if de <= ds:
            continue
        if ds > cursor:
            high = bgm_clip.subclip(cursor, ds).volumex(base_volume).set_start(cursor)
            try:
                high = high.audio_fadein(min(fade, (ds - cursor) / 2)).audio_fadeout(
                    min(fade, (ds - cursor) / 2)
                )
            except Exception:
                pass
            pieces.append(high)
        low = bgm_clip.subclip(ds, de).volumex(duck_volume).set_start(ds)
        try:
            low = low.audio_fadein(min(fade, (de - ds) / 2)).audio_fadeout(
                min(fade, (de - ds) / 2)
            )
        except Exception:
            pass
        pieces.append(low)
        cursor = de
    if cursor < total_duration:
        high = bgm_clip.subclip(cursor, total_duration).volumex(base_volume).set_start(cursor)
        try:
            high = high.audio_fadein(min(fade, (total_duration - cursor) / 2))
        except Exception:
            pass
        pieces.append(high)
    return pieces


def build_audio_with_mix(
    base_audio,
    se_cues: List[dict],
    bgm_conf: Optional[dict],
    total_duration: float,
    duck_segments_edit: Optional[List[Tuple[float, float]]] = None,
):
    """元音声 + SE + BGM(ダッキング対応) を合成して返す。"""
    tracks = []
    if base_audio is not None:
        tracks.append(base_audio.volumex(1.0))

    # SE
    for cue in se_cues:
        path = _resolve_se_path(cue.get("sfx", ""))
        if not path:
            logger.warning(f"SE未発見: {cue.get('sfx')}")
            continue
        try:
            se = AudioFileClip(str(path))
            t = float(cue.get("time", 0.0))
            vol = float(cue.get("volume", 0.55))
            se = se.volumex(vol).set_start(max(0.0, t))
            if t + se.duration > total_duration:
                se = se.set_duration(max(0.05, total_duration - t))
            tracks.append(se)
        except Exception as e:
            logger.warning(f"SE合成失敗 {path}: {e}")

    # BGM (ducking 適用)
    if bgm_conf and bgm_conf.get("path"):
        bgm_path = Path(bgm_conf["path"])
        if not bgm_path.is_absolute():
            bgm_path = (BASE_DIR / bgm_path).resolve()
        if bgm_path.exists():
            try:
                bgm = AudioFileClip(str(bgm_path))
                if bgm.duration < total_duration:
                    n = int(total_duration / bgm.duration) + 1
                    bgm = concatenate_audioclips([bgm] * n)
                bgm = bgm.set_duration(total_duration)
                base_vol = float(bgm_conf.get("volume", 0.12))
                duck_vol = float(bgm_conf.get("duck_volume", base_vol * 0.4))
                if bgm_conf.get("duck_during_speech", True) and duck_segments_edit:
                    pieces = _ducked_bgm_segments(
                        bgm, base_vol, duck_vol, duck_segments_edit, total_duration
                    )
                    tracks.extend(pieces)
                    logger.info(
                        f"BGM ducking: {len(duck_segments_edit)} 区間を {duck_vol:.2f}, 他は {base_vol:.2f}"
                    )
                else:
                    tracks.append(bgm.volumex(base_vol))
            except Exception as e:
                logger.warning(f"BGM合成失敗: {e}")

    if len(tracks) <= 1:
        return tracks[0] if tracks else None
    return CompositeAudioClip(tracks)


def concatenate_audioclips(clips):
    """moviepy 1.0.3互換: concatenate_audioclips が無い場合の簡易実装。"""
    try:
        from moviepy.editor import concatenate_audioclips as _ca
        return _ca(clips)
    except Exception:
        # フォールバック: set_start で並べてCompositeAudioClipに
        out = []
        cum = 0.0
        for c in clips:
            out.append(c.set_start(cum))
            cum += c.duration
        return CompositeAudioClip(out)


# =====================================================================
#                            メイン
# =====================================================================
def run(input_plan: Path, output_path: Path, font_path: Optional[Path], font_size: int) -> Path:
    if not input_plan.exists():
        raise FileNotFoundError(f"EditPlan が無い: {input_plan}")
    with input_plan.open("r", encoding="utf-8") as f:
        plan = json.load(f)
    plan = upgrade_v1_to_v2(plan)

    source = Path(plan["source"])
    if not source.is_absolute():
        cand = (BASE_DIR / source).resolve()
        if cand.exists():
            source = cand

    clips_plan = plan.get("clips", [])
    subs_plan = plan.get("subtitles", [])
    se_cues = plan.get("se_cues", [])
    broll_cues = plan.get("broll_cues", [])
    hook = plan.get("hook")
    outro = plan.get("outro")
    bgm_conf = plan.get("bgm")
    duck_segments_orig = plan.get("bgm_duck_segments", []) or []
    template_conf = plan.get("template", {}) or {}
    base_font_size = int(template_conf.get("default_font_size", font_size))

    if not clips_plan:
        raise RuntimeError("clips が空")

    logger.info(
        f"v2.5レンダ開始 genre={plan.get('genre')} clips={len(clips_plan)} "
        f"subs={len(subs_plan)} se={len(se_cues)} broll={len(broll_cues)} "
        f"hook={'有' if hook else '無'} outro={'有' if outro else '無'} duck={len(duck_segments_orig)}"
    )

    src_clip = None
    try:
        src_clip, base = build_base_video(source, clips_plan)
        mapping = build_time_mapping(clips_plan)

        sub_overlays = build_subtitle_overlays(subs_plan, mapping, base_font_size, font_path)
        broll_overlays = build_broll_overlays(broll_cues, font_path, base_font_size)
        hook_overlay = build_hook_overlay(hook, font_path)
        outro_overlay = build_outro_overlay(outro, font_path, base.duration)

        # ダッキング区間を edit時刻 に変換
        duck_edit: List[Tuple[float, float]] = []
        for seg in duck_segments_orig:
            try:
                s_orig, e_orig = float(seg[0]), float(seg[1])
                ms = map_orig_to_edit(s_orig, mapping)
                me = map_orig_to_edit(e_orig, mapping)
                if ms is not None and me is not None and me > ms:
                    duck_edit.append((ms, me))
            except (TypeError, ValueError, IndexError):
                continue

        layers = [base]
        layers.extend(broll_overlays)
        layers.extend(sub_overlays)
        if hook_overlay:
            layers.append(hook_overlay)
        if outro_overlay:
            layers.append(outro_overlay)

        final = CompositeVideoClip(layers, size=(TARGET_W, TARGET_H))
        final = final.set_duration(base.duration)

        # 音声: 元音声 + SE + BGM(ダッキング)
        mixed_audio = build_audio_with_mix(
            base.audio, se_cues, bgm_conf, base.duration, duck_segments_edit=duck_edit
        )
        if mixed_audio is not None:
            final = final.set_audio(mixed_audio)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_audio = TEMP_DIR / "_tmp_audio.m4a"
        logger.info(f"エンコード → {output_path}")
        final.write_videofile(
            str(output_path),
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            audio_bitrate="192k",
            preset="medium",
            threads=max(2, (os.cpu_count() or 4) - 1),
            ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
            temp_audiofile=str(tmp_audio),
            remove_temp=True,
            logger=None,
        )
    finally:
        if src_clip is not None:
            try:
                src_clip.close()
            except Exception:
                pass

    logger.success(f"レンダ完了: {output_path}")
    return output_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="step3: EditPlan v2 → 縦型ショート動画")
    p.add_argument("--input", type=Path, default=TEMP_DIR / "edit_plan.json")
    p.add_argument("--output", type=Path, default=OUTPUT_DIR / "final.mp4")
    p.add_argument("--font", type=Path, default=None)
    p.add_argument("--font-size", type=int, default=DEFAULT_FONT_SIZE)
    return p.parse_args()


def main() -> int:
    load_dotenv(BASE_DIR / ".env")
    args = parse_args()
    try:
        run(args.input, args.output, args.font, args.font_size)
        return 0
    except Exception as e:
        logger.exception(f"step3 失敗: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
