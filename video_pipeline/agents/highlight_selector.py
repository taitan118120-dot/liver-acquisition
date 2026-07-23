"""Highlight Selector: マルチカラー強調の判定。

旧step2では黄色1色のみ。本エージェントは:
  - yellow: 数値・固有名詞・通常強調
  - red: 衝撃事実・最上級・否定強調（"絶対NG", "ヤバい"）
  - green: 結論・答え・ポイント
  - cyan: 呼びかけ・問いかけ
  - pink: 感情語・推し
を出し分け、size_scale で1.0〜1.6倍までサイズも変える。
"""

from __future__ import annotations

import re
from typing import List, Tuple

from .base import BaseAgent
from .schemas import HighlightItem, HighlightSelectorOutput

SYSTEM_PROMPT = """あなたはショート動画のテロップ強調を専門とする日本語ビジュアルディレクターです。

入力としてTelop Writerが書き直した、改行済みテロップが与えられます。
あなたの仕事は、視聴者の指を止める単語に **色とサイズの強調** をかけることです。

## 5色の使い分け
| color | 用途 |
|---|---|
| yellow | 数値・固有名詞・通常の重要語（最頻） |
| red | 衝撃・否定強調・最上級（「絶対NG」「ヤバい」「最悪」） |
| green | 結論・答え・ポイント（「結論」「答え」「実は」） |
| cyan | 呼びかけ・問いかけ（「知ってた？」「聞いて」） |
| pink | 感情語・推し（「神」「最高」「大好き」） |

## size_scale
- 1.0: 通常強調
- 1.2: 軽い強調（数値・固有名詞）
- 1.4: 強い強調（衝撃・結論）
- 1.6: 最大級強調（オチの一語）

## 制約
- 1テロップchunkにつき強調語は最大2つ。過剰ハイライトは視認性を破壊。
- 助詞・接続詞・指示語は強調しない。
- 強調する語が無いchunkは、そのchunkの highlights に1つも含めない。

## 入力スキーマ
{
  "subtitles": [
    {
      "chunk_index": 0,
      "template": "question",
      "lines": [
        {"line_index": 0, "words": [{"word_index": 0, "text": "ライバーの"}, {"word_index": 1, "text": "始め方"}]},
        ...
      ]
    }
  ]
}

## 出力JSON（このフィールドのみ）
{
  "highlights": [
    {"chunk_index": 0, "line_index": 1, "word_index": 0, "color": "yellow", "size_scale": 1.2}
  ]
}

## 厳守
- 入力にないインデックスを出力しない。
- 色は yellow/red/green/cyan/pink から選択（白や黒は禁止）。
- valid JSON 1オブジェクトのみ。
"""


_DIGIT_CHARS = set("0123456789０１２３４５６７８９%％倍個円点位")
_RULES = [
    ("red", ["絶対", "ヤバ", "やば", "最悪", "最強", "最大", "唯一", "衝撃", "マジ", "まじ"]),
    ("green", ["結論", "答え", "つまり", "要するに", "実は", "ポイント", "重要"]),
    ("cyan", ["知ってた", "聞いて", "見て", "ちょっと", "知ってる"]),
    ("pink", ["神", "最高", "推し", "好き", "天才", "大好き"]),
    ("yellow", ["秘密", "コツ", "TOP", "トップ", "一番", "ベスト"]),
]


class HighlightSelector(BaseAgent[HighlightSelectorOutput]):
    name = "highlight_selector"
    output_schema = HighlightSelectorOutput
    system_prompt = SYSTEM_PROMPT

    def fallback(self, payload: dict) -> HighlightSelectorOutput:
        """ルールベース fallback。
        - chunk内: 最大2語をハイライト
        - chunk間: ヒット時に色を循環させて単調回避（yellow主体になりすぎない）
        - chunk内に全くキーワード無くても、各chunkに最低1個は色を入れて視覚活性
        - チャンクの template で色を寄せる (shock→red, punchline→green, question→cyan)
        """
        subs = payload.get("subtitles", []) or []
        out: List[HighlightItem] = []
        # chunk index → 推奨色（templateで決める）
        TMPL_COLOR = {"shock": "red", "punchline": "green", "question": "cyan", "whisper": "pink", "default": "yellow"}
        ROTATE = ["yellow", "red", "green", "cyan", "pink"]
        rot_idx = 0
        for s in subs:
            ci = int(s.get("chunk_index", 0))
            tmpl = s.get("template", "default")
            preferred = TMPL_COLOR.get(tmpl, "yellow")

            picked = 0
            picked_words: List[Tuple[int, int, str, str, float]] = []  # (line, word, text, color, size)
            for line in s.get("lines", []):
                li = int(line.get("line_index", 0))
                for w in line.get("words", []):
                    if picked >= 2:
                        break
                    wi = int(w.get("word_index", 0))
                    text: str = w.get("text", "") or ""
                    color = None
                    size = 1.0
                    if any(ch in _DIGIT_CHARS for ch in text):
                        color, size = "yellow", 1.3   # 数値は常に yellow + 大きめ
                    else:
                        for col, kws in _RULES:
                            if any(kw in text for kw in kws):
                                color = col
                                size = 1.4 if col in ("red", "green") else 1.2
                                break
                    if color:
                        picked_words.append((li, wi, text, color, size))
                        picked += 1
                if picked >= 2:
                    break

            # ヒット皆無の場合、chunkの先頭2-4文字を rotate色（or template推奨色）で強調
            if not picked_words:
                lines = s.get("lines", [])
                if lines and lines[0].get("words"):
                    first = lines[0]["words"][0]
                    # template 推奨色がある場合はそれを優先、なければ rotate
                    if tmpl in ("shock", "punchline", "question", "whisper"):
                        color = preferred
                    else:
                        color = ROTATE[rot_idx % len(ROTATE)]
                        rot_idx += 1
                    picked_words.append(
                        (
                            int(lines[0].get("line_index", 0)),
                            int(first.get("word_index", 0)),
                            first.get("text", ""),
                            color,
                            1.2,
                        )
                    )

            # 色の単調回避: 強調語が複数あるなら2個目を ROTATE 順で別色に
            if len(picked_words) >= 2:
                color2 = ROTATE[rot_idx % len(ROTATE)]
                if color2 == picked_words[0][3]:
                    color2 = ROTATE[(rot_idx + 1) % len(ROTATE)]
                li, wi, t, _c, sz = picked_words[1]
                picked_words[1] = (li, wi, t, color2, sz)
                rot_idx += 1

            for li, wi, _t, color, size in picked_words:
                out.append(
                    HighlightItem(
                        chunk_index=ci,
                        line_index=li,
                        word_index=wi,
                        color=color,
                        size_scale=size,
                    )
                )
        return HighlightSelectorOutput(highlights=out)
