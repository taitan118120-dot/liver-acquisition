"""
投稿自動進化スクリプト
伸びた投稿を分析 → パターン特定 → 新しい投稿を自動生成

毎週実行して投稿ライブラリを進化させ続ける
"""

import os
import json
import random
import tweepy


# 投稿パターン別の深掘りテンプレート
EVOLUTION_TEMPLATES = {
    # あるある系が伸びた → あるある深掘り
    "あるある": [
        "配信始めて{期間}の人あるある\n\n{箇条書き}\n\nわかる人RT",
        "ライバーが絶対経験すること\n\n{箇条書き}\n\n全部当てはまったら立派なライバー",
        "配信者の{場面}あるある\n\n{箇条書き}\n\n共感したらRT",
    ],
    # 質問系が伸びた → 質問深掘り
    "質問": [
        "配信者さんに聞きたい\n\n{質問文}？\n\n❤️ {選択肢A}\n🔁 {選択肢B}\n💬 リプで教えて",
        "ぶっちゃけ\n\n{質問文}？\n\nガチで気になるから教えて",
        "これ気になるんだけど\n\n{質問文}\n\n自分は{自分の意見}だと思ってる",
    ],
    # リスト系が伸びた → リスト深掘り
    "リスト": [
        "{テーマ}\n\n{箇条書き}\n\nこれ知らない人多すぎる",
        "{テーマ}を正直に書く\n\n{箇条書き}\n\n綺麗事じゃなくてリアルな話",
        "{テーマ}\n\n❌やっちゃダメ\n{NG箇条書き}\n\n⭕これやって\n{OK箇条書き}",
    ],
    # ストーリー系が伸びた → ストーリー深掘り
    "ストーリー": [
        "{人物}の話\n\n{ビフォー}\n\n{期間}後\n\n{アフター}\n\n{教訓}",
        "これ実話なんだけど\n\n{エピソード}\n\n{オチ}",
    ],
    # ぶっちゃけ系が伸びた → 本音深掘り
    "ぶっちゃけ": [
        "ぶっちゃけ{テーマ}\n\n{本音}\n\nこれ言うと怒られるかもだけど事実",
        "正直に言う\n\n{テーマ}\n\n{箇条書き}\n\nでも{ポジティブ転換}",
        "みんな言わないけど{テーマ}\n\n{本音}\n\n知ってた？",
    ],
    # 副業比較系（新規層向け）
    "副業比較": [
        "{テーマ}を比較してみた\n\n{箇条書き}\n\n始めやすさで選ぶなら答え出てる",
        "副業選びで迷ってる人へ\n\n{箇条書き}\n\nどれが自分に合うか考えてみて",
    ],
    # お金リアル系（共感で広がる）
    "お金リアル": [
        "{テーマ}\n\n{本音}\n\nみんなどうしてる？",
        "{テーマ}\n\n{箇条書き}\n\n共感したら❤️",
    ],
}

# パターン別の具体的な投稿ネタ
EVOLUTION_CONTENT = {
    "あるある": [
        {
            "期間": "1ヶ月",
            "箇条書き": "・枠開けるの毎回緊張する\n・BGM何にするか30分迷う\n・コメント1個で嬉しすぎる\n・配信切った後に反省会始まる\n・寝る前に明日のネタ考える",
        },
        {
            "期間": "半年",
            "箇条書き": "・初見さんへの挨拶がプロ化する\n・配信しない日にソワソワする\n・リスナーの名前全員覚えてる\n・他の配信者の枠行くと職業病出る\n・「いつもの時間」が確立される",
        },
        {
            "場面": "深夜配信",
            "箇条書き": "・テンション謎に高くなる\n・リスナーと距離感バグる\n・翌日の声がガラガラ\n・「あと10分で終わる」→1時間経過\n・布団の中から配信しがち",
        },
        {
            "場面": "イベント期間中",
            "箇条書き": "・配信時間が倍になる\n・リスナーに感謝しすぎて泣く\n・順位気にしすぎて寝れない\n・終わった後の虚無感やばい\n・でも次もやりたくなる",
        },
    ],
    "質問": [
        {"質問文": "配信中に一番嬉しいコメントってどれ", "選択肢A": "初見です！", "選択肢B": "毎日来てます"},
        {"質問文": "配信何時間くらいやってる", "選択肢A": "1時間以内", "選択肢B": "2時間以上"},
        {"質問文": "顔出しと声だけどっちが楽", "選択肢A": "顔出し", "選択肢B": "声だけ"},
        {"質問文": "配信始めたきっかけって何", "自分の意見": "「暇だったから」が一番多い"},
    ],
    "リスト": [
        {
            "テーマ": "配信3ヶ月目にやるべきこと",
            "箇条書き": "・配信時間を固定する\n・SNSで告知する\n・他のライバーの配信を見る\n・自分の配信を録画して見返す\n・コラボを1回やってみる",
        },
        {
            "テーマ": "リスナーが離れる原因TOP5",
            "箇条書き": "1. 配信時間がバラバラ\n2. コメント拾わない\n3. ネガティブな発言が多い\n4. 内輪ノリすぎる\n5. 投げ銭の催促",
        },
        {
            "テーマ": "Pocochaで最初にやること",
            "NG箇条書き": "・いきなりランク上げ\n・長時間配信\n・他の枠で営業",
            "OK箇条書き": "・毎日30分配信\n・来てくれた人と話す\n・プロフ整える",
        },
    ],
    "ストーリー": [
        {
            "人物": "フリーターだった21歳の子",
            "ビフォー": "「バイト掛け持ちで月12万、将来不安しかない」",
            "期間": "半年",
            "アフター": "「配信だけで月20万、休みも自分で決められる」",
            "教訓": "学歴も資格もいらない\nスマホと「やってみよう」って気持ちだけでよかった",
        },
        {
            "人物": "人見知りの大学生",
            "ビフォー": "「リアルだと3人以上いると話せない」",
            "期間": "3ヶ月",
            "アフター": "「画面越しだと不思議と話せる。\n今は毎日20人以上と会話してる」",
            "教訓": "配信ってコミュ障の方が向いてるのかもしれない",
        },
        {
            "エピソード": "うちの事務所に来た子が\n「石川県からなんですけど大丈夫ですか？」\nって聞いてきた\n\n大丈夫どころか地方の方が有利だって話したら\n3ヶ月後にその地域でトップになってた",
            "オチ": "場所は関係ない\n始めるかどうかだけ",
        },
    ],
    "ぶっちゃけ": [
        {
            "テーマ": "ライバー事務所の闇",
            "箇条書き": "・契約書読ませない事務所がある\n・「月100万確定」は嘘\n・辞められない契約は危険\n・手数料50%以上は高すぎ",
            "ポジティブ転換": "ちゃんとした事務所もあるから\n見極め方は知っておいた方がいい",
        },
        {
            "テーマ": "配信で稼ぐのは簡単じゃない",
            "本音": "最初の1ヶ月は時給換算100円以下\n誰も見に来ない日もある\n心折れそうになる\n\nでも3ヶ月超えたら\n「あの時やめなくてよかった」って全員言う",
        },
        {
            "テーマ": "「誰でも稼げます」は嘘",
            "本音": "正確には\n「続けた人は稼げるようになる」\n\n問題は続けられるかどうか\n才能じゃなくて継続力の勝負",
        },
    ],
    "副業比較": [
        {
            "テーマ": "在宅副業の初期費用と収益化スピード",
            "箇条書き": "ブログ → 0円 / 収益まで半年\nせどり → 1万円 / 収益まで1ヶ月\n動画編集 → 5万円 / 収益まで2ヶ月\nWebライター → 0円 / 収益まで1ヶ月\nライブ配信 → 0円 / 収益まで初日",
        },
        {
            "テーマ": "副業のストレス度を正直に書く",
            "箇条書き": "せどり → 在庫リスクと梱包: ★★★★\nライター → 納期プレッシャー: ★★★\n動画編集 → 修正地獄: ★★★★\nブログ → 結果出ない焦り: ★★★★★\nライブ配信 → 慣れるまでの緊張: ★★",
        },
    ],
    "お金リアル": [
        {
            "テーマ": "20代の手取り事情",
            "本音": "手取り18万で家賃6万\n食費3万、通信1万、保険1万\n残り7万で服も交際費も趣味も\n\n貯金？無理だって\nこの構造で「貯金しろ」は酷すぎる",
        },
        {
            "テーマ": "あと月5万あったら何する？",
            "箇条書き": "・毎月旅行行ける\n・好きなもの我慢しなくていい\n・貯金できる安心感\n・将来の不安が減る\n・人に奢れる余裕",
        },
        {
            "テーマ": "物価は上がるのに給料は上がらない件",
            "本音": "卵もパンもガソリンも上がった\nでも給料は据え置き\n\n「節約しろ」じゃなくて\n収入の柱を増やす方が建設的\n\n文句言ってても変わらないから\n自分で動くしかない",
        },
    ],
}


def analyze_tweets():
    """過去の投稿を分析して伸びたパターンを特定する。API制限で失敗したらNoneを返す。"""
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
            print("ツイートなし。")
            return None

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

        top_texts = [s["text"] for s in scored[:10]]
        pattern_scores = {
            "あるある": sum(1 for t in top_texts if "あるある" in t or "・" in t and len(t.split("・")) > 3),
            "質問": sum(1 for t in top_texts if "？" in t and ("❤️" in t or "🔁" in t)),
            "リスト": sum(1 for t in top_texts if "→" in t or (t.count("・") >= 3)),
            "ストーリー": sum(1 for t in top_texts if "ヶ月" in t or "の話" in t),
            "ぶっちゃけ": sum(1 for t in top_texts if "ぶっちゃけ" in t or "正直" in t or "リアル" in t),
            "副業比較": sum(1 for t in top_texts if "副業" in t or "比較" in t or "在宅" in t),
            "お金リアル": sum(1 for t in top_texts if "手取り" in t or "給料" in t or "万円" in t or "月" in t and "稼" in t),
        }

        return scored, pattern_scores

    except Exception as e:
        print(f"Twitter API分析をスキップ（{type(e).__name__}: {e}）")
        return None


def main():
    # --- 1. 過去の投稿を分析 ---
    result = analyze_tweets()

    if result:
        scored, pattern_scores = result
        top_patterns = sorted(pattern_scores.items(), key=lambda x: -x[1])
        print(f"パターン分析: {dict(top_patterns)}")
        winning_patterns = [p[0] for p in top_patterns[:2]]
        if not any(pattern_scores[p] > 0 for p in winning_patterns):
            winning_patterns = ["あるある", "ぶっちゃけ"]
    else:
        scored = []
        pattern_scores = {}
        # API使えない場合は全パターンからランダムに2つ選択
        all_patterns = list(EVOLUTION_CONTENT.keys())
        winning_patterns = random.sample(all_patterns, min(2, len(all_patterns)))
        print(f"API分析不可。ランダムパターンで生成。")

    print(f"重点パターン: {winning_patterns}")

    # --- 3. 新しい投稿を生成 ---
    with open("posts/twitter_posts.json", "r", encoding="utf-8") as f:
        existing = json.load(f)

    existing_texts = {p["text"][:30] for p in existing if "text" in p}
    new_count = 0
    next_id = len(existing) + 1

    for pattern in winning_patterns:
        contents = EVOLUTION_CONTENT.get(pattern, [])
        templates = EVOLUTION_TEMPLATES.get(pattern, [])

        for content in contents:
            template = random.choice(templates)

            # テンプレートに値を埋め込む
            text = template
            for key, value in content.items():
                text = text.replace(f"{{{key}}}", value)

            # 未使用の{xxx}が残ってたらスキップ
            if "{" in text:
                continue

            # 重複チェック
            if text[:30] in existing_texts:
                continue

            existing.append({
                "id": f"evo_{next_id:03d}",
                "phase": "growth",
                "text": text,
            })
            existing_texts.add(text[:30])
            new_count += 1
            next_id += 1

    # --- 4. 保存 ---
    with open("posts/twitter_posts.json", "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=4)

    print(f"\n{new_count}件の新投稿を追加（合計: {len(existing)}件）")

    # 分析レポート保存
    os.makedirs("data", exist_ok=True)
    with open("data/evolution_report.json", "w", encoding="utf-8") as f:
        json.dump({
            "top_posts": scored[:5],
            "pattern_scores": pattern_scores,
            "winning_patterns": winning_patterns,
            "new_posts_added": new_count,
            "total_posts": len(existing),
        }, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
