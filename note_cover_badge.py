#!/usr/bin/env python3
"""note_cover_badge.py — Noteカバー下部バッジ（「所属◯名のライバー事務所」）の文言照合

背景（2026-10-09）:
  カバーPNGには確定ファクトの所属数が**画像として焼き込まれている**。
  2026-10-02 に所属数を 200名→300名へ更新したとき、note_cover_make.py の文字列は
  直したが、それまでに作ったカバー（公開51本＋未投稿在庫19本）は「所属200名」のまま
  公開され続けていた。content_facts_guard / note_live_facts_guard はテキストしか見ないので、
  画像の中の旧ファクトはどの番犬にも引っかからなかった。

仕組み:
  note_cover_make.py はカバーを作るたびに、バッジ2行（「TAITAN PRO」と事務所名）を
  無地の上に描いた「基準」を data/note_cover_badge_ref.json に書き出す
  （1文字ごとの位置＋文字マスク）。照合側はカバー画像の同じ位置から同じ色の画素を拾い、
  **1文字ずつ** 基準と重なり具合（IoU）を比べる。
    - 「TAITAN PRO」行が基準と重ならない → バッジなし（旧イラストカバー）＝対象外
    - バッジはあるのに事務所名行のどれか1文字が基準とずれる → 文言が古い（stale）
  行全体で比べると「200」と「300」は数字1文字しか違わず差が埋もれる（実測で IoU 差0.02）。
  1文字単位なら、旧200名の公開画像は「2」の文字で最大0.58、正しい公開画像は全文字0.9以上
  （ローカルPNGは1.0）、バッジなしは「TAITAN PRO」行が0.35以下と、はっきり分かれる。

  CI（Ubuntu）にはカバーのフォント（ヒラギノ）が無く基準を描けないので、基準はmacで
  note_cover_make.py を走らせたときに作ってコミットする。照合は Pillow だけで動く。
  基準の文言が facts_patterns.NOTE_COVER_BADGE と食い違っていたら、照合結果ではなく
  「基準が古い」として赤にする（note_cover_guard.py）。
"""
import json
import os

from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REF_PATH = os.path.join(BASE_DIR, "data", "note_cover_badge_ref.json")

COLOR_TOL = 120       # 文字色からの距離（RGB各差の合計）
# note は eyecatch を256色パレットに減色して配信する。60 だと細い「ー」の縁が落ちて
# 正しい画像でも0.69まで下がった（差し替え済み16本の実測）。120 で正しい画像は0.90以上、
# 旧「所属200名」は0.58以下。
PRESENT_MIN = 0.7     # 「TAITAN PRO」行の文字IoU中央値がこれ以上ならバッジあり
STALE_BELOW = 0.75    # 事務所名行で1文字でもこれ未満なら文言が古い


def _mask(img, box, color):
    """box 内で color に近い画素を 1 にした行優先のビット列（list[bool]）。"""
    x0, y0, x1, y1 = box
    px = img.crop(box).getdata()
    r, g, b = color
    return [abs(p[0] - r) + abs(p[1] - g) + abs(p[2] - b) < COLOR_TOL for p in px], x1 - x0


def _pack(bits):
    n = 0
    for i, v in enumerate(bits):
        if v:
            n |= 1 << i
    return format(n, "x")


def _unpack(hexstr, length):
    n = int(hexstr, 16)
    return [bool((n >> i) & 1) for i in range(length)]


def build_ref(canvas, lines, size):
    """note_cover_make から呼ぶ。lines = [(name, text, (x, y), font, color), ...]
    canvas は無地の上に lines だけを描いたもの。"""
    out = {"size": list(size), "lines": []}
    for name, text, (x, y), fnt, color in lines:
        x0, y0, x1, y1 = fnt.getbbox(text, stroke_width=4)
        box = (int(x + x0), int(y + y0), int(x + x1) + 1, int(y + y1) + 1)
        bits, _ = _mask(canvas, box, color)
        chars = []
        for i, ch in enumerate(text):
            cx0 = int(x + fnt.getlength(text[:i])) - box[0]
            cx1 = int(x + fnt.getlength(text[:i + 1])) - box[0]
            chars.append([ch, max(cx0, 0), min(cx1, box[2] - box[0])])
        out["lines"].append({"name": name, "text": text, "color": list(color),
                             "box": list(box), "chars": chars, "mask": _pack(bits)})
    return out


def write_ref(ref):
    os.makedirs(os.path.dirname(REF_PATH), exist_ok=True)
    with open(REF_PATH, "w", encoding="utf-8") as f:
        json.dump(ref, f, ensure_ascii=False, indent=1)
        f.write("\n")


def load_ref():
    with open(REF_PATH, encoding="utf-8") as f:
        return json.load(f)


def badge_text(ref):
    return next(l["text"] for l in ref["lines"] if l["name"] == "badge")


def _char_ious(img, line):
    box = tuple(line["box"])
    w, h = box[2] - box[0], box[3] - box[1]
    ref_bits = _unpack(line["mask"], w * h)
    img_bits, _ = _mask(img, box, tuple(line["color"]))
    res = []
    for ch, cx0, cx1 in line["chars"]:
        inter = union = 0
        for yy in range(h):
            base = yy * w
            for xx in range(cx0, cx1):
                a, b = ref_bits[base + xx], img_bits[base + xx]
                inter += a and b
                union += a or b
        res.append((ch, inter / union if union else 1.0))
    return res


def inspect(img, ref):
    """カバー画像を照合して {"state": "none"|"ok"|"stale", ...} を返す。"""
    img = img.convert("RGB")
    size = tuple(ref["size"])
    if img.size != size:
        img = img.resize(size)
    lines = {l["name"]: l for l in ref["lines"]}
    title = sorted(v for _, v in _char_ious(img, lines["title"]))
    median = title[len(title) // 2]
    if median < PRESENT_MIN:
        return {"state": "none", "title_median": round(median, 3)}
    badge = _char_ious(img, lines["badge"])
    worst_ch, worst = min(badge, key=lambda t: t[1])
    state = "stale" if worst < STALE_BELOW else "ok"
    return {"state": state, "title_median": round(median, 3),
            "worst_char": worst_ch, "worst_iou": round(worst, 3)}


def inspect_path(path, ref):
    with Image.open(path) as im:
        return inspect(im, ref)
