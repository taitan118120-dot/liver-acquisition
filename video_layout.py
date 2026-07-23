#!/usr/bin/env python3
"""
video_layout.py — tensyokuzunda 風レイアウト部品
=====================================================
video_generator.py から呼び出される描画ユーティリティ群。
- build_bg()            : bg_preset に応じたシンプル固定配色背景
- render_caption()      : 中央上の大型2〜3行キャプション + emphasis 強調
- render_speaker_layout(): 左右立ち絵（active/inactive で明度・サイズ差）
- render_speaker_badge(): 話者名ピルバッジ（緑/ピンク）
- build_end_card()      : 最終CTA用 脈打ち「チャンネル登録」カード
"""

from __future__ import annotations
import math
import os
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import ImageClip, CompositeVideoClip, vfx

# shared constants from video_generator
WIDTH = 1080
HEIGHT = 1920

# ─── パレット ────────────────────────────────
BG_PRESETS = {
    # (top_rgb, bottom_rgb, particle_on)
    "navy":          ((18, 24, 58),   (6, 10, 28),    True),
    "gradient_pink": ((255, 77, 128), (160, 24, 80),  True),
    "gradient_cool": ((30, 110, 180), (14, 40, 90),   True),
    "cta_pink":      ((255, 110, 150), (220, 40, 90), True),
    "sunset":        ((255, 170, 70), (215, 60, 70),  True),
}

# ─── tensyokuzunda 寄せモード ─────────────────
# 環境変数 VIDEO_STYLE=sunburst を立てると、背景を放射線+黄オレンジ、
# キャプションを白箱+黒文字+赤強調、第X位は巨大ヘッダーに再描画する。
TENSYOKU_STYLE = os.environ.get("VIDEO_STYLE", "").lower() == "sunburst"
_RANK_RE = re.compile(r"第(\d+)位")

SPEAKER_BADGE = {
    "zunda": {"label": "ずんだもん", "fill": (22, 163, 74)},   # 緑
    "metan": {"label": "四国めたん", "fill": (236, 72, 153)},  # ピンク
}

SPEAKER_SIDE_DEFAULT = {"zunda": "left", "metan": "right"}

# フォント解決（バンドル→ヒラギノ→Arial Unicode）
FONT_CANDIDATES = [
    Path(__file__).resolve().parent / "shorts" / "assets" / "fonts" / "NotoSansJP-Black.otf",
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


# ─── 背景 ────────────────────────────────────

def _draw_gradient(img: Image.Image, top_rgb, bot_rgb):
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        r = y / (HEIGHT - 1)
        c = (
            int(top_rgb[0] + (bot_rgb[0] - top_rgb[0]) * r),
            int(top_rgb[1] + (bot_rgb[1] - top_rgb[1]) * r),
            int(top_rgb[2] + (bot_rgb[2] - top_rgb[2]) * r),
        )
        draw.line([(0, y), (WIDTH, y)], fill=c)


def _sprinkle_particles(img: Image.Image, n: int = 18, seed: int = 0):
    """sparse な白い光粒を重ねる"""
    rng = np.random.default_rng(seed or 42)
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for _ in range(n):
        px = int(rng.integers(40, WIDTH - 40))
        py = int(rng.integers(40, HEIGHT - 40))
        pr = int(rng.integers(2, 7))
        a = int(rng.integers(30, 90))
        od.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(255, 255, 255, a))
    img.alpha_composite(overlay)


def _build_sunburst_image(seed: int = 0) -> np.ndarray:
    """@tensyokuzunda 寄せの黄色サンバースト背景"""
    cx = WIDTH // 2
    cy = int(HEIGHT * 0.35)
    center_color = (255, 231, 92)
    rim_color = (255, 120, 10)
    ray_a = (255, 195, 37)
    ray_b = (255, 150, 20)
    num_rays = 24

    pixels = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    yy, xx = np.ogrid[:HEIGHT, :WIDTH]
    dx = xx - cx
    dy = yy - cy
    dist = np.sqrt(dx * dx + dy * dy)
    r_max = math.hypot(max(cx, WIDTH - cx), max(cy, HEIGHT - cy))
    t = np.clip(dist / r_max, 0.0, 1.0)
    for i, (ca, cb) in enumerate(zip(center_color, rim_color)):
        pixels[..., i] = (ca * (1 - t) + cb * t).astype(np.uint8)
    img = Image.fromarray(pixels).convert("RGBA")

    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    angle_step = 360 / num_rays
    for i in range(num_rays):
        a0 = math.radians(i * angle_step)
        a1 = math.radians((i + 1) * angle_step)
        half = math.radians(angle_step / 2)
        color = ray_a if i % 2 == 0 else ray_b
        length = r_max * 1.4
        p1 = (cx, cy)
        p2 = (cx + length * math.cos(a0 + half * 0.1), cy + length * math.sin(a0 + half * 0.1))
        p3 = (cx + length * math.cos(a1 - half * 0.1), cy + length * math.sin(a1 - half * 0.1))
        draw.polygon([p1, p2, p3], fill=(*color, 200 if i % 2 == 0 else 120))
    img = Image.alpha_composite(img, overlay)

    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r, a in [(520, 60), (360, 90), (220, 130), (120, 170)]:
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 240, 140, a))
    glow = glow.filter(ImageFilter.GaussianBlur(30))
    img = Image.alpha_composite(img, glow)

    vignette = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    vd.rectangle([0, HEIGHT - 200, WIDTH, HEIGHT], fill=(0, 0, 0, 70))
    vd.rectangle([0, 0, WIDTH, 80], fill=(0, 0, 0, 60))
    img = Image.alpha_composite(img, vignette)
    return np.array(img.convert("RGB"))


def build_bg_image(bg_preset: str, seed: int = 0) -> np.ndarray:
    # TENSYOKU_STYLE 時は cta 系以外をサンバーストに差し替え
    if TENSYOKU_STYLE and bg_preset not in ("cta_pink",):
        return _build_sunburst_image(seed=seed)
    top, bot, particle = BG_PRESETS.get(bg_preset, BG_PRESETS["navy"])
    img = Image.new("RGB", (WIDTH, HEIGHT), top)
    _draw_gradient(img, top, bot)
    img = img.convert("RGBA")
    if particle:
        _sprinkle_particles(img, n=18, seed=seed)
    return np.array(img.convert("RGB"))


def build_bg(bg_preset: str, duration: float, seed: int = 0) -> ImageClip:
    return ImageClip(build_bg_image(bg_preset, seed=seed)).with_duration(duration)


# ─── キャプション（中央上・大型・強調色） ────

def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """日本語向け: 文字幅を個別計測して折り返す"""
    if not text:
        return [""]
    lines, buf = [], ""
    for ch in text:
        test = buf + ch
        w = font.getbbox(test)[2] - font.getbbox(test)[0]
        if w > max_width and buf:
            lines.append(buf)
            buf = ch
        else:
            buf = test
    if buf:
        lines.append(buf)
    # 強制最大3行
    if len(lines) > 3:
        lines = lines[:3]
        # 3行目の末尾に…を付ける
        last = lines[-1]
        while last and font.getbbox(last + "…")[2] > max_width:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


def _emphasis_spans(text: str, emphasis: list[str]) -> list[tuple[int, int]]:
    spans = []
    for e in emphasis or []:
        if not e:
            continue
        start = 0
        while True:
            idx = text.find(e, start)
            if idx < 0:
                break
            spans.append((idx, idx + len(e)))
            start = idx + len(e)
    return spans


def _char_in_spans(char_idx: int, spans: list[tuple[int, int]]) -> bool:
    return any(s <= char_idx < e for s, e in spans)


def _render_caption_tensyoku(
    text: str,
    emphasis: list[str] | None,
    font_size: int,
) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    """@tensyokuzunda 風: 白箱+黒文字+赤強調、第X位は上段巨大ヘッダーに分離。"""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 本文用テキストから「第X位」を剥がして上段ヘッダーに昇格
    rank_text: str | None = None
    keyword_text: str | None = None
    rank_m = _RANK_RE.search(text)
    body_text = text
    if rank_m:
        rank_text = rank_m.group(0)  # "第3位"
        # 最長の emphasis をキーワードとして採用（第X位以外）
        for e in sorted(emphasis or [], key=len, reverse=True):
            if e and e != rank_text:
                keyword_text = e
                break
        # 本文からランクとキーワードを除去
        body_text = text.replace(rank_text, "")
        if keyword_text:
            body_text = body_text.replace(keyword_text, "")
        # 残りの助詞・記号を整理
        body_text = body_text.strip(" 　は「」、。！？!?…,.")
        # 残った連続記号の圧縮
        body_text = re.sub(r"[「」、。　 ]{2,}", " ", body_text).strip()
        # 残骸が2文字以下なら非表示にする（「よ」「ね」等）
        if len(body_text) <= 2:
            body_text = ""

    # ── 上段: ランキング/キーワード巨大ヘッダー（白箱 + 黒/赤文字） ──
    def draw_header_box(t, y, font_size, text_color, stroke_color=(0, 0, 0), stroke_w=10):
        f = _font(font_size)
        bb = f.getbbox(t)
        tw = bb[2] - bb[0]
        th = bb[3] - bb[1]
        pad_x, pad_y = 70, 28
        bw = tw + pad_x * 2
        bh = th + pad_y * 2
        bx = (WIDTH - bw) // 2
        by = y
        # shadow
        shadow = Image.new("RGBA", (bw + 60, bh + 60), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle([0, 0, bw, bh], radius=bh // 3, fill=(0, 0, 0, 150))
        shadow = shadow.filter(ImageFilter.GaussianBlur(16))
        img.paste(shadow, (bx - 8, by + 14), shadow)
        # box
        draw.rounded_rectangle(
            [bx, by, bx + bw, by + bh],
            radius=bh // 3,
            fill=(255, 255, 255, 255),
            outline=stroke_color,
            width=stroke_w,
        )
        draw.text((bx + pad_x - bb[0], by + pad_y - bb[1]), t, fill=(*text_color, 255), font=f)
        return by + bh

    header_bottom = 120
    if rank_text:
        header_bottom = draw_header_box(rank_text, 140, 170, text_color=(20, 20, 20))
        header_bottom += 20
    if keyword_text:
        header_bottom = draw_header_box(keyword_text, header_bottom, 180, text_color=(220, 35, 35), stroke_w=12)

    # ── 下段: 本文の白角丸キャプション ──
    font = _font(font_size)
    char_boxes: list[tuple[int, int, int, int]] = []
    if body_text.strip():
        lines = _wrap(body_text, font, int(WIDTH * 0.84) - 120)
        line_h = int(font_size * 1.35)
        block_h = line_h * len(lines)
        box_pad_x, box_pad_y = 56, 30
        max_line_w = max((font.getbbox(l)[2] - font.getbbox(l)[0]) for l in lines) if lines else 0
        box_w = max_line_w + box_pad_x * 2
        box_h = block_h + box_pad_y * 2
        box_x = (WIDTH - box_w) // 2
        box_y = int(HEIGHT * 0.62) - box_h // 2

        # shadow
        shadow = Image.new("RGBA", (box_w + 60, box_h + 60), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle([0, 0, box_w, box_h], radius=36, fill=(0, 0, 0, 170))
        shadow = shadow.filter(ImageFilter.GaussianBlur(18))
        img.paste(shadow, (box_x - 8, box_y + 16), shadow)

        draw.rounded_rectangle(
            [box_x, box_y, box_x + box_w, box_y + box_h],
            radius=34,
            fill=(255, 255, 255, 248),
            outline=(0, 0, 0, 255),
            width=6,
        )

        # emphasis 文字インデックス集合（body_text ベース）
        spans_body = _emphasis_spans(body_text, [e for e in (emphasis or []) if e and e != rank_text])
        cursor_global = 0
        for li, line in enumerate(lines):
            lw = font.getbbox(line)[2] - font.getbbox(line)[0]
            x = box_x + (box_w - lw) // 2
            y = box_y + box_pad_y + li * line_h
            for ch in line:
                cb = font.getbbox(ch)
                cw = cb[2] - cb[0]
                is_emph = _char_in_spans(cursor_global, spans_body)
                color = (220, 35, 35) if is_emph else (20, 20, 20)
                if is_emph:
                    for dx in (-2, 0, 2):
                        for dy in (-2, 0, 2):
                            if dx or dy:
                                draw.text((x + dx, y + dy), ch, fill=(255, 255, 255, 255), font=font)
                draw.text((x, y), ch, fill=color, font=font)
                char_boxes.append((cursor_global, x, y, cw))
                x += cw
                cursor_global += 1

    return np.array(img), char_boxes


def render_caption_image(
    text: str,
    emphasis: list[str] | None,
    font_size: int = 84,
    y_ratio: float = 0.14,
    fill_white: tuple = (255, 255, 255, 255),
    fill_emphasis: tuple = (255, 235, 59, 255),  # 黄
    outline: tuple = (0, 0, 0, 255),
    outline_px: int = 12,
) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    """大型センタートップキャプション。
    戻り値: (画像, 各文字のbbox [(ch_idx, x, y, w)]) — カラオケ層が再利用する。
    """
    if TENSYOKU_STYLE:
        return _render_caption_tensyoku(text, emphasis, font_size)
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _font(font_size)
    font_big = _font(int(font_size * 1.15))

    lines = _wrap(text, font, WIDTH - 120)
    spans = _emphasis_spans(text, emphasis or [])

    line_h = int(font_size * 1.35)
    y_start = int(HEIGHT * y_ratio)

    # 半透明の背景帯（視認性確保）
    band_top = y_start - 30
    band_bot = y_start + line_h * len(lines) + 30
    draw.rounded_rectangle(
        [40, band_top, WIDTH - 40, band_bot],
        radius=24,
        fill=(0, 0, 0, 90),
    )

    char_boxes: list[tuple[int, int, int, int]] = []
    # lines を横断する元テキストのインデックス
    ch_global = 0

    for li, line in enumerate(lines):
        # 行幅（文字ごとにフォントサイズが違うので個別加算）
        widths = []
        for ch in line:
            # この文字が emphasis ? 大きいフォント
            use_big = _char_in_spans(ch_global + widths.__len__(), spans)
            f = font_big if use_big else font
            bb = f.getbbox(ch)
            widths.append((ch, f, bb[2] - bb[0], use_big))
        total_w = sum(w for _, _, w, _ in widths)
        x = (WIDTH - total_w) // 2
        y = y_start + li * line_h

        for ch, f, w, use_big in widths:
            # 縁取り
            for ox in range(-outline_px, outline_px + 1, 2):
                for oy in range(-outline_px, outline_px + 1, 2):
                    if ox * ox + oy * oy <= outline_px * outline_px:
                        draw.text((x + ox, y + oy), ch, fill=outline, font=f)
            # 本体
            fill = fill_emphasis if use_big else fill_white
            draw.text((x, y), ch, fill=fill, font=f)
            char_boxes.append((ch_global, x, y, w))
            x += w
            ch_global += 1
        # 改行ぶんのインデックスは進めない（wrap は元テキストの連続部分なので）

    return np.array(img), char_boxes


def render_caption(text, emphasis, duration, font_size=84, y_ratio=0.14):
    arr, _ = render_caption_image(text, emphasis, font_size=font_size, y_ratio=y_ratio)
    return ImageClip(arr, transparent=True).with_duration(duration)


# ─── 話者名バッジ ─────────────────────────────

def render_speaker_badge_image(speaker: str) -> np.ndarray:
    cfg = SPEAKER_BADGE.get(speaker, SPEAKER_BADGE["zunda"])
    label = cfg["label"]
    fill = cfg["fill"]

    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _font(46)
    bb = font.getbbox(label)
    tw = bb[2] - bb[0]
    th = bb[3] - bb[1]
    pad_x, pad_y = 28, 12

    # 位置: 画面中央（後段で x_offset を with_position で上書き）
    x = (WIDTH - (tw + pad_x * 2)) // 2
    y = int(HEIGHT * 0.08)  # 下層で再配置するので控えめ
    draw.rounded_rectangle(
        [x, y, x + tw + pad_x * 2, y + th + pad_y * 2],
        radius=(th + pad_y * 2) // 2,
        fill=(*fill, 255),
    )
    draw.text((x + pad_x, y + pad_y - bb[1]), label, fill=(255, 255, 255, 255), font=font)
    return np.array(img)


def render_speaker_badge(speaker: str, duration: float, x_center: int, y: int) -> ImageClip:
    arr = render_speaker_badge_image(speaker)
    clip = ImageClip(arr, transparent=True).with_duration(duration)
    # 全画面座標系での badge 画像なので、そのまま (0,0) に置いて可。
    return clip.with_position((0, 0))


# ─── L/R 立ち絵 ────────────────────────────────

def build_speaker_clips(
    active_speaker: str,
    duration: float,
    assets_dir: Path,
    pulse: bool = True,
) -> list:
    """左右の立ち絵を返す。zunda=左、metan=右。アクティブ側はフル・非アクティブは暗く小さい。"""
    clips = []
    for spk in ("zunda", "metan"):
        # 資産名は従来通り zundamon.png / metan.png
        fname_pattern = "zundamon*.png" if spk == "zunda" else "metan*.png"
        files = list(assets_dir.glob(fname_pattern))
        if not files:
            continue

        is_active = (spk == active_speaker)
        try:
            base = ImageClip(str(files[0]), transparent=True).with_duration(duration)
        except Exception:
            continue

        target_h = 820 if is_active else 700
        scale = target_h / base.h
        target_w = int(base.w * scale)
        clip = base.resized((target_w, target_h))

        # 位置
        margin = 30
        if SPEAKER_SIDE_DEFAULT[spk] == "left":
            x_pos = margin
        else:
            x_pos = WIDTH - target_w - margin
        y_pos = HEIGHT - target_h - 60

        if not is_active:
            clip = clip.with_effects([vfx.MultiplyColor(0.55)])
            clip = clip.with_position((x_pos, y_pos + 20))
        else:
            if pulse:
                # 冒頭 0.3s だけ 1.0→1.05→1.0 のパルス + 全体軽く縦揺れ
                def make_scale(dur):
                    def f(t):
                        if t < 0.15:
                            return 1.0 + (t / 0.15) * 0.05
                        if t < 0.30:
                            return 1.05 - ((t - 0.15) / 0.15) * 0.05
                        return 1.0
                    return f

                try:
                    clip = clip.with_effects([vfx.Resize(make_scale(duration))])
                except Exception:
                    pass
                # 縦揺れ
                _base_y = y_pos
                clip = clip.with_position(lambda t, x=x_pos, y=_base_y: (x, y + int(math.sin(t * math.pi * 1.2) * 5)))
            else:
                clip = clip.with_position((x_pos, y_pos))

        # badge を active 側だけ重ねる
        if is_active:
            badge_arr = render_speaker_badge_image(spk)
            badge_clip = ImageClip(badge_arr, transparent=True).with_duration(duration)
            # 立ち絵の頭上に寄せる: badge 画像は中央配置なので、x 方向にオフセット
            bx = (x_pos + target_w // 2) - WIDTH // 2  # 立ち絵中央との差分
            # badge 画像内での badge 描画位置は y = 0.08*H。立ち絵の頭上 (y_pos-20) に合わせて平行移動
            by = (y_pos - 110) - int(HEIGHT * 0.08)
            badge_clip = badge_clip.with_position((bx, by))
            clips.append(clip)
            clips.append(badge_clip)
        else:
            clips.append(clip)
    return clips


# ─── エンドカード（脈打つCTA） ──────────────

def build_end_card(text: str, duration: float) -> CompositeVideoClip:
    """最終CTA: 中央にピンク丸 + テキスト、軽く脈打つ。"""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 中央下にピル形状の購読風ボタン
    cx, cy = WIDTH // 2, int(HEIGHT * 0.72)
    bw, bh = 760, 180
    draw.rounded_rectangle(
        [cx - bw // 2, cy - bh // 2, cx + bw // 2, cy + bh // 2],
        radius=bh // 2,
        fill=(255, 45, 85, 255),
    )
    font = _font(72)
    label = "チャンネル登録してね！"
    bb = font.getbbox(label)
    tw = bb[2] - bb[0]
    th = bb[3] - bb[1]
    draw.text((cx - tw // 2, cy - th // 2 - 4), label, fill=(255, 255, 255, 255), font=font)

    # 小さい🔔アイコン風（黄色丸）
    draw.ellipse([cx + bw // 2 - 40, cy - 28, cx + bw // 2 + 16, cy + 28], fill=(255, 214, 10, 255))

    arr = np.array(img)
    clip = ImageClip(arr, transparent=True).with_duration(duration)

    # 脈打ち
    def scale_at(t):
        return 1.0 + 0.06 * abs(math.sin(t * math.pi * 1.5))

    try:
        clip = clip.with_effects([vfx.Resize(scale_at)])
    except Exception:
        pass
    return clip


# ─── 常時プログレスバー ────────────────────

def build_progress_bar(total_duration: float, steps: int = 40) -> list:
    """画面最下部 4px のプログレスバーを ImageClip 列として返す。"""
    step_dur = total_duration / steps
    out = []
    bar_h = 4
    for i in range(steps):
        ratio = (i + 1) / steps
        img = Image.new("RGBA", (WIDTH, bar_h + 4), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, WIDTH, bar_h], fill=(255, 255, 255, 60))
        d.rectangle([0, 0, int(WIDTH * ratio), bar_h], fill=(255, 235, 59, 230))
        clip = (
            ImageClip(np.array(img), transparent=True)
            .with_duration(step_dur)
            .with_start(i * step_dur)
            .with_position((0, HEIGHT - bar_h - 2))
        )
        out.append(clip)
    return out
