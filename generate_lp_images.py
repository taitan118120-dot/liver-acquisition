#!/usr/bin/env python3
"""
beginner LP 専用イラストの一括生成

Pollinations.ai (無料・無制限・商用OK) で生成 → lp/shared/img/ に保存。
Google APIの予算は一切消費しない。

全カットで STYLE を共有し、seed を固定することで
「同じ絵柄シリーズ」に見えるようにしている。

使い方:
  python3 generate_lp_images.py --test          # 3枚だけ試す
  python3 generate_lp_images.py                 # 全カット生成
  python3 generate_lp_images.py --only hero     # 特定カットだけ再生成
  python3 generate_lp_images.py --only hero --seed 99   # 気に入らない絵はseedを変えて引き直す
"""
import argparse
import time
import urllib.parse
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "lp" / "shared" / "img"

# ---- 全カット共通のスタイル指定（ここを変えると絵柄が一括で変わる） ----
STYLE = (
    "flat vector illustration, soft pastel color palette, "
    "dusty pink lavender and cream tones, "
    "clean minimal shapes, no outlines, gentle rounded forms, "
    "modern japanese web illustration style, warm and friendly atmosphere, "
    "soft ambient lighting, plenty of white space, "
    "pure white background, centered composition, "
    "NO text, NO letters, NO words, NO logos, NO watermark, "
    "NOT photorealistic, NOT 3D render, NOT anime, flat 2D only"
)

SUBJECT_PREFIX = "young japanese woman in her twenties, casual comfortable clothes, natural relaxed expression, "

# ---- カット定義：ファイル名 -> (被写体プロンプト, seed) ----
CUTS = {
    "hero-liver": (
        SUBJECT_PREFIX + "sitting relaxed at home holding a smartphone with both hands, "
        "smiling warmly at the phone, cozy living room with plants and soft cushions",
        101,
    ),
    "worry-start": (
        SUBJECT_PREFIX + "sitting at a desk at home looking thoughtful and unsure, "
        "hand resting on cheek, laptop closed in front of her, contemplative mood",
        102,
    ),
    "worry-skill": (
        SUBJECT_PREFIX + "standing with slightly hunched shoulders looking hesitant and shy, "
        "hands clasped together, small question marks floating around her head",
        103,
    ),
    "worry-time": (
        SUBJECT_PREFIX + "looking tired after work, holding a bag, "
        "a large wall clock behind her, busy schedule feeling",
        104,
    ),
    "step-stream": (
        SUBJECT_PREFIX + "tapping the screen of a smartphone mounted on a small tripod, "
        "about to start a live stream, simple ring light beside her",
        105,
    ),
    "step-talk": (
        SUBJECT_PREFIX + "talking cheerfully to a smartphone on a stand, "
        "speech bubbles and heart icons floating around, lively conversation",
        106,
    ),
    "step-reward": (
        "flat illustration of a smartphone standing upright with an upward growth chart on screen, "
        "coins and small heart icons rising gently around it, no people",
        107,
    ),
    "mechanism": (
        "flat illustration of a smartphone with a rising bar chart, "
        "a clock icon and small heart icons arranged around it, "
        "clean infographic feeling, no people",
        108,
    ),
    "setup": (
        "flat illustration of a simple live streaming setup at home, "
        "smartphone on a tripod, ring light, small desk with a plant, "
        "no people, tidy minimal scene",
        109,
    ),
    "case-student": (
        SUBJECT_PREFIX + "university student style with a tote bag, "
        "sitting on the floor of her room with a smartphone, books nearby, casual and youthful",
        110,
    ),
    "case-housewife": (
        SUBJECT_PREFIX + "at home in a bright kitchen and living space, "
        "holding a smartphone with a calm gentle smile, homey domestic atmosphere",
        111,
    ),
    "fans": (
        "flat illustration of a smartphone screen surrounded by many small floating heart icons "
        "and simple abstract people silhouettes cheering, warm supportive feeling, pastel colors",
        112,
    ),
    "meeting": (
        SUBJECT_PREFIX + "having a friendly online video call on a laptop, "
        "another person visible on the laptop screen, relaxed consultation mood",
        113,
    ),
    "safety": (
        SUBJECT_PREFIX + "sitting calmly and peacefully with a relieved gentle expression, "
        "a soft protective shield shape glowing behind her, feeling of safety and reassurance",
        114,
    ),
    "age": (
        "flat illustration of four different japanese women of various ages standing together, "
        "student, office worker, mother, and middle aged woman, "
        "each holding a smartphone, friendly diverse group",
        115,
    ),
    "desk": (
        "flat illustration of a cozy home desk in the evening, "
        "smartphone on a stand, warm lamp light, a mug and a small plant, "
        "no people, calm night atmosphere",
        116,
    ),
    "no-face": (
        SUBJECT_PREFIX + "streaming without showing her face, seen from behind over her shoulder, "
        "facing a smartphone on a stand, microphone icon floating, privacy friendly mood",
        117,
    ),
    "prepare": (
        SUBJECT_PREFIX + "checking a notebook checklist while sitting at a desk, "
        "smartphone beside her, preparing and planning mood",
        118,
    ),
}

TEST_CUTS = ["hero-liver", "worry-start", "step-talk"]


def generate(prompt: str, seed: int, size: int = 1024, retries: int = 6) -> Image.Image:
    """Pollinations は匿名利用だとレート制限(429)が出るので、指数バックオフで粘る"""
    full = f"{prompt}, {STYLE}"
    encoded = urllib.parse.quote(full)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={size}&height={size}&model=flux&nologo=true&seed={seed}"
    )
    wait = 20
    last = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=240)
            if resp.status_code in (429, 500, 502, 503, 504, 524):
                last = f"HTTP {resp.status_code}"
                print(f"        ⏳ {last} / {wait}秒待って再試行 ({attempt}/{retries})")
                time.sleep(wait)
                wait = min(int(wait * 1.8), 180)
                continue
            resp.raise_for_status()
            return Image.open(BytesIO(resp.content)).convert("RGB")
        except requests.RequestException as e:
            last = str(e)
            print(f"        ⏳ 通信エラー / {wait}秒待って再試行 ({attempt}/{retries})")
            time.sleep(wait)
            wait = min(int(wait * 1.8), 180)
    raise RuntimeError(f"{retries}回試行しても取得できませんでした: {last}")


def save_optimized(img: Image.Image, name: str) -> int:
    """LP用に900px・JPEG品質82へ落として保存"""
    img.thumbnail((900, 900), Image.LANCZOS)
    out = OUT_DIR / f"{name}.jpg"
    img.save(out, "JPEG", quality=82, optimize=True, progressive=True)
    return out.stat().st_size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="代表3カットだけ生成")
    ap.add_argument("--only", type=str, help="指定カットのみ生成")
    ap.add_argument("--seed", type=int, help="seedを上書き（絵を引き直す）")
    ap.add_argument("--delay", type=int, default=12, help="各カット間の待ち秒数（レート制限回避）")
    ap.add_argument("--missing", action="store_true", help="まだ生成していないカットだけ処理")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.only:
        targets = [t.strip() for t in args.only.split(",") if t.strip()]
    elif args.test:
        targets = TEST_CUTS
    else:
        targets = list(CUTS)

    if args.missing:
        done = {p.stem for p in OUT_DIR.glob("*.jpg")}
        targets = [t for t in targets if t not in done]

    print(f"生成対象: {len(targets)}カット（各カット間 {args.delay}秒待機）\n", flush=True)
    failed = []
    for i, name in enumerate(targets, 1):
        if name not in CUTS:
            print(f"  ✗ 未定義のカット: {name}", flush=True)
            continue
        prompt, seed = CUTS[name]
        if args.seed is not None:
            seed = args.seed
        print(f"[{i}/{len(targets)}] {name} (seed={seed}) 生成中...", flush=True)
        try:
            img = generate(prompt, seed)
            size = save_optimized(img, name)
            print(f"        ✓ {name}.jpg  {size // 1024}KB", flush=True)
        except Exception as e:
            print(f"        ✗ 失敗: {e}", flush=True)
            failed.append(name)
        if i < len(targets):
            time.sleep(args.delay)

    print(f"\n完了  成功={len(targets) - len(failed)} 失敗={len(failed)}", flush=True)
    if failed:
        print("失敗したカット: " + " ".join(failed), flush=True)


if __name__ == "__main__":
    main()
