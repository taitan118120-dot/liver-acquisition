#!/usr/bin/env python3
"""
caption_preview.py
==================
TikTok風テロップデザインの静止画プレビュー生成（動画生成前のデザイン確認用）。
video_layout.py の render_caption_image を置き換える試作版を単独で出力する。

各語に鮮やかな色ピル背景 + 強調語は黄色ピル + 大型フォント。
bottom-center配置でTikTok寄り。
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

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


# TikTok寄りパレット: 話者別のビビッドピル
SPEAKER_PILL = {
    "zunda":   (22, 163, 74, 255),    # 緑
    "metan":   (236, 72, 153, 255),   # ピンク
    "neutral": (15, 23, 42, 235),     # ダークスレート
}
EMPHASIS_PILL = (250, 204, 21, 255)        # 黄 (#facc15)
EMPHASIS_TEXT = (15, 23, 42, 255)          # 黒背景でコントラスト
DEFAULT_TEXT = (255, 255, 255, 255)
OUTLINE = (0, 0, 0, 255)


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


def _char_segment(text: str, spans: list[tuple[int, int]]) -> list[tuple[str, bool]]:
    """文字列を [(chunk, is_emphasis), ...] に分割（emphasisスパンで区切る）"""
    if not spans:
        return [(text, False)]
    spans = sorted(spans)
    out: list[tuple[str, bool]] = []
    i = 0
    for s, e in spans:
        if i < s:
            out.append((text[i:s], False))
        if s < e:
            out.append((text[s:e], True))
        i = e
    if i < len(text):
        out.append((text[i:], False))
    return [(c, h) for c, h in out if c]


def _wrap_chunks(chunks: list[tuple[str, bool]], font_plain, font_emph, max_width: int) -> list[list[tuple[str, bool]]]:
    """chunk列を行に折り返す。chunk境界を尊重しつつ、長すぎるchunkは文字単位で割る。"""
    lines: list[list[tuple[str, bool]]] = [[]]

    def line_width(line: list[tuple[str, bool]]) -> int:
        w = 0
        for text, emph in line:
            f = font_emph if emph else font_plain
            bb = f.getbbox(text)
            w += bb[2] - bb[0]
        return w

    def chunk_width(text: str, emph: bool) -> int:
        f = font_emph if emph else font_plain
        bb = f.getbbox(text)
        return bb[2] - bb[0]

    for text, emph in chunks:
        # そのまま追加で収まる？
        if line_width(lines[-1]) + chunk_width(text, emph) <= max_width:
            lines[-1].append((text, emph))
            continue
        # 収まらない → 文字単位で詰める
        buf = ""
        for ch in text:
            test = buf + ch
            if line_width(lines[-1]) + chunk_width(test, emph) > max_width:
                if buf:
                    lines[-1].append((buf, emph))
                lines.append([])
                buf = ch
            else:
                buf = test
        if buf:
            lines[-1].append((buf, emph))
    return lines


def render_caption_tiktok(
    text: str,
    emphasis: list[str] | None = None,
    speaker: str = "zunda",
    font_size: int = 92,
    y_ratio: float = 0.58,  # 中央やや下（TikTok定番）
) -> np.ndarray:
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_plain = _font(font_size)
    font_emph = _font(int(font_size * 1.15))

    spans = _emphasis_spans(text, emphasis or [])
    chunks = _char_segment(text, spans)

    max_w = WIDTH - 120
    lines = _wrap_chunks(chunks, font_plain, font_emph, max_w)

    line_h = int(font_size * 1.55)
    total_h = line_h * len(lines)
    y_top = int(HEIGHT * y_ratio) - total_h // 2

    pad_x, pad_y = 22, 10
    gap = 8
    pill_color = SPEAKER_PILL.get(speaker, SPEAKER_PILL["neutral"])
    line_bg_color = (15, 23, 42, 210)  # 共通ダーク行帯

    for li, line in enumerate(lines):
        # 行の合計幅
        segments = []
        for text_seg, emph in line:
            f = font_emph if emph else font_plain
            bb = f.getbbox(text_seg)
            w = bb[2] - bb[0]
            h = bb[3] - bb[1]
            segments.append({"text": text_seg, "emph": emph, "font": f, "w": w, "h": h, "bb": bb})
        total_w = sum(s["w"] for s in segments)
        x0 = (WIDTH - total_w) // 2
        y = y_top + li * line_h

        # ライン全体の背景帯（ダーク）- 1行につき1本、丸角
        band_x0 = x0 - 30
        band_y0 = y - 14
        band_x1 = x0 + total_w + 30
        band_y1 = y + max(s["h"] for s in segments) + 14 + 10
        draw.rounded_rectangle(
            [band_x0, band_y0, band_x1, band_y1],
            radius=28,
            fill=line_bg_color,
        )

        # 各セグメントを順に描画
        x = x0
        for s in segments:
            f = s["font"]
            t = s["text"]
            bb = s["bb"]
            # emphasis セグメントは別色ピルで上書き
            if s["emph"]:
                pill_x0 = x - 10
                pill_y0 = y - 6
                pill_x1 = x + s["w"] + 10
                pill_y1 = y + s["h"] + 10 + 6
                draw.rounded_rectangle(
                    [pill_x0, pill_y0, pill_x1, pill_y1],
                    radius=20,
                    fill=EMPHASIS_PILL,
                )
                text_color = EMPHASIS_TEXT
            else:
                text_color = DEFAULT_TEXT

            # 縁取り（軽め、ピル背景があるので）
            for dx in (-3, 0, 3):
                for dy in (-3, 0, 3):
                    if dx == 0 and dy == 0:
                        continue
                    draw.text((x + dx, y + dy), t, fill=OUTLINE, font=f)
            # 本体
            draw.text((x, y), t, fill=text_color, font=f)
            x += s["w"]

    return np.array(img)


def build_preview_composite(
    bg_rgba: tuple,
    text: str,
    emphasis: list[str] | None,
    speaker: str,
    label: str,
) -> Image.Image:
    """背景+テロップ合成した1080x1920のプレビュー画像"""
    bg = Image.new("RGB", (WIDTH, HEIGHT), bg_rgba[:3])
    # グラデっぽく下を暗く
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in range(HEIGHT):
        a = int(80 * y / HEIGHT)
        od.line([(0, y), (WIDTH, y)], fill=(0, 0, 0, a))
    bg.paste(overlay.convert("RGB"), mask=overlay.split()[3])

    cap = Image.fromarray(render_caption_tiktok(text, emphasis, speaker))
    result = bg.convert("RGBA")
    result = Image.alpha_composite(result, cap)

    # ラベル（上端にファイル判別用）
    d = ImageDraw.Draw(result)
    f = _font(36)
    d.rectangle([0, 0, WIDTH, 60], fill=(0, 0, 0, 200))
    d.text((30, 12), label, fill=(255, 255, 255, 255), font=f)
    return result.convert("RGB")


def main():
    out_dir = Path(__file__).resolve().parent / "outputs" / "caption_previews"
    out_dir.mkdir(parents=True, exist_ok=True)

    samples = [
        {
            "text": "1000人稼げる世界なのよ",
            "emphasis": ["1000人"],
            "speaker": "metan",
            "bg": (22, 15, 58, 255),
        },
        {
            "text": "めたん、始め方って実際どうなのだ？",
            "emphasis": ["始め方"],
            "speaker": "zunda",
            "bg": (12, 40, 80, 255),
        },
        {
            "text": "収益化まで 初日から可能 登録者1000人+再生4000",
            "emphasis": ["初日から可能", "1000人"],
            "speaker": "metan",
            "bg": (44, 16, 58, 255),
        },
        {
            "text": "他にもコツあるのだ？",
            "emphasis": [],
            "speaker": "zunda",
            "bg": (8, 30, 70, 255),
        },
    ]

    for i, s in enumerate(samples):
        img = build_preview_composite(
            bg_rgba=s["bg"],
            text=s["text"],
            emphasis=s["emphasis"],
            speaker=s["speaker"],
            label=f"preview{i+1}: {s['speaker']} / emph={s['emphasis']}",
        )
        out = out_dir / f"preview_{i+1}_{s['speaker']}.jpg"
        img.save(out, quality=88)
        print(f"saved: {out}")


if __name__ == "__main__":
    main()
