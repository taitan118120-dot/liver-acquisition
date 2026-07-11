"""
Threads 投稿コンテンツ生成（Gemini）

ライバー集客のPull戦略に沿った募集"投稿"を生成してキューに足す。
コールドDM・自動フォロー・自動いいねは一切やらない（投稿だけ）。

2系統:
  - liver  : ライバー本人募集（未経験/副業/移籍）→ LINE（友だち追加特典PDF導線）
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

# LINE登録特典（リードマグネット）。liverのリンク付き投稿はLPではなく
# LINEへ直接誘導し、特典PDFを受け取り理由にする。
LEAD_MAGNET_LINE = (
    "🎁 新人期30日でやることを全部まとめた非売品PDF"
    "『Pococha新人期スタートダッシュガイド』を、下のリンクの友だち追加で無料配布中"
)

FACTS = """
【絶対に守る確定ファクト】
- 事務所名：TAITAN PRO
- 還元率100%。「90%」「相場70-85%」等は書かない。※「手数料なし」「手数料0円」という表現は使わない（還元率100%だけ書く）
- 所属ライバー数：Pococha・TikTok合わせて150人以上（内訳は書かない）
- 代表たいたん：元Pococha Sランク、ミクチャ8,000人中ミスターコン1位、Pococha歴4年
- 代表の最高月収は3桁（=100万円台）とだけ。「200万」等の具体額NG
- Pococha B帯月収＝月20〜30万（他レンジ禁止）。Pocochaは時間ダイヤで投げ銭ゼロでも時間報酬
- 「オフの日」は月4日の強制休配信日（配信できない日）
- TikTokギフト換金はフリーも事務所も同じ（事務所だと手取り増、は書かない）
【禁止表現】
- 「手数料なし」「手数料0円」「手数料ゼロ」（還元率100%とだけ書く）
- 「絶対稼げる」「確実に」「必ず月◯万」等の断定・誇大
- 業界収入分布の%、DM返信率、倍率（2-3倍）等の根拠なし数字
- 月収の具体額の捏造
"""

VIRAL_RULES = """
【Threadsでバズるための鉄則（最重要・全投稿に適用）】
Threadsのアルゴリズムは「最初の1行で止まったか」と「リプライ（会話）がどれだけ付いたか」をいちばん見る。
だから次を必ず守る：

1. フック1行目で勝負を決める。タイムラインでは最初の約1〜2行しか見えない。
   ベタな自己紹介・告知（「ライバー募集してます」「TAITAN PROです」）で始めるのは絶対NG。
   下のどれかの型で、思わず続きを読みたくなる1行から始める：
   - 告白型：「正直に言うと、〜」「これ言うと怒られるんだけど」
   - 常識壊し型：「“顔がいい人ほど稼げる”は嘘です」「ライバー＝夜のイメージ、もう古い」
   - 具体シーン型：「先月うちに来た23歳の子、前職コンビニバイト。今は〜」
   - 数字チラ見せ型：「Pocochaの“時間ダイヤ”、知らずに損してる人多すぎる」
   - 問いかけ型：「スマホ副業、結局なにが一番マシなんだろうって考えた結果」
   - 逆張り共感型：「無理して毎日配信しなくていい、ってまず言いたい」「“稼がなきゃ”で始めると続かない」
2. 1投稿＝1メッセージ。情報を詰め込みすぎない。言いたいことを1つに絞ると伸びる。
3. 売り込みは最後に小さく1回だけ。本文の主役は「読者にとっての気づき・本音」。
   宣伝色が強い投稿はアルゴに沈められる。価値→さりげない誘導の順。
4. 締めは“会話を生む”一言で終える（リプライがアルゴ最大の燃料）。
   例：「同じこと思ってた人いる？」「どっち派？」「気になる人はリプかプロフのリンクで」。
   毎回リンクをベタ貼りしない。リンクが多い投稿は表示が落ちる。
5. 短い行＋空行でリズムを作る。長い段落で埋めない。絵文字は0〜2個。盛りすぎない。
6. ハッシュタグは0〜2個。付けるなら文末に1行で。タグ乱用はスパム判定。
"""

PROMPT_LIVER = """あなたはライバー事務所TAITAN PROのSNS運用担当で、Threadsでフォロワーを伸ばすのが得意なコピーライター。
Threads(テキストSNS、本文上限500字)用の「ライバー募集」投稿を{n}本作る。
狙いはPull＝読んだ人が「これ私かも」と刺さって自分から応募・LINE登録したくなること。コールドDMはしない。

ターゲット：スマホ副業を探してる人／配信に興味がある未経験者／伸び悩んでる現役ライバー（移籍検討）。

ネタの引き出し（実体験ベースで具体的に。毎回ちがう切り口にする）：
- Pocochaの“時間ダイヤ”＝投げ銭ゼロの日でも配信時間で報酬が出る話
- 「顔・若さ・トーク力がなくても続けた人が伸びる」というリアル
- 未経験の人が最初の数週間でつまずくポイントと、事務所がそこをどう支えるか
- 副業として夜だけ配信してる会社員/主婦/学生の等身大エピソード
- 現役で伸び悩んでる人へ：環境（事務所）を変えるだけで変わることがある、という移籍視点
- 還元率100%が当たり前じゃない業界で、それが何を意味するか（手数料という言葉は使わない）

{viral}

{facts}

各投稿は「フック1行 → 本音/具体 → 会話を生む締め」の流れ。500字以内。
{n}本それぞれフックの型を変えて、被らないようにする。

出力は必ず次のJSON配列のみ（前置き・説明・コードフェンス禁止）：
[
  {{"angle":"liver","text":"投稿本文","tags":["#ライバー募集"]}},
  ...
]
"""

PROMPT_AGENCY = """あなたはライバー事務所TAITAN PROのSNS運用担当で、Threadsでフォロワーを伸ばすのが得意なコピーライター。
Threads(テキストSNS、本文上限500字)用の「配信代理店パートナー募集」投稿を{n}本作る。
狙いはPull＝営業/副業独立志向の人が「この仕事おもしろそう」と自分から問い合わせたくなること。

重要な作法（規約と信頼のため厳守）：
- 報酬・稼げる額を釣り文句の主役にしない。ミッション・仕組み・働き方・将来性で語る。
- 「絶対儲かる」「不労所得」「権利収入で楽して」等のマルチ的表現は絶対NG。
- TAITAN PROは11の配信代理店と提携、還元率100%、所属150人以上という実体のある事務所だと伝える。
- 対象：営業経験者・副業から独立したい人・人を応援するのが好きな人。

ネタの引き出し（毎回ちがう切り口に）：
- 「人の成長で食べていく」という仕事観／マネジメントの面白さ
- 在宅・スキマ時間でできる新しい働き方としての配信代理店
- ライバーを“発掘して伸ばす”プロセスのリアル（うまくいった話・難しさ）
- 個人で全部抱えなくていい＝事務所と組むからこそ続けられる構造
- 営業や接客の経験が、まったく別の形で活きる話

{viral}

{facts}

各投稿は「フック1行 → 仕事の中身/本音 → 会話を生む締め」の流れ。500字以内。
ただし煽り・誇大は厳禁。落ち着いた信頼感のあるトーンでフックを作る。
{n}本それぞれフックの型を変えて被らせない。

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
    prompt = tmpl.format(n=n, facts=FACTS, viral=VIRAL_RULES)

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
    # 全投稿にリンクは貼らない。代理店はLP、ライバーはLINE（特典PDF導線）を時々。
    return LP_AGENCY if angle == "agency" else LINE_URL


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
        # liverのリンク付き投稿には特典PDFの受け取り理由を1行添える（500字上限は守る）
        if link == LINE_URL and len(text) + len(LEAD_MAGNET_LINE) + 2 <= 500:
            text = text + "\n\n" + LEAD_MAGNET_LINE
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
