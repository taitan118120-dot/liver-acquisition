"""ジャンル判定エージェント。動画全体の文字起こしから genre を1つ選ぶ。

genre は後段の各エージェントに配布され、SE選定・テンプレート選択・色使い等を切り替える。
"""

from __future__ import annotations

import re
from typing import List

from .base import BaseAgent
from .schemas import GenreDecision

SYSTEM_PROMPT = """あなたはTikTok・YouTube Shortsのジャンル判定を専門とする日本語ショート動画ディレクターです。

入力として動画全体の文字起こしテキストが与えられます。
動画を以下の7ジャンルから**1つだけ**選び、JSONで返してください。

| genre | 特徴 |
|---|---|
| howto | 手順解説、ノウハウ、やり方の紹介 |
| qa | Q&A形式、質問→回答 |
| ranking | TOP3, TOP5, ランキング、比較 |
| explanation | 概念説明、用語解説、知識共有 |
| emotional | 感動・共感系、エモい話、ストーリー |
| comedy | お笑い、ボケツッコミ、面白系 |
| default | 上記いずれにも明確に当てはまらない |

## 出力JSON（このフィールドのみ、他のフィールド禁止）
{
  "genre": "howto",
  "reason": "30字以内で根拠を1文"
}

## 厳守
- valid JSON 1オブジェクトのみ。コードフェンス・前後テキスト禁止。
- 迷ったら "default"。
"""


class GenreClassifier(BaseAgent[GenreDecision]):
    name = "genre_classifier"
    output_schema = GenreDecision
    system_prompt = SYSTEM_PROMPT

    def fallback(self, payload: dict) -> GenreDecision:
        text: str = payload.get("transcript", "") or ""
        # 単純なキーワードヒューリスティック
        rules = [
            ("ranking", [r"TOP\s*\d", r"トップ\s*\d", r"第[一二三四五]位", r"ランキング", r"\d+\s*位"]),
            ("qa", [r"質問", r"教えて", r"どうやって", r"\?", r"？"]),
            ("howto", [r"やり方", r"始め方", r"方法", r"ステップ", r"手順", r"コツ"]),
            ("explanation", [r"とは", r"理由", r"仕組み", r"なぜ", r"つまり"]),
            ("comedy", [r"草", r"笑", r"ww", r"ボケ", r"ツッコミ"]),
            ("emotional", [r"感動", r"泣", r"心が", r"応援", r"頑張"]),
        ]
        for genre, patterns in rules:
            if any(re.search(p, text) for p in patterns):
                return GenreDecision(genre=genre, reason=f"fallback: keyword match")
        return GenreDecision(genre="default", reason="fallback: no match")
