"""
Threads 投稿コンテンツ生成（Gemini）

ライバー集客のPull戦略に沿った募集"投稿"を生成してキューに足す。
コールドDM・自動フォロー・自動いいねは一切やらない（投稿だけ）。

2系統:
  - liver  : ライバー本人募集（未経験/副業/移籍）→ LINE/LP
  - agency : 代理店パートナー募集 → /agency/ LP（報酬を釣り文句にしない作法）

確定ファクト（project_taitan_pro_note_facts）を厳守:
  還元率100% / 所属150人以上 / Pococha歴4年 / B帯月20-30万 /
  代表=元Pococha Sランク・ミクチャ8000人ミスターコン1位 /
  「絶対稼げる」等の断定NG・具体月収の捏造NG。

使い方:
  python threads/threads_content.py --gen 8                 # liver/agency混在8本生成
  python threads/threads_content.py --gen 8 --angle liver   # liverのみ
  python threads/threads_content.py --gen 4 --angle agency
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POSTS_FILE = os.path.join(SCRIPT_DIR, "threads_posts.json")

LP_BEGINNER = "https://taitan-pro-lp.netlify.app/#apply"
LP_AGENCY = "https://taitan-pro-lp.netlify.app/agency/"
LINE_URL = "https://lin.ee/xchCfdn"

FACTS = """
【絶対に守る確定ファクト】
- 事務所名：TAITAN PRO
- 還元率100%（手数料なし）。「90%」「相場70-85%」等は書かない
- 所属ライバー数：Pococha・TikTok合わせて150人以上（内訳は書かない）
- 代表たいたん：元Pococha Sランク、ミクチャ8,000人中ミスターコン1位、Pococha歴4年
- 代表の最高月収は3桁（=100万円台）とだけ。「200万」等の具体額NG
- Pococha B帯月収＝月20〜30万（他レンジ禁止）。Pocochaは時間ダイヤで投げ銭ゼロでも時間報酬
- 「オフの日」は月4日の強制休配信日（配信できない日）
- TikTokギフト換金はフリーも事務所も同じ（事務所だと手取り増、は書かない）
【禁止表現】
- 「絶対稼げる」「確実に」「必ず月◯万」等の断定・誇大
- 業界収入分布の%、DM返信率、倍率（2-3倍）等の根拠なし数字
- 月収の具体額の捏造
"""

PROMPT_LIVER = """あなたはライバー事務所TAITAN PROのSNS運用担当。Threads(テキストSNS、本文上限500字)用の
「ライバー募集」投稿を{n}本作る。狙いはPull＝読んだ人が自分から応募・LINE登録したくなること。
コールドDMはしない。投稿で価値を出して向こうから来てもらう。

ターゲット：スマホ副業を探してる人／配信に興味がある未経験者／伸び悩んでる現役ライバー（移籍検討）。

各投稿の作り方：
- 1〜3行目で「おっ」と止まる引き（共感・あるある・意外な事実）。煽りすぎない。
- 本文は実体験ベースで具体的に。Pocochaの時間ダイヤ／未経験スタート／事務所のサポート等。
- 末尾に軽いCTA（「気になる人はプロフのリンクから」「DMじゃなくて応募ページ見てね」等）。
  毎回ベタなリンク貼り付けにしない。自然に。
- 500字以内。ハッシュタグは付けても2〜3個まで（#ライブ配信 #ライバー募集 #スマホ副業 等）、無くてもいい。
- 改行を使って読みやすく。絵文字は1〜3個程度。

{facts}

出力は必ず次のJSON配列のみ（前置き・説明・コードフェンス禁止）：
[
  {{"angle":"liver","text":"投稿本文","tags":["#ライバー募集"]}},
  ...
]
"""

PROMPT_AGENCY = """あなたはライバー事務所TAITAN PROのSNS運用担当。Threads(テキストSNS、本文上限500字)用の
「配信代理店パートナー募集」投稿を{n}本作る。狙いはPull＝営業/副業独立志向の人が自分から問い合わせたくなること。

重要な作法（規約と信頼のため厳守）：
- 報酬・稼げる額を釣り文句の主役にしない。ミッション・仕組み・働き方・将来性で語る。
- 「絶対儲かる」「不労所得」「権利収入で楽して」等のマルチ的表現は絶対NG。
- TAITAN PROは11の配信代理店と提携、還元率100%、所属150人以上という実体のある事務所だと伝える。
- 対象：営業経験者・副業から独立したい人・人を応援するのが好きな人。

各投稿：
- 引き→代理店業の中身（ライバーの発掘とマネジメント、事務所と組む形）→軽いCTA。
- 500字以内、改行で読みやすく、絵文字控えめ、ハッシュタグ0〜2個。

{facts}

出力は必ず次のJSON配列のみ（前置き・説明・コードフェンス禁止）：
[
  {{"angle":"agency","text":"投稿本文","tags":["#業務委託"]}},
  ...
]
"""


def _extract_json_array(raw):
    raw = raw.strip()
    raw = re.sub(r"^```(json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    return m.group(0) if m else None


def _gen_one_angle(angle, n):
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY 未設定")
        return []
    tmpl = PROMPT_LIVER if angle == "liver" else PROMPT_AGENCY
    prompt = tmpl.format(n=n, facts=FACTS)

    client = genai.Client(api_key=api_key)
    models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.1-flash-lite-preview"]
    for model_name in models:
        for attempt in range(3):
            try:
                resp = client.models.generate_content(model=model_name, contents=prompt)
                payload = _extract_json_array(resp.text or "")
                if not payload:
                    print(f"  [WARN] {model_name}: JSON無し（試行{attempt+1}）")
                    continue
                items = json.loads(payload)
                out = []
                for it in items:
                    text = (it.get("text") or "").strip()
                    if not text or len(text) > 500:
                        continue
                    out.append({"angle": angle, "text": text, "tags": it.get("tags", [])})
                if out:
                    print(f"  [OK] {model_name}: {angle} {len(out)}本生成")
                    return out
            except Exception as e:
                print(f"  [WARN] {model_name} 失敗（試行{attempt+1}）: {e}")
    return []


def _link_for(angle):
    # 全投稿にリンクは貼らない。代理店はLP、ライバーはLINE/LPを時々。
    return LP_AGENCY if angle == "agency" else LP_BEGINNER


def generate(total, angle_filter=None):
    posts = []
    if os.path.exists(POSTS_FILE):
        with open(POSTS_FILE, encoding="utf-8") as f:
            posts = json.load(f)
    existing = {p.get("text", "").strip() for p in posts}

    new_items = []
    if angle_filter in (None, "liver"):
        n = total if angle_filter == "liver" else max(1, round(total * 0.7))
        new_items += _gen_one_angle("liver", n)
    if angle_filter in (None, "agency"):
        n = total if angle_filter == "agency" else max(1, total - len(new_items))
        new_items += _gen_one_angle("agency", n)

    added = 0
    for it in new_items:
        text = it["text"].strip()
        if text in existing:
            continue
        # 約3本に1本だけリンクを付ける（リンク貼りすぎでスパム判定を避ける）
        link = _link_for(it["angle"]) if (added % 3 == 0) else None
        posts.append({
            "text": text,
            "angle": it["angle"],
            "tags": it.get("tags", []),
            "link": link,
            "reply_control": "everyone",
            "posted": False,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        existing.add(text)
        added += 1

    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    unposted = sum(1 for p in posts if not p.get("posted"))
    print(f"[DONE] {added}本追加。キュー総数{len(posts)}、未投稿{unposted}本。")
    return added


def main():
    ap = argparse.ArgumentParser(description="Threads コンテンツ生成")
    ap.add_argument("--gen", type=int, default=6, help="生成本数")
    ap.add_argument("--angle", choices=["liver", "agency"], help="片方のみ生成")
    args = ap.parse_args()
    generate(args.gen, args.angle)


if __name__ == "__main__":
    main()
