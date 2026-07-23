"""
batch_run.py
============
ディレクトリ内のmp4をまとめてパイプライン処理する量産ラッパー。

各動画ごとに temp/ と outputs/ をサブフォルダに分離し、
失敗しても次の動画は継続する（--stop-on-error で即中断に切替可能）。

処理結果はサマリJSONとして outputs/batch_summary_YYYYMMDD_HHMMSS.json に記録。

Usage:
  python batch_run.py --input-dir ../shorts/videos
  python batch_run.py --input-dir ../shorts/videos --no-llm --whisper-model small
  python batch_run.py --input-dir ../shorts/videos --provider anthropic --model claude-opus-4-7
  python batch_run.py --files vid1.mp4 vid2.mp4
  python batch_run.py --input-dir ../shorts/videos --parallel 2   # 2並列
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from loguru import logger

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
TEMP_DIR = BASE_DIR / "temp"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}")
logger.add(LOG_DIR / "batch_{time:YYYYMMDD}.log", level="DEBUG", rotation="10 MB", retention="7 days")


@dataclass
class JobResult:
    input: str
    output: Optional[str] = None
    transcription: Optional[str] = None
    edit_plan: Optional[str] = None
    status: str = "pending"       # pending|success|failed
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    elapsed_sec: float = 0.0
    stage_failed: Optional[str] = None  # step1|step2|step3


def collect_inputs(input_dir: Optional[Path], explicit_files: List[Path]) -> List[Path]:
    files: List[Path] = []
    if input_dir:
        for ext in ("*.mp4", "*.mov", "*.m4v", "*.mkv"):
            files.extend(sorted(input_dir.glob(ext)))
    for f in explicit_files:
        if f.exists():
            files.append(f)
        else:
            logger.warning(f"指定ファイルが存在しません: {f}")
    # 重複除去
    seen = set()
    uniq: List[Path] = []
    for f in files:
        r = f.resolve()
        if r not in seen:
            seen.add(r)
            uniq.append(f)
    return uniq


def slugify(name: str) -> str:
    # 日本語名そのままで扱うが、パス区切り/空白を置換
    return (
        name.replace("/", "_")
        .replace("\\", "_")
        .replace(" ", "_")
        .strip()
    )


def run_single(
    video: Path,
    backend: str,
    whisper_model: str,
    language: Optional[str],
    provider: str,
    model: str,
    no_llm: bool,
    font: Optional[Path],
    font_size: int,
    legacy_step2: bool = False,
    no_critic: bool = False,
    no_se: bool = False,
    no_broll: bool = False,
    bgm: Optional[Path] = None,
) -> JobResult:
    stem = slugify(video.stem)
    job_dir = OUTPUT_DIR / stem
    job_dir.mkdir(exist_ok=True)
    transcription_json = job_dir / "transcription.json"
    edit_plan_json = job_dir / "edit_plan.json"
    final_mp4 = job_dir / "final.mp4"
    py = sys.executable

    result = JobResult(input=str(video), started_at=datetime.now().isoformat())
    t0 = time.time()

    try:
        # step1
        cmd1 = [py, str(BASE_DIR / "step1_transcribe.py"),
                str(video),
                "--backend", backend,
                "--model", whisper_model,
                "--output", str(transcription_json)]
        if language:
            cmd1 += ["--language", language]
        logger.info(f"[{stem}] step1 開始")
        r1 = subprocess.run(cmd1, capture_output=True, text=True)
        if r1.returncode != 0:
            result.stage_failed = "step1"
            raise RuntimeError(f"step1失敗: {r1.stderr[-500:] if r1.stderr else 'unknown'}")
        result.transcription = str(transcription_json)

        # step2 (director or legacy)
        step2_script = "step2_logic_engine.py" if legacy_step2 else "step2_director.py"
        cmd2 = [py, str(BASE_DIR / step2_script),
                "--input", str(transcription_json),
                "--output", str(edit_plan_json),
                "--provider", provider,
                "--model", model]
        if no_llm:
            cmd2.append("--no-llm")
        if not legacy_step2:
            if no_critic:
                cmd2.append("--no-critic")
            if no_se:
                cmd2.append("--no-se")
            if no_broll:
                cmd2.append("--no-broll")
            if bgm:
                cmd2 += ["--bgm", str(bgm)]
        logger.info(f"[{stem}] step2 開始")
        r2 = subprocess.run(cmd2, capture_output=True, text=True)
        if r2.returncode != 0:
            result.stage_failed = "step2"
            raise RuntimeError(f"step2失敗: {r2.stderr[-500:] if r2.stderr else 'unknown'}")
        result.edit_plan = str(edit_plan_json)

        # step3
        cmd3 = [py, str(BASE_DIR / "step3_renderer.py"),
                "--input", str(edit_plan_json),
                "--output", str(final_mp4),
                "--font-size", str(font_size)]
        if font:
            cmd3 += ["--font", str(font)]
        logger.info(f"[{stem}] step3 開始")
        r3 = subprocess.run(cmd3, capture_output=True, text=True)
        if r3.returncode != 0:
            result.stage_failed = "step3"
            raise RuntimeError(f"step3失敗: {r3.stderr[-500:] if r3.stderr else 'unknown'}")
        result.output = str(final_mp4)
        result.status = "success"
        logger.success(f"[{stem}] 完了 → {final_mp4}")
    except Exception as e:
        result.status = "failed"
        result.error = str(e)[:800]
        logger.error(f"[{stem}] 失敗 ({result.stage_failed}): {e}")
    finally:
        result.finished_at = datetime.now().isoformat()
        result.elapsed_sec = round(time.time() - t0, 2)

    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="batch_run: 複数mp4をまとめて処理")
    ap.add_argument("--input-dir", type=Path, default=None, help="mp4を含むディレクトリ")
    ap.add_argument("--files", type=Path, nargs="*", default=[], help="個別指定ファイル")
    ap.add_argument("--backend", choices=["local", "api"], default="local")
    ap.add_argument("--whisper-model", default="large-v3")
    ap.add_argument("--language", default="ja")
    ap.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    ap.add_argument("--model", default="claude-opus-4-7")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--font", type=Path, default=None)
    ap.add_argument("--font-size", type=int, default=72)
    ap.add_argument("--parallel", type=int, default=1, help="同時実行数（GPU/メモリに注意）")
    ap.add_argument("--stop-on-error", action="store_true", help="失敗で全体中断")
    ap.add_argument("--legacy-step2", action="store_true", help="旧 step2_logic_engine.py を使う")
    ap.add_argument("--no-critic", action="store_true", help="director: Criticループスキップ")
    ap.add_argument("--no-se", action="store_true", help="director: SE合成無効")
    ap.add_argument("--no-broll", action="store_true", help="director: B-roll無効")
    ap.add_argument("--bgm", type=Path, default=None, help="BGM音源パス")
    args = ap.parse_args()

    videos = collect_inputs(args.input_dir, args.files)
    if not videos:
        logger.error("処理対象の動画が見つかりません。--input-dir か --files を指定してください。")
        return 1

    logger.info(f"処理対象: {len(videos)}件 / 並列数={args.parallel}")
    for i, v in enumerate(videos, 1):
        logger.info(f"  [{i}] {v}")

    results: List[JobResult] = []

    def _run(v: Path) -> JobResult:
        return run_single(
            v, args.backend, args.whisper_model, args.language,
            args.provider, args.model, args.no_llm, args.font, args.font_size,
            legacy_step2=args.legacy_step2,
            no_critic=args.no_critic,
            no_se=args.no_se,
            no_broll=args.no_broll,
            bgm=args.bgm,
        )

    if args.parallel <= 1:
        for v in videos:
            r = _run(v)
            results.append(r)
            if args.stop_on_error and r.status == "failed":
                logger.error("stop-on-error: 以降を中断")
                break
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as ex:
            futures = {ex.submit(_run, v): v for v in videos}
            for fut in concurrent.futures.as_completed(futures):
                r = fut.result()
                results.append(r)
                if args.stop_on_error and r.status == "failed":
                    logger.error("stop-on-error: 残りジョブをキャンセル")
                    for f in futures:
                        f.cancel()
                    break

    # サマリ
    success = sum(1 for r in results if r.status == "success")
    failed = sum(1 for r in results if r.status == "failed")
    total_elapsed = sum(r.elapsed_sec for r in results)
    summary = {
        "generated_at": datetime.now().isoformat(),
        "total": len(results),
        "success": success,
        "failed": failed,
        "total_elapsed_sec": round(total_elapsed, 2),
        "params": {
            "backend": args.backend, "whisper_model": args.whisper_model,
            "provider": args.provider, "model": args.model, "no_llm": args.no_llm,
            "parallel": args.parallel,
        },
        "jobs": [asdict(r) for r in results],
    }
    summary_path = OUTPUT_DIR / f"batch_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.success(f"★ バッチ完了: 成功{success} / 失敗{failed} / 計{len(results)} / {total_elapsed:.1f}s")
    logger.info(f"サマリ: {summary_path}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
