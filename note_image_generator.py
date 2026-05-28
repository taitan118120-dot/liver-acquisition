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
    "37_ライバー月収平均2026": "A flat illustration of a bar chart showing rising income across multiple streaming platforms with yen coin icons and a smiling person checking the chart on a smartphone, navy blue and gold color scheme, financial professional, no text",
    "38_ライバー代理店副業始め方ステップ": "A flat illustration of a person climbing numbered staircase steps from a smartphone toward a goal flag, agency partnership icons floating, gradient blue to green, journey theme, no text",
    "44_初配信コツ": "A flat illustration of a nervous but determined person about to press a glowing live broadcast button on a smartphone, soft hopeful sunrise colors with hearts and stars rising, encouraging atmosphere, pastel pink and orange, no text",
    "45_ライバー時給": "A flat illustration of a clock face merging with yen coins and a smartphone showing live streaming, hourly rate concept with rising arrow, teal and gold color scheme, no text",
    "46_ライバー向いてる人": "A flat illustration of diverse people silhouettes with a bright spotlight highlighting one in the middle holding a smartphone, personality compatibility concept, warm purple and yellow, no text",
    "47_副業月5万在宅": "A flat illustration of a cozy home desk setup with a laptop and smartphone, coins and yen banknotes stacked, plants and coffee, work-from-home theme, soft beige and green, no text",
    "48_Pocochaライバー始め方完全ガイド": "A flat illustration of a smartphone surrounded by Pococha-style live streaming icons (microphone, hearts, gifts) with a cheerful starting line and rising path, modern and bright, pink and purple gradient, no text",
    "49_Pocochaダイヤ換金完全ガイド": "A flat illustration of diamond gems flowing from a smartphone into a bank ATM with yen banknotes coming out, calculator and clock icons floating around, purple and gold color scheme, modern and clean, no text",
    "50_TikTokLIVE収益化完全ガイド": "A flat illustration of a smartphone with the TikTok-style live streaming interface, gift icons floating with coins and dollar signs, music notes and hearts, vibrant pink red and black color scheme, energetic, no text",
    "51_ライバー経費完全リスト75項目": "A flat illustration of receipts and a calculator with checkmark icons, a notebook listing categorized expenses, microphone and ring light next to it, professional accounting theme, green and white color scheme, no text",
    "52_Pocochaメーター期間完全攻略": "A flat illustration of a meter or speedometer gauge filling up to a target, with a smartphone showing live streaming and stars rising upward, sense of achievement, orange and yellow color scheme, motivational, no text",
    "53_IRIAMVライバー始め方完全ガイド": "A flat illustration of a cute anime-style virtual avatar character on a smartphone screen waving cheerfully, sparkles and a microphone nearby, a person in shadow behind controlling the avatar, pastel purple and pink color scheme, modern V-tuber theme, no text",
    "54_ライブ配信緊張克服メンタル術": "A flat illustration of a person taking a deep calming breath in front of a smartphone with a soft glow, peaceful aura with leaves and stars floating, before and after concept showing transformation from nervous to confident, soft blue and green color scheme, calming, no text",
    "55_PocochaS帯なり方": "A flat illustration of a person climbing a glowing staircase toward a giant golden S-rank badge with a smartphone showing live streaming and floating diamonds, achievement and ascension theme, royal purple and gold color scheme, dramatic motivational atmosphere, no text",
    "56_副業ライバーおすすめ": "A flat illustration of a person at a home desk smiling while holding a smartphone with live streaming icons, yen coins and clock showing flexible hours, plants and cozy lighting, side-hustle freedom theme, soft mint green and warm orange color scheme, no text",
    "57_ライバーデビュー準備": "A flat illustration of a checklist being marked off next to live streaming gear (ring light, microphone, smartphone on tripod), opening curtains revealing a stage with sparkles, pre-debut excitement theme, fresh sky blue and pastel pink color scheme, no text",
    "58_ふわっち稼げる": "A flat illustration of a smartphone with cute bubble-like floating items (gifts, hearts, coins) rising upward, a relaxed casual streamer figure, friendly community atmosphere, soft pastel sky blue and yellow color scheme, gentle and approachable, no text",
    "59_ライバーなるには": "A flat illustration of a signpost with arrows pointing to a smartphone glowing with a live stream, a determined person walking the path with a backpack, requirements icons (ID, age, app) floating along the way, journey theme, navy blue and orange sunrise color scheme, no text",
    "77_PocochaC帯御新規攻略": "A minimal flat illustration of a smartphone glowing with a live stream icon, a path leading toward it with small silhouette of a friendly streamer waving from inside, tiny visitor figures walking along the path with hearts floating above them, a signpost with welcome arrows, mountains and rising sun in the background, journey and hospitality theme, navy blue and orange sunrise color scheme, simple flat vector style, no text, no human face on liver, no organ illustration",
    "78_ライバー事務所メリットデメリット": "A flat illustration of two balanced scales, one side holding a building icon representing an agency with star badges and a support hand, the other side showing a solo figure with a smartphone, golden light illuminating the agency side, neutral navy blue and gold color scheme, professional and informative, no text",
    "79_PocochaB帯攻略": "A flat illustration of a glowing staircase ascending from a lower C-band zone to a bright B-band banner at the top, a determined silhouette streamer climbing with a smartphone, diamond gems and hearts floating upward, Pococha-style reward icons along the steps, purple and gold color scheme, motivational achievement theme, no text",
    "80_TikTokLIVEギフト増やし方": "A flat illustration of a smartphone screen with a TikTok LIVE interface, colorful gift boxes and rose icons floating outward with sparkle effects, coins and hearts rising around the phone, a crowd of small viewer silhouettes sending gifts, vibrant red pink and gold color scheme, celebratory and energetic, no text",
    "81_Pococha同接増やし方": "A flat illustration of a smartphone showing a live stream with a rising bar chart of viewer count overlaid, small silhouette figures walking toward the screen from multiple directions, hearts and chat bubbles filling the space, a megaphone broadcasting waves, green and blue gradient color scheme, community growth theme, no text",
    "82_TikTokLIVE伸びない原因": "A flat illustration of a TikTok LIVE smartphone screen with a magnifying glass revealing hidden growth blockers as puzzle pieces, a path forward lit by a lightbulb, small streamer silhouette looking at the solved puzzle, dark navy to bright teal gradient symbolizing transformation from stuck to growing, no text",
    "83_Pocochaコアファン増えない": "A flat illustration of a smartphone live streaming screen with one bright glowing star representing a core fan being gently held by warm hands, surrounded by smaller hearts and floating star sparkles growing in number, a soft pathway leading from many small dots to a single shining star, warm purple and gold color palette, nurturing and growth theme, modern minimal style, no text",
    "84_Pocochaコメント来ない": "A flat illustration of a smartphone live streaming screen split in two halves, left side shows empty silent speech bubbles and a quiet streamer silhouette, right side shows the same streamer surrounded by colorful active chat bubbles and engaged viewers, before-and-after transformation concept, soft blue transitioning to bright orange color palette, friendly and approachable, no text",
    "85_Pocochaフォロワー増えない": "A flat illustration of a smartphone displaying a follower count rising with an upward arrow graph, small profile avatar icons appearing one after another from below the phone like a stream joining the count, gentle confetti and plus signs floating, bright pink and white color palette, energetic and uplifting growth theme, modern flat design, no text",
    "86_Pococha始めたばかり人来ない": "A flat illustration of a beginner Japanese livestreamer at a cozy desk with a smartphone on a tripod and a ring light, looking hopeful and determined, a calendar on the wall behind shows day 1 to day 30 marked with small stars showing progress, soft sunrise light coming through a window, warm pastel orange and cream color palette, encouraging first-month-journey theme, no text",
    "87_ライバー小規模企業共済": "A flat illustration of a smartphone showing a live stream connected to a growing piggy bank and a shield, gold coins and yen symbols flowing safely into the piggy bank, a small upward growth arrow and a calculator nearby, concept of an individual business owner building a safe retirement fund while saving on tax, navy blue and gold color palette, trustworthy financial and self-employed theme, modern minimal flat design, no text",
    "88_小規模企業共済加入条件始め方": "A flat illustration of a clear step-by-step path with numbered stepping stones leading from a business registration document to a smartphone and a piggy bank with a shield, a checklist with checkmarks and a pen, an open business owner figure walking the path, concept of enrollment steps for a mutual aid pension, fresh teal and gold color palette, onboarding and how-to-start theme, modern flat design, no text",
    "89_ライバー老後資金小規模企業共済iDeCo比較": "A flat illustration of three labeled jars or pillars of different heights representing retirement savings options side by side, a balance scale weighing them, coins and a small growth chart with an upward trend, a thoughtful self-employed person comparing them with a smartphone, concept of comparing pension and retirement fund options for the future, deep navy blue and warm gold color palette, comparison and long-term planning theme, modern minimal flat design, no text",
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
