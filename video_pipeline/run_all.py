"""
run_all.py
==========
step1 → step2 (director, multi-agent) → step3 を順に実行するオーケストレーター。

step2 は新しいマルチエージェント版 step2_director.py を使用。
旧 step2_logic_engine.py を使いたい場合は --legacy-step2 を指定。

Usage:
  python run_all.py inputs/source.mp4
  python run_all.py inputs/source.mp4 --no-llm                   # 動作確認
  python run_all.py inputs/source.mp4 --bgm ../shorts/bgm/main.mp3
  python run_all.py inputs/source.mp4 --legacy-step2             # 旧step2を使う
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from loguru import logger

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}")
logger.add(LOG_DIR / "run_all_{time:YYYYMMDD}.log", level="DEBUG", rotation="10 MB", retention="7 days")


def run_step(cmd: list[str], label: str) -> None:
    logger.info(f"▶ {label}: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"{label} が非0終了 (code={result.returncode})")
    logger.success(f"✓ {label} 完了")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path, help="入力動画 (mp4等)")
    ap.add_argument("--backend", choices=["local", "api"], default="local")
    ap.add_argument("--whisper-model", default="large-v3")
    ap.add_argument("--language", default=None)
    ap.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    ap.add_argument("--model", default="claude-opus-4-7")
    ap.add_argument("--no-llm", action="store_true", help="step2 のLLM呼出をスキップ（動作確認用）")
    ap.add_argument("--no-critic", action="store_true", help="director: Criticループをスキップ")
    ap.add_argument("--no-se", action="store_true", help="director: SE合成を無効化")
    ap.add_argument("--no-broll", action="store_true", help="director: B-roll提案を無効化")
    ap.add_argument("--bgm", type=Path, default=None, help="BGM音源パス")
    ap.add_argument("--legacy-step2", action="store_true", help="旧step2_logic_engine.pyを使う")
    ap.add_argument("--font", type=Path, default=None)
    ap.add_argument("--font-size", type=int, default=72)
    ap.add_argument("--output", type=Path, default=BASE_DIR / "outputs" / "final.mp4")
    args = ap.parse_args()

    transcription_json = BASE_DIR / "temp" / "transcription.json"
    edit_plan_json = BASE_DIR / "temp" / "edit_plan.json"
    py = sys.executable

    try:
        cmd1 = [py, str(BASE_DIR / "step1_transcribe.py"),
                str(args.input),
                "--backend", args.backend,
                "--model", args.whisper_model,
                "--output", str(transcription_json)]
        if args.language:
            cmd1 += ["--language", args.language]
        run_step(cmd1, "step1_transcribe")

        step2_script = "step2_logic_engine.py" if args.legacy_step2 else "step2_director.py"
        cmd2 = [py, str(BASE_DIR / step2_script),
                "--input", str(transcription_json),
                "--output", str(edit_plan_json),
                "--provider", args.provider,
                "--model", args.model]
        if args.no_llm:
            cmd2.append("--no-llm")
        if not args.legacy_step2:
            if args.no_critic:
                cmd2.append("--no-critic")
            if args.no_se:
                cmd2.append("--no-se")
            if args.no_broll:
                cmd2.append("--no-broll")
            if args.bgm:
                cmd2 += ["--bgm", str(args.bgm)]
        run_step(cmd2, "step2" + (" (legacy)" if args.legacy_step2 else " (director)"))

        cmd3 = [py, str(BASE_DIR / "step3_renderer.py"),
                "--input", str(edit_plan_json),
                "--output", str(args.output),
                "--font-size", str(args.font_size)]
        if args.font:
            cmd3 += ["--font", str(args.font)]
        run_step(cmd3, "step3_renderer")

        logger.success(f"★ 全工程完了: {args.output}")
        return 0
    except Exception as e:
        logger.exception(f"パイプライン失敗: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
