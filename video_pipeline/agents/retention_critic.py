"""Retention Critic: 完成planを「3秒離脱回避」「最後まで見てもらえるか」観点で採点。

採点が低ければ Director にフィードバックして1回だけ Hook を再生成させる。
"""

from __future__ import annotations

import re
from typing import List

from .base import BaseAgent
from .schemas import RetentionCriticOutput

SYSTEM_PROMPT = """あなたはTikTok・YouTube Shortsのリテンション分析を専門とするデータディレクターです。
**3秒離脱率**と**完視聴率**を予測することがあなたの仕事です。

入力として完成したEditPlan（hook, subtitles, se_cues, broll_cues, 全体長）が与えられます。
これを以下の観点で評価し、JSONで採点してください。

## 評価軸
1. **3秒離脱回避力** (retention_3s, 0-100)
   - hookが強烈か（指止め単語、彩度の高い色）
   - 冒頭3秒に強調・SE・色変化があるか
2. **総合質スコア** (score, 0-100)
   - テンポ（chunk平均長 < 2秒が理想）
   - 色変化（強調色のバリエーション）
   - SEの過不足
   - オチ・クロージングの存在
3. **weak_points**: 改善すべき具体ポイント（最大3つ、各40字以内）
4. **notes**: 良かった点（最大3つ）
5. **suggested_hook_rewrite**: hookが弱いと判断した場合の代替案（15文字以内）

## 出力JSON
{
  "score": 78.5,
  "retention_3s": 82.0,
  "weak_points": [
    "Hookに数値が無く、訴求力が弱い"
  ],
  "notes": [
    "オチで tada SEが効いている"
  ],
  "suggested_hook_rewrite": "3秒で分かるTOP3"
}

## 厳守
- score / retention_3s は 0.0〜100.0 の浮動小数。
- weak_points / notes は配列、空でも構わない。
- suggested_hook_rewrite は不要なら null。
- valid JSON 1オブジェクトのみ。
"""


class RetentionCritic(BaseAgent[RetentionCriticOutput]):
    name = "retention_critic"
    output_schema = RetentionCriticOutput
    system_prompt = SYSTEM_PROMPT

    def fallback(self, payload: dict) -> RetentionCriticOutput:
        hook = payload.get("hook")
        subs = payload.get("subtitles", []) or []
        se = payload.get("se_cues", []) or []
        # 簡易スコアリング
        retention = 50.0
        score = 50.0
        weak: List[str] = []
        notes: List[str] = []
        if hook:
            text = hook.get("text", "") if isinstance(hook, dict) else ""
            retention += 20
            if any(c.isdigit() for c in text):
                retention += 10
                notes.append("Hookに数値あり")
            else:
                weak.append("Hookに数値が無い")
            if any(k in text for k in ["絶対", "ヤバ", "マジ", "神", "TOP"]):
                retention += 10
                notes.append("指止め語あり")
            else:
                weak.append("指止め単語が弱い")
        else:
            weak.append("Hookが無い（離脱大）")

        if subs:
            avg_len = sum((s["end"] - s["start"]) for s in subs) / len(subs)
            if avg_len < 2.0:
                score += 15
                notes.append(f"chunk平均{avg_len:.1f}sでテンポ良好")
            else:
                weak.append(f"chunk平均{avg_len:.1f}sは長め")
        if se:
            score += 10
            notes.append(f"SE {len(se)}個配置")
        else:
            weak.append("SEが無く単調")

        return RetentionCriticOutput(
            score=min(100.0, score),
            retention_3s=min(100.0, retention),
            weak_points=weak[:3],
            notes=notes[:3],
            suggested_hook_rewrite=None,
        )
