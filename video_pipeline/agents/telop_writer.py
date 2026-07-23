"""Telop Writer: Whisper原文を「読みやすい短文テロップ」に書き直す。

ショート動画では1テロップ ≤8文字×2行が読みやすさの黄金比。
原文を意味は変えずに圧縮、句読点・助詞を削る、改行位置を最適化する。
template (default/punchline/question/shock) も判定する。
"""

from __future__ import annotations

import re
from typing import List

from .base import BaseAgent
from .schemas import TelopRewriteItem, TelopWriterOutput

SYSTEM_PROMPT = """あなたは「ショート動画の読みやすいテロップ」専門の日本語コピーエディターです。

ショート動画は **1秒以内に読み切れる短さ** が命です。
入力として原文テロップチャンク（Whisperの単語列）が与えられます。
あなたの仕事はこれを **意味を変えずに、画面で1秒で読める短さに圧縮** することです。

## 書き直し原則
1. **1行 ≤ 10文字**、**最大2行**（合計20文字以内）。
2. 助詞・接続詞・冗長表現を削る（「〜なんですけど」→削除、「〜という」→削除）。
3. 句読点（、。）はテロップでは原則削除。
4. 倒置で「結論先出し」にできるなら積極的に倒置。
5. **意味は変えない**、固有名詞・数値は絶対に保持する。
6. 元の感情・トーンは保つ（「マジで」「やばい」は残す）。

## template判定（強調演出のヒント）
各チャンクに以下のタグを付ける:
- "default": 通常テロップ
- "punchline": オチ・結論・キメ台詞（強調表示用）
- "question": 問いかけ（「？」終わり、視聴者への呼びかけ）
- "shock": 衝撃事実、驚き表現（「えっ」「マジで」「やばい」）
- "whisper": 余韻、ささやき、独り言調

## 入力スキーマ
{
  "subtitles_raw": [
    {"chunk_index": 0, "text": "ライバーって始め方が分からないんだよね"},
    ...
  ]
}

## 出力JSON（このフィールドのみ）
{
  "rewrites": [
    {
      "chunk_index": 0,
      "rewritten_lines": ["ライバーって", "始め方どうすんの"],
      "template": "question"
    }
  ]
}

## 厳守
- 全chunk_indexに対してrewritesを返す（省略禁止）。
- rewritten_lines は1〜3個の文字列、各文字列は最大10文字。
- 元のchunk_indexに無い番号は出力しない。
- valid JSON 1オブジェクトのみ。
"""


_PARTICLES_TO_DROP = [
    "なんですけど", "なんですよ", "って言うか", "という", "ということ",
    "わけです", "わけ", "んです", "ですよね", "んだよね",
    "ってこと", "みたいな", "じゃなくて", "ですから",
]
_PUNCT_TO_STRIP = "、。"
_LEADING_FILLER = ["えーと", "えっと", "あの", "そのー", "まあ", "なんか"]


def _strip_phrase(s: str) -> str:
    s = re.sub(r"\s+", "", s)
    for p in _PUNCT_TO_STRIP:
        s = s.replace(p, "")
    return s


def _wrap_phrases(phrases: List[str], max_chars: int = 10, max_lines: int = 2) -> List[str]:
    """phrase（フレーズ）列を、各行 max_chars 以内になるように貪欲詰め込み。
    max_lines を超える分は切り捨て。"""
    cleaned = [_strip_phrase(p) for p in phrases]
    cleaned = [c for c in cleaned if c]
    if not cleaned:
        return []
    lines: List[str] = []
    cur = ""
    for ph in cleaned:
        # 1フレーズが max_chars を超える場合は強制改行
        if len(ph) > max_chars:
            if cur:
                lines.append(cur)
                cur = ""
                if len(lines) >= max_lines:
                    break
            # ハードラップ
            for i in range(0, len(ph), max_chars):
                lines.append(ph[i : i + max_chars])
                if len(lines) >= max_lines:
                    break
            cur = ""
            if len(lines) >= max_lines:
                break
            continue
        if len(cur) + len(ph) <= max_chars:
            cur += ph
        else:
            if cur:
                lines.append(cur)
            cur = ph
            if len(lines) >= max_lines:
                # max_lines 到達: 残りは捨てる
                cur = ""
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines or [cleaned[0][:max_chars]]


def _detect_template(text: str) -> str:
    t = text
    if t.endswith(("?", "？")):
        return "question"
    if any(k in t for k in ["マジ", "ヤバ", "やば", "えっ", "衝撃", "！？", "なんと"]):
        return "shock"
    if any(k in t for k in ["つまり", "結論", "答え", "実は", "ポイント"]):
        return "punchline"
    if any(k in t for k in ["…", "ささやき"]):
        return "whisper"
    return "default"


class TelopWriter(BaseAgent[TelopWriterOutput]):
    name = "telop_writer"
    output_schema = TelopWriterOutput
    system_prompt = SYSTEM_PROMPT

    def fallback(self, payload: dict) -> TelopWriterOutput:
        chunks = payload.get("subtitles_raw", []) or []
        rewrites: List[TelopRewriteItem] = []
        for c in chunks:
            ci = int(c.get("chunk_index", 0))
            phrases = c.get("phrases") or []
            text: str = c.get("text", "") or ""

            # 言い淀みを先頭から削る
            for filler in _LEADING_FILLER:
                if phrases and phrases[0].strip() == filler:
                    phrases = phrases[1:]

            # 冗長語を各フレーズから削る
            cleaned_phrases: List[str] = []
            for ph in phrases:
                pp = ph
                for drop in _PARTICLES_TO_DROP:
                    pp = pp.replace(drop, "")
                cleaned_phrases.append(pp)

            if cleaned_phrases:
                lines = _wrap_phrases(cleaned_phrases, max_chars=10, max_lines=2)
            else:
                # フォールバックの中のフォールバック: text を10文字で機械分割
                t = _strip_phrase(text)
                for drop in _PARTICLES_TO_DROP:
                    t = t.replace(drop, "")
                lines = [t[:10]] if t else ["…"]
                if len(t) > 10:
                    lines.append(t[10:20])

            if not lines:
                lines = ["…"]

            template = _detect_template(text)
            rewrites.append(
                TelopRewriteItem(chunk_index=ci, rewritten_lines=lines, template=template)
            )
        return TelopWriterOutput(rewrites=rewrites)
