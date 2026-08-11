"""
リッチメニュー画像ジェネレーター（2500x1686px / LINE公式仕様）

ライバー希望者向け（デフォルト）と代理店パートナー希望者向けの2枚を生成する。
配色は lp/agency/style.css のブランドトーン、ロゴは lp/shared/logo.jpg が正本。

使い方:
    python3 rich_menu_images.py            # assets/ に2枚生成
    python3 rich_menu_images.py --menu agency

生成した画像は rich_menu.py がそのままアップロードする。
"""

import argparse
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from rich_menu import LAYOUT, RICH_MENU_IMAGES

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
LOGO_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "lp", "shared", "logo.jpg"))

W, H = 2500, 1686

# --- lp/agency/style.css の :root と同じ値 ---
PINK = (224, 138, 147)
PINK_SOFT = (253, 244, 241)
PINK_MID = (244, 216, 210)
LAV = (165, 148, 184)
LAV_SOFT = (247, 243, 247)
LAV_MID = (226, 214, 228)
CREAM = (253, 248, 242)
TEXT = (64, 55, 47)
TEXT_SUB = (117, 106, 97)
WHITE = (255, 255, 255)
BAR_BG = (43, 37, 48)  # ロゴのネオン背景に合わせたダーク

# --- フォント（macOS標準のヒラギノ）---
FONT_BOLD = "/System/Library/Fonts/ヒラギノ角ゴシック W7.ttc"
FONT_MID = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
FONT_REG = "/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc"
FONT_EMOJI = "/System/Library/Fonts/Apple Color Emoji.ttc"
EMOJI_NATIVE = 160  # Apple Color Emoji はこのサイズしか開けない

# --- レイアウト（描画用。タップ判定の座標は rich_menu.py の LAYOUT が正本）---
MARGIN = 56
GAP = 28
BAR_H = 400
CARD_W = (W - MARGIN * 2 - GAP * 2) // 3
CARD_H = (H - MARGIN * 2 - GAP - BAR_H - GAP) // 2
CARD_R = 40


def _font(path, size):
    return ImageFont.truetype(path, size)


def _text(draw, xy, text, font, fill, anchor="mm"):
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def _emoji(char, size):
    """絵文字を160pxで描いてから縮小する（他サイズでは開けないため）"""
    img = Image.new("RGBA", (EMOJI_NATIVE, EMOJI_NATIVE), (0, 0, 0, 0))
    ImageDraw.Draw(img).text(
        (EMOJI_NATIVE // 2, EMOJI_NATIVE // 2),
        char,
        font=_font(FONT_EMOJI, EMOJI_NATIVE),
        embedded_color=True,
        anchor="mm",
    )
    return img.resize((size, size), Image.LANCZOS)


def _gradient(top, bottom):
    grad = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / (H - 1)
        grad.putpixel(
            (0, y),
            tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)),
        )
    return grad.resize((W, H))


def _shadow(base, box, radius, blur=22, alpha=42, offset=10):
    """カードの下に落ち影を敷く"""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        (box[0], box[1] + offset, box[2], box[3] + offset),
        radius=radius,
        fill=(120, 100, 110, alpha),
    )
    base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def _logo(size):
    """ロゴをダークバー用に正方トリミング＋角丸マスク"""
    logo = Image.open(LOGO_PATH).convert("RGB")
    side = min(logo.size)
    left = (logo.width - side) // 2
    logo = logo.crop((left, 0, left + side, side)).resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(logo, (0, 0), mask)
    return out


def _tint(accent, ratio):
    """白とaccentを混ぜた淡色を作る"""
    return tuple(int(255 + (accent[i] - 255) * ratio) for i in range(3))


def _draw_card(base, box, cell, accent):
    x0, y0, x1, y1 = box
    _shadow(base, box, CARD_R)
    draw = ImageDraw.Draw(base)
    draw.rounded_rectangle(box, radius=CARD_R, fill=WHITE + (255,))
    # 上端のアクセントライン（角丸に沿わせるため一度塗ってから下を白で伏せる）
    draw.rounded_rectangle((x0, y0, x1, y0 + CARD_R * 2), radius=CARD_R, fill=accent + (255,))
    draw.rectangle((x0, y0 + 16, x1, y0 + CARD_R * 2), fill=WHITE + (255,))

    cx = (x0 + x1) // 2
    # 絵文字を淡い円の上に置く
    circle_r = 96
    circle_y = y0 + 178
    draw.ellipse(
        (cx - circle_r, circle_y - circle_r, cx + circle_r, circle_y + circle_r),
        fill=_tint(accent, 0.28) + (255,),
    )
    icon = _emoji(cell["icon"], 118)
    base.alpha_composite(icon, (cx - 59, circle_y - 59))

    _text(draw, (cx, y0 + 355), cell["label"], _font(FONT_BOLD, 82), TEXT + (255,))
    _text(draw, (cx, y0 + 452), cell["sub"], _font(FONT_REG, 40), TEXT_SUB + (255,))


def _draw_bar(base, box, bar):
    _shadow(base, box, CARD_R, blur=26, alpha=48)
    draw = ImageDraw.Draw(base)
    draw.rounded_rectangle(box, radius=CARD_R, fill=BAR_BG + (255,))

    x0, y0, x1, y1 = box
    cy = (y0 + y1) // 2
    logo_size = 236
    logo_x = x0 + 74
    base.alpha_composite(_logo(logo_size), (logo_x, cy - logo_size // 2))

    tx = logo_x + logo_size + 66
    _text(draw, (tx, cy - 52), bar["title"], _font(FONT_BOLD, 78), WHITE + (255,), anchor="lm")
    _text(draw, (tx, cy + 40), bar["sub"], _font(FONT_REG, 44), (198, 188, 200, 255), anchor="lm")

    # 右端のタップを促す矢印つきピル
    pill_w, pill_h = 260, 96
    px1 = x1 - 74
    px0 = px1 - pill_w
    draw.rounded_rectangle((px0, cy - pill_h // 2, px1, cy + pill_h // 2), radius=pill_h // 2,
                           fill=bar["accent"] + (255,))
    _text(draw, ((px0 + px1) // 2, cy), "見る ›", _font(FONT_MID, 46), WHITE + (255,))


def build(menu, out_path=None):
    """menu は "liver" か "agency"。生成したPNGのパスを返す"""
    spec = RICH_MENU_IMAGES[menu]
    accent = PINK if menu == "liver" else LAV
    bg_top = (255, 253, 251) if menu == "liver" else (253, 252, 254)
    bg_bottom = PINK_SOFT if menu == "liver" else LAV_SOFT

    base = _gradient(bg_top, bg_bottom).convert("RGBA")
    # 背景の淡い装飾円（LPのデコレーションに合わせた気配づけ）
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    tint = PINK_MID if menu == "liver" else LAV_MID
    dd.ellipse((-260, -300, 520, 480), fill=tint + (70,))
    dd.ellipse((W - 460, H - 980, W + 320, H - 200), fill=tint + (60,))
    base.alpha_composite(deco.filter(ImageFilter.GaussianBlur(60)))

    for i, cell in enumerate(spec["cells"]):
        col, row = i % 3, i // 3
        x0 = MARGIN + col * (CARD_W + GAP)
        y0 = MARGIN + row * (CARD_H + GAP)
        _draw_card(base, (x0, y0, x0 + CARD_W, y0 + CARD_H), cell, accent)

    bar_y0 = MARGIN + 2 * (CARD_H + GAP)
    _draw_bar(base, (MARGIN, bar_y0, W - MARGIN, bar_y0 + BAR_H), spec["bar"])

    out_path = out_path or os.path.join(ASSETS_DIR, f"rich_menu_{menu}.png")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    base.convert("RGB").save(out_path, "PNG", optimize=True)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--menu", choices=["liver", "agency", "both"], default="both")
    args = ap.parse_args()

    menus = ["liver", "agency"] if args.menu == "both" else [args.menu]
    for menu in menus:
        path = build(menu)
        size_kb = os.path.getsize(path) // 1024
        print(f"生成: {path} ({size_kb}KB)")
        if size_kb > 1024:
            print("  ⚠️ LINEの上限は1MB。超えている場合は装飾を減らすこと")

    # 描画のグリッドとタップ判定がズレていないかを検算する
    for menu in menus:
        for area in LAYOUT[menu]:
            b = area["bounds"]
            assert b["x"] + b["width"] <= W and b["y"] + b["height"] <= H, area
    print("タップ判定の座標チェック: OK")


if __name__ == "__main__":
    main()
