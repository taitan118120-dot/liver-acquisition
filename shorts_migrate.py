#!/usr/bin/env python3
"""
shorts_migrate.py — 旧 CapCut JSON → tzunda-v1 スキーマ移行
==========================================================
- 旧スキーマ: speaker 任意 / bg_color / color / 中央ボックス字幕前提
- 新スキーマ: speaker 必須(zunda|metan) / side / emphasis / bg_preset /
             is_end_card / style_version:"tzunda-v1"

使い方:
  python3 shorts_migrate.py shorts/capcut/*.json           # 上書き
  python3 shorts_migrate.py --dry-run shorts/capcut/*.json # 変更点だけ表示
"""

from __future__ import annotations
import argparse
import json
import os
import re
import sys
import glob

TYPE_TO_BG = {
    "hook":    "gradient_pink",
    "number":  "navy",
    "compare": "gradient_cool",
    "cta":     "cta_pink",
    "point":   "navy",
    "dialogue":"navy",
}

SPEAKER_MAP = {
    "zundamon": "zunda",
    "zunda":    "zunda",
    "metan":    "metan",
    "metan_ama":"metan",
    "zundamon_ama":   "zunda",
    "zundamon_tsun":  "zunda",
    "zundamon_sexy":  "zunda",
}

SIDE_DEFAULT = {"zunda": "left", "metan": "right"}

EMPH_RE = re.compile(r"(第\d+位|\d+[\d,]*(?:万円|円|%|人|時間|ヶ月|倍)|①|②|③|④|⑤)")


def _infer_emphasis(text: str) -> list[str]:
    found = EMPH_RE.findall(text or "")
    # ユニーク化
    seen, out = set(), []
    for f in found:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _infer_speaker(seg: dict, alternation_state: dict) -> str:
    if "speaker" in seg and seg["speaker"]:
        return SPEAKER_MAP.get(seg["speaker"], "zunda")
    # speaker が無いレガシーモノローグ: 交互に割当（hook=zunda スタート, cta=metan）
    if seg.get("type") == "hook":
        alternation_state["last"] = "metan"
        return "zunda"
    if seg.get("type") == "cta":
        return "metan"
    last = alternation_state.get("last", "zunda")
    nxt = "metan" if last == "zunda" else "zunda"
    alternation_state["last"] = nxt
    return nxt


def migrate_one(data: dict) -> dict:
    if data.get("style_version") == "tzunda-v1":
        return data  # すでに最新

    segs_out = []
    state = {"last": "zunda"}
    segs_in = data.get("segments", [])
    n = len(segs_in)
    for i, seg in enumerate(segs_in):
        speaker = _infer_speaker(seg, state)
        side = SIDE_DEFAULT[speaker]
        s_type = seg.get("type", "point")
        is_end = (i == n - 1) and s_type == "cta"
        bg_preset = "cta_pink" if is_end else TYPE_TO_BG.get(s_type, "navy")
        emphasis = _infer_emphasis(seg.get("text", ""))

        new_seg = {
            "text": seg.get("text", ""),
            "start": seg.get("start", 0.0),
            "end": seg.get("end", 0.0),
            "font_size": seg.get("font_size", 72),
            "position": seg.get("position", "center"),
            "type": s_type,
            "speaker": speaker,
            "side": side,
            "emphasis": emphasis,
            "bg_preset": bg_preset,
            "is_end_card": is_end,
            # 旧フィールドも残して互換性保持（読まれなくなる）
            "color": seg.get("color"),
            "bg_color": seg.get("bg_color"),
        }
        segs_out.append(new_seg)

    data["segments"] = segs_out
    data["style_version"] = "tzunda-v1"
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="対象 JSON（glob 可）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # glob 展開（シェルが展開しないケース対応）
    paths = []
    for pat in args.files:
        expanded = glob.glob(pat)
        paths.extend(expanded if expanded else [pat])

    changed = 0
    for p in paths:
        if not os.path.isfile(p):
            print(f"  skip (not file): {p}")
            continue
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        before_ver = data.get("style_version")
        new_data = migrate_one(data)
        after_ver = new_data.get("style_version")

        if before_ver == after_ver:
            print(f"  ✓ unchanged: {p}")
            continue

        changed += 1
        if args.dry_run:
            print(f"  → would migrate: {p}  ({before_ver} → {after_ver})")
        else:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(new_data, f, ensure_ascii=False, indent=2)
            print(f"  ✅ migrated: {p}")

    print(f"\n完了: {changed} 件{' (dry-run)' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
