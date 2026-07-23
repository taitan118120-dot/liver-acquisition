"""Hook Strategist: 冒頭3秒の全画面オーバーレイを設計する。

ショート動画の離脱は最初3秒で60%発生するため、ここに**結論先出し or 強い問いかけ**
のテロップを差し込むことで滞留率を上げる。
"""

from __future__ import annotations

import re
from typing import List

from .base import BaseAgent
from .schemas import HookDecision, HookOverlay

SYSTEM_PROMPT = """あなたは月間1億再生を出すTikTok・YouTube Shortsの**冒頭3秒設計**を専門とする日本語コピーライターです。

ショート動画は**最初の3秒で60%が離脱**します。冒頭の全画面オーバーレイ（=フック）が滞留率を決めます。

入力として動画のジャンルと、冒頭5秒程度のセリフ全文が与えられます。
あなたの仕事はこの動画にふさわしい**1〜2行の強烈なフック**を設計することです。

## ジャンル別の鉄板パターン
- howto: 「3秒で分かる○○」「○○のコツ3つ」「絶対やるな○○」
- qa: 「え、これマジ？」「○○って実際どうなの？」
- ranking: 「○○TOP3」「絶対1位は○○」「これ知らないとヤバい」
- explanation: 「○○とは？」「実は○○なんです」「99%が誤解」
- emotional: 「これ涙腺崩壊」「全人類見て」「最後まで見て」
- comedy: 「これ草」「天才か？」
- default: 「○○の話」「実は…」

## 出力JSON（このフィールドのみ、他禁止）
{
  "hook": {
    "text": "10〜15文字以内のメインテキスト",
    "subtext": null または "サブテキスト（10文字以内、なくても良い）",
    "style": "banner" | "centered_huge" | "chat_bubble" | "scribble" | "none",
    "text_color": "#FFFFFF",
    "bg_color": "#FF3C3C" のような16進カラーコード,
    "start": 0.0,
    "end": 3.0,
    "font_size": 100〜180の整数,
    "y_ratio": 0.0〜1.0 の浮動小数（画面縦方向の中心比、デフォルト0.38）
  },
  "reason": "30字以内"
}

## 厳守
- text は最大15文字、subtext は最大10文字。長すぎたら詰めて短くする。
- 「絶対」「マジ」「ヤバい」「神」「3秒」「TOP3」など、指止め単語を必ず1つ以上含める。
- bg_color は彩度の高い赤系・黄系・青系から選ぶ（パステル・グレーは禁止）。
- ジャンルが emotional/explanation の場合は bg_color="#1a1a2e" のような暗色 + text_color="#FFFFFF" で落ち着いた印象に。
- フックを入れない方が良い場合のみ "hook": null を返す。
- valid JSON 1オブジェクトのみ。
"""


class HookStrategist(BaseAgent[HookDecision]):
    name = "hook_strategist"
    output_schema = HookDecision
    system_prompt = SYSTEM_PROMPT

    def fallback(self, payload: dict) -> HookDecision:
        genre = payload.get("genre", "default")
        intro: str = payload.get("intro_text", "") or ""
        # 冒頭から名詞っぽい塊を抜く（簡易）
        first_phrase = intro.split("。")[0].strip()
        first_phrase = re.sub(r"[、,\s]+", "", first_phrase)[:14] or "知らないとヤバい"

        templates = {
            "howto": ("3秒で分かる", first_phrase[:12], "#FF3C3C"),
            "qa": ("え、マジ？", first_phrase[:12], "#FFD60A"),
            "ranking": ("これがTOP3", first_phrase[:12], "#FF3C3C"),
            "explanation": ("実は…", first_phrase[:12], "#1a1a2e"),
            "emotional": ("最後まで見て", first_phrase[:12], "#1a1a2e"),
            "comedy": ("これ草", first_phrase[:12], "#00D9FF"),
            "default": ("これ知ってた？", first_phrase[:12], "#FF3C3C"),
        }
        text, subtext, bg = templates.get(genre, templates["default"])
        return HookDecision(
            hook=HookOverlay(
                text=text,
                subtext=subtext if subtext else None,
                style="banner",
                text_color="#FFFFFF",
                bg_color=bg,
                start=0.0,
                end=2.5,
                font_size=120,
                y_ratio=0.35,
            ),
            reason="fallback template",
        )
