"""step2_director.py
====================
マルチエージェント版 step2。step1の transcription.json を読み、
agents/ 配下の各エージェントを並列に動かして EditPlan v2 JSON を出力する。

旧 step2_logic_engine.py との違い:
  - 7エージェント分担（GenreClassifier / HookStrategist / CutDirector / TelopWriter
    / HighlightSelector / SEComposer / BRollPlanner + RetentionCritic）
  - asyncio.gather で並列実行（LLM呼び出し回数は増えるが prompt cache でコスト低減）
  - Critic ループで Hook を1回だけ再生成
  - --no-llm で全エージェントがルールベース fallback に切替

Usage:
  python step2_director.py
  python step2_director.py --input temp/transcription.json --output temp/edit_plan.json
  python step2_director.py --provider openai --model gpt-4o
  python step2_director.py --no-llm   (APIキー無し動作確認)
  python step2_director.py --bgm ../shorts/bgm/main.mp3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}")
logger.add(LOG_DIR / "step2_{time:YYYYMMDD}.log", level="DEBUG", rotation="10 MB", retention="7 days")

from agents.base import LLMConfig
from agents.director import DirectorConfig, build_edit_plan


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="step2 (director): transcription→EditPlan v2")
    p.add_argument("--input", type=Path, default=TEMP_DIR / "transcription.json")
    p.add_argument("--output", type=Path, default=TEMP_DIR / "edit_plan.json")
    p.add_argument(
        "--provider",
        choices=["anthropic", "openai"],
        default=os.environ.get("LLM_PROVIDER", "anthropic"),
    )
    p.add_argument("--model", default=os.environ.get("LLM_MODEL", "claude-opus-4-7"))
    p.add_argument("--no-llm", action="store_true", help="LLM呼出全スキップ（ルールベースfallback）")
    p.add_argument("--no-critic", action="store_true", help="Critic loopをスキップ")
    p.add_argument("--no-se", action="store_true", help="SE合成を無効化")
    p.add_argument("--no-broll", action="store_true", help="B-roll提案を無効化")
    p.add_argument("--bgm", type=Path, default=None, help="BGM音源パス（任意）")
    p.add_argument("--temperature", type=float, default=0.4)
    return p.parse_args()


async def _amain(args: argparse.Namespace) -> int:
    if not args.input.exists():
        logger.error(f"transcription JSON が無い: {args.input}")
        return 1

    with args.input.open("r", encoding="utf-8") as f:
        transcription = json.load(f)

    # OpenAI で claude モデル名が指定されてたら補正
    model = args.model
    if args.provider == "openai" and model.startswith("claude"):
        model = "gpt-4o"

    llm_cfg = LLMConfig(
        provider=args.provider,
        model=model,
        temperature=args.temperature,
        max_tokens=4096,
        enable_cache=True,
    )
    director_cfg = DirectorConfig(
        llm=llm_cfg,
        no_llm=args.no_llm,
        enable_critic_loop=not args.no_critic,
        enable_se=not args.no_se,
        enable_broll=not args.no_broll,
    )

    plan = await build_edit_plan(
        transcription, director_cfg, bgm_path=str(args.bgm) if args.bgm else None
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(plan.model_dump(), f, ensure_ascii=False, indent=2)
    logger.success(
        f"EditPlan v2 出力: {args.output} "
        f"(genre={plan.genre} clips={len(plan.clips)} subs={len(plan.subtitles)} "
        f"se={len(plan.se_cues)} broll={len(plan.broll_cues)} hook={'有' if plan.hook else '無'})"
    )
    return 0


def main() -> int:
    load_dotenv(BASE_DIR / ".env", override=True)
    args = parse_args()
    try:
        return asyncio.run(_amain(args))
    except Exception as e:
        logger.exception(f"step2_director 失敗: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
