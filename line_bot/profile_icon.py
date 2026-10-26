"""
公式LINEのプロフィール画像ジェネレーター（640x640px / LINE公式アカウント推奨サイズ）

ロゴは lp/shared/logo.jpg が正本。LINEのアイコンは丸く切り抜かれるため、
そのままアップすると「TAITAN PRO」の両端（T・O）が欠けて別の綴りに見える。
ここではロゴの外周を引き延ばして地を広げ、円の内側に文字まで収める。

使い方:
    python3 profile_icon.py     # assets/line_profile_icon.jpg を生成

生成した画像は LINE Official Account Manager の「プロフィール画像」に手動でアップする。
"""

import os

import numpy as np
from PIL import Image, ImageFilter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "lp", "shared", "logo.jpg"))
OUT_PATH = os.path.join(BASE_DIR, "assets", "line_profile_icon.jpg")

SIZE = 640
CANVAS = 1640           # ロゴ描画域の対角線が円に収まる一辺
CENTER = (651, 686)     # logo.jpg 上のハート＋文字の描画域の中心


def build(out_path=OUT_PATH):
    logo = np.asarray(Image.open(LOGO_PATH).convert("RGB"))
    h, w, _ = logo.shape
    ox, oy = CANVAS // 2 - CENTER[0], CANVAS // 2 - CENTER[1]
    # 外周1pxを外へ引き延ばし、ぼかした地とロゴの境目をなじませる
    edge = np.pad(logo, ((oy, CANVAS - h - oy), (ox, CANVAS - w - ox), (0, 0)), mode="edge")
    soft = np.asarray(Image.fromarray(edge).filter(ImageFilter.GaussianBlur(40)))
    mask = np.zeros((CANVAS, CANVAS), np.uint8)
    mask[oy:oy + h, ox:ox + w] = 255
    mask = np.asarray(Image.fromarray(mask).filter(ImageFilter.GaussianBlur(25)))[..., None] / 255.0
    img = (edge * mask + soft * (1 - mask)).astype(np.uint8)
    Image.fromarray(img).resize((SIZE, SIZE), Image.LANCZOS).save(out_path, quality=95)
    return out_path


if __name__ == "__main__":
    print(f"生成: {build()}")
