#!/usr/bin/env python3
"""
Note記事用 アイキャッチ画像生成（Gemini API）
=============================================
blog/articles_note/ の各記事に対応するアイキャッチ画像を
Google Gemini の画像生成APIで作成し、blog/images/ に保存。

使い方:
  export GEMINI_API_KEY="your-api-key"
  python3 note_image_generator.py [--article 22] [--list] [--all]

必要パッケージ:
  pip install google-genai Pillow
"""

import os
import sys
import glob
import argparse
import re
import base64
from pathlib import Path

# ─── 設定 ───────────────────────────────────────────
ARTICLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blog", "articles_note")
IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blog", "images")

# 記事ごとの画像生成プロンプト
IMAGE_PROMPTS = {
    "01_ライバー始め方": "A bright, modern flat illustration of a young Japanese woman smiling and holding a smartphone doing a live stream, pastel pink and blue color scheme, clean and cheerful, no text, digital art style",
    "02_Pococha稼げる": "A flat illustration of a smartphone screen showing a live streaming app with coins and hearts floating around it, gold and purple color scheme, modern and clean, no text",
    "03_事務所選び方": "A flat illustration of a magnifying glass examining a building with checkmark badges, warm orange and white color scheme, professional, no text",
    "04_配信初心者コツ": "A flat illustration of a person sitting in front of a ring light and smartphone on a tripod, cozy room setting, soft warm lighting, no text",
    "05_ライバー収入現実": "A flat illustration of a person looking at a rising bar chart on a tablet, coins and dollar signs floating, green and gold color scheme, motivational, no text",
    "06_在宅副業おすすめ": "A flat illustration of a person working from home at a desk with a laptop and smartphone, cozy room with plants, blue and green color scheme, no text",
    "07_Pococha時間ダイヤ完全ガイド": "A flat illustration of a clock with diamond gems around it, sparkling effects, purple and gold color scheme, elegant, no text",
    "08_ライバー事務所フリー比較": "A flat illustration of a balance scale comparing two options, one side with a building (office) and other side with a person alone, blue color scheme, no text",
    "09_顔出しなしライバー": "A flat illustration of a cute anime-style avatar character waving from a smartphone screen, a microphone nearby, pastel purple and pink, no text",
    "10_大学生ライバー": "A flat illustration of a university student with books and a smartphone showing a live stream, campus setting, fresh blue and white color scheme, no text",
    "11_主婦ライバー": "A flat illustration of a cheerful woman at home with a smartphone on a tripod, kitchen and living room background, warm and cozy, pastel colors, no text",
    "12_ライバー確定申告": "A flat illustration of a calculator, tax documents, and a laptop on a desk, organized and professional, blue and white color scheme, no text",
    "13_ライバーイベント攻略": "A flat illustration of a trophy and a smartphone with confetti and celebration effects, gold and red color scheme, exciting and festive, no text",
    "14_ライバー辞めたい": "A flat illustration of a person at a crossroads, one path dark and one path bright with light, thoughtful and hopeful, blue tones, no text",
    "15_ライバー男性": "A flat illustration of a young Japanese man confidently doing a live stream with a smartphone, modern and cool, dark blue and silver color scheme, no text",
    "16_ライバー還元率": "A flat illustration of a pie chart showing revenue split with coins, clear and informative, green and gold color scheme, no text",
    "17_ライバー面接対策": "A flat illustration of two people in an online video interview, one with a notepad, professional and friendly, light blue color scheme, no text",
    "18_Pocochaランク上げ方": "A flat illustration of stairs going upward with stars at the top, a person climbing with determination, purple and gold color scheme, motivational, no text",
    "19_ライバー機材おすすめ": "A flat illustration of live streaming equipment: ring light, microphone, smartphone on tripod, neatly arranged, tech-style, gray and blue color scheme, no text",
    "20_ライバー配信ネタ": "A flat illustration of thought bubbles with various fun topics (music, food, games, chat) around a smiling person, colorful and playful, no text",
    "21_ライバー伸びない原因": "A flat illustration of a person looking puzzled at a flat graph on their phone, with a lightbulb turning on above their head, orange and blue, no text",
    "22_30代ライバー": "A flat illustration of a confident 30-something Japanese adult with a smartphone doing a live stream in a stylish home office, mature and sophisticated, warm earth tones, no text",
    "23_ライブ配信市場将来性": "A flat illustration of a rocket launching from a smartphone with a rising trend graph in the background, futuristic, blue and orange color scheme, no text",
    "24_ライバー事務所代理店": "A flat illustration of a handshake between two people with a network diagram connecting multiple profile icons, business partnership theme, blue and green, no text",
    "25_ライバーマネージャー": "A flat illustration of a supportive manager with a headset guiding a liver through a screen, with strategy icons (chart, calendar, star) floating around, professional and caring, teal and white, no text",
    "26_ライバー副業バレない": "A flat illustration of a person with a subtle disguise (glasses, hat) holding a smartphone with a lock icon, secretive but positive, dark blue and silver, no text",
    "27_ライバー事務所おすすめランキング": "A flat illustration of a podium with gold silver bronze trophies and smartphone live streaming icons, ranking theme, red and gold color scheme, no text",
    "28_ライバー1日スケジュール": "A flat illustration of a daily schedule timeline with clock icons showing morning noon and night, a person with smartphone at different times, pastel blue and orange, no text",
    "29_ライバー事務所怪しい見分け方": "A flat illustration of a magnifying glass inspecting a suspicious document with warning signs and red flags, detective theme, red and dark blue, no text",
    "30_ライバーファン増やし方": "A flat illustration of a person on smartphone screen with growing crowd of fans and hearts floating upward, cheerful and vibrant, pink and purple, no text",
    "31_ライバーメンタルケア": "A flat illustration of a person meditating peacefully with a smartphone nearby, calming nature elements like leaves and clouds, soft green and lavender, no text",
    "32_ライバー事務所移籍": "A flat illustration of a person walking from one building to another with an arrow path between them, fresh start theme, blue and green gradient, no text",
    "33_ライブ配信アプリ比較": "A flat illustration of multiple smartphone screens showing different live streaming app interfaces side by side, colorful and modern, rainbow color scheme, no text",
    "34_ライバー容姿関係ない": "A flat illustration of diverse people of different appearances all happily live streaming on smartphones, inclusive and positive, warm colorful tones, no text",
    "35_ライバー事務所契約書注意点": "A flat illustration of a magnifying glass over a contract document with checkmark and warning icons, professional and careful, navy blue and gold, no text",
    "36_ライバーコラボ配信": "A flat illustration of two people doing a collaborative live stream together on a split smartphone screen, fun and energetic, orange and teal, no text",
}

# Gemini画像生成の共通サフィックス
STYLE_SUFFIX = ", 16:9 aspect ratio, suitable for a blog header image, high quality, professional"


def get_gemini_api_key():
    """Gemini APIキーを取得"""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        # config.pyからの読み込みを試みる
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from config import GEMINI_API_KEY
            key = GEMINI_API_KEY
        except (ImportError, AttributeError):
            pass
    return key


def get_article_files():
    """記事ファイルを番号順にソートして返す"""
    pattern = os.path.join(ARTICLES_DIR, "*.md")
    return sorted(glob.glob(pattern))


def get_article_number(filepath):
    """ファイルパスから記事番号を取得"""
    basename = os.path.basename(filepath)
    match = re.match(r"(\d+)_", basename)
    return int(match.group(1)) if match else 0


def get_article_key(filepath):
    """ファイルパスから記事キーを取得"""
    return os.path.splitext(os.path.basename(filepath))[0]


def get_title(filepath):
    """記事ファイルからタイトルを取得"""
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("# "):
                return line.lstrip("# ").strip()
    return ""


def generate_image(api_key, prompt, output_path):
    """Gemini APIで画像を生成して保存"""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    full_prompt = prompt + STYLE_SUFFIX

    print(f"  生成中... (プロンプト: {prompt[:60]}...)")

    response = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=full_prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )

    # レスポンスから画像データを抽出
    for part in response.candidates[0].content.parts:
        if part.inline_data is not None:
            image_data = part.inline_data.data
            with open(output_path, "wb") as f:
                f.write(image_data)
            print(f"  ✅ 保存: {output_path}")
            return True

    print("  ❌ 画像データが見つかりませんでした")
    return False


def list_articles():
    """記事一覧と画像生成状態を表示"""
    files = get_article_files()
    print(f"\n全{len(files)}本の記事:\n")
    for f in files:
        key = get_article_key(f)
        title = get_title(f)
        num = get_article_number(f)
        image_path = os.path.join(IMAGES_DIR, f"{key}.png")
        has_image = "✅" if os.path.exists(image_path) else "❌"
        has_prompt = "📝" if key in IMAGE_PROMPTS else "⚠️"
        print(f"  {num:2d}. [{has_image} 画像] [{has_prompt} プロンプト] {title}")
    print()


def generate_for_article(api_key, filepath):
    """1記事分の画像を生成"""
    key = get_article_key(filepath)
    title = get_title(filepath)
    num = get_article_number(filepath)

    print(f"\n── 記事 {num}: {title} ──")

    if key not in IMAGE_PROMPTS:
        print(f"  ⚠️ プロンプト未定義 ({key})")
        return False

    os.makedirs(IMAGES_DIR, exist_ok=True)
    output_path = os.path.join(IMAGES_DIR, f"{key}.png")

    if os.path.exists(output_path):
        print(f"  ⏭️ 既に存在: {output_path}")
        return True

    return generate_image(api_key, IMAGE_PROMPTS[key], output_path)


def main():
    parser = argparse.ArgumentParser(description="Note記事用アイキャッチ画像生成（Gemini API）")
    parser.add_argument("--article", type=int, help="特定の記事番号だけ生成")
    parser.add_argument("--list", action="store_true", help="記事一覧と画像状態を表示")
    parser.add_argument("--all", action="store_true", help="全記事の画像を生成")
    parser.add_argument("--new", action="store_true", help="新規記事（22〜26）の画像だけ生成")
    parser.add_argument("--force", action="store_true", help="既存画像を上書き")

    args = parser.parse_args()

    if args.list:
        list_articles()
        return

    api_key = get_gemini_api_key()
    if not api_key:
        print("❌ GEMINI_API_KEY が設定されていません")
        print("  export GEMINI_API_KEY='your-api-key'")
        print("  または config.py の GEMINI_API_KEY を設定してください")
        sys.exit(1)

    files = get_article_files()

    if args.article:
        # 特定の記事だけ
        target = [f for f in files if get_article_number(f) == args.article]
        if not target:
            print(f"❌ 記事番号 {args.article} が見つかりません")
            sys.exit(1)
        files = target
    elif args.new:
        # 新規記事だけ
        files = [f for f in files if get_article_number(f) >= 22]
    elif not args.all:
        print("使い方:")
        print("  python3 note_image_generator.py --list      # 一覧表示")
        print("  python3 note_image_generator.py --all       # 全記事の画像生成")
        print("  python3 note_image_generator.py --new       # 新規記事の画像生成")
        print("  python3 note_image_generator.py --article 22 # 特定記事の画像生成")
        return

    if args.force:
        # 既存画像を削除
        for f in files:
            key = get_article_key(f)
            img = os.path.join(IMAGES_DIR, f"{key}.png")
            if os.path.exists(img):
                os.remove(img)

    print("=" * 60)
    print("  Note記事 アイキャッチ画像生成")
    print(f"  対象: {len(files)}記事")
    print("=" * 60)

    success = 0
    failed = 0

    for f in files:
        try:
            if generate_for_article(api_key, f):
                success += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ❌ エラー: {e}")
            failed += 1

    print()
    print("=" * 60)
    print(f"  完了！ 成功: {success} / 失敗: {failed}")
    print(f"  画像保存先: {IMAGES_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
