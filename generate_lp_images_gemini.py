#!/usr/bin/env python3
"""
beginner LP 写真の生成（Gemini版）

Pollinations(flux) は手指と機材がよく破綻するため、2026-07-21 に Gemini
(gemini-2.5-flash-image) 経路へ移行した。note_image_generator.py と同じAPIを使う。

使い方:
  GEMINI_API_KEY=... python3 generate_lp_images_gemini.py --only setup
  GEMINI_API_KEY=... python3 generate_lp_images_gemini.py --out /tmp/candidates
  （--out を付けると lp/shared/img ではなく検品用ディレクトリに書き出す）

注意: Google APIの予算は限られているので、必要なカットだけ生成すること。
"""
import argparse
import os
from io import BytesIO
from pathlib import Path

from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "lp" / "shared" / "img"

# ---- 全カット共通の撮影指定 ----
STYLE = (
    "Photorealistic square lifestyle photograph shot on a 50mm lens, "
    "soft natural window light, warm cream and pastel pink Japanese apartment interior, "
    "cozy and comfortable atmosphere, shallow depth of field, sharp focus on the person. "
    "Hands must be anatomically correct with exactly five fingers per hand, "
    "no deformed or extra fingers, no distorted limbs. "
    "Any equipment must look like a real, recognizable consumer product with correct structure. "
    "No text, no letters, no logos, no watermark. "
    "Not an illustration, not anime, not a 3D render."
)

WOMAN = (
    "A pretty Japanese woman in her early twenties with natural light makeup "
    "and dark brown medium-long hair, wearing casual comfortable clothes"
)
# STEPカード3枚は同一人物・上半身に統一する
STEP_WOMAN = (
    "A pretty Japanese woman in her early twenties with natural light makeup, "
    "dark brown medium-long hair and a cream knit sweater, "
    "framed from the waist up so her legs are not visible"
)

CUTS = {
    "worry-start": (
        f"{WOMAN} sits at a small desk at home in front of an open laptop, "
        "resting her chin on one hand with a slightly troubled, thoughtful expression, "
        "searching for a work-from-home job in the daytime."
    ),
    "worry-skill": (
        f"{WOMAN} sits on a sofa hugging a soft cushion with both arms, "
        "an unsure shy expression looking slightly away, lacking confidence."
    ),
    "worry-time": (
        f"{WOMAN} in office-casual clothes has just come home in the evening and "
        "sits on the edge of her bed still holding a tote bag, "
        "tired but gentle expression, warm lamp light."
    ),
    "step-stream": (
        f"{STEP_WOMAN} sits at a tidy white desk in her bright cozy room. "
        "An ordinary smartphone is correctly mounted vertically in a small black "
        "smartphone tripod in front of her, screen facing her. "
        "She smiles with gentle excitement, about to start a live stream, "
        "both hands resting calmly and clearly on the desk, fingers relaxed and separated."
    ),
    "step-talk": (
        f"{STEP_WOMAN} waves hello at the camera with one open hand, "
        "bright happy laughing expression, cozy room, lively fun mood."
    ),
    "step-reward": (
        f"{STEP_WOMAN} holds a smartphone with both hands near her chest and looks at "
        "the screen with a delighted happy smile, warm evening light."
    ),
    "mechanism": (
        f"{WOMAN} seen completely from behind so her face is not visible at all. "
        "She is live streaming to a smartphone mounted on a small tripod in front of her, "
        "her hands are empty and relaxed at her sides, she is not holding anything, "
        "cozy warm room, soft round bokeh of warm lamps in the background."
    ),
    "safety": (
        f"{WOMAN} relaxes on a sofa wrapped in a soft blanket, "
        "holding a warm mug with both hands, gentle relieved smile, safe and comfortable at home."
    ),
    "meeting": (
        "A pretty Japanese woman in her mid twenties with a black shoulder-length bob "
        "and a white blouse smiles and waves at a laptop screen during a friendly "
        "one-on-one online video call at home. Only a single blurred person is visible "
        "on the laptop screen, no grid of many faces. Relaxed consultation mood."
    ),
    "setup": (
        "A pretty Japanese woman in her mid twenties with a black shoulder-length bob "
        "and a cream knit sweater sits at a tidy white desk in a bright cozy room. "
        "In front of her an ordinary smartphone is correctly mounted vertically in a "
        "small black smartphone tripod, screen facing her, and a simple white ring light "
        "on a slim stand glows at the side. A small potted plant and a mug are on the desk. "
        "She smiles gently toward the phone with her hands resting naturally on the desk."
    ),
    "agency-mechanism": (
        "An over-the-shoulder view of a pretty Japanese woman in her twenties with a "
        "black shoulder-length bob, sitting side-on at a wooden desk by a bright window "
        "with a small potted plant, typing on an open laptop. "
        "Both hands rest naturally on the laptop keyboard with all fingers correctly "
        "formed, calm focused gentle expression, soft natural daylight, cozy home office."
    ),
    "agency-setup": (
        "A pretty Japanese woman in her late twenties with dark brown medium-long hair "
        "and a cream knit sweater sits at a minimal tidy home desk with only a laptop "
        "on it, resting one hand on the laptop and the other hand relaxed on the desk. "
        "She looks toward the camera with a calm, natural, gentle closed-mouth smile and "
        "relaxed friendly eyes, not wide open, not staring. A small potted plant is "
        "beside her. Warm cozy morning light, candid everyday photo, not a posed portrait."
    ),
    "agency-hero": (
        "A pretty Japanese woman in her late twenties with natural makeup and dark brown "
        "medium-long hair, wearing a cozy cream knit sweater with a soft beige cardigan, "
        "sits at a bright tidy home desk with an open notebook and a smartphone in front of her. "
        "She looks toward the camera with a warm, natural, gentle smile and relaxed friendly eyes "
        "that are softly narrowed from smiling, not wide open, not staring, not an intense gaze. "
        "Her head is tilted slightly, calm approachable everyday expression, like a genuine "
        "candid photo of a friendly person, not a posed studio portrait. Warm morning light."
    ),
}


def generate(api_key: str, prompt: str) -> Image.Image:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=f"{prompt}\n\n{STYLE}",
        config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
    )
    for part in resp.candidates[0].content.parts:
        if part.inline_data is not None:
            return Image.open(BytesIO(part.inline_data.data)).convert("RGB")
    raise RuntimeError("画像データが返ってきませんでした")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=str, help="カンマ区切りで対象カットを指定")
    ap.add_argument("--out", type=str, help="出力先ディレクトリ（検品用）")
    ap.add_argument("--suffix", type=str, default="", help="ファイル名末尾（候補の引き直し用）")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY が未設定です")

    out_dir = Path(args.out) if args.out else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = [t.strip() for t in args.only.split(",")] if args.only else list(CUTS)
    for name in targets:
        if name not in CUTS:
            print(f"⚠️ 未定義のカット: {name}")
            continue
        print(f"▶ {name}")
        img = generate(api_key, CUTS[name])
        img.thumbnail((900, 900), Image.LANCZOS)
        path = out_dir / f"{name}{args.suffix}.jpg"
        img.save(path, "JPEG", quality=86, optimize=True, progressive=True)
        print(f"  ✅ {path} ({path.stat().st_size // 1024}KB)")


if __name__ == "__main__":
    main()
