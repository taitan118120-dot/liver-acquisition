"""Edge-TTS ラッパー: ビート単位で mp3 と word-level timing を返す."""
from __future__ import annotations
import asyncio
import hashlib
from pathlib import Path
from typing import List, Tuple

import edge_tts

from ..config import VOICES, VOICE_TUNING, DEFAULT_VOICE, TTS_RATE, TTS_PITCH, CACHE_DIR


def _audio_cache_path(text: str, voice: str, rate: str, pitch: str) -> Path:
    h = hashlib.sha256(f"{voice}|{rate}|{pitch}|{text}".encode()).hexdigest()[:20]
    return CACHE_DIR / f"tts_{h}.mp3"


async def _synthesize(text: str, voice: str, rate: str, pitch: str, out: Path):
    """mp3 を out に保存 + word-level cue list を返す.

    edge-tts 7.x では SubMaker.feed(chunk) に dict をそのまま渡す。
    cues は (offset_100ns, duration_100ns, word_text) のタプル想定。
    """
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    sm = edge_tts.SubMaker()
    with open(out, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                sm.feed(chunk)

    cues: List[Tuple[float, float, str]] = []
    for c in sm.cues:
        # c は srt.Subtitle: index/start/end/content
        try:
            s = c.start.total_seconds()
            e = c.end.total_seconds()
            t = c.content
            cues.append((s, e, t))
        except Exception:
            pass
    return cues


def synthesize(
    text: str,
    voice_key: str = DEFAULT_VOICE,
    rate: str | None = None,
    pitch: str | None = None,
    use_cache: bool = True,
) -> Tuple[Path, List[Tuple[float, float, str]], float]:
    """戻り値: (mp3 path, word cues, duration_sec)

    voice_key で Nanami/Keita に振り分け、VOICE_TUNING で rate/pitch を調整。
    rate/pitch を明示すれば上書き。
    """
    voice = VOICES.get(voice_key, VOICES[DEFAULT_VOICE])
    tune = VOICE_TUNING.get(voice_key, {"rate": TTS_RATE, "pitch": TTS_PITCH})
    if rate is None:
        rate = tune["rate"]
    if pitch is None:
        pitch = tune["pitch"]
    mp3 = _audio_cache_path(text, voice, rate, pitch)
    cues_cache = mp3.with_suffix(".cues.txt")

    if use_cache and mp3.exists() and cues_cache.exists():
        cues = []
        for line in cues_cache.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                cues.append((float(parts[0]), float(parts[1]), parts[2]))
    else:
        cues = asyncio.run(_synthesize(text, voice, rate, pitch, mp3))
        cues_cache.write_text(
            "\n".join(f"{s:.3f}\t{e:.3f}\t{t}" for s, e, t in cues),
            encoding="utf-8",
        )

    from moviepy import AudioFileClip
    clip = AudioFileClip(str(mp3))
    dur = float(clip.duration)
    clip.close()
    return mp3, cues, dur


if __name__ == "__main__":
    import sys
    text = sys.argv[1] if len(sys.argv) > 1 else "え、ライバーの月収って実はバグってるの？"
    mp3, cues, dur = synthesize(text, use_cache=False)
    print(f"mp3: {mp3}")
    print(f"duration: {dur:.2f}s")
    print(f"cues ({len(cues)}):")
    for s, e, t in cues[:10]:
        print(f"  {s:.2f}-{e:.2f}: {t}")
