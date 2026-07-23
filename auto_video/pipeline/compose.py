"""MoviePy コンポーザ: ビート列 → 1080x1920 mp4."""
from __future__ import annotations
from pathlib import Path
from typing import List, Dict

import numpy as np
from moviepy import (
    AudioFileClip, VideoClip, CompositeVideoClip, CompositeAudioClip,
    concatenate_videoclips, afx,
)

from ..config import WIDTH, HEIGHT, FPS, BGM_PATH, SE_DIR
from .visual import render_beat_frame


def _beat_clip(beat: Dict, duration: float, time_offset: float, total_duration: float) -> VideoClip:
    """1ビート分の VideoClip を返す (音声なし)."""
    role = beat.get("role", "payoff")
    caption = beat.get("caption", "")
    emphasis = beat.get("emphasis", []) or []
    emph_color = beat.get("emphasis_color", "yellow")
    big_num = beat.get("big_number")
    hint = beat.get("visual_hint", "static")

    def make_frame(t: float) -> np.ndarray:
        progress = (time_offset + t) / max(0.01, total_duration)
        return render_beat_frame(
            caption=caption,
            emphasis=emphasis,
            emph_color_name=emph_color,
            big_number=big_num,
            visual_hint=hint,
            progress=progress,
            beat_t=t,
            beat_dur=duration,
            role=role,
        )

    return VideoClip(make_frame, duration=duration)


def compose_video(
    beats_with_audio: List[Dict],
    out_path: Path,
    bgm_path: Path = BGM_PATH,
    bgm_volume: float = 0.12,
) -> Path:
    """beats_with_audio: [{beat, mp3_path, duration}, ...]
    各 mp3 を voiceover、背景に BGM を敷いて 1本の mp4 を書き出す.
    """
    total_dur = sum(b["duration"] for b in beats_with_audio)
    video_clips = []
    audio_clips = []
    cursor = 0.0

    for item in beats_with_audio:
        beat = item["beat"]
        dur = float(item["duration"])       # 映像の長さ (ナレーション + 余白)
        mp3 = item["mp3_path"]
        vc = _beat_clip(beat, dur, cursor, total_dur)
        video_clips.append(vc)

        # voiceover: mp3 の自然長で再生 (with_duration で延ばさない)
        a = AudioFileClip(str(mp3)).with_start(cursor)
        audio_clips.append(a)

        # SE
        sfx_name = beat.get("sfx")
        if sfx_name:
            se_file = SE_DIR / f"{sfx_name}.mp3"
            if se_file.exists():
                se = (AudioFileClip(str(se_file))
                      .with_start(cursor)
                      .with_effects([afx.MultiplyVolume(0.7)]))
                if se.duration > dur:
                    se = se.with_effects([afx.AudioFadeOut(0.3)])
                    se = se.subclipped(0, min(se.duration, dur))
                audio_clips.append(se)

        cursor += dur

    video = concatenate_videoclips(video_clips, method="chain")

    # BGM ループ + ダッキング (bgm 自体の長さ以下に切って並べる)
    if bgm_path and Path(bgm_path).exists():
        bgm_src = AudioFileClip(str(bgm_path))
        t = 0.0
        while t < total_dur:
            remain = total_dur - t
            chunk = bgm_src.subclipped(0, min(bgm_src.duration, remain))
            chunk = chunk.with_start(t).with_effects(
                [afx.MultiplyVolume(bgm_volume)]
            )
            audio_clips.append(chunk)
            t += bgm_src.duration

    composite_audio = CompositeAudioClip(audio_clips)
    video = video.with_audio(composite_audio)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    video.write_videofile(
        str(out_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        bitrate="6000k",
        threads=4,
        logger=None,
    )

    # クリーンアップ
    for a in audio_clips:
        try:
            a.close()
        except Exception:
            pass
    try:
        video.close()
    except Exception:
        pass

    return out_path
