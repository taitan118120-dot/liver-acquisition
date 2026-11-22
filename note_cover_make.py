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

レイアウト（2026-11-22 改定「目立つカバー」）:
  旧版は写真全面＋左を紺で暗く落とす形だったが、背景が茶系の机・マグばかりで
  タイムラインに並ぶと全部同じに見え、色も沈んでいた。PV上位のカバーに共通するのは
  「彩度の高い色」と「一目で分かる主役」。そこで
    左＝カテゴリ色のベタパネル（斜めカット＋黄色ライン）に特大見出し
    右＝主役の写る写真（彩度を上げる）
  の分割にした。見出しは白文字＋太い縁取り＋影、ハイライト行は黄色ベタ帯に黒文字。
  パネル色は kicker ごと（PANEL_COLORS）。note_cover_text.json の "color": [r,g,b] で上書きできる。
  写真は斜めカットより右の枠に主役を据えて切り出す。主役を外したら同じJSONの
  "focus"（元画像での主役の横位置0..1）と "zoom"（既定1.12）で直す。
  写真が右4割に入るので「背景が単色で文字だけのカード」には当たらない。
  下部バッジは位置・色・大きさを変えていない（note_cover_guard が画素位置で照合するため）。

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
  python3 note_cover_make.py --ref-only      # 番犬用のバッジ基準だけ書き出す

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

import note_cover_badge
from facts_patterns import NOTE_COVER_BADGE

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
STAMP_RED = (226, 38, 54)   # 判子
ACCENTS = {                 # kicker チップの色（プラットフォーム別）
    "Pococha": (255, 92, 138),
    "TikTok LIVE": (0, 224, 196),
    "代理店": (167, 139, 250),
    "_default": (79, 195, 247),
}
# 左パネルの色（kicker別）。黄色はハイライト帯と潰し合うので使わない。
PANEL_COLORS = {
    "Pococha": (236, 64, 122),
    "TikTok LIVE": (0, 172, 193),
    "代理店": (98, 54, 196),
    "用語解説": (33, 118, 230),
    "配信のコツ": (245, 110, 30),
    "続け方": (0, 150, 110),
    "顔出しなし": (63, 81, 181),
    "_default": (229, 57, 53),
}
PANEL_TOP_X, PANEL_BOTTOM_X = 830, 730   # 斜めカットの境目（上端・下端のx）

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
    # 2026-11-22 補充 #279-288（タイトル語で拾う。汎用語「顔出しなし」「TikTok」「代理店」より先に置く）
    ("辞める理由", "close-up of a warm mug of tea and a closed notebook on a wooden desk by a window, a small potted plant behind them, the mug is the main subject on the right side, soft evening light"),
    ("ライバー育成", "close-up of an open spiral notebook with a handwritten checklist and a pen lying on it, a smartphone on a small stand behind it, bright wooden desk, the notebook is the main subject on the right side, morning sunlight"),
    ("ガチ恋", "close-up of a single red rose lying on a plain wooden table, no paper, no card, no text, no letters, the rose is the main subject on the right side, soft warm evening light, shallow depth of field"),
    ("カメラの位置", "close-up of a smartphone mounted on a small black tripod at eye level on a wooden desk, a round ring light glowing behind it, the smartphone and tripod are the main subject on the right side, warm cozy room"),
    ("スカウト代行", "close-up of a stack of white envelopes tied with string next to a laptop and a smartphone on an office desk, the envelopes are the main subject on the right side, morning light"),
    ("モデレーター", "close-up of a smartphone standing on a small desk stand next to a pair of over-ear headphones and a small potted plant, clean modern desk, the smartphone is the main subject on the right side, cool blue evening light"),
    ("初見さん", "close-up of a smartphone on a stand on a wooden desk next to a small potted flower and a cup of coffee, a warm welcoming desk lamp, the smartphone is the main subject on the right side, cozy evening light"),
    ("1on1", "two coffee cups facing each other on a wooden table with an open notebook and a pen between them, the cups are the main subject on the right side, warm afternoon window light"),
    ("マスク", "close-up of a white face mask lying on a wooden desk next to a smartphone on a stand and a small desk microphone, the mask is the main subject on the right side, warm lamp light, cozy room at night"),
    ("一次店", "extreme close-up of a large golden padlock and heavy steel chain on top of a stack of paper documents beside a calculator, the padlock is the main subject and fills the right side of the frame, dark wooden desk, dramatic side light, high contrast, dark background"),
    # 2026-10-22 補充 #237-246（在宅の仕事・副業・40/50/60代・マネージャー）
    ("家でできる仕事", "a tidy home workspace by a window, a laptop, a smartphone on a stand and a notebook on a wooden desk, a houseplant, soft daylight"),
    ("夜だけできる", "a desk at night in a quiet apartment, a smartphone on a small tripod and a desk lamp glowing warmly, a cup of tea, blurred city lights through the window"),
    ("副業禁止", "a closed ring binder and a smartphone on a home desk beside a cup of coffee and a pen, calm evening lamp light"),
    ("50代女性", "a calm living room with a smartphone on a stand on a low wooden table, a cup of tea, reading glasses and a small flower vase, soft afternoon light"),
    ("40代から在宅", "a home desk in the evening, a smartphone on a stand, a closed laptop, a wristwatch and a mug, warm lamp light"),
    ("60代から", "a japanese style room with a low wooden table, a smartphone on a small stand, a teapot and two cups, a potted plant, soft natural light"),
    ("マネージャーの求人", "a home office desk with a laptop, a smartphone, headphones and an open planner, bright morning light through the window"),
    ("スカウトDM", "a smartphone lying face up on a wooden desk beside an open notebook, a pen and a coffee cup, warm afternoon light"),
    ("副業でできる", "a home desk in the evening with a laptop, a smartphone, a paper weekly planner and a cup of coffee, warm lamp light"),
    ("新人期間", "a smartphone on a small tripod on a wooden desk, an open notebook with a pen and a paper calendar beside it, a mug of coffee, morning sunlight through the window"),
    ("しんどい", "a quiet living room in the evening, a warm mug on a low table, a folded blanket on the sofa, a small lamp glowing softly"),
    ("顔出しなし", "a desk microphone and headphones on a wooden desk, a smartphone beside them, warm desk lamp light, dark cozy room at night"),
    ("主婦", "a bright kitchen counter with a smartphone on a stand, a mug and a small plant, laundry basket in the soft background, daytime sunlight"),
    ("TikTok", "a smartphone on a tripod facing a ring light on a modern desk, cool blue light, clean simple room"),
    ("代理店", "a laptop, a notebook and a cup of coffee on a bright office desk, documents neatly stacked, morning light"),
    ("確定申告", "a calculator, receipts and tax documents on a desk with a laptop, tidy and organized, daylight"),
    ("SNS運用", "a smartphone lying on a wooden desk next to a laptop and a small notepad, a cup of coffee, warm afternoon light through a window"),
    ("続ける仕組み", "a paper weekly planner open on a desk with a pen, a smartphone on a stand behind it, a mug of tea, calm morning light"),
    ("振り返り", "an open notebook with a pen resting on it beside a smartphone on a wooden desk, a small desk lamp, quiet night light"),
    ("お礼", "a small wrapped gift box and a handwritten letter on a wooden table next to a smartphone, soft warm light"),
    ("休むとき", "a closed notebook and a warm mug on a low table in a dim quiet living room, a folded blanket nearby, soft lamp light"),
    ("コメント", "a smartphone on a stand on a desk seen from a low angle, a mug and a notepad beside it, cozy room in the evening"),
    ("聞き取りやすい声", "a close-up of a desk microphone on a wooden desk, headphones beside it, soft warm light, dark quiet room"),
    ("大学生", "a student desk with textbooks, a notebook, a laptop and a smartphone on a stand, a canvas backpack on the chair, daylight"),
    ("専業", "a tidy home office desk with a laptop, a calculator, a paper calendar and a mug, morning light through the window"),
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
    for name in ("Pococha", "TikTok LIVE", "TikTok"):
        if name in title:
            return "TikTok LIVE" if name == "TikTok" else name
    return "ライブ配信"


# 代理店（＝事務所を"作る側"）の記事に「ライブ配信」と貼ると、読者がライバー志望向けの
# 記事だと思って素通りする。ただしタイトルだけでは判別しきれない（「事務所運営の
# トラブル対応」「事務所の立ち上げ」は is_agency_article の強いしるしに当たらないし、
# そこを緩めると「事務所の選び方」＝ライバー志望向けまで代理店扱いになる）。
# 本文のCTAは note_article_generator が**カテゴリで**出し分けているので、
# 代理店向け特典が入っているかを見るのがいちばん確実。
_AGENCY_CTA_MARK = "ライバー代理店パートナー スタートガイド"


def is_agency_article_file(num):
    path = article_path(num)
    if not path:
        return False
    try:
        with open(path, encoding="utf-8") as f:
            return _AGENCY_CTA_MARK in f.read()
    except OSError:
        return False


def auto_lines(title, max_chars=11, max_lines=3):
    """タイトルから見出し2〜3行を組む。句読点・記号で折る。

    最後に lines[:max_lines] で切ると、**入りきらなかった行が文の途中で消える**。
    実測（#167「初めての担当ライバーが初配信で号泣。あの夜から私が変えた、事務所運営の
    「トラブル対応」」）では3行目が「ら私が変えた、」になり、単語の途中から始まって
    読点で終わる断片が、よりによって黄色ハイライトの位置に来ていた。

    なので**入りきる「かたまり」だけを積む**。次のかたまりが丸ごと入らないなら
    そこで打ち切る（途中から始めない）。最後に句読点で終わっていれば落とす。
    """
    head = title.split("｜")[0]
    head = re.sub(r"【[^】]*】", "", head).strip()
    for mark in ("、", "。", "？", "！"):
        head = head.replace(mark, mark + "\n")
    chunks = [c for c in (s.strip() for s in head.split("\n")) if c]

    lines = []
    for c in chunks:
        # このかたまりを積むのに要る行数
        need = -(-len(c) // max_chars)
        if len(lines) + need > max_lines:
            break  # 丸ごと入らないなら手を付けない
        piece = [c[i:i + max_chars] for i in range(0, len(c), max_chars)]
        # 端数が1〜2文字だと「…のスカウ / ト」のように1文字だけ行に取り残される。
        # そのぶんは前の行にあふれさせる（多少はみ出しても孤立文字よりは読める）。
        if len(piece) > 1 and len(piece[-1]) <= 2:
            piece[-2] += piece[-1]
            piece.pop()
        lines.extend(piece)
    if not lines:  # 1かたまりも入らないほど長い場合だけ機械的に折る
        flat = "".join(chunks)
        lines = [flat[i:i + max_chars] for i in range(0, len(flat), max_chars)][:max_lines]
    while lines and lines[-1] and lines[-1][-1] in "、。・「（":
        lines[-1] = lines[-1][:-1]
        if not lines[-1]:
            lines.pop()
    return lines[:max_lines]


def resolve_text(num):
    """(kicker, lines, highlight_index) を返す。"""
    title = article_title(num)
    spec = load_text_map().get(str(num))
    default_kicker = guess_kicker(title)
    if default_kicker == "ライブ配信" and is_agency_article_file(num):
        default_kicker = "代理店"
    if spec:
        lines = spec["lines"]
        kicker = spec.get("kicker") or default_kicker
        hi = spec.get("highlight", len(lines) - 1)
    else:
        lines = auto_lines(title)
        kicker = default_kicker
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


def strip_watermark(img, ratio=0.08):
    """Pollinations が右下に焼き込む「pollinations.ai」の透かしを下端ごと落とす。

    nologo=true が効かなくなり（2026-10 確認）、focus_crop の左右反転で
    左下に鏡文字として出ていた。下端 8% を切れば透かしの帯ごと消える。
    """
    return img.crop((0, 0, img.width, int(img.height * (1 - ratio))))


def ensure_bg(num, regenerate=False, seed=None):
    os.makedirs(BG_DIR, exist_ok=True)
    path = os.path.join(BG_DIR, f"{num:02d}.jpg")
    if os.path.exists(path) and not regenerate:
        return strip_watermark(Image.open(path).convert("RGB"))
    img = fetch_bg(num, seed if seed is not None else 1000 + num)
    img.save(path, "JPEG", quality=88, optimize=True)
    return strip_watermark(img)


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


def draw_stamp(canvas, label):
    """右上に赤い判子を傾けて重ねる（data/note_cover_text.json の stamp で指定）。"""
    f = font(46)
    tw = text_w(ImageDraw.Draw(canvas), label, f)
    w, h = tw + 72, 104
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((3, 3, w - 4, h - 4), radius=16, fill=STAMP_RED + (255,),
                        outline=WHITE + (255,), width=5)
    d.text((w // 2, h // 2), label, font=f, fill=WHITE, anchor="mm")
    layer = layer.rotate(-7, expand=True, resample=Image.BICUBIC)
    canvas.alpha_composite(layer, (W - layer.width - 36, 40))


def photo_window(img, zoom=1.12, focus=None):
    """写真の見える部分（x = PANEL_BOTTOM_X より右）に主役が収まるよう切り出して W×H に置く。

    写真全面を縮めて右に寄せる（focus_crop）と、見える幅が全体の4割しかないので
    主役（リングライト・カップ等）が斜めの境目で切れる。高さ基準で拡大し、
    「見える枠」の幅だけを主役中心で切り出して右端に貼る。左はパネルで隠れる。
    """
    if focus is None:  # 主役の位置をエッジ量で推定（外すことがあるので検品で確認する）
        focus = subject_x(img)
        if focus < 0.5:  # 主役が左 → 反転（静物は反転しても違和感が無い）
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
            focus = 1.0 - focus
    view_w = W - PANEL_BOTTOM_X + 40
    scale = max(H / img.height, view_w / img.width) * zoom
    sw, sh = int(img.width * scale), int(img.height * scale)
    big = img.resize((sw, sh), Image.LANCZOS)
    left = max(0, min(sw - view_w, int(focus * sw - view_w / 2)))
    top = max(0, (sh - H) // 2)
    out = Image.new("RGB", (W, H), INK)
    out.paste(big.crop((left, top, left + view_w, top + H)), (W - view_w, 0))
    return out


def panel_edge(y):
    """斜めカットの境目の x（y の位置）。"""
    return PANEL_TOP_X + (PANEL_BOTTOM_X - PANEL_TOP_X) * y / H


def layout_headline(draw, lines, top, bottom, margin, start=128, floor=48):
    """見出しが「上下の枠」と「斜めの境目」の両方に収まる最大サイズで、各行の y を返す。"""
    size = start
    while True:
        f = font(size)
        gap = int(size * 0.22)
        pad = int(size * 0.16)           # ハイライト帯のはみ出し
        block_h = len(lines) * size + (len(lines) - 1) * gap
        y0 = top + (bottom - top - block_h) // 2
        ys = [y0 + i * (size + gap) for i in range(len(lines))]
        fits = block_h <= bottom - top and all(
            margin + text_w(draw, ln, f) + pad + 34 <= panel_edge(y + size + pad)
            for ln, y in zip(lines, ys))
        if fits or size <= floor:
            return size, f, ys
        size -= 2


def build(num, regenerate_bg=False, seed=None):
    kicker, lines, hi = resolve_text(num)
    spec = load_text_map().get(str(num)) or {}
    color = tuple(spec.get("color") or PANEL_COLORS.get(kicker, PANEL_COLORS["_default"]))

    # 右の写真：見えている枠（斜めカットより右）の真ん中に主役を据え、彩度を上げる
    # 主役の位置を外したときは note_cover_text.json の "focus"（元画像での横位置0..1）と
    # "zoom" で直す（例: #284 は鉢植えが 0.74 にあるのに推定が 0.47 で壁を映していた）
    bg = photo_window(ensure_bg(num, regenerate_bg, seed),
                      zoom=spec.get("zoom", 1.12), focus=spec.get("focus"))
    bg = ImageEnhance.Color(bg).enhance(1.3)
    bg = ImageEnhance.Contrast(bg).enhance(1.08)
    canvas = bg.convert("RGBA")

    # 左のカテゴリ色パネル（上→下へわずかに濃くして平板に見えないようにする）
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    for y in range(H):
        k = 1.0 - 0.16 * (y / H)
        pd.line([(0, y), (int(panel_edge(y)), y)],
                fill=tuple(int(c * k) for c in color) + (255,))
    pd.line([(PANEL_TOP_X + 10, 0), (PANEL_BOTTOM_X + 10, H)], fill=MARK + (255,), width=12)
    canvas = Image.alpha_composite(canvas, panel)

    # 下端を締める（バッジの可読性と、番犬の画素照合の下地を暗く保つ）
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(H - 150, H):
        t = (y - (H - 150)) / 150
        sd.line([(0, y), (W, y)], fill=INK + (int(150 * t),))
    canvas = Image.alpha_composite(canvas, shade)
    draw = ImageDraw.Draw(canvas)

    margin = 64

    if spec.get("stamp"):
        draw_stamp(canvas, spec["stamp"])
        draw = ImageDraw.Draw(canvas)

    # kicker チップ（白地にパネル色の文字）
    kf = font(34)
    kw = text_w(draw, kicker, kf)
    draw.rounded_rectangle((margin, 46, margin + kw + 48, 46 + 60), radius=30, fill=WHITE + (255,))
    draw.text((margin + 24, 46 + 30), kicker, font=kf, fill=color, anchor="lm")

    # 見出し：白文字＋太い縁取り＋影。ハイライト行は黄色ベタ帯に黒文字
    size, f, ys = layout_headline(draw, lines, 128, H - 128, margin,
                                  start=spec.get("font_start", 128))
    stroke = max(5, size // 15)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shd = ImageDraw.Draw(shadow)
    for i, (line, y) in enumerate(zip(lines, ys)):
        if i != hi:
            shd.text((margin + 5, y + 6), line, font=f, fill=(0, 0, 0, 140),
                     stroke_width=stroke, stroke_fill=(0, 0, 0, 140))
    from PIL import ImageFilter
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(4)))
    draw = ImageDraw.Draw(canvas)
    for i, (line, y) in enumerate(zip(lines, ys)):
        if i == hi:
            bb = draw.textbbox((margin, y), line, font=f)
            pad = int(size * 0.16)
            draw.rounded_rectangle((bb[0] - pad, bb[1] - pad, bb[2] + pad, bb[3] + pad),
                                   radius=int(size * 0.12), fill=MARK + (255,))
            draw.text((margin, y), line, font=f, fill=INK)
        else:
            draw.text((margin, y), line, font=f, fill=WHITE,
                      stroke_width=stroke, stroke_fill=INK)

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

    draw_badge_text(draw, margin, badge_y)

    out = output_path(num)
    canvas.convert("RGB").save(out, "PNG", optimize=True)
    return out, kicker, lines


def badge_lines(margin=64, badge_y=H - 108):
    """下部バッジの2行。事務所名は facts_patterns.NOTE_COVER_BADGE が正本
    （ここに数字を直書きすると、ファクト更新で直し漏れたまま焼き込まれる）。"""
    tx = margin + 96
    return [("title", "TAITAN PRO", (tx, badge_y + 8), font(32), WHITE),
            ("badge", NOTE_COVER_BADGE, (tx, badge_y + 48), font(24), SUB)]


def draw_badge_text(draw, margin=64, badge_y=H - 108):
    for _, text, xy, fnt, color in badge_lines(margin, badge_y):
        draw.text(xy, text, font=fnt, fill=color,
                  stroke_width=4, stroke_fill=(6, 9, 20))


def write_badge_ref():
    """番犬（note_cover_guard）が照合に使う基準を書き出す。CIにはヒラギノが無く
    基準を描けないので、カバーを作る mac 側で毎回作ってコミットする。"""
    canvas = Image.new("RGB", (W, H), (10, 12, 20))
    draw_badge_text(ImageDraw.Draw(canvas))
    note_cover_badge.write_ref(note_cover_badge.build_ref(canvas, badge_lines(), (W, H)))


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
    ap.add_argument("--ref-only", action="store_true",
                    help="番犬用のバッジ基準(data/note_cover_badge_ref.json)だけ書き出す")
    args = ap.parse_args()

    # バッジ文言（facts_patterns.NOTE_COVER_BADGE）を変えたら基準も必ず変わるよう、
    # カバーを作るたびに書き出す（内容が同じなら差分は出ない）。
    write_badge_ref()
    if args.ref_only:
        print(f"✓ {os.path.relpath(note_cover_badge.REF_PATH, BASE_DIR)}")
        return 0

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
