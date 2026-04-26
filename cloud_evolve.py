"""
投稿自動進化スクリプト（Gemini AI版）
伸びた投稿パターンを分析 → Gemini AIで毎回ユニークな投稿を生成

テンプレ投稿はXアルゴリズムに嫌われるため、
毎週AIで新鮮なコンテンツを自動生成する
"""

import os
import json
import random
import sys
import time

import tweepy

try:
    from google import genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
POSTS_FILE = "posts/twitter_posts.json"

# 投稿テーマ（Geminiに渡すコンテキスト）
THEMES = [
    "ライブ配信初心者が最初の1ヶ月で経験するあるある",
    "ライブ配信を副業として始めるメリットとデメリット",
    "Pocochaで配信を始めた人の体験談風ストーリー",
    "配信者の収入のリアルな話（月0円〜月50万の幅）",
    "配信を続けられる人と辞める人の違い",
    "ライバー事務所の選び方（怪しい事務所の見分け方）",
    "スマホ1台で始められる副業としてのライブ配信",
    "地方在住でもライブ配信で成功できる理由",
    "配信で人見知りが克服できた話",
    "20代〜30代の手取り事情と副業の必要性",
    "在宅副業の種類比較（ライブ配信vs他の副業）",
    "配信者がリスナーとの距離感で悩む話",
    "イベント期間中のライバーの日常あるある",
    "配信を始めるのが怖い人への背中を押す言葉",
    "シングルマザーや主婦がライバーとして活躍する話",
]

PROMPT_TEMPLATE = """あなたはX(Twitter)で「ライブ配信の始め方」「副業としてのライバー」について発信しているアカウントの投稿を書きます。

【データに基づく必勝パターン（直近の分析結果）】
- 伸びる: ・箇条書き5項目、❌⭕対比、比較表、具体的な数字
- 沈む: 「人見知り」「リスナーとの距離感」等の内輪話、抽象論、エモ系つぶやき
- TOP1の構造例: 「副業禁止の会社にいる人へ／・ライブ配信は雑所得／・年間20万以下なら確定申告不要／・住民税を普通徴収に」(具体ノウハウ＋箇条書き5)

以下のルールを厳守してください：
1. 文字数は100〜130文字（日本語、全角）
2. 絵文字は冒頭か末尾に1個だけ。本文中は使わない
3. 改行を効果的に使い、読みやすくする
4. **必ず以下のいずれかの構造を使う**:
   (A) ・箇条書き5項目（必ず5つ、4つや3つは禁止）
   (B) ❌〜→⭕〜の対比（最低3組）
   (C) 表形式の比較（「Aは月3万、Bは月10万」のような具体比較）
5. **数字を必ず1つ以上入れる**（金額・時間・人数・%等）
6. **末尾に質問または呼びかけを入れる**（「あなたはどう？」「やってみない？」等／リプ喚起）
7. ハッシュタグは不要（後で自動付与される）
8. 宣伝臭は一切出さない。事務所名やURLは入れない
9. 「〜します」「〜です」の丁寧語は使わず、タメ口で書く
10. **禁止**: 「人見知り」「リスナーとの距離」「あるある」「〜な話」「〜なんよな」のような内輪向け・抽象つぶやき。実用ノウハウ・具体事例だけ書く
11. 過去の投稿と同じ表現は避ける（以下の既存投稿を参考）

テーマ: {theme}

{top_posts_context}

上記テーマで、新しいXの投稿を5つ書いてください。
各投稿は改行2つ（空行）で区切ってください。番号は付けないでください。
"""


def analyze_tweets():
    """過去の投稿を分析して伸びたパターンを特定する"""
    try:
        client = tweepy.Client(
            bearer_token=os.environ.get("TWITTER_BEARER_TOKEN", ""),
            consumer_key=os.environ.get("TWITTER_API_KEY", ""),
            consumer_secret=os.environ.get("TWITTER_API_SECRET", ""),
            access_token=os.environ.get("TWITTER_ACCESS_TOKEN", ""),
            access_token_secret=os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", ""),
        )

        me = client.get_me()
        tweets = client.get_users_tweets(
            id=me.data.id,
            max_results=50,
            tweet_fields=["public_metrics", "text"],
        )

        if not tweets.data:
            return []

        scored = []
        for t in tweets.data:
            m = t.public_metrics
            score = (
                m["like_count"] * 1
                + m["retweet_count"] * 3
                + m["reply_count"] * 2
                + m["impression_count"] * 0.001
            )
            scored.append({"text": t.text, "score": score})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:10]

    except Exception as e:
        print(f"Twitter API分析をスキップ（{type(e).__name__}: {e}）")
        return []


def generate_with_gemini(theme, top_posts):
    """Gemini AIで投稿を生成"""
    if not HAS_GEMINI or not GEMINI_API_KEY:
        print("[WARN] Gemini API未設定。スキップ。")
        return []

    top_posts_context = ""
    if top_posts:
        top_posts_context = "【参考: 伸びた過去の投稿】\n"
        for i, p in enumerate(top_posts[:5], 1):
            text_preview = p["text"][:80].replace("\n", " ")
            top_posts_context += f"{i}. {text_preview}...\n"

    prompt = PROMPT_TEMPLATE.format(
        theme=theme,
        top_posts_context=top_posts_context,
    )

    client = genai.Client(api_key=GEMINI_API_KEY)

    # リトライ（Gemini 503対策）
    # 2026-04: gemini-2.0-flash / 1.5-flash は deprecated/404。
    # 2.5-flash → 2.5-flash-lite → 3.1-flash-lite-preview の順にフォールバック。
    models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.1-flash-lite-preview"]
    for model_name in models:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                text = response.text.strip()
                # 空行で分割して個別の投稿に
                posts = [p.strip() for p in text.split("\n\n") if p.strip()]
                # 短すぎるもの・長すぎるものを除外
                posts = [p for p in posts if 30 < len(p) < 200]
                if posts:
                    return posts
            except Exception as e:
                print(f"  Gemini {model_name} 試行{attempt+1}: {e}")
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))

    return []


def main():
    # 1. 過去の投稿を分析
    top_posts = analyze_tweets()
    if top_posts:
        print(f"トップ投稿 {len(top_posts)}件を分析済み")
    else:
        print("過去投稿の分析なし（新規生成モード）")

    # 2. 既存投稿を読み込み
    with open(POSTS_FILE, "r", encoding="utf-8") as f:
        existing = json.load(f)

    existing_texts = {p.get("text", "")[:30] for p in existing}
    next_id = len(existing) + 1
    new_count = 0

    # 3. ランダムに3-4テーマを選んで生成
    selected_themes = random.sample(THEMES, min(4, len(THEMES)))

    for theme in selected_themes:
        print(f"\nテーマ: {theme}")
        posts = generate_with_gemini(theme, top_posts)

        for text in posts:
            # 重複チェック
            if text[:30] in existing_texts:
                print(f"  [SKIP] 重複: {text[:30]}...")
                continue

            # 番号付きの場合は除去
            import re
            text = re.sub(r"^\d+[\.\)）]\s*", "", text)

            existing.append({
                "id": f"evo_{next_id:03d}",
                "phase": "growth",
                "text": text,
            })
            existing_texts.add(text[:30])
            new_count += 1
            next_id += 1
            print(f"  ✅ 追加: {text[:40]}...")

    # 4. 保存
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=4)

    print(f"\n{new_count}件の新投稿を追加（合計: {len(existing)}件）")

    # 分析レポート保存
    os.makedirs("data", exist_ok=True)
    with open("data/evolution_report.json", "w", encoding="utf-8") as f:
        json.dump({
            "top_posts": top_posts[:5] if top_posts else [],
            "themes_used": selected_themes,
            "new_posts_added": new_count,
            "total_posts": len(existing),
        }, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
