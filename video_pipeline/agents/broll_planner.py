"""B-roll Planner: 単調な区間に Ken Burns / blur_bg / color_block の差し込みを提案。

実映像に変化が乏しい長chunk連続区間や、長セリフのbreak点に
背景効果（Ken Burns風ズーム、ぼかし背景、カラー帯）を差して画面に動きを作る。
"""

from __future__ import annotations

from typing import List

from .base import BaseAgent
from .schemas import BRollPlannerOutput, BRollProposal

SYSTEM_PROMPT = """あなたはショート動画のB-roll/インサート演出を担当するビジュアルディレクターです。

ショート動画は **5秒に1回は画面に変化** が必要です。同じ顔・同じ背景が10秒続くと離脱します。
長chunk連続や、説明が冗長な区間に **B-roll差し込み** を提案します。

## B-rollスタイル
- "ken_burns": 元動画の現在フレームを静止画として、ゆっくりズーム/パン
- "color_block": 単色背景 + 中央に大きなテキスト（インパクト重視）
- "blur_bg": 元動画をぼかして背景にし、上に大きなテキスト
- "split_screen": 上下/左右に分割（解説向き、複雑なので使い所限定）

## 配置原則
- chunk連続が **3つ以上同じ template (default)** の区間に1回
- 「ながーい説明」chunk（長音節が多い）の中盤に1回
- 動画後半の重要な転換点に1回（最大1回）

## 制約
- B-rollは動画全体で **3個以下** に抑える（多すぎると元動画が見えない）
- chunk_index_start <= chunk_index_end、最低2chunk以上をカバー
- text_overlay は20文字以内、ジャンルに合った言葉

## 入力スキーマ
{
  "genre": "howto",
  "subtitles": [
    {"chunk_index": 0, "template": "default", "text": "..."},
    ...
  ]
}

## 出力JSON
{
  "broll_cues": [
    {
      "chunk_index_start": 5,
      "chunk_index_end": 7,
      "style": "blur_bg",
      "text_overlay": "ここがポイント"
    }
  ]
}

## 厳守
- chunk_index は入力に存在するもののみ。
- style は4種類から選択。
- valid JSON 1オブジェクトのみ。
- 不要なら "broll_cues": [] で良い。
"""


class BRollPlanner(BaseAgent[BRollPlannerOutput]):
    name = "broll_planner"
    output_schema = BRollPlannerOutput
    system_prompt = SYSTEM_PROMPT

    def fallback(self, payload: dict) -> BRollPlannerOutput:
        subs = payload.get("subtitles", []) or []
        if len(subs) < 6:
            return BRollPlannerOutput(broll_cues=[])
        # 連続するdefault chunkを探す
        out: List[BRollProposal] = []
        run_start = 0
        run_count = 0
        for i, s in enumerate(subs):
            tmpl = s.get("template", "default")
            if tmpl == "default":
                if run_count == 0:
                    run_start = i
                run_count += 1
            else:
                if run_count >= 3 and len(out) < 2:
                    out.append(
                        BRollProposal(
                            chunk_index_start=int(subs[run_start]["chunk_index"]),
                            chunk_index_end=int(subs[run_start + run_count - 1]["chunk_index"]),
                            style="blur_bg",
                            text_overlay=None,
                        )
                    )
                run_count = 0
        return BRollPlannerOutput(broll_cues=out)
