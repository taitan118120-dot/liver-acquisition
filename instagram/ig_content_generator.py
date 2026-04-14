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

    # =====================================================================
    # 共通の品質ルール（保存・シェアされる高品質キャプションを生成するための型）
    # =====================================================================
    common_rules = f"""【絶対遵守の構成テンプレート】
以下の7ブロック構成を必ず守ること。各ブロックの間は空行1つで区切る。

①フック（1行目・最重要）
   - 【】で囲んだ短いキャッチ。15〜22文字。
   - 必ず以下のいずれかのパターンを使う:
     a) 数字 +「実は…」「9割が知らない」「やってはいけない」型
     b) 損失回避型「知らないと損する○○」「○○で失敗する人の共通点」
     c) ギャップ型「○○なのに△△」「未経験から○ヶ月で○万円」
   - 抽象的な美辞麗句や絵文字だらけのタイトルは禁止。

②共感の2行（読者の悩みを言語化）
   - 「○○って思ってませんか？」「こんな経験ないですか？」型
   - 1行目で悩みを提示、2行目で「わかります、私も同じでした」と寄り添う
   - 絵文字なし、淡々と短く

③結論（PREP法のP：1〜2行）
   - 「結論、○○です。」と言い切る
   - ふわっとした一般論ではなく、具体的な答えを先出しする

④根拠と具体例（数字・実体験を必ず1つ以上入れる）
   - 「事務所所属で平均○％アップ」「Pocochaの時給は最大○円」など具体数値
   - 元記事に数字があれば必ず拾う。なければ業界の一般値を使う
   - 3〜4行で簡潔に

⑤実践リスト（保存される最重要パート）
   - 「✅ ○○する」形式で4〜6項目
   - 各項目は1行25文字以内、動詞で終わる行動指示にする
   - 各項目の下に1行だけ補足（理由・コツ）を入れてOK
   - 抽象論NG。「明日からできる」レベルの具体性

⑥CTA（固定文）
   - 必ず以下の3行を改行込みで入れる（一字一句変えない）:
     ━━━━━━━━━━━━━━━
     ✨ {config.OFFICE_NAME}の無料相談はプロフィール（@taitan_pro）のリンクから
     ━━━━━━━━━━━━━━━

⑦保存促進＋ハッシュタグ
   - 「📌 後で見返せるように保存推奨」の1行を入れる
   - その後に空行をはさんでハッシュタグを以下の比率で出す:
     ・大ボリューム(投稿100万件以上): 4個 例 #ライバー #副業 #ライブ配信 #在宅ワーク
     ・中ボリューム(10万〜100万): 8個 例 #ライバー募集 #Pococha #ポコチャ #副業女子 #ライバー事務所 #ライバーになりたい #スマホ副業 #フリーランス
     ・スモール/ニッチ(〜10万): 6個 例 #ライバーデビュー #ポコチャ初心者 #時間ダイヤ #ライバーママ #副業始めたい #タイタンプロ
   - 計18個。記事内容に合わせて入れ替えて構わないが、必ずこのボリューム別構成。
   - ハッシュタグは1行にまとめず、改行で大→中→小の3グループに分ける。

【厳守事項】
- 全体の文字数は1200〜1700文字（ベスト）。2200文字を超えない。
- 絵文字は1ブロックにつき最大1個。フック行と実践リストの先頭以外では使わない。
   許可絵文字のみ: ✨📌✅━ あとは🎯💡のみOK。😌🤗😊💕🚀💰📈🌟など顔文字・装飾系は禁止。
- URL（https://... lin.ee/... 等）絶対に書かない。リンクは「プロフィールから」のみ。
- LINE IDや@から始まる識別子は @taitan_pro 以外書かない。
- 「絶対稼げる」「必ず儲かる」など断定的な誇大表現を避ける（景表法対策）
- 元記事の文章を丸コピーしない。要約・再構成すること。
- 事務所名は {config.OFFICE_NAME}（混入させる場合もこの表記）。
- 出力はキャプション本文のみ。前置き「以下に作成しました」等は不要。
"""

    if is_remix:
        prompt = f"""あなたは月100万Instagram投稿を量産するライバー業界専門コピーライターです。
以下の素材を元に、まったく新しい切り口でInstagramフィード投稿のキャプションを作成してください。
元の文章は参考程度にし、視点・表現・例え話を変えて再構成すること。

{common_rules}

【素材】
{article['body']}
"""

    elif is_twitter:
        prompt = f"""あなたは月100万Instagram投稿を量産するライバー業界専門コピーライターです。
以下の短いX投稿を素材に、保存価値の高いInstagramフィード投稿用キャプションに膨らませてください。
ツイートの主張を軸にしつつ、根拠・具体例・実践ステップを補強すること。

{common_rules}

【元のX投稿】
{article['body']}
"""

    else:
        prompt = f"""あなたは月100万Instagram投稿を量産するライバー業界専門コピーライターです。
以下のブログ記事を素材に、Instagramフィード投稿用の高品質キャプションを作成してください。
ブログをただ要約するのではなく、Instagram読者（20〜30代女性中心、スマホで流し見）が
「保存して後で読みたい」と思う構成と密度に再編集すること。

{common_rules}

【記事タイトル】
{article['title']}

【記事本文】
{article['body']}
"""

    import time as _time

    # 503対策: モデルフォールバック付き指数バックオフリトライ
    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash"]
    for model_name in models_to_try:
        max_retries = 5
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(
                        temperature=0.85,
                    ),
                )
                text = response.text.strip()
                return _polish_caption(text)
            except Exception as e:
                is_server_error = "503" in str(e) or "UNAVAILABLE" in str(e) or "500" in str(e)
                if attempt < max_retries - 1 and is_server_error:
                    wait = min(15 * (2 ** attempt), 120)  # 15, 30, 60, 120秒
                    print(f"  [RETRY] {model_name} キャプション生成失敗({e})、{wait}秒後にリトライ ({attempt+1}/{max_retries})...")
                    _time.sleep(wait)
                elif attempt < max_retries - 1:
                    wait = 10 * (attempt + 1)
                    print(f"  [RETRY] {model_name} キャプション生成失敗({e})、{wait}秒後にリトライ ({attempt+1}/{max_retries})...")
                    _time.sleep(wait)
                else:
                    print(f"  [WARNING] {model_name} で{max_retries}回失敗、次のモデルを試行...")
                    break  # 次のモデルへフォールバック

    raise RuntimeError("全モデルでキャプション生成に失敗しました")


# =====================================================================
# キャプション後処理（プロンプトに従わない部分を機械的に補正・検証）
# =====================================================================

# 残してよい絵文字（プロンプトの「許可絵文字」と一致させる）
_ALLOWED_EMOJIS = set("✨📌✅━🎯💡【】")

# 削除したい装飾絵文字（プロンプトで禁止しているもの＋頻出のフリクション）
_BANNED_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"   # symbols & pictographs
    "\U0001F600-\U0001F64F"   # emoticons
    "\U0001F680-\U0001F6FF"   # transport
    "\U0001F700-\U0001F77F"
    "\U0001F900-\U0001F9FF"   # supplemental symbols
    "\U0001FA70-\U0001FAFF"
    "\u2600-\u26FF"             # misc symbols
    "\u2700-\u27BF"             # dingbats
    "]"
)

# 必ず入れたい固定CTAブロック
_REQUIRED_CTA = (
    "━━━━━━━━━━━━━━━\n"
    f"✨ {config.OFFICE_NAME}の無料相談はプロフィール（@taitan_pro）のリンクから\n"
    "━━━━━━━━━━━━━━━"
)

_SAVE_HINT = "📌 後で見返せるように保存推奨"

_URL_RE = re.compile(r"https?://\S+|lin\.ee/\S+|bit\.ly/\S+", re.IGNORECASE)
_HASHTAG_RE = re.compile(r"#[\wぁ-んァ-ヶー一-龥0-9_]+")


def _strip_banned_emojis(text):
    """許可外絵文字を全削除（許可リストの文字は残す）"""
    def _repl(m):
        ch = m.group(0)
        return ch if ch in _ALLOWED_EMOJIS else ""
    return _BANNED_EMOJI_RE.sub(_repl, text)


def _polish_caption(text):
    """生成キャプションを品質基準に合わせて補正する。
    - URL/外部リンクの除去
    - 禁止絵文字の削除
    - 固定CTAの強制差し込み
    - 保存促進行の確保
    - 末尾ハッシュタグの個数チェック（不足時は警告）
    - 文字数オーバーの軽量カット
    """
    if not text:
        return text

    # 1. URL除去
    cleaned = _URL_RE.sub("", text)

    # 2. 禁止絵文字除去
    cleaned = _strip_banned_emojis(cleaned)

    # 3. 連続空行を最大1つに圧縮
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    # 4. ハッシュタグを末尾から抽出（後で再付与するため一度切り離す）
    lines = cleaned.split("\n")
    tag_start = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if not line:
            continue
        if _HASHTAG_RE.search(line) and not re.search(r"[。！？]", line):
            tag_start = i
        else:
            break
    body_part = "\n".join(lines[:tag_start]).rstrip()
    tag_part = "\n".join(lines[tag_start:]).strip()

    # 5. CTAが含まれているかチェック。不足/破損していれば差し替え
    has_cta = (
        f"{config.OFFICE_NAME}の無料相談はプロフィール" in body_part
        and "━━━" in body_part
    )
    if not has_cta:
        # 既存の弱いCTA行を除去
        body_part = re.sub(
            r"(?m)^.*(無料相談|プロフィール.*リンク|DM.*お問い合わせ|お気軽に).*$",
            "",
            body_part,
        )
        body_part = re.sub(r"\n{3,}", "\n\n", body_part).rstrip()
        body_part += "\n\n" + _REQUIRED_CTA

    # 6. 保存促進行
    if _SAVE_HINT not in body_part and _SAVE_HINT not in tag_part:
        body_part += "\n\n" + _SAVE_HINT

    # 7. ハッシュタグの個数チェック
    tags = _HASHTAG_RE.findall(tag_part)
    if len(tags) < 12:
        # 不足時はライバー業界の汎用補完タグを足す
        fallback_tags = [
            "#ライバー", "#副業", "#ライブ配信", "#在宅ワーク",
            "#ライバー募集", "#Pococha", "#ポコチャ", "#ライバー事務所",
            "#ライバーになりたい", "#スマホ副業", "#副業女子", "#フリーランス",
            "#ライバーデビュー", "#ポコチャ初心者", "#副業始めたい",
            "#タイタンプロ", "#おうち時間", "#夢を叶える",
        ]
        seen = set(tags)
        for t in fallback_tags:
            if t not in seen:
                tags.append(t)
                seen.add(t)
            if len(tags) >= 18:
                break
        # 大/中/小の3行に分けて再構築
        tag_part = (
            " ".join(tags[:4]) + "\n"
            + " ".join(tags[4:12]) + "\n"
            + " ".join(tags[12:18])
        )

    polished = body_part.rstrip() + "\n\n" + tag_part.strip()

    # 8. 2200文字制限（Instagram上限）
    if len(polished) > 2150:
        # 本文を末尾から削って収める
        excess = len(polished) - 2150
        body_part = body_part[: max(0, len(body_part) - excess - 20)].rstrip()
        polished = body_part + "\n\n" + tag_part.strip()

    return polished


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

    # Imagen 4.0で画像生成（503対策: 指数バックオフリトライ）
    max_retries = 5
    for attempt in range(max_retries):
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
            is_server_error = "503" in str(e) or "UNAVAILABLE" in str(e) or "500" in str(e)
            if attempt < max_retries - 1:
                wait = min(15 * (2 ** attempt), 120) if is_server_error else 15 * (attempt + 1)
                print(f"  [RETRY] Imagen 4.0失敗({e})、{wait}秒後にリトライ ({attempt+1}/{max_retries})...")
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
