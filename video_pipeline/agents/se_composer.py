"""SE/BGM Composer: 効果音とBGMの配置を決める。

利用可能なSE: pop / tada / whoosh （shorts/se/）
- pop: 強調・キラリ・ポイント提示
- tada: オチ・正解・到達点
- whoosh: 場面転換・スワイプ
BGM: 1ジャンルにつき1ループ（暫定 shorts/bgm/main.mp3）
"""

from __future__ import annotations

from typing import List

from .base import BaseAgent
from .schemas import SEComposerOutput, SECueProposal

SYSTEM_PROMPT = """あなたはショート動画の音響演出を担当するサウンドディレクターです。

利用可能なSE（効果音）:
- "pop": 軽快な「ポンッ」音。強調・項目提示・キラリ
- "tada": 「ジャーン」のような達成・正解音。オチ・結論到達
- "whoosh": スワイプ音。場面転換・話題切替

入力として書き直し済みテロップチャンク列が与えられます。
**重要なチャンクの先頭または末尾**にだけSEを入れます。

## 配置原則
- pop: 数値や固有名詞が出るchunk、項目を提示するchunkの **start** に配置
- tada: 動画後半の「結論」「答え」「オチ」のchunk **start** に1回だけ
- whoosh: 話題が大きく切り替わる地点（chunk start）に配置、最大2回まで

## 制約
- SE総数は **chunk数の30%以下** （鳴らしすぎは耳障り）
- 連続するchunkに連続でSEを入れない（最低1chunk空ける）
- pop の volume は 0.4-0.6、tada は 0.5-0.7、whoosh は 0.4-0.5 推奨

## 入力スキーマ
{
  "genre": "howto",
  "subtitles": [
    {"chunk_index": 0, "template": "question", "text": "ライバー始め方どうすんの"},
    ...
  ]
}

## 出力JSON
{
  "se_cues": [
    {"chunk_index": 3, "sfx": "pop", "volume": 0.5, "at": "start", "reason": "数値提示"},
    {"chunk_index": 12, "sfx": "tada", "volume": 0.6, "at": "start", "reason": "結論"}
  ]
}

## 厳守
- chunk_index は入力に存在するもののみ。
- sfx は "pop"|"tada"|"whoosh" のみ。
- valid JSON 1オブジェクトのみ。
- 自信が無いchunkにはSEを入れない（少ない方がプロっぽい）。
"""


class SEComposer(BaseAgent[SEComposerOutput]):
    name = "se_composer"
    output_schema = SEComposerOutput
    system_prompt = SYSTEM_PROMPT

    def fallback(self, payload: dict) -> SEComposerOutput:
        subs = payload.get("subtitles", []) or []
        out: List[SECueProposal] = []
        last_se_chunk = -10
        tada_used = False
        whoosh_count = 0
        for s in subs:
            ci = int(s.get("chunk_index", 0))
            if ci - last_se_chunk < 2:
                continue
            tmpl = s.get("template", "default")
            text = s.get("text", "") or ""
            sfx = None
            vol = 0.5
            if tmpl == "punchline" and not tada_used and ci > len(subs) // 2:
                sfx, vol, tada_used = "tada", 0.6, True
            elif tmpl == "shock":
                sfx, vol = "pop", 0.55
            elif tmpl == "question" and whoosh_count < 2:
                sfx, vol = "whoosh", 0.4
                whoosh_count += 1
            elif any(ch.isdigit() for ch in text):
                sfx, vol = "pop", 0.5
            if sfx:
                out.append(
                    SECueProposal(chunk_index=ci, sfx=sfx, volume=vol, at="start", reason="rule")
                )
                last_se_chunk = ci
        # 上限: 全chunkの30%
        max_se = max(1, len(subs) * 30 // 100)
        return SEComposerOutput(se_cues=out[:max_se])
