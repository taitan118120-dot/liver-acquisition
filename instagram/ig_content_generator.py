"""
Instagram投稿コンテンツ生成（Gemini API）

ブログ記事を元に、Instagram向けのキャプション＋画像を自動生成する。
--generate で全記事から投稿を生成、--dry-run で生成内容を確認。
"""

import argparse
import base64
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

POSTS_FILE = os.path.join(os.path.dirname(__file__), "ig_posts.json")
IMAGES_DIR = os.path.join(os.path.dirname(__file__), "images")
BLOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "blog", "articles_note")


def load_blog_articles():
    """blog/articles_note/ からマークダウン記事を読み込む"""
    articles = []
    for path in sorted(glob.glob(os.path.join(BLOG_DIR, "*.md"))):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # frontmatterからタイトルを抽出
        title_match = re.search(r'^title:\s*"?(.+?)"?\s*$', content, re.MULTILINE)
        title = title_match.group(1) if title_match else os.path.basename(path).replace(".md", "")

        # frontmatterを除いた本文
        body = re.sub(r"^---.*?---\s*", "", content, flags=re.DOTALL).strip()

        articles.append({
            "filename": os.path.basename(path),
            "title": title,
            "body": body[:3000],  # Geminiに送る分量を制限
        })

    return articles


def generate_caption(article, dry_run=False):
    """Gemini APIでInstagram用キャプションを生成"""
    if dry_run:
        return f"【{article['title']}】\n\nこの記事の要約キャプションがここに入ります。\n\n#ライバー #ライブ配信 #副業 #在宅ワーク"

    import google.generativeai as genai

    genai.configure(api_key=config.GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = f"""以下のブログ記事をInstagramのフィード投稿用キャプションに変換してください。

ルール:
- 最大2200文字以内
- 冒頭に目を引くタイトル行（【】で囲む）
- 箇条書きで要点を3〜5個
- 最後にCTA（「詳しくはプロフィールのリンクから」など）
- ハッシュタグは15〜20個（ライバー、副業、在宅ワーク系）
- 絵文字は控えめに（1行に1個まで）
- 事務所名: {config.OFFICE_NAME}
- LINE: {config.CONTACT_LINE}

記事タイトル: {article['title']}

記事本文:
{article['body']}

キャプションのみを出力してください。"""

    response = model.generate_content(prompt)
    return response.text.strip()


def generate_image(article, index, dry_run=False):
    """Gemini Imagen APIで投稿用画像を生成"""
    os.makedirs(IMAGES_DIR, exist_ok=True)
    image_path = os.path.join(IMAGES_DIR, f"post_{index:03d}.png")

    if dry_run:
        print(f"  [DRY RUN] 画像生成スキップ: {image_path}")
        return None

    import google.generativeai as genai

    genai.configure(api_key=config.GEMINI_API_KEY)

    imagen = genai.ImageGenerationModel("imagen-3.0-generate-002")

    prompt = f"""Create a clean, modern Instagram post image for a Japanese live streaming talent agency.
Topic: {article['title']}
Style: Minimalist, pastel colors, professional.
Include subtle Japanese text elements.
Square format (1080x1080).
Do NOT include any human faces or realistic people.
Use abstract shapes, icons, or illustrations instead."""

    try:
        result = imagen.generate_images(
            prompt=prompt,
            number_of_images=1,
            aspect_ratio="1:1",
        )

        if result.images:
            image_data = result.images[0]._image_bytes
            with open(image_path, "wb") as f:
                f.write(image_data)
            print(f"  画像生成完了: {image_path}")
            return image_path
    except Exception as e:
        print(f"  [WARNING] Imagen生成失敗、フォールバック: {e}")

    # フォールバック: Geminiテキストモデルで画像生成
    try:
        model = genai.GenerativeModel("gemini-2.0-flash-exp")
        response = model.generate_content(
            f"Generate a simple, clean illustration for an Instagram post about: {article['title']}. "
            "Use pastel colors, minimalist style. Square format. No text overlay.",
            generation_config={"response_mime_type": "image/png"},
        )
        if response.parts:
            for part in response.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    with open(image_path, "wb") as f:
                        f.write(part.inline_data.data)
                    print(f"  画像生成完了 (フォールバック): {image_path}")
                    return image_path
    except Exception as e:
        print(f"  [ERROR] 画像生成失敗: {e}")

    return None


def generate_all(dry_run=False):
    """全ブログ記事からInstagram投稿を生成"""
    articles = load_blog_articles()
    if not articles:
        print("[ERROR] ブログ記事が見つかりません。")
        return

    print(f"ブログ記事 {len(articles)}件 からInstagram投稿を生成します...\n")

    # 既存の投稿を読み込み
    existing_posts = load_posts()
    existing_ids = {p["source_file"] for p in existing_posts}

    new_posts = []
    for i, article in enumerate(articles):
        if article["filename"] in existing_ids:
            print(f"[SKIP] {article['filename']} は生成済み")
            continue

        print(f"[{i+1}/{len(articles)}] {article['title']}")

        # キャプション生成
        caption = generate_caption(article, dry_run=dry_run)
        print(f"  キャプション: {caption[:80]}...")

        # 画像生成
        image_path = generate_image(article, len(existing_posts) + len(new_posts), dry_run=dry_run)

        post = {
            "id": f"ig_auto_{len(existing_posts) + len(new_posts):03d}",
            "source_file": article["filename"],
            "title": article["title"],
            "caption": caption,
            "image_path": image_path,
            "posted": False,
        }
        new_posts.append(post)
        print()

    if new_posts and not dry_run:
        all_posts = existing_posts + new_posts
        save_posts(all_posts)
        print(f"\n{len(new_posts)}件の投稿を生成しました → {POSTS_FILE}")
    elif dry_run:
        print(f"\n[DRY RUN] {len(new_posts)}件の投稿を生成予定")

    return new_posts


def load_posts():
    """投稿キューを読み込み"""
    if not os.path.exists(POSTS_FILE):
        return []
    with open(POSTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_posts(posts):
    """投稿キューを保存"""
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Instagram投稿コンテンツ生成（Gemini API）")
    parser.add_argument("--generate", action="store_true", help="全記事から投稿を生成")
    parser.add_argument("--dry-run", action="store_true", help="生成内容を確認（APIを叩かない）")
    parser.add_argument("--list", action="store_true", help="生成済み投稿一覧を表示")
    args = parser.parse_args()

    if args.list:
        posts = load_posts()
        for p in posts:
            status = "投稿済" if p["posted"] else "未投稿"
            print(f"  [{status}] {p['id']}: {p['title']}")
        print(f"\n合計: {len(posts)}件")
    elif args.generate or args.dry_run:
        generate_all(dry_run=args.dry_run)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
