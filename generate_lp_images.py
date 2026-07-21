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
# 2026-07-21: フラットイラスト → ヒーロー写真(hero-liver-photo.jpg)に合わせた
# 実写風ライフスタイルフォトへ刷新。全カットに人物を入れて「自分ごと化」させる。
STYLE = (
    "photorealistic lifestyle photography, soft natural window light, "
    "warm cream and pastel pink japanese apartment interior, "
    "cozy comfortable atmosphere, shallow depth of field, "
    "high resolution, sharp focus on the person, "
    "NO text, NO letters, NO words, NO logos, NO watermark, "
    "NOT illustration, NOT anime, NOT 3D render"
)

SUBJECT_PREFIX = (
    "pretty young japanese woman in her early twenties, natural makeup, "
    "dark brown medium-long hair, casual cute comfortable clothes, "
)

# ---- カット定義：ファイル名 -> (被写体プロンプト, seed) ----
CUTS = {
    "worry-start": (
        SUBJECT_PREFIX + "sitting at a small desk at home in front of a laptop, "
        "resting her chin on one hand, slightly troubled thoughtful expression, "
        "searching for a work-from-home job, daytime room",
        102,
    ),
    "worry-skill": (
        SUBJECT_PREFIX + "sitting on a sofa hugging a soft cushion, "
        "unsure shy expression looking slightly away, lacking confidence mood",
        103,
    ),
    "worry-time": (
        SUBJECT_PREFIX + "in office casual clothes just back home in the evening, "
        "sitting on her bed still holding a tote bag, tired but gentle expression, "
        "warm lamp light, busy daily life feeling",
        104,
    ),
    "step-stream": (
        SUBJECT_PREFIX + "sitting comfortably in her cozy room facing the camera, "
        "a blurred smartphone on a small tripod in the near foreground edge, "
        "gentle excited smile, about to start a live stream, ring light glow, "
        "her hands resting relaxed on her lap",
        205,
    ),
    "step-talk": (
        SUBJECT_PREFIX + "waving hello at the camera as if greeting her "
        "livestream viewers, bright happy laughing expression, "
        "sitting in her cozy room, lively fun mood, one open hand waving",
        206,
    ),
    "step-reward": (
        SUBJECT_PREFIX + "holding her smartphone with both hands close to her chest, "
        "looking at the screen with a delighted happy smile, "
        "pleasant surprise, warm evening light",
        107,
    ),
    "mechanism": (
        SUBJECT_PREFIX + "seen completely from behind, back of her head, "
        "face not visible at all, she is live streaming, "
        "smartphone mounted on a tripod in front of her, "
        "cozy warm room, soft round bokeh of warm lamps in the background",
        308,
    ),
    "setup": (
        "smartphone mounted on a small tripod and a ring light "
        "on a tidy white desk with a small plant, sharp focus on the gear, "
        "a young japanese woman smiling softly blurred in the background, "
        "simple minimal streaming corner at home",
        209,
    ),
    "safety": (
        SUBJECT_PREFIX + "relaxed on a sofa wrapped in a soft blanket, "
        "holding a warm mug with both hands, gentle relieved smile, "
        "feeling safe and comfortable at home",
        114,
    ),
    "meeting": (
        SUBJECT_PREFIX + "smiling and waving at a laptop screen "
        "during a friendly online video call at home, relaxed consultation mood",
        113,
    ),
    # 働き方の実例：主婦ライバーのイメージカット（case-avatar 用・正方形バストアップ）
    "liver-housewife": (
        "pretty japanese woman in her early thirties, natural makeup, "
        "dark brown medium-long hair, soft beige knit, "
        "bust-up portrait facing the camera, gentle warm smile, "
        "relaxed at home in a bright tidy living room, "
        "calm confident housewife atmosphere",
        410,
    ),
}

TEST_CUTS = ["worry-start", "step-talk", "mechanism"]


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
