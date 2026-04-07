"""
Instagram投稿コンテンツ生成（Gemini API）

ブログ記事 or X投稿を元に、Instagram向けのキャプション＋画像を自動生成する。

ソース:
  - blog: blog/articles_note/ のマークダウン記事
  - twitter: posts/twitter_posts.json のツイート
  - auto: 未使用のブログ記事 → 未使用のツイート → 全投稿済みなら再生成

使い方:
  python ig_content_generator.py --generate                # ブログから生成
  python ig_content_generator.py --generate --source twitter  # X投稿から生成
  python ig_content_generator.py --generate --source auto     # 自動選択
  python ig_content_generator.py --dry-run                    # 確認のみ
"""

import argparse
import base64
import glob
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

POSTS_FILE = os.path.join(os.path.dirname(__file__), "ig_posts.json")
IMAGES_DIR = os.path.join(os.path.dirname(__file__), "images")
BLOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "blog", "articles_note")
TWITTER_POSTS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "posts", "twitter_posts.json")


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
            "body": body[:3000],
            "source": "blog",
        })

    return articles


def load_twitter_posts():
    """posts/twitter_posts.json からツイートを読み込み、Instagram用ソースとして返す"""
    if not os.path.exists(TWITTER_POSTS_FILE):
        print("[WARNING] twitter_posts.json が見つかりません。")
        return []

    with open(TWITTER_POSTS_FILE, "r", encoding="utf-8") as f:
        tweets = json.load(f)

    articles = []
    for tweet in tweets:
        if tweet.get("phase") != "growth":
            continue

        text = tweet["text"]
        # スレッドがあれば結合
        if "thread" in tweet:
            text = text + "\n\n" + "\n\n".join(tweet["thread"])

        articles.append({
            "filename": f"twitter_{tweet['id']}.json",
            "title": text.split("\n")[0][:50],  # 1行目をタイトルに
            "body": text,
            "source": "twitter",
        })

    return articles


def get_available_sources(source_type="auto"):
    """未使用のコンテンツソースを取得（auto時は優先順位付き）"""
    existing_posts = load_posts()
    existing_ids = {p["source_file"] for p in existing_posts}

    if source_type == "blog":
        articles = load_blog_articles()
        unused = [a for a in articles if a["filename"] not in existing_ids]
        return unused

    if source_type == "twitter":
        tweets = load_twitter_posts()
        unused = [t for t in tweets if t["filename"] not in existing_ids]
        return unused

    # auto: ブログ未使用 → ツイート未使用 → 全て使い切ったら再生成用にリセット
    blog_articles = load_blog_articles()
    blog_unused = [a for a in blog_articles if a["filename"] not in existing_ids]

    if blog_unused:
        print(f"[SOURCE] ブログ記事から生成（未使用{len(blog_unused)}件）")
        return blog_unused

    twitter_posts = load_twitter_posts()
    twitter_unused = [t for t in twitter_posts if t["filename"] not in existing_ids]

    if twitter_unused:
        print(f"[SOURCE] X投稿から生成（未使用{len(twitter_unused)}件）")
        return twitter_unused

    # 全て使い切った → リミックスモード（既存コンテンツを組み合わせて新規生成）
    print("[SOURCE] 全ソース使用済み → リミックスモードで新規生成")
    all_sources = blog_articles + twitter_posts
    if all_sources:
        selected = random.sample(all_sources, min(3, len(all_sources)))
        # リミックス用にファイル名を変更して重複回避
        remix_count = sum(1 for p in existing_posts if "remix" in p.get("source_file", ""))
        for i, s in enumerate(selected):
            s["filename"] = f"remix_{remix_count + i:03d}_{s['filename']}"
            s["remix"] = True
        return selected

    return []


def generate_caption(article, dry_run=False):
    """Gemini APIでInstagram用キャプションを生成"""
    if dry_run:
        return f"【{article['title']}】\n\nこの記事の要約キャプションがここに入ります。\n\n#ライバー #ライブ配信 #副業 #在宅ワーク"

    import google.generativeai as genai

    genai.configure(api_key=config.GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")

    is_remix = article.get("remix", False)
    is_twitter = article.get("source") == "twitter"

    if is_remix:
        prompt = f"""以下の内容を元に、新しい切り口でInstagramのフィード投稿用キャプションを作成してください。
元の内容とは違う視点・表現で書き直してください。

ルール:
- 最大2200文字以内
- 冒頭に目を引くタイトル行（【】で囲む）
- 箇条書きで要点を3〜5個
- 最後にCTA（「詳しくはプロフィールのリンクから」など）
- ハッシュタグは15〜20個（ライバー、副業、在宅ワーク系）
- 絵文字は控えめに（1行に1個まで）
- 事務所名: {config.OFFICE_NAME}
- LINE: {config.CONTACT_LINE}
- 元の文章をそのままコピーしない。新しい表現で。

元の内容:
{article['body']}

キャプションのみを出力してください。"""

    elif is_twitter:
        prompt = f"""以下のX（Twitter）投稿をInstagramのフィード投稿用キャプションに変換してください。
短いツイートをInstagram向けに膨らませてください。

ルール:
- 最大2200文字以内
- 冒頭に目を引くタイトル行（【】で囲む）
- ツイートの内容を深掘りして詳しく説明
- 箇条書きで要点を3〜5個
- 最後にCTA（「詳しくはプロフィールのリンクから」など）
- ハッシュタグは15〜20個（ライバー、副業、在宅ワーク系）
- 絵文字は控えめに（1行に1個まで）
- 事務所名: {config.OFFICE_NAME}
- LINE: {config.CONTACT_LINE}

X投稿:
{article['body']}

キャプションのみを出力してください。"""

    else:
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

    from google import genai

    client = genai.Client(api_key=config.GEMINI_API_KEY)

    prompt = f"""Create a clean, modern Instagram post image for a Japanese live streaming talent agency.
Topic: {article['title']}
Style: Minimalist, pastel colors, professional.
Include subtle Japanese text elements.
Square format (1080x1080).
Do NOT include any human faces or realistic people.
Use abstract shapes, icons, or illustrations instead."""

    # Imagen 4.0で画像生成
    try:
        response = client.models.generate_images(
            model="imagen-4.0-generate-001",
            prompt=prompt,
            config=genai.types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="1:1",
            ),
        )

        if response.generated_images:
            image_data = response.generated_images[0].image.image_bytes
            with open(image_path, "wb") as f:
                f.write(image_data)
            print(f"  画像生成完了: {image_path}")
            return image_path
    except Exception as e:
        print(f"  [WARNING] Imagen 4.0生成失敗、フォールバック: {e}")

    # フォールバック: Gemini 2.5 Flash Imageで画像生成
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=f"Generate a simple, clean illustration for an Instagram post about: {article['title']}. "
            "Use pastel colors, minimalist style. Square format. No text overlay.",
            config=genai.types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    with open(image_path, "wb") as f:
                        f.write(part.inline_data.data)
                    print(f"  画像生成完了 (フォールバック): {image_path}")
                    return image_path
    except Exception as e:
        print(f"  [ERROR] 画像生成失敗: {e}")

    return None


def generate_posts(source_type="auto", count=1, dry_run=False):
    """指定ソースからInstagram投稿を生成"""
    available = get_available_sources(source_type)

    if not available:
        print("[ERROR] 利用可能なコンテンツソースがありません。")
        return []

    # 必要数だけ取得
    targets = available[:count]
    print(f"\n{len(targets)}件の投稿を生成します...\n")

    existing_posts = load_posts()
    new_posts = []

    for i, article in enumerate(targets):
        source_label = {"blog": "ブログ", "twitter": "X投稿"}.get(article["source"], "リミックス")
        remix_tag = " [REMIX]" if article.get("remix") else ""
        print(f"[{i+1}/{len(targets)}] {source_label}{remix_tag}: {article['title']}")

        # キャプション生成
        caption = generate_caption(article, dry_run=dry_run)
        print(f"  キャプション: {caption[:80]}...")

        # 画像生成
        image_path = generate_image(article, len(existing_posts) + len(new_posts), dry_run=dry_run)

        post = {
            "id": f"ig_auto_{len(existing_posts) + len(new_posts):03d}",
            "source_file": article["filename"],
            "source_type": article["source"],
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


def generate_all(source_type="auto", dry_run=False):
    """全ソースからInstagram投稿を一括生成（後方互換用）"""
    available = get_available_sources(source_type)
    if not available:
        print("[ERROR] 利用可能なコンテンツソースがありません。")
        return []
    return generate_posts(source_type=source_type, count=len(available), dry_run=dry_run)


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
    parser.add_argument("--generate", action="store_true", help="投稿を生成")
    parser.add_argument("--source", choices=["blog", "twitter", "auto"], default="auto",
                        help="コンテンツソース（default: auto）")
    parser.add_argument("--count", type=int, default=0,
                        help="生成数（0=全件）")
    parser.add_argument("--dry-run", action="store_true", help="生成内容を確認（APIを叩かない）")
    parser.add_argument("--list", action="store_true", help="生成済み投稿一覧を表示")
    args = parser.parse_args()

    if args.list:
        posts = load_posts()
        for p in posts:
            status = "投稿済" if p["posted"] else "未投稿"
            src = p.get("source_type", "blog")
            print(f"  [{status}] [{src}] {p['id']}: {p['title']}")
        print(f"\n合計: {len(posts)}件 / 未投稿: {sum(1 for p in posts if not p['posted'])}件")
    elif args.generate or args.dry_run:
        if args.count > 0:
            generate_posts(source_type=args.source, count=args.count, dry_run=args.dry_run)
        else:
            generate_all(source_type=args.source, dry_run=args.dry_run)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
