"""エージェント基盤: 非同期LLMクライアント + プロンプトキャッシュ + リトライ。

各エージェントは BaseAgent を継承して:
  - name (識別子)
  - system_prompt (Anthropic prompt cache 対象)
  - output_schema (Pydantic で出力検証)
  - async run(payload) -> output_schema instance
を実装する。
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Generic, Optional, Type, TypeVar

from loguru import logger
from pydantic import BaseModel, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

T = TypeVar("T", bound=BaseModel)


# =====================================================================
#                       LLM クライアント（async）
# =====================================================================
@dataclass
class LLMConfig:
    provider: str = "anthropic"            # anthropic | openai | none
    model: str = "claude-opus-4-7"
    max_tokens: int = 4096
    temperature: float = 0.4               # 演出系は少し揺らぎがある方が自然
    enable_cache: bool = True              # Anthropic prompt cache
    timeout_sec: float = 60.0


class LLMUsage:
    """セッション全体のトークン使用量を集計（コスト可視化用）。"""

    def __init__(self) -> None:
        self.input_tokens = 0
        self.cache_creation_tokens = 0
        self.cache_read_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def add_anthropic(self, usage_obj) -> None:
        self.calls += 1
        self.input_tokens += getattr(usage_obj, "input_tokens", 0) or 0
        self.cache_creation_tokens += getattr(usage_obj, "cache_creation_input_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage_obj, "cache_read_input_tokens", 0) or 0
        self.output_tokens += getattr(usage_obj, "output_tokens", 0) or 0

    def add_openai(self, usage_obj) -> None:
        self.calls += 1
        if usage_obj is None:
            return
        self.input_tokens += getattr(usage_obj, "prompt_tokens", 0) or 0
        self.output_tokens += getattr(usage_obj, "completion_tokens", 0) or 0

    def to_dict(self) -> dict:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "output_tokens": self.output_tokens,
        }


_USAGE = LLMUsage()


def get_global_usage() -> LLMUsage:
    return _USAGE


# ---------- Anthropic ----------
async def _call_anthropic_async(
    system_prompt: str,
    user_text: str,
    cfg: LLMConfig,
) -> str:
    try:
        from anthropic import AsyncAnthropic
    except ImportError as e:
        raise RuntimeError("anthropic 未インストール: pip install anthropic") from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 未設定")

    client = AsyncAnthropic(api_key=api_key, timeout=cfg.timeout_sec)

    # Prompt caching: system を ephemeral cache として送る
    if cfg.enable_cache:
        system_block = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    else:
        system_block = system_prompt

    # claude-opus-4-7 等の新モデルは temperature 非対応。古いモデルだけ送る。
    create_kwargs = dict(
        model=cfg.model,
        max_tokens=cfg.max_tokens,
        system=system_block,
        messages=[{"role": "user", "content": user_text}],
    )
    if not cfg.model.startswith(("claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5")):
        create_kwargs["temperature"] = cfg.temperature
    resp = await client.messages.create(**create_kwargs)
    if resp.usage is not None:
        _USAGE.add_anthropic(resp.usage)
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    return text


# ---------- OpenAI ----------
async def _call_openai_async(system_prompt: str, user_text: str, cfg: LLMConfig) -> str:
    try:
        from openai import AsyncOpenAI
    except ImportError as e:
        raise RuntimeError("openai 未インストール") from e

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 未設定")

    client = AsyncOpenAI(api_key=api_key, timeout=cfg.timeout_sec)
    resp = await client.chat.completions.create(
        model=cfg.model,
        response_format={"type": "json_object"},
        temperature=cfg.temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
    )
    _USAGE.add_openai(getattr(resp, "usage", None))
    return resp.choices[0].message.content.strip()


def _extract_json(text: str) -> dict:
    if not text:
        raise json.JSONDecodeError("LLM返答が空", text, 0)
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1:
        raise json.JSONDecodeError("JSONオブジェクトが見つからない", text, 0)
    return json.loads(text[first : last + 1])


# =====================================================================
#                            BaseAgent
# =====================================================================
class BaseAgent(Generic[T]):
    name: str = "base"
    output_schema: Type[T]                 # サブクラスで上書き
    system_prompt: str = ""                # サブクラスで上書き

    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg

    # ---------- LLM経路 ----------
    async def call_llm(self, payload: dict) -> T:
        user_text = json.dumps(payload, ensure_ascii=False)

        async for attempt in AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=2, min=2, max=15),
            retry=retry_if_exception_type((RuntimeError, json.JSONDecodeError, ValidationError)),
        ):
            with attempt:
                if self.cfg.provider == "anthropic":
                    raw = await _call_anthropic_async(self.system_prompt, user_text, self.cfg)
                elif self.cfg.provider == "openai":
                    raw = await _call_openai_async(self.system_prompt, user_text, self.cfg)
                else:
                    raise RuntimeError(f"未対応provider: {self.cfg.provider}")

                obj = _extract_json(raw)
                return self.output_schema.model_validate(obj)

        raise RuntimeError(f"agent {self.name} が3回失敗")  # 念のため

    # ---------- ルールベース fallback（サブクラスで上書き） ----------
    def fallback(self, payload: dict) -> T:
        raise NotImplementedError(f"{self.name}.fallback() 未実装")

    # ---------- エントリポイント ----------
    async def run(self, payload: dict, *, no_llm: bool = False) -> T:
        if no_llm or self.cfg.provider == "none":
            logger.debug(f"[{self.name}] ルールベース fallback")
            return self.fallback(payload)
        try:
            result = await self.call_llm(payload)
            logger.debug(f"[{self.name}] LLM応答 OK")
            return result
        except Exception as e:
            logger.warning(f"[{self.name}] LLM失敗 → fallback: {e}")
            return self.fallback(payload)


# =====================================================================
#                       並列実行ユーティリティ
# =====================================================================
async def run_in_parallel(*coros) -> tuple:
    """複数エージェントを同時実行。1つ失敗しても他は続行。"""
    return await asyncio.gather(*coros, return_exceptions=False)
