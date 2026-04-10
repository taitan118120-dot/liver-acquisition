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

POSTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ig_posts.json")
IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
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

    from google import genai

    client = genai.Client(api_key=config.GEMINI_API_KEY)

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
- LINE友だち追加URL: {config.CONTACT_LINE}（必ずこの完全なURLをそのまま記載すること。短縮や @ID 形式にしない）
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
- LINE友だち追加URL: {config.CONTACT_LINE}（必ずこの完全なURLをそのまま記載すること。短縮や @ID 形式にしない）

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
- LINE友だち追加URL: {config.CONTACT_LINE}（必ずこの完全なURLをそのまま記載すること。短縮や @ID 形式にしない）

記事タイトル: {article['title']}

記事本文:
{article['body']}

キャプションのみを出力してください。"""

    import time as _time
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            return response.text.strip()
        except Exception as e:
            if attempt < 2:
                wait = 10 * (attempt + 1)
                print(f"  [RETRY] キャプション生成失敗({e})、{wait}秒後にリトライ...")
                _time.sleep(wait)
            else:
                raise


# =====================================================================
# カテゴリ別ビジュアル体系（全投稿を統一感のある高品質デザインに）
# =====================================================================
# 各カテゴリ: badge / badge_color / bg_palette / accent / marker / category_icons
CATEGORY_THEMES = {
    "BEGINNER": {
        "badge": "BEGINNER",
        "badge_bg": (70, 120, 180),          # 深いブルー
        "bg_palette": [(224, 236, 250), (230, 240, 252), (240, 232, 250)],
        "blob_colors": [
            (180, 210, 250, 110),
            (200, 220, 252, 100),
            (220, 225, 250, 110),
            (200, 240, 250, 100),
        ],
        "accent": (255, 215, 100, 210),      # ゴールド系マーカー
        "divider": (100, 150, 210, 255),
        "title_color": (30, 45, 85),
        "catch_color": (95, 115, 155),
        "brand_color": (130, 155, 200, 255),
    },
    "EARN": {
        "badge": "EARN",
        "badge_bg": (200, 145, 40),          # 深いゴールド
        "bg_palette": [(255, 242, 212), (255, 232, 210), (255, 224, 228)],
        "blob_colors": [
            (255, 215, 150, 120),
            (255, 225, 170, 110),
            (255, 205, 180, 110),
            (255, 235, 190, 110),
        ],
        "accent": (255, 200, 120, 220),
        "divider": (220, 160, 60, 255),
        "title_color": (70, 45, 20),
        "catch_color": (135, 100, 60),
        "brand_color": (185, 140, 70, 255),
    },
    "AGENCY": {
        "badge": "AGENCY",
        "badge_bg": (110, 80, 145),          # モーブパープル
        "bg_palette": [(238, 228, 250), (244, 226, 248), (251, 228, 240)],
        "blob_colors": [
            (220, 195, 250, 110),
            (240, 210, 248, 100),
            (230, 200, 245, 110),
            (250, 225, 245, 100),
        ],
        "accent": (255, 220, 140, 215),
        "divider": (175, 130, 205, 255),
        "title_color": (55, 35, 80),
        "catch_color": (120, 95, 145),
        "brand_color": (155, 120, 180, 255),
    },
    "GROW": {
        "badge": "GROW",
        "badge_bg": (55, 140, 110),          # 深いミント
        "bg_palette": [(222, 246, 232), (232, 248, 226), (245, 252, 228)],
        "blob_colors": [
            (180, 230, 200, 110),
            (200, 240, 210, 110),
            (215, 245, 200, 100),
            (235, 250, 215, 100),
        ],
        "accent": (255, 225, 130, 215),
        "divider": (90, 170, 130, 255),
        "title_color": (25, 60, 45),
        "catch_color": (85, 130, 100),
        "brand_color": (110, 160, 130, 255),
    },
    "LIFESTYLE": {
        "badge": "LIFESTYLE",
        "badge_bg": (205, 100, 130),         # ローズピンク
        "bg_palette": [(255, 228, 232), (255, 218, 230), (248, 224, 245)],
        "blob_colors": [
            (255, 200, 215, 120),
            (255, 215, 225, 110),
            (250, 210, 235, 110),
            (255, 225, 240, 100),
        ],
        "accent": (255, 220, 140, 220),
        "divider": (225, 140, 165, 255),
        "title_color": (85, 30, 55),
        "catch_color": (140, 85, 105),
        "brand_color": (200, 125, 155, 255),
    },
}

# キーワード → カテゴリ（先に一致したものを採用、順序重要）
CATEGORY_RULES = [
    # AGENCY（事務所関連を最優先）
    ("AGENCY", ["事務所", "マネージャー", "契約", "移籍", "代理店", "面接", "怪しい"]),
    # EARN（稼ぎ・収入）
    ("EARN", ["稼", "収入", "副業", "ダイヤ", "還元", "お金", "確定申告", "月10万", "月5万"]),
    # BEGINNER（始め方・属性）
    ("BEGINNER", ["始め方", "初心者", "機材", "主婦", "大学生", "学生", "30代", "始める", "未経験"]),
    # GROW（スキル・成長）
    ("GROW", ["コツ", "ランク", "ネタ", "ファン", "イベント", "伸び", "コラボ", "スケジュール", "攻略", "上げ"]),
    # LIFESTYLE（ライフスタイル・メンタル）
    ("LIFESTYLE", ["辞めたい", "メンタル", "顔出し", "バレ", "男性", "容姿", "将来", "比較", "市場", "アプリ"]),
]

# キャッチコピー辞書（先に一致したキーが採用されるため、具体的なキーワードを先に配置）
CATCHCOPY_MAP = {
    # --- 最も具体的な複合キーワード（優先） ---
    "怪しい": "安全な事務所の見分け方",
    "契約": "損しない契約書チェックポイント",
    "面接": "事務所面接のよくある質問と答え方",
    "代理店": "ライバー事務所と代理店の違い",
    "ランキング": "人気事務所の選び方ガイド",
    "移籍": "事務所移籍のベストタイミング",
    "マネージャー": "プロのサポートで成長が加速",
    "確定申告": "ライバーのお金まわり完全ガイド",
    "還元率": "知らないと損する報酬のしくみ",
    "時間ダイヤ": "報酬のしくみを徹底解説",
    "ダイヤ": "報酬のしくみを徹底解説",
    "フリー比較": "事務所と個人、どっちが得？",
    "上げ方": "最短でランクを上げる戦略",
    "伸びない": "伸び悩みを突破する方法",
    "辞めたい": "もう悩まない！次のステップへ",
    "メンタル": "配信疲れを防ぐセルフケア",
    "副業バレ": "本業にバレずに副業する方法",
    "バレない": "身バレを防いで安心配信",
    "バレ": "身バレを防いで安心配信",
    "顔出し": "顔出しなしでも稼げる方法",
    "容姿": "見た目じゃない！トーク力が武器",
    "始め方": "スマホ1台で今日からスタート",
    "主婦": "ママでもできる在宅ワーク",
    "大学生": "学生×ライバーの新しい生き方",
    "30代": "30代から始める新しい挑戦",
    "男性": "男性ライバーの可能性は無限大",
    "機材": "必要なのはスマホだけ",
    "スケジュール": "ムリなく続けるコツ",
    "イベント": "イベント攻略で一気にランクUP",
    "コラボ": "コラボで一気にファン拡大",
    "ファン": "ファンに愛されるライバーに",
    "ネタ": "配信が楽しくなるアイデア集",
    "初心者": "未経験でも大丈夫",
    "アプリ比較": "アプリ選びで差がつく",
    "将来": "ライブ配信市場はまだまだ成長中",
    "副業": "おうち時間を収入に変える",
    "収入": "自分らしく稼ぐ新しい働き方",
    "稼": "好きなことで収入GET",
    "コツ": "人気ライバーの秘密を公開",
    "ランク": "トップライバーへの道",
    "比較": "アプリ選びで差がつく",
    # --- 最終フォールバック（ジェネリック） ---
    "事務所": "あなたに合う事務所が見つかる",
}


def _detect_category(title):
    """タイトルからカテゴリを判定。どれにも当たらなければ BEGINNER をデフォルト。"""
    for cat, keywords in CATEGORY_RULES:
        if any(k in title for k in keywords):
            return cat
    return "BEGINNER"


def _build_image_prompt(article):
    """記事内容に応じた画像生成プロンプトを構築。
    戻り値: (prompt, short_title, catchcopy, category)
    """
    title = article["title"]

    catchcopy = "あなたの魅力を、収入に変えよう"
    for keyword, copy in CATCHCOPY_MAP.items():
        if keyword in title:
            catchcopy = copy
            break

    # タイトルを短く整形（数字プレフィックスを除去）
    short_title = re.sub(r"^\d+_", "", title)

    category = _detect_category(title)

    # ⚠️ 画像モデル（Imagen / Gemini）は日本語テキストを正しく描画できないため、
    # プロンプトでは「テキストを一切入れない背景イラスト」のみ生成させる。
    # タイトル・キャッチコピーは後段の _overlay_text_on_image() でPillowで描画する。
    return f"""Create an aesthetic Instagram post background illustration (1080x1080, square).

STYLE:
- Korean-cafe-style, soft pastel illustration (lavender, mint green, peach pink, cream yellow)
- Flat-design cute elements: smartphone, stars, hearts, speech bubbles, sparkles, flowers
- Hand-drawn decorative lines, dotted borders, or floral frames
- A single light gradient or solid pastel background
- Generous empty space in the CENTER of the image (this is critical — text will be overlaid there later)
- Aesthetic that young women in their 20s would save and share

LAYOUT:
- Decorative elements arranged around the edges/corners, NEVER in the center
- The center 60% of the image must be clean, light, and unobstructed
- Soft and airy, not cluttered

STRICT RULES:
- ABSOLUTELY NO TEXT, NO LETTERS, NO CHARACTERS of any language (no Japanese, no English, no numbers, no symbols that look like letters)
- No realistic human faces or photorealistic people
- No dark colors, no busy compositions
- No watermarks, no logos""", short_title, catchcopy, category


def _create_pastel_background(size=1080, seed=None, category="BEGINNER"):
    """Pillowでカテゴリ別パステル装飾背景を生成（API不要・完全ローカル）。
    Imagen失敗時のフォールバック、および崩壊画像の修復に使用。"""
    import random as _rd
    from PIL import Image, ImageDraw, ImageFilter

    rng = _rd.Random(seed)

    theme = CATEGORY_THEMES.get(category, CATEGORY_THEMES["BEGINNER"])
    palette = theme["bg_palette"]
    blob_colors = theme["blob_colors"]

    img = Image.new("RGB", (size, size), palette[0])

    # --- 1. 対角グラデーション ---
    grad = Image.new("RGB", (size, size), palette[0])
    for y in range(size):
        t = y / size
        # 3点補間
        if t < 0.5:
            ratio = t * 2
            c = tuple(int(palette[0][k] * (1 - ratio) + palette[1][k] * ratio) for k in range(3))
        else:
            ratio = (t - 0.5) * 2
            c = tuple(int(palette[1][k] * (1 - ratio) + palette[2][k] * ratio) for k in range(3))
        ImageDraw.Draw(grad).line([(0, y), (size, y)], fill=c)
    img = grad

    draw = ImageDraw.Draw(img, "RGBA")

    # --- 2. 大きなぼかし円（雰囲気作り、コーナー配置） ---
    blob_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(blob_layer)
    corners = [(0, 0), (size, 0), (0, size), (size, size)]
    for (cx, cy), col in zip(corners, blob_colors):
        r = rng.randint(260, 360)
        bdraw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    blob_layer = blob_layer.filter(ImageFilter.GaussianBlur(radius=60))
    img = Image.alpha_composite(img.convert("RGBA"), blob_layer).convert("RGB")

    draw = ImageDraw.Draw(img, "RGBA")

    # --- 3. 小さな装飾（星・ドット・ハート風円） ---
    # コーナー領域のみ（中央のテキストエリアは避ける）
    accent_colors = [
        (255, 180, 200, 220),
        (255, 215, 180, 220),
        (200, 190, 240, 220),
        (180, 220, 205, 220),
        (255, 235, 180, 220),
    ]
    forbidden_cx, forbidden_cy = size // 2, size // 2
    forbidden_r = int(size * 0.32)  # 中央を避ける

    def _in_forbidden(x, y):
        return (x - forbidden_cx) ** 2 + (y - forbidden_cy) ** 2 < forbidden_r ** 2

    placed = 0
    attempts = 0
    while placed < 45 and attempts < 400:
        attempts += 1
        x = rng.randint(30, size - 30)
        y = rng.randint(30, size - 30)
        if _in_forbidden(x, y):
            continue
        color = rng.choice(accent_colors)
        kind = rng.choice(["dot", "dot", "dot", "ring", "star"])
        if kind == "dot":
            r = rng.randint(4, 12)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=color)
        elif kind == "ring":
            r = rng.randint(10, 22)
            draw.ellipse([x - r, y - r, x + r, y + r],
                         outline=color, width=3)
        else:  # star = simple 4-point (plus sign)
            r = rng.randint(6, 14)
            draw.line([(x - r, y), (x + r, y)], fill=color, width=3)
            draw.line([(x, y - r), (x, y + r)], fill=color, width=3)
        placed += 1

    # --- 4. 外周の薄い点線フレーム ---
    frame_color = (255, 255, 255, 180)
    margin = 24
    dot_r = 3
    gap = 18
    for x in range(margin, size - margin, gap):
        draw.ellipse([x - dot_r, margin - dot_r, x + dot_r, margin + dot_r], fill=frame_color)
        draw.ellipse([x - dot_r, size - margin - dot_r, x + dot_r, size - margin + dot_r], fill=frame_color)
    for y in range(margin, size - margin, gap):
        draw.ellipse([margin - dot_r, y - dot_r, margin + dot_r, y + dot_r], fill=frame_color)
        draw.ellipse([size - margin - dot_r, y - dot_r, size - margin + dot_r, y + dot_r], fill=frame_color)

    return img


def _wrap_japanese(text, max_chars_per_line):
    """日本語テキストを賢く折り返す。
    - カタカナ連続の途中では切らない
    - 助詞・句読点の後ろで優先的に切る
    - 英数字連続の途中では切らない
    """
    if len(text) <= max_chars_per_line:
        return [text]

    def _is_kana(ch):
        return "\u30A0" <= ch <= "\u30FF" or ch == "ー"

    def _is_alnum(ch):
        return ch.isascii() and ch.isalnum()

    # 2文字助詞・熟語（途中で切らない）
    two_char_atoms = {
        "から", "まで", "より", "への", "には", "では", "とは", "でも",
        "って", "けど", "のに", "ので", "から", "ため", "こと", "もの",
    }

    # 切断してはいけない境界: カタカナ↔カタカナ / 英数字↔英数字 / 2文字助詞の内部
    def _is_breakable_at(i):
        if i <= 0 or i >= len(text):
            return False
        prev, nxt = text[i - 1], text[i]
        if _is_kana(prev) and _is_kana(nxt):
            return False
        if _is_alnum(prev) and _is_alnum(nxt):
            return False
        # 2文字助詞の途中ではない
        if i - 1 >= 0 and i + 1 <= len(text):
            if text[i - 1:i + 1] in two_char_atoms:
                return False
        return True

    # 優先的に切りたい位置: 助詞の後、句読点の後
    particles = set("をにはがでとへもやのか、。！？・")
    def _priority_at(i):
        if i <= 0 or i >= len(text):
            return 0
        return 2 if text[i - 1] in particles else 1

    lines = []
    start = 0
    while start < len(text):
        end_ideal = start + max_chars_per_line
        if end_ideal >= len(text):
            lines.append(text[start:])
            break

        # end_ideal 付近で最適な break point を探す
        # 1. end_ideal から後ろ方向に、優先度の高い位置を探す
        best = None
        for i in range(end_ideal, max(start + 1, end_ideal - max_chars_per_line // 2), -1):
            if _is_breakable_at(i):
                pr = _priority_at(i)
                if best is None or pr > best[1]:
                    best = (i, pr)
                if pr >= 2:
                    break

        if best is None:
            # fallback: ハード切断（本当に切れる位置が見つからなければ理想位置）
            cut = end_ideal
        else:
            cut = best[0]

        lines.append(text[start:cut])
        start = cut

    return lines


def _get_font(weight, size):
    """Noto Sans JP（可変フォント）を指定ウェイトで読み込む。"""
    from PIL import ImageFont

    vf_path = os.path.join(FONTS_DIR, "NotoSansJP-VF.ttf")
    if os.path.exists(vf_path):
        font = ImageFont.truetype(vf_path, size=size)
        try:
            # 可変フォントのウェイト軸を設定（100-900）
            font.set_variation_by_axes([weight])
        except Exception:
            pass
        return font

    # フォールバック（macOSシステムフォント）
    for p in [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size=size)

    return ImageFont.load_default()


def _overlay_text_on_image(image_path, title, catchcopy, category="BEGINNER", brand="@taitan_pro"):
    """生成された背景画像にPillowで日本語タイトル＋キャッチコピーを合成。
    Instagramで保存されるカルーセル投稿を意識したバズる構成:
      [カテゴリバッジ] → [HUGEタイトル（マーカーハイライト）] → [区切り] → [キャッチコピー] → [ブランド名]
    """
    from PIL import Image, ImageDraw, ImageFilter

    theme = CATEGORY_THEMES.get(category, CATEGORY_THEMES["BEGINNER"])

    img = Image.open(image_path).convert("RGBA")
    W, H = img.size

    # --- 1. 中央に半透明白パネル＋影 ---
    panel_margin_x = int(W * 0.07)
    panel_margin_y = int(H * 0.15)
    panel_box = [panel_margin_x, panel_margin_y, W - panel_margin_x, H - panel_margin_y]

    # 影（下方向にオフセット）
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    shadow_offset = 14
    sdraw.rounded_rectangle(
        [panel_box[0] + 4, panel_box[1] + shadow_offset,
         panel_box[2] + 4, panel_box[3] + shadow_offset],
        radius=int(W * 0.045),
        fill=(150, 120, 140, 70),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=18))
    img = Image.alpha_composite(img, shadow)

    # 白パネル
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(panel)
    pdraw.rounded_rectangle(panel_box, radius=int(W * 0.045), fill=(255, 255, 255, 232))
    img = Image.alpha_composite(img, panel)

    draw = ImageDraw.Draw(img, "RGBA")

    # --- 2. カテゴリバッジ（パネル上部、ピル型） ---
    badge_font = _get_font(weight=800, size=int(W * 0.028))
    badge_text = theme["badge"]
    b_bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
    b_w = b_bbox[2] - b_bbox[0]
    b_h = b_bbox[3] - b_bbox[1]
    badge_pad_x = int(W * 0.028)
    badge_pad_y = int(W * 0.013)
    badge_w = b_w + 2 * badge_pad_x
    badge_h = b_h + 2 * badge_pad_y + 4
    badge_x = (W - badge_w) // 2
    badge_y = panel_margin_y + int(H * 0.055)
    badge_color = theme["badge_bg"] + (255,)
    draw.rounded_rectangle(
        [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
        radius=badge_h // 2, fill=badge_color,
    )
    draw.text(
        (badge_x + badge_pad_x, badge_y + badge_pad_y - 2),
        badge_text, font=badge_font, fill=(255, 255, 255, 255),
    )

    # --- 3. タイトル準備 ---
    inner_width = (W - 2 * panel_margin_x) - int(W * 0.10)

    max_chars = 10 if len(title) > 11 else max(len(title), 8)
    title_lines = _wrap_japanese(title, max_chars)

    if len(title_lines) == 1:
        title_size = int(W * 0.115)
    elif len(title_lines) == 2:
        title_size = int(W * 0.095)
    else:
        title_size = int(W * 0.075)

    title_font = _get_font(weight=900, size=title_size)

    for _ in range(12):
        max_line_w = max(
            draw.textbbox((0, 0), line, font=title_font)[2] for line in title_lines
        )
        if max_line_w <= inner_width:
            break
        title_size = int(title_size * 0.92)
        title_font = _get_font(weight=900, size=title_size)

    line_height = int(title_size * 1.22)
    total_title_h = line_height * len(title_lines)

    # --- 4. キャッチコピー準備 ---
    catch_size = int(W * 0.038)
    catch_font = _get_font(weight=700, size=catch_size)
    catch_lines = _wrap_japanese(catchcopy, 18)
    catch_line_h = int(catch_size * 1.5)
    total_catch_h = catch_line_h * len(catch_lines)

    divider_gap = int(W * 0.035)

    # 全体ブロックの中心を、バッジより下かつブランドより上の領域の中央に配置
    brand_font_size = int(W * 0.026)
    brand_bottom_margin = int(H * 0.065)
    content_top = badge_y + badge_h + int(H * 0.04)
    content_bottom = H - panel_margin_y - brand_bottom_margin - brand_font_size - 10
    content_h = content_bottom - content_top

    block_total_h = total_title_h + divider_gap * 2 + int(W * 0.008) + total_catch_h
    block_start_y = content_top + (content_h - block_total_h) // 2

    # --- 5. タイトル描画（マーカーハイライトを最後の行の背景に敷く） ---
    y = block_start_y
    title_color = theme["title_color"]
    highlight_color = theme["accent"]

    for i, line in enumerate(title_lines):
        bbox = draw.textbbox((0, 0), line, font=title_font)
        line_w = bbox[2] - bbox[0]
        line_h = bbox[3] - bbox[1]
        x = (W - line_w) // 2

        # マーカー（最終行にだけ敷く、目を引く）
        if i == len(title_lines) - 1:
            mk_pad_x = int(title_size * 0.12)
            mk_top = y + int(title_size * 0.55)
            mk_bot = y + int(title_size * 1.05)
            draw.rectangle(
                [x - mk_pad_x, mk_top, x + line_w + mk_pad_x, mk_bot],
                fill=highlight_color,
            )

        draw.text((x, y), line, font=title_font, fill=title_color,
                  stroke_width=2, stroke_fill=(255, 255, 255, 255))
        y += line_height

    # --- 6. 区切り（ドット3つ） ---
    divider_y = y + divider_gap // 2
    dot_r = int(W * 0.008)
    dot_gap = int(W * 0.035)
    dot_color = theme["divider"]
    for k in (-1, 0, 1):
        cx = W // 2 + k * dot_gap
        draw.ellipse([cx - dot_r, divider_y - dot_r, cx + dot_r, divider_y + dot_r],
                     fill=dot_color)

    # --- 7. キャッチコピー描画 ---
    catch_y = divider_y + int(catch_size * 1.1)
    catch_color = theme["catch_color"]
    for line in catch_lines:
        bbox = draw.textbbox((0, 0), line, font=catch_font)
        line_w = bbox[2] - bbox[0]
        x = (W - line_w) // 2
        draw.text((x, catch_y), line, font=catch_font, fill=catch_color,
                  stroke_width=1, stroke_fill=(255, 255, 255, 255))
        catch_y += catch_line_h

    # --- 8. ブランド名（パネル下部） ---
    brand_font = _get_font(weight=700, size=brand_font_size)
    bbox = draw.textbbox((0, 0), brand, font=brand_font)
    brand_w = bbox[2] - bbox[0]
    brand_x = (W - brand_w) // 2
    brand_y = H - panel_margin_y - brand_bottom_margin - brand_font_size
    draw.text((brand_x, brand_y), brand, font=brand_font,
              fill=theme["brand_color"])

    # 保存（PNG）
    img.convert("RGB").save(image_path, "PNG", optimize=True)
    print(f"  テキスト合成完了: {os.path.basename(image_path)} "
          f"[{category}] (title={len(title_lines)}行 @{title_size}px)")


def generate_image(article, index, dry_run=False):
    """Gemini Imagen APIで投稿用画像を生成"""
    os.makedirs(IMAGES_DIR, exist_ok=True)
    image_path = os.path.join(IMAGES_DIR, f"post_{index:03d}.png")

    if dry_run:
        print(f"  [DRY RUN] 画像生成スキップ: {image_path}")
        return None

    from google import genai

    client = genai.Client(api_key=config.GEMINI_API_KEY)

    prompt, short_title, catchcopy, category = _build_image_prompt(article)
    print(f"  タイトル: {short_title} / キャッチ: {catchcopy} / [{category}]")

    import time as _time

    # Imagen 4.0で画像生成（リトライ付き）
    for attempt in range(3):
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
                try:
                    _overlay_text_on_image(image_path, short_title, catchcopy, category=category)
                except Exception as e:
                    print(f"  [WARNING] テキスト合成失敗: {e}")
                return image_path
        except Exception as e:
            if attempt < 2:
                wait = 15 * (attempt + 1)
                print(f"  [RETRY] Imagen 4.0失敗({e})、{wait}秒後にリトライ...")
                _time.sleep(wait)
            else:
                print(f"  [WARNING] Imagen 4.0生成失敗、フォールバック: {e}")

    # フォールバック: Gemini 2.5 Flashで画像生成
    for fb_model in ["gemini-2.5-flash", "gemini-2.0-flash"]:
        try:
            print(f"  [FALLBACK] {fb_model} で画像生成を試行...")
            response = client.models.generate_content(
                model=fb_model,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                ),
            )
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.data:
                        with open(image_path, "wb") as f:
                            f.write(part.inline_data.data)
                        print(f"  画像生成完了 (フォールバック {fb_model}): {image_path}")
                        try:
                            _overlay_text_on_image(image_path, short_title, catchcopy, category=category)
                        except Exception as e:
                            print(f"  [WARNING] テキスト合成失敗: {e}")
                        return image_path
        except Exception as e:
            print(f"  [WARNING] {fb_model} 画像生成失敗: {e}")

    print("  [WARNING] Imagen/Gemini画像生成失敗 → Pillowフォールバック背景を使用")
    try:
        bg = _create_pastel_background(size=1080, seed=hash(short_title) & 0xFFFFFFFF, category=category)
        bg.save(image_path)
        _overlay_text_on_image(image_path, short_title, catchcopy, category=category)
        print(f"  フォールバック画像生成完了: {image_path}")
        return image_path
    except Exception as e:
        print(f"  [ERROR] フォールバック背景生成も失敗: {e}")
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

        # 画像パスを相対パスで保存（GitHub Actions互換）
        relative_image_path = None
        if image_path:
            relative_image_path = os.path.relpath(image_path, os.path.dirname(os.path.dirname(IMAGES_DIR)))

        post = {
            "id": f"ig_auto_{len(existing_posts) + len(new_posts):03d}",
            "source_file": article["filename"],
            "source_type": article["source"],
            "title": article["title"],
            "caption": caption,
            "image_path": relative_image_path,
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
