"""auto_video オーケストレータ: topic → mp4.

使い方:
  python3 -m auto_video.make --topic "ライバー月収のリアル格差"
  python3 -m auto_video.make --topic "..." --voice narrator_m --no-cache
  python3 -m auto_video.make --yaml auto_video/topics.yaml --count 3
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path

import yaml

from .config import OUTPUT_DIR, BGM_PATH, MODEL
from .pipeline.script import generate_script
from .pipeline.voice import synthesize
from .pipeline.compose import compose_video


def _slugify(name: str) -> str:
    name = re.sub(r"[\s/\\:\*\?\"<>\|]", "_", name).strip("_")
    return name[:60]


def make_one(
    topic: str,
    angle: str = "",
    audience: str = "スマホ副業を探す20代女性",
    target_sec: int = 26,
    voice_override: str | None = None,
    use_cache: bool = True,
    model: str = MODEL,
    out_dir: Path = OUTPUT_DIR,
    verbose: bool = True,
) -> dict:
    """1トピック → mp4. 戻り値: {mp4, script, duration_sec, ...}"""
    t0 = time.time()
    if verbose:
        print(f"━━━ {topic} ━━━")
        print(f"  [1/3] Claude でスクリプト生成 (model={model})…")

    script = generate_script(
        topic=topic, angle=angle, audience=audience,
        target_sec=target_sec, use_cache=use_cache, model=model,
    )

    if verbose:
        u = script.get("_usage", {})
        print(f"        beats={len(script['beats'])} title={script.get('title','')[:30]}")
        print(f"        tokens: in={u.get('input_tokens',0)} out={u.get('output_tokens',0)}"
              f" cache_read={u.get('cache_read_input_tokens',0)}")
        print(f"  [2/3] Edge-TTS 合成 ({len(script['beats'])} beats)…")

    beats_with_audio = []
    for i, beat in enumerate(script["beats"], 1):
        voice_key = voice_override or beat.get("voice", "narrator_f")
        narration = beat.get("narration", "").strip()
        if not narration:
            narration = beat.get("caption", "").replace("\n", " ")
        mp3, _cues, dur = synthesize(narration, voice_key=voice_key,
                                     use_cache=use_cache)
        # 視聴体感: 発声直後に余白 0.35s 追加（読ませる時間）
        pad = 0.35 if beat.get("role") in ("hook", "payoff", "turn") else 0.20
        total = dur + pad
        beats_with_audio.append({
            "beat": beat, "mp3_path": mp3, "duration": total,
        })
        if verbose:
            print(f"    ({i:>2}/{len(script['beats'])}) [{beat['role']:>10}]"
                  f" {dur:4.1f}s+{pad:.2f} | {beat.get('caption','')[:18]}")

    total_dur = sum(b["duration"] for b in beats_with_audio)
    slug = _slugify(script.get("title", topic))
    out_mp4 = out_dir / f"{slug}.mp4"

    if verbose:
        print(f"  [3/3] 合成: {total_dur:.1f}s → {out_mp4.name}")

    compose_video(beats_with_audio, out_mp4, bgm_path=BGM_PATH)

    meta = {
        "topic": topic,
        "angle": angle,
        "title": script.get("title"),
        "caption": script.get("caption"),
        "hashtags": script.get("hashtags"),
        "thumbnail_text": script.get("thumbnail_text"),
        "duration_sec": round(total_dur, 2),
        "beats": len(script["beats"]),
        "mp4": str(out_mp4),
        "elapsed_sec": round(time.time() - t0, 1),
        "model": script.get("_model"),
        "usage": script.get("_usage"),
    }
    (out_mp4.with_suffix(".json")).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    if verbose:
        print(f"  ✅ {out_mp4} ({meta['duration_sec']}s / {meta['elapsed_sec']}s)")
    return meta


def main():
    p = argparse.ArgumentParser(description="auto_video: topic→mp4 pipeline")
    p.add_argument("--topic", type=str, help="単発トピック")
    p.add_argument("--angle", type=str, default="", help="切り口ヒント")
    p.add_argument("--audience", type=str, default="スマホ副業を探す20代女性")
    p.add_argument("--sec", type=int, default=26, help="目標尺")
    p.add_argument("--voice", type=str, default=None,
                   help="narrator_f | narrator_m | young_f | mature_f")
    p.add_argument("--model", type=str, default=MODEL)
    p.add_argument("--yaml", type=str, help="トピックリスト YAML")
    p.add_argument("--count", type=int, default=0, help="YAMLから先頭N件")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--out", type=str, default=str(OUTPUT_DIR))
    args = p.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    use_cache = not args.no_cache

    tasks = []
    if args.topic:
        tasks.append({"topic": args.topic, "angle": args.angle,
                      "audience": args.audience})
    elif args.yaml:
        data = yaml.safe_load(Path(args.yaml).read_text(encoding="utf-8"))
        items = data.get("topics", data) if isinstance(data, dict) else data
        tasks = items[: args.count or len(items)]
    else:
        print("--topic か --yaml を指定してください", file=sys.stderr)
        sys.exit(2)

    results = []
    for t in tasks:
        try:
            meta = make_one(
                topic=t["topic"],
                angle=t.get("angle", ""),
                audience=t.get("audience", args.audience),
                target_sec=t.get("sec", args.sec),
                voice_override=args.voice,
                use_cache=use_cache,
                model=args.model,
                out_dir=out_dir,
            )
            results.append(meta)
        except Exception as e:
            traceback.print_exc()
            print(f"❌ failed: {t} — {e}", file=sys.stderr)

    print(f"\n=== 完了 {len(results)}/{len(tasks)} ===")
    for r in results:
        print(f" • {r['title']} ({r['duration_sec']}s)  → {r['mp4']}")


if __name__ == "__main__":
    main()
