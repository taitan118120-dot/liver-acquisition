#!/usr/bin/env python3
"""note_cover_make.py
Note記事のアイキャッチ（サムネイル）を「一目で内容が分かる」形で作る。

方針（2026-08-18 決定）:
  絵だけのイラストカバーはタイムライン上で何の記事か分からず素通りされる。
  これからのカバーは必ず
    実写風の写真背景（人物なし・物と部屋だけ）＋ 大きな見出しテキスト
    ＋ 黄色ハイライト ＋ TAITAN PROバッジ
  の合成にする。文字だけのカード（背景が単色/グラデ）は従来どおり禁止。
  人物写真は「顔が怖い」というユーザー判断で不採用（AI生成の顔は不気味の谷に落ちる）。

背景画像:
  Pollinations.ai（無料・Google APIの予算を使わない）で1本ずつ生成し
  blog/images/bg/{番号}.jpg にキャッシュする。once生成したら使い回す。

見出しテキスト:
  data/note_cover_text.json に記事番号ごとの指定があればそれを使い、
  無ければ記事タイトルから自動で組む（kicker＝プラットフォーム名／本文2〜3行）。

使い方:
  python3 note_cover_make.py 137 138 139     # 指定記事のカバーを作り直す
  python3 note_cover_make.py --missing       # blog/images に未生成の記事だけ
  python3 note_cover_make.py 137 --no-bg     # 背景を作り直さずキャッシュだけ使う
  python3 note_cover_make.py 137 --bg-seed 5 # 背景の絵を引き直す

出力: blog/images/{番号}_{slug}.png（既存ファイル名を維持して上書き）
"""
import argparse
import glob
import json
import os
import re
import time
import urllib.parse
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTICLES_DIR = os.path.join(BASE_DIR, "blog", "articles_note")
IMAGES_DIR = os.path.join(BASE_DIR, "blog", "images")
BG_DIR = os.path.join(IMAGES_DIR, "bg")
TEXT_MAP = os.path.join(BASE_DIR, "data", "note_cover_text.json")
LOGO_PATH = os.path.join(BASE_DIR, "lp", "shared", "logo.jpg")

W, H = 1280, 670  # noteの推奨サイズ

# ── 配色 ──────────────────────────────────────────────
INK = (10, 14, 28)          # 左側パネルの下地
WHITE = (255, 255, 255)
MARK = (255, 226, 77)       # ハイライト（黄）
SUB = (214, 222, 240)       # バッジの補足文字
ACCENTS = {                 # kicker チップの色（プラットフォーム別）
    "Pococha": (255, 92, 138),
    "TikTok LIVE": (0, 224, 196),
    "17LIVE": (255, 140, 60),
    "_default": (79, 195, 247),
}

FONT_CANDIDATES = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W7.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]

# 背景生成の共通スタイル
# 2026-08-18: 人物ありで作ったところ「顔写真は怖い」とNG。
# 以降サムネイルの背景に**人物は入れない**（顔・手・人影すべて）。物と部屋だけで撮る。
BG_STYLE = (
    "photorealistic interior still life photography, no people, nobody in frame, "
    "objects and room only, soft natural light, calm and clean, "
    "the subject fills the frame and is clearly recognizable, "
    "shallow depth of field, high resolution, "
    "NO text, NO letters, NO words, NO logos, NO watermark, "
    "NO person, NO face, NO hands, NO human, "
    "NOT illustration, NOT anime, NOT 3D render"
)

# 記事テーマ→背景プロンプトの手がかり（タイトルに含まれる語で拾う）
BG_HINTS = [
    ("新人期間", "a smartphone on a small tripod on a wooden desk, an open notebook with a pen and a paper calendar beside it, a mug of coffee, morning sunlight through the window"),
    ("しんどい", "a quiet living room in the evening, a warm mug on a low table, a folded blanket on the sofa, a small lamp glowing softly"),
    ("顔出しなし", "a desk microphone and headphones on a wooden desk, a smartphone beside them, warm desk lamp light, dark cozy room at night"),
    ("主婦", "a bright kitchen counter with a smartphone on a stand, a mug and a small plant, laundry basket in the soft background, daytime sunlight"),
    ("TikTok", "a smartphone on a tripod facing a ring light on a modern desk, cool blue light, clean simple room"),
    ("代理店", "a laptop, a notebook and a cup of coffee on a bright office desk, documents neatly stacked, morning light"),
    ("確定申告", "a calculator, receipts and tax documents on a desk with a laptop, tidy and organized, daylight"),
    ("_default", "a smartphone on a tripod on a wooden desk in a cozy japanese room, a ring light and a mug beside it, warm natural light"),
]



# ── 記事情報 ───────────────────────────────────────────
def article_path(num):
    hits = glob.glob(os.path.join(ARTICLES_DIR, f"{num:02d}_*.md"))
    return hits[0] if hits else None


def article_title(num):
    path = article_path(num)
    if not path:
        return ""
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("# "):
                return line[2:].strip()
    return ""


def output_path(num):
    """既存のカバーがあればそのファイル名を維持し、無ければ記事名から作る。"""
    hits = glob.glob(os.path.join(IMAGES_DIR, f"{num:02d}_*.png"))
    if hits:
        return hits[0]
    path = article_path(num)
    slug = os.path.basename(path)[:-3] if path else f"{num:02d}_cover"
    return os.path.join(IMAGES_DIR, f"{slug}.png")


# ── 見出しテキストの決定 ────────────────────────────────
def load_text_map():
    if os.path.exists(TEXT_MAP):
        with open(TEXT_MAP, encoding="utf-8") as f:
            return json.load(f)
    return {}


def guess_kicker(title):
    for name in ("Pococha", "TikTok LIVE", "TikTok", "17LIVE"):
        if name in title:
            return "TikTok LIVE" if name == "TikTok" else name
    return "ライブ配信"


def auto_lines(title, max_chars=11, max_lines=3):
    """タイトルから見出し2〜3行を組む。句読点・記号で折る。"""
    head = title.split("｜")[0]
    head = re.sub(r"【[^】]*】", "", head).strip()
    head = head.replace("、", "、\n").replace("？", "？\n").replace("！", "！\n")
    chunks = [c for c in (s.strip() for s in head.split("\n")) if c]

    lines, cur = [], ""
    for c in chunks:
        while len(c) > max_chars:  # 長いかたまりは機械的に折る
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(c[:max_chars])
            c = c[max_chars:]
        if len(cur) + len(c) <= max_chars:
            cur += c
        else:
            if cur:
                lines.append(cur)
            cur = c
    if cur:
        lines.append(cur)
    return lines[:max_lines]


def resolve_text(num):
    """(kicker, lines, highlight_index) を返す。"""
    title = article_title(num)
    spec = load_text_map().get(str(num))
    if spec:
        lines = spec["lines"]
        kicker = spec.get("kicker") or guess_kicker(title)
        hi = spec.get("highlight", len(lines) - 1)
    else:
        lines = auto_lines(title)
        kicker = guess_kicker(title)
        hi = len(lines) - 1
    return kicker, lines, hi


# ── 背景 ──────────────────────────────────────────────
def bg_prompt(num):
    title = article_title(num)
    for key, prompt in BG_HINTS:
        if key != "_default" and key in title:
            return prompt
    return dict(BG_HINTS)["_default"]


def fetch_bg(num, seed, retries=5):
    prompt = f"{bg_prompt(num)}, {BG_STYLE}"
    url = (
        "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt) +
        f"?width=1280&height=704&model=flux&nologo=true&seed={seed}"
    )
    wait = 20
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=300)
            if r.status_code in (429, 500, 502, 503, 504, 524):
                print(f"    ⏳ HTTP {r.status_code} → {wait}秒待機 ({attempt}/{retries})")
                time.sleep(wait)
                wait = min(int(wait * 1.8), 180)
                continue
            r.raise_for_status()
            return Image.open(BytesIO(r.content)).convert("RGB")
        except requests.RequestException as e:
            print(f"    ⏳ 通信エラー({str(e)[:40]}) → {wait}秒待機 ({attempt}/{retries})")
            time.sleep(wait)
            wait = min(int(wait * 1.8), 180)
    raise RuntimeError("背景画像を取得できませんでした")


def ensure_bg(num, regenerate=False, seed=None):
    os.makedirs(BG_DIR, exist_ok=True)
    path = os.path.join(BG_DIR, f"{num:02d}.jpg")
    if os.path.exists(path) and not regenerate:
        return Image.open(path).convert("RGB")
    img = fetch_bg(num, seed if seed is not None else 1000 + num)
    img.save(path, "JPEG", quality=88, optimize=True)
    return img


# ── 合成 ──────────────────────────────────────────────
def font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size, index=0)
            except Exception:
                continue
    return ImageFont.load_default()


def cover_crop(img, w, h):
    src_ratio, dst_ratio = img.width / img.height, w / h
    if src_ratio > dst_ratio:
        new_w = int(img.height * dst_ratio)
        img = img.crop(((img.width - new_w) // 2, 0, (img.width + new_w) // 2, img.height))
    else:
        new_h = int(img.width / dst_ratio)
        img = img.crop((0, (img.height - new_h) // 2, img.width, (img.height + new_h) // 2))
    return img.resize((w, h), Image.LANCZOS)


def detect_face(img):
    """最大の顔の中心x(0..1)を返す。検出できなければ None。

    生成画像は人物が中央に来ることが多く、そのままだと見出しが顔に被る。
    顔位置を測って右側に寄せるために使う（OpenCVが無い環境では中央扱い）。
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
    if len(faces) == 0:
        return None
    x, y, w_, h_ = max(faces, key=lambda f: f[2] * f[3])
    return (x + w_ / 2) / img.width


def subject_x(img):
    """人物なし写真で「主役の物」が横方向のどこにあるかを 0..1 で返す。

    小さくしたグレースケールのエッジ量を列ごとに合計し、その重心を取る。
    ランプや机の上の小物のように「情報が集中している場所」が主役になる。
    """
    from PIL import ImageFilter
    small = img.convert("L").resize((160, 90), Image.LANCZOS).filter(ImageFilter.FIND_EDGES)
    cols = [0] * 160
    px = small.load()
    for x in range(160):
        cols[x] = sum(px[x, y] for y in range(90))
    total = sum(cols)
    if total == 0:
        return 0.5
    return sum(x * v for x, v in enumerate(cols)) / total / 160


def focus_crop(img, w, h, target=0.74, zoom=1.06):
    """主役が右側 target の位置に来るように（必要なら左右反転して）切り出す。

    見出しは左半分に置くので、主役が左にあるとテキストの下敷きになって
    「机しか写っていないサムネ」になる。静物写真は左右反転しても違和感が無いので、
    主役が左寄りなら反転させてから右に寄せる。
    """
    focus = detect_face(img)
    if focus is None:
        focus = subject_x(img)
        if focus < 0.5:  # 主役が左 → 反転して右へ持ってくる
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
            focus = 1.0 - focus

    scale = max(w / img.width, h / img.height) * zoom
    sw, sh = int(img.width * scale), int(img.height * scale)
    big = img.resize((sw, sh), Image.LANCZOS)

    left = max(0, min(sw - w, int(focus * sw - target * w)))
    top = max(0, min(sh - h, int(sh * 0.10)))  # 顔が切れないよう気持ち上寄せ
    return big.crop((left, top, left + w, top + h))


def text_w(draw, s, f):
    return draw.textbbox((0, 0), s, font=f)[2]


def fit_size(lines, max_w, start=84, floor=46):
    """全行が max_w に収まる最大の文字サイズを返す。"""
    probe = Image.new("RGB", (10, 10))
    d = ImageDraw.Draw(probe)
    size = start
    while size > floor:
        f = font(size)
        if all(text_w(d, ln, f) <= max_w for ln in lines):
            return size
        size -= 2
    return floor


def build(num, regenerate_bg=False, seed=None):
    kicker, lines, hi = resolve_text(num)
    bg = focus_crop(ensure_bg(num, regenerate_bg, seed), W, H)
    bg = ImageEnhance.Brightness(bg).enhance(0.9)

    canvas = bg.convert("RGBA")

    # 左half を暗く落として文字を読ませる（右の人物は残す）
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for x in range(W):
        t = min(max((x - 40) / (W * 0.72), 0.0), 1.0)
        sd.line([(x, 0), (x, H)], fill=INK + (int(238 * (1 - t) ** 1.35),))
    # 下端も少し締める（バッジの可読性）
    for y in range(H - 150, H):
        t = (y - (H - 150)) / 150
        sd.line([(0, y), (W, y)], fill=INK + (int(120 * t),))
    canvas = Image.alpha_composite(canvas, shade)
    draw = ImageDraw.Draw(canvas)

    margin = 64
    max_w = 720

    # kicker チップ
    kf = font(30)
    kw = text_w(draw, kicker, kf)
    chip = (margin, 60, margin + kw + 44, 60 + 54)
    accent = ACCENTS.get(kicker, ACCENTS["_default"])
    draw.rounded_rectangle(chip, radius=27, fill=accent + (255,))
    draw.text((margin + 22, 60 + 27), kicker, font=kf, fill=(12, 16, 30),
              anchor="lm")

    # 見出し
    size = fit_size(lines, max_w)
    f = font(size)
    gap = int(size * 0.34)
    block_h = len(lines) * size + (len(lines) - 1) * gap
    y = max(150, (H - 120 - block_h) // 2 + 30)
    for i, line in enumerate(lines):
        color = MARK if i == hi else WHITE
        if i == hi:  # ハイライト行は黄色の下線マーカーも敷く
            lw = text_w(draw, line, f)
            bar_top = y + int(size * 0.86)
            draw.rounded_rectangle(
                (margin - 6, bar_top, margin + lw + 10, bar_top + int(size * 0.20)),
                radius=int(size * 0.10), fill=MARK + (90,))
        draw.text((margin, y), line, font=f, fill=color,
                  stroke_width=max(5, size // 14), stroke_fill=(6, 9, 20))
        y += size + gap

    # 下部バッジ（ロゴ＋事務所名）
    badge_y = H - 108
    try:
        logo = Image.open(LOGO_PATH).convert("RGB")
        lw_, lh_ = logo.size
        logo = logo.crop((int(lw_ * 0.20), int(lh_ * 0.16),
                          int(lw_ * 0.86), int(lh_ * 0.68)))  # ハートマークだけ
        logo = cover_crop(logo, 76, 76)
        mask = Image.new("L", (76, 76), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 75, 75), fill=255)
        canvas.paste(logo, (margin, badge_y), mask)
        draw.ellipse((margin, badge_y, margin + 75, badge_y + 75),
                     outline=(255, 255, 255, 150), width=2)
    except Exception as e:
        print(f"    ロゴ合成スキップ: {e}")

    tx = margin + 96
    draw.text((tx, badge_y + 8), "TAITAN PRO", font=font(32), fill=WHITE,
              stroke_width=4, stroke_fill=(6, 9, 20))
    draw.text((tx, badge_y + 48), "所属200名のライバー事務所", font=font(24), fill=SUB,
              stroke_width=4, stroke_fill=(6, 9, 20))

    out = output_path(num)
    canvas.convert("RGB").save(out, "PNG", optimize=True)
    return out, kicker, lines


def missing_numbers():
    nums = []
    for path in sorted(glob.glob(os.path.join(ARTICLES_DIR, "*.md"))):
        m = re.match(r"^(\d+)_", os.path.basename(path))
        if not m:
            continue
        num = int(m.group(1))
        if not glob.glob(os.path.join(IMAGES_DIR, f"{num:02d}_*.png")):
            nums.append(num)
    return nums


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("nums", nargs="*", type=int, help="記事番号")
    ap.add_argument("--missing", action="store_true", help="カバー未生成の記事だけ処理")
    ap.add_argument("--regen-bg", action="store_true", help="背景を作り直す")
    ap.add_argument("--no-bg", action="store_true", help="背景キャッシュのみ使う（生成しない）")
    ap.add_argument("--bg-seed", type=int, help="背景のseedを指定して絵を引き直す")
    args = ap.parse_args()

    nums = args.nums or (missing_numbers() if args.missing else [])
    if not nums:
        print("対象がありません（記事番号を指定するか --missing を付けてください）")
        return 1

    for num in nums:
        title = article_title(num)
        print(f"#{num} {title[:44]}")
        if args.no_bg and not os.path.exists(os.path.join(BG_DIR, f"{num:02d}.jpg")):
            print("    背景キャッシュなし → スキップ")
            continue
        out, kicker, lines = build(
            num,
            regenerate_bg=args.regen_bg or args.bg_seed is not None,
            seed=args.bg_seed,
        )
        print(f"    [{kicker}] {' / '.join(lines)}")
        print(f"    ✓ {os.path.relpath(out, BASE_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
