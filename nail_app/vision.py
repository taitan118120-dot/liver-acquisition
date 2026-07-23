"""
Gemini で ネイル写真を解析し、キャプション文＋デザイン系ハッシュタグ を生成する。
"""

import base64
import json
import re

import requests

import config

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]


def _mime_from_path(path):
    p = path.lower()
    if p.endswith(".png"):
        return "image/png"
    if p.endswith(".webp"):
        return "image/webp"
    if p.endswith(".heic") or p.endswith(".heif"):
        return "image/heic"
    return "image/jpeg"


PROMPT = """あなたは石川県小松市のネイルサロンのSNS担当です。
この画像はサロンで施術したネイルの写真です。写真をよく見て、Instagramのハッシュタグ用の単語だけを作ってください。
（キャプション本文は作りません。ハッシュタグ用のタグだけでOKです）

必ず次のJSONだけを返してください（前後に説明文やコードブロックは付けない）:
{{
  "is_nail": true または false（ネイルの写真かどうか）,
  "design_tags": ["ハッシュタグにする単語を8〜12個。#は付けない。写真から読み取れる色・デザイン・技法・季節感・雰囲気（例: ニュアンスネイル, くすみピンク, マグネットネイル, 秋ネイル, ワンホン, フレンチ, 天然石ネイル 等）。実在するネイル用語で、日本語中心に。"]
}}

エリア: {area}
"""


def analyze_nail_image(image_path):
    """
    戻り値 dict: {is_nail, caption, design_tags:[...]}。
    失敗時は例外を送出。
    """
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY が未設定です（.env に入れてください）")

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("ascii")

    prompt = PROMPT.format(area=config.SALON_AREA)

    body = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": _mime_from_path(image_path),
                            "data": img_b64,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"temperature": 0.8, "responseMimeType": "application/json"},
    }

    last_err = None
    for model in MODELS:
        url = GEMINI_ENDPOINT.format(model=model)
        try:
            r = requests.post(
                url,
                params={"key": config.GEMINI_API_KEY},
                json=body,
                timeout=60,
            )
            if r.status_code != 200:
                last_err = f"{model}: HTTP {r.status_code} {r.text[:200]}"
                continue
            data = r.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return _parse(text)
        except Exception as e:  # noqa: BLE001
            last_err = f"{model}: {e}"
            continue

    raise RuntimeError(f"Gemini解析に失敗: {last_err}")


def _parse(text):
    text = text.strip()
    # コードブロックが混じった場合を除去
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    obj = json.loads(text)
    return {
        "is_nail": bool(obj.get("is_nail", True)),
        "design_tags": [str(t) for t in obj.get("design_tags", []) if str(t).strip()],
    }
