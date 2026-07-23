"""
step1_transcribe.py
===================
動画から音声を抽出し、単語単位のタイムスタンプ付き文字起こしを生成する。

Backends:
  - "local" (default): faster-whisper (CTranslate2) をローカル実行
  - "api"            : OpenAI Whisper API (whisper-1) を呼び出し

Output:
  temp/transcription.json
  {
    "source": "inputs/xxx.mp4",
    "duration": float,
    "language": "ja",
    "backend": "local|api",
    "model": "large-v3",
    "segments": [{"start": float, "end": float, "word": str}, ...]
  }

Usage:
  python step1_transcribe.py inputs/source.mp4
  python step1_transcribe.py inputs/source.mp4 --backend local --model large-v3
  python step1_transcribe.py inputs/source.mp4 --backend api
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from loguru import logger

BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}")
logger.add(LOG_DIR / "step1_{time:YYYYMMDD}.log", level="DEBUG", rotation="10 MB", retention="7 days")


@dataclass
class WordSegment:
    start: float
    end: float
    word: str


@dataclass
class TranscriptionResult:
    source: str
    duration: float
    language: str
    backend: str
    model: str
    segments: List[WordSegment]

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ----------------------------------------------------------------------
# 音声抽出 (FFmpeg)
# ----------------------------------------------------------------------
def extract_audio(video_path: Path) -> Path:
    """動画から 16kHz mono WAV を一時ファイルに抽出する。"""
    if not video_path.exists():
        raise FileNotFoundError(f"入力動画が見つかりません: {video_path}")

    tmp_wav = Path(tempfile.mkstemp(suffix=".wav", prefix="step1_audio_")[1])
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(video_path),
        "-ac", "1",           # mono
        "-ar", "16000",        # 16kHz (Whisperの要求)
        "-vn",                  # 音声のみ
        str(tmp_wav),
    ]
    logger.debug(f"FFmpeg: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise RuntimeError("FFmpegが見つかりません。`brew install ffmpeg` でインストールしてください。") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg音声抽出に失敗: {e.stderr}") from e

    if not tmp_wav.exists() or tmp_wav.stat().st_size == 0:
        raise RuntimeError("FFmpegで抽出した音声ファイルが空です。")

    logger.info(f"音声抽出完了: {tmp_wav} ({tmp_wav.stat().st_size/1024:.1f} KB)")
    return tmp_wav


def probe_duration(video_path: Path) -> float:
    """ffprobeで動画の長さを秒で返す。"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()
        return float(out)
    except Exception as e:
        logger.warning(f"ffprobe 失敗、durationを0で継続: {e}")
        return 0.0


# ----------------------------------------------------------------------
# Backend: ローカル faster-whisper
# ----------------------------------------------------------------------
def transcribe_local(audio_path: Path, model_size: str, language: Optional[str]) -> tuple[List[WordSegment], str, float]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError("faster-whisper が未インストールです: pip install faster-whisper") from e

    logger.info(f"faster-whisper モデルをロード中: {model_size}")
    # compute_type="int8" はCPU向けで最速。GPUなら "float16"。
    compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
    device = os.environ.get("WHISPER_DEVICE", "cpu")
    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as e:
        raise RuntimeError(f"Whisperモデルロード失敗 ({model_size}/{device}/{compute_type}): {e}") from e

    logger.info("文字起こし開始（VAD filter ON, word_timestamps=True）")
    segments_gen, info = model.transcribe(
        str(audio_path),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
    )

    words: List[WordSegment] = []
    for seg in segments_gen:
        if seg.words is None:
            # word_timestampsが効かない場合のフォールバック：segment全体を1つのwordとして登録
            words.append(WordSegment(start=float(seg.start), end=float(seg.end), word=seg.text.strip()))
            continue
        for w in seg.words:
            if w.word is None:
                continue
            word_text = w.word.strip()
            if not word_text:
                continue
            words.append(WordSegment(start=float(w.start), end=float(w.end), word=word_text))

    detected_lang = info.language if info and info.language else (language or "unknown")
    duration = float(info.duration) if info and info.duration else 0.0
    logger.info(f"文字起こし完了: {len(words)}語 / 検出言語={detected_lang} / 音声長={duration:.2f}s")
    return words, detected_lang, duration


# ----------------------------------------------------------------------
# Backend: OpenAI Whisper API
# ----------------------------------------------------------------------
def transcribe_api(audio_path: Path, language: Optional[str]) -> tuple[List[WordSegment], str, float]:
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai が未インストールです: pip install openai") from e

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY が未設定です。")

    client = OpenAI(api_key=api_key)
    logger.info("OpenAI Whisper API 呼び出し中...")
    try:
        with open(audio_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["word"],
                language=language,
            )
    except Exception as e:
        raise RuntimeError(f"Whisper API呼び出し失敗: {e}") from e

    # resp.words: list of {"word": str, "start": float, "end": float}
    words: List[WordSegment] = []
    raw_words = getattr(resp, "words", None) or resp.model_dump().get("words", [])
    for w in raw_words:
        if isinstance(w, dict):
            words.append(WordSegment(start=float(w["start"]), end=float(w["end"]), word=w["word"].strip()))
        else:
            words.append(WordSegment(start=float(w.start), end=float(w.end), word=w.word.strip()))

    detected_lang = getattr(resp, "language", None) or (language or "unknown")
    duration = float(getattr(resp, "duration", 0.0) or 0.0)
    logger.info(f"API文字起こし完了: {len(words)}語 / 言語={detected_lang} / 長さ={duration:.2f}s")
    return words, detected_lang, duration


# ----------------------------------------------------------------------
# メイン
# ----------------------------------------------------------------------
def run(video_path: Path, backend: str, model_size: str, language: Optional[str], output: Path) -> Path:
    if not video_path.exists():
        raise FileNotFoundError(f"入力ファイルがありません: {video_path}")

    duration_probe = probe_duration(video_path)
    logger.info(f"入力動画: {video_path}  長さ={duration_probe:.2f}s")

    wav_path = extract_audio(video_path)
    try:
        if backend == "local":
            words, lang, duration = transcribe_local(wav_path, model_size, language)
            used_model = model_size
        elif backend == "api":
            words, lang, duration = transcribe_api(wav_path, language)
            used_model = "whisper-1"
        else:
            raise ValueError(f"未知のbackend: {backend}")
    finally:
        try:
            wav_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"一時WAV削除失敗: {e}")

    if not words:
        raise RuntimeError("文字起こし結果が0語でした。音声に発話が含まれているか確認してください。")

    result = TranscriptionResult(
        source=str(video_path),
        duration=duration or duration_probe,
        language=lang,
        backend=backend,
        model=used_model,
        segments=words,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
    logger.success(f"出力: {output}  ({len(words)}語)")
    return output


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="step1: 動画から単語単位の文字起こしJSONを生成")
    p.add_argument("input", type=Path, help="入力動画 (mp4 等)")
    p.add_argument("--backend", choices=["local", "api"], default="local", help="Whisperバックエンド")
    p.add_argument("--model", default=os.environ.get("WHISPER_MODEL", "large-v3"), help="localモデルサイズ (tiny/base/small/medium/large-v3)")
    p.add_argument("--language", default=None, help="言語コード (ja/en 等)。未指定なら自動判定")
    p.add_argument("--output", type=Path, default=TEMP_DIR / "transcription.json", help="出力JSONパス")
    return p.parse_args()


def main() -> int:
    load_dotenv(BASE_DIR / ".env")
    args = parse_args()
    try:
        run(args.input, args.backend, args.model, args.language, args.output)
        return 0
    except Exception as e:
        logger.exception(f"step1 失敗: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
