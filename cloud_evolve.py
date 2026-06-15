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

# --- 対立軸テーマ（論争・引用を誘発）---
# 人間化改修(2026-06-15): これ「だけ」だと毎投稿が同じ煽りテンプレでbot臭くなる。
# 下の EXPERIENCE_THEMES と交互に使い、生成プロンプトも分ける。
THEMES = [
    "事務所所属 vs フリーランスのライバー、結局どっちが得か（対立軸）",
    "Pococha vs 17LIVE vs IRIAM、稼げるアプリ論争（対立軸）",
    "ライバー副業を会社にバレずにやる方法（ツッコミ歓迎の言い切り）",
    "「ライバーは楽して稼いでる」論への反論（噛みつき誘発）",
    "顔出しなしライバー vs 顔出しライバー、収入の現実差（対立軸）",
    "ライバー業界の月収格差はなぜ起こるか（強めの主張）",
    "ライバー事務所の取り分は搾取か投資か（業界論争）",
    "副業勢ライバー vs 専業ライバー、続くのはどっち（対立軸）",
    "20代女性が会社員辞めてライバー専業になるのはアリかナシか",
    "男性ライバーが稼げない説は本当か（少数派視点で反論）",
    "ライバー初月で稼げない人が99%辞める理由（言い切り）",
    "代理店ビジネスは稼げる/稼げない論争（実数字で殴る）",
    "ライブ配信は若い子のもの説に40代が反論（世代論争）",
    "イベント期間中の課金圧、ファンに頼るのはアリかナシか",
    "「楽しいから配信してる」勢 vs 「金のため」勢、どっちが伸びるか",
]

# --- 経験・一次情報テーマ（AIに書けない「中の人」ネタ）---
# たいたん＝Pococha歴4年・運営ダッシュボードで所属ライバーの成績が見える立場。
# 対立軸の煽りではなく、現場で見てきた具体的な観察・気づきを淡々と書く。
EXPERIENCE_THEMES = [
    "Pococha運営4年で見てきた『伸びる配信者』と『消える配信者』の分かれ目",
    "所属ライバーを見ていて気づいた、配信続く人の共通点（地味な習慣）",
    "ライバー始めた人が最初の1ヶ月でつまずくポイントと、その乗り越え方",
    "事務所代表として実際にやっているサポートの中身（誇張なし・等身大）",
    "配信現場でよく聞かれる質問に、4年見てきた立場から正直に答える",
    "ランクが上がる子が配信前後でやっている、目立たない準備",
    "副業でライバーをしている人が、無理なく続けられている工夫",
    "数字が伸び悩んだ時期の配信者が、どう立て直していったかの観察",
    "コメントが少ない配信を、コメントが増える配信に変えた小さな変化",
    "『顔出ししたくない』人が実際にどう配信を組み立てているか",
]

PROMPT_TEMPLATE = """あなたはX(Twitter)で「ライブ配信」「ライバー副業」「ライバー事務所」について発信しているアカウントの投稿を書きます。
目的は **インプレッション最大化** と **DM/LP流入**。そのために以下の収益構造を最大限利用します。

【X伸ばしの根幹原理（最重要）】
- Xの露出は「リプ欄を開かせた時間」「リプ数」「引用数」で決まる
- KPI: ①リプ欄を開かせる ②リプを書かせる ③引用させる
- そのために投稿には **意図的に「噛みつきたくなる隙」「ツッコミどころ」「断言」** を残す
- 完璧な情報を出し切らない。「続きはリプで」or「スレッドで答え」 で**リプ欄に誘導**する

【勝ちパターン3種（必ずどれかを使う）】
(A) **分割スレッド型** — 1ツイート目で強い問題提起・断言・ランキング予告で切る → リプライで答え/続きを書く
    例: 「ライバー事務所、99%が知らない裏側を全部書く ↓」→ 続きをスレッドで展開
(B) **対立軸・論争型** — ❌⭕や A vs B で立場をハッキリ取る。賛否両論を呼ぶ言い切り
    例: 「フリーで稼げる人は1割、残り9割は事務所入った方が早い。理由は3つ↓」
(C) **ツッコミどころ断言型** — わざと突っ込まれそうな極端な断言を入れる（事実ベースで）
    例: 「Pocochaで月10万行かない人、配信時間が足りないだけ」

【守るべきルール】
1. 出力は **必ずJSON配列**。各要素は **2〜4ツイートのスレッド配列**
2. 1ツイート目は120〜140文字（日本語全角）、強いフック。最後を「↓」「↓続く」「答えは下に」等で締めてリプ欄を開かせる
3. 2ツイート目以降は100〜140文字。具体ノウハウ・数字・箇条書きで本体を展開
4. 数字（金額・%・人数・時間）を最低1つ含める
5. 最終ツイートの末尾に **議論を呼ぶ問いかけ or 引用させる挑発** を入れる
   例: 「異論あれば引用で殴ってきてOK」「あなたはどっち派？」「これ反対する人おる？」
6. 絵文字は1スレッドにつき1〜2個まで。本文中の乱用は禁止
7. タメ口・断定調。「〜です／〜します」の丁寧語禁止
8. 宣伝臭・URL・事務所名は入れない
9. **「あるある」「人見知り」「エモい」系の内輪話は完全禁止**。論争・実数字・断言だけ
10. ブランド毀損になる過激ネタは禁止（性的・差別・違法・他社実名disり）。論争は「業界構造」「働き方」に限定

【データに基づく勝ちパターン（直近の分析）】
- 伸びる: 箇条書き5項目、❌⭕対比、具体数字、断言、リプ誘導
- 沈む: あるある、内輪話、抽象論、丁寧すぎる説明

テーマ: {theme}

{top_posts_context}

上記テーマで、3スレッド分の投稿案をJSONで出力してください。
出力フォーマット（**これ以外の文字を出力しない**、コードブロックも不要、純粋なJSONのみ）:
[
  ["1ツイート目（フック）", "2ツイート目", "3ツイート目"],
  ["1ツイート目", "2ツイート目", "3ツイート目", "4ツイート目"],
  ["1ツイート目", "2ツイート目"]
]
"""


EXPERIENCE_PROMPT_TEMPLATE = """あなたはX(Twitter)でライブ配信・ライバー事務所について発信しているアカウントの「中の人」です。
このアカウントの人物像：**Pococha歴4年。今はライバー事務所の代表で、所属ライバーの配信を日々見ている。**
今回は対立軸で煽る投稿ではなく、**現場で実際に見てきた等身大の気づき**を書きます。フォロワーに「この人は本物だ」と思わせるのが目的。

【このタイプの投稿が刺さる理由】
- AIや他のアカウントは一般論しか書けない。あなたは「4年見てきた具体的な場面」を書ける。ここが唯一の武器。
- 煽り・断言・ランキングではなく、**観察の解像度**で信頼を取る。

【守るべきルール】
1. 出力は **必ずJSON配列**。各要素は **2〜4ツイートのスレッド配列**
2. 1ツイート目は具体的な場面・観察から入る。フックは「煽り」ではなく「あ、それ分かる/それ知りたい」と思わせる具体性で作る
   良い例:「配信が続く子と辞める子、4年見てきて差が出るのは才能じゃなくて配信後の5分だった」
   悪い例:「99%が知らない裏側を全部書く↓」(←煽りテンプレ。今回は禁止)
3. 2ツイート目以降は具体的な行動・場面を描写する。抽象的な精神論にしない
4. **数字は、確実に言える範囲でだけ使う。盛らない・でっち上げない。** 数字が無くても「ある子は〜」「よく見るのは〜」と具体場面で語れば十分
5. 末尾は自然に終える。**「異論あれば引用で殴ってこい」「あなたはどっち派？」等の定型挑発は禁止。**
   問いかけるなら「みんなはどう？」程度の自然なトーン、もしくは静かに言い切って終わってもいい
6. タメ口・自然な語り口。ただし煽らない。先輩が後輩に話すくらいの温度
7. 絵文字は0〜1個。乱用禁止
8. 宣伝臭・URL・事務所名は入れない
9. **毎回同じ書き出し・同じ締めにしない。** スレッドごとに入り方を変える
10. 断定しすぎない。「〜なことが多い」「〜な子をよく見る」など、観察ベースの誠実な言い回しを混ぜる

テーマ: {theme}

{top_posts_context}

上記テーマで、3スレッド分の投稿案をJSONで出力してください。
出力フォーマット（**これ以外の文字を出力しない**、コードブロックも不要、純粋なJSONのみ）:
[
  ["1ツイート目", "2ツイート目", "3ツイート目"],
  ["1ツイート目", "2ツイート目"],
  ["1ツイート目", "2ツイート目", "3ツイート目", "4ツイート目"]
]
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


def _extract_json_array(text):
    """Geminiの応答から最初のJSON配列を抽出（コードフェンス・前置きを許容）"""
    import re
    # コードフェンス除去
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    # 最初の '[' から対応する ']' までを抜き出す
    start = text.find("[")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def generate_with_gemini(theme, top_posts, style="debate"):
    """Gemini AIでスレッド投稿を生成。返り値は List[List[str]]
    style: "debate"=対立軸・煽り型 / "experience"=経験・一次情報型
    """
    if not HAS_GEMINI or not GEMINI_API_KEY:
        print("[WARN] Gemini API未設定。スキップ。")
        return []

    top_posts_context = ""
    if top_posts:
        top_posts_context = "【参考: 伸びた過去の投稿】\n"
        for i, p in enumerate(top_posts[:5], 1):
            text_preview = p["text"][:80].replace("\n", " ")
            top_posts_context += f"{i}. {text_preview}...\n"

    template = EXPERIENCE_PROMPT_TEMPLATE if style == "experience" else PROMPT_TEMPLATE
    prompt = template.format(
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
                raw = response.text.strip()
                payload = _extract_json_array(raw)
                if not payload:
                    print(f"  [WARN] {model_name}: JSON配列が見つからない (試行{attempt+1})")
                    continue
                try:
                    threads = json.loads(payload)
                except json.JSONDecodeError as e:
                    print(f"  [WARN] {model_name}: JSON parse失敗 {e} (試行{attempt+1})")
                    continue

                # 構造バリデーション
                cleaned = []
                for th in threads:
                    if not isinstance(th, list):
                        continue
                    tweets = [t.strip() for t in th if isinstance(t, str) and t.strip()]
                    # 各ツイート 30〜260 文字（X上限280）でフィルタ
                    tweets = [t for t in tweets if 20 < len(t) < 270]
                    if 2 <= len(tweets) <= 5:
                        cleaned.append(tweets)
                if cleaned:
                    return cleaned
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

    # 重複防止: 既存の先頭ツイート(または text)の頭30文字をキー化
    def _head_key(post):
        if "thread" in post and post["thread"]:
            return post["thread"][0][:30]
        return post.get("text", "")[:30]

    existing_keys = {_head_key(p) for p in existing}
    # evo_NNN の最大番号から続きを採番（カウント方式だと衝突する）
    import re
    used_nums = [int(m.group(1)) for p in existing
                 if (m := re.match(r"evo_(\d+)$", p.get("id", "")))]
    next_id = (max(used_nums) + 1) if used_nums else 1
    new_count = 0

    # 3. テーマ選定: 経験型を多めに(2)、対立軸を控えめに(2)。
    #    人間化改修(2026-06-15): 以前は対立軸4テーマ=全投稿が煽りテンプレでbot臭かった。
    #    経験・一次情報型を半分入れて「中の人」感を出す。
    exp_themes = [("experience", t) for t in random.sample(EXPERIENCE_THEMES, 2)]
    deb_themes = [("debate", t) for t in random.sample(THEMES, 2)]
    selected = exp_themes + deb_themes
    random.shuffle(selected)
    selected_themes = [t for _, t in selected]  # レポート用

    for style, theme in selected:
        print(f"\n[{style}] テーマ: {theme}")
        threads = generate_with_gemini(theme, top_posts, style=style)

        for thread in threads:
            head = thread[0][:30]
            if head in existing_keys:
                print(f"  [SKIP] 重複: {head}...")
                continue

            existing.append({
                "id": f"evo_{next_id:03d}",
                "phase": "growth",
                "style": style,
                "thread": thread,
            })
            existing_keys.add(head)
            new_count += 1
            next_id += 1
            print(f"  ✅ 追加({len(thread)}T): {thread[0][:40]}...")

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
