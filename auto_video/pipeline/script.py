"""Claude-powered viral script writer for Japanese short-form video.

Input: topic (str), optional angle / audience.
Output: structured JSON with hook + beats + CTA, validated.
"""
from __future__ import annotations
import json
import os
import re
import hashlib
from pathlib import Path
from typing import Optional

import anthropic

from ..config import MODEL, MAX_TOKENS, CACHE_DIR, AGENCY_NAME, LP_URL, CTA_TEXT


SYSTEM_PROMPT = """あなたは日本のTikTok / YouTube Shorts / Reels向け短尺動画の構成作家です。\
ターゲットは「ライブ配信（ライバー）に興味ある10〜30代、特にスマホ副業・在宅ワーク探してる層」。
目的はライバー事務所『TAITAN PRO』の LINE 登録（無料診断）への誘導。

【バズる構成の鉄則】
1. 冒頭0〜1.5秒は強い"Pattern Interrupt"。常識破壊 / 数字ショック / 強い逆張り / 失敗告白 / 質問フック。「え、〜なの？」「実は〜」「99%が知らない〜」「〜は嘘です」系で始める。
2. 冒頭テロップは**12文字以下**・画面中央大サイズ。
3. 2秒目以降はテンションを一度ガクッと下げて「え、どういうこと？」と続きを見たくさせる。
4. 数字は具体。曖昧な『たくさん』『多い』は禁止。月収・％・人数は必ず具体値。ただし誇張や断言は避ける。「〜のケースもある」「上位10%で」等のフレーミングを使う。
5. テロップは1画面 ≤ 20文字×2行 が上限。文章ではなく単語で刻む。
6. 途中で必ず『意外な事実（逆張り）』を1つ入れる。常識と逆の情報で視聴完了率を上げる。
7. CTAは末尾1〜2秒。必ず「プロフのLINEで無料診断」と誘導。

【絶対禁止】
- 『〜のだ』『〜なのだ』のずんだもん口調（幼稚に見える）。普通の会話調で。
- 誇張断言：『誰でも稼げる』『必ず月100万』等。必ず確率やレンジで語る。
- 『チャンネル登録してね』等の古典CTA。LINE誘導一択。
- 稼働時間・配信時間等の法令に抵触する断言。

【出力形式】
次のJSON スキーマに厳密に従うこと。余計なコメント・前置き一切禁止。コードブロックも禁止、生JSONのみ。

{
  "title": "内部タイトル（SNSキャプションにも使う、≤24字）",
  "caption": "投稿キャプション 80-120字 + ハッシュタグ",
  "hashtags": ["#ライバー", ...],
  "target_duration_sec": 26,
  "beats": [
    {
      "id": 1,
      "role": "hook" | "tension" | "payoff" | "turn" | "resolution" | "cta",
      "narration": "ナレーション原稿（音声）。1文、句読点含め25字以内推奨。CTAは33字以内。",
      "caption": "画面テロップ。≤20字。改行は \\n",
      "emphasis": ["強調する単語1", "強調する単語2"],
      "emphasis_color": "yellow" | "red" | "cyan" | "pink" | "green",
      "voice": "narrator_f" | "narrator_m" | "young_f" | "mature_f",
      "sfx": null | "pop" | "tada" | "whoosh",
      "big_number": null | "月100万円" ,
      "visual_hint": "背景motion: zoom_in | pan_left | shake | pulse | static"
    }
  ],
  "thumbnail_text": "サムネ用1行テキスト（≤14字、冒頭フックと別バリエ）"
}

beats数は 7〜9。合計 narration 発声時間で約 24〜28秒に収まるよう字数調整。hook 1本 → tension 1本 → payoff 2〜4本 → turn 1本 → resolution 1本 → cta 1本 の順。
"""


def _cache_key(topic: str, angle: str = "", audience: str = "") -> str:
    h = hashlib.sha256(f"{topic}|{angle}|{audience}|v2".encode()).hexdigest()[:16]
    safe = re.sub(r"[^A-Za-z0-9_]", "_", topic)[:40]
    return f"{safe}_{h}"


def _strip_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    return raw.strip()


def generate_script(
    topic: str,
    angle: str = "",
    audience: str = "スマホ副業を探す20代女性",
    target_sec: int = 26,
    use_cache: bool = True,
    model: str = MODEL,
) -> dict:
    """topic → 構造化スクリプト JSON."""
    key = _cache_key(topic, angle, audience)
    cache_file = CACHE_DIR / f"script_{key}.json"

    if use_cache and cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    user_msg = (
        f"【テーマ】{topic}\n"
        f"【切り口】{angle or '（任意・最もバズる角度を自分で選んで）'}\n"
        f"【想定視聴者】{audience}\n"
        f"【目標尺】{target_sec}秒\n"
        f"【事務所名】{AGENCY_NAME}\n"
        f"【CTA誘導先】{LP_URL}（LINE経由で無料診断）\n"
        f"JSON のみ出力。"
    )

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = "".join(b.text for b in resp.content if b.type == "text")
    raw = _strip_json(raw)
    data = json.loads(raw)

    # 最低限の検証
    assert "beats" in data and len(data["beats"]) >= 5, "beats 不足"
    for b in data["beats"]:
        assert "narration" in b and "caption" in b, f"invalid beat: {b}"
        b.setdefault("emphasis", [])
        b.setdefault("emphasis_color", "yellow")
        b.setdefault("voice", "narrator_f")
        b.setdefault("sfx", None)
        b.setdefault("visual_hint", "static")

    data["_topic"] = topic
    data["_angle"] = angle
    data["_model"] = model
    data["_usage"] = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0),
        "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0),
    }

    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


if __name__ == "__main__":
    import sys
    topic = sys.argv[1] if len(sys.argv) > 1 else "ライバー月収のリアル格差"
    s = generate_script(topic, use_cache=False)
    print(json.dumps(s, ensure_ascii=False, indent=2))
