#!/usr/bin/env python3
"""x_post_guard.py — X投稿本文の確定ファクト機械検品
=====================================================
Threads の threads/threads_content.py `_violations()` に相当するものを X 側に用意する。

背景（2026-08-09）:
  X @taitan_LIVER の稼働中ポストに、Note記事側では全数除去済みの
  「出典なしの割合統計」がそのまま出ていた（2026-08-08 実測）:
    「結論から言うと、9割の副業ライバーはフリーで十分。」            (evo_413)
    「成功する奴は10人に1人もいない。」                              (evo_283)

  真因は経路の設計:
    - 生成側 cloud_evolve.py … Gemini出力に対して長さ・JSON構造しか見ていなかった。
      それどころかプロンプトの「勝ちパターン例」自体が
      「フリーで稼げる人は1割、残り9割は事務所入った方が早い」を手本として提示し、
      THEMES にも「初月で稼げない人が99%辞める理由（言い切り）」が入っていた。
      = AIが割合統計を出すよう**指示していた**。
    - 投稿側 cloud_post.py … キューから引いてそのまま投稿。検品ゼロ。
  → Threads(_violations) / Note(一括ファクト修正) / プロフィール(social_profile_guard)
     には検品があるのに、X の投稿本文だけ素通りだった。

このモジュールの位置づけ:
  - 割合統計・収入レンジの正本パターンは facts_patterns.py（媒体共通）
  - X投稿本文にだけ当てる禁止語はこのファイルの NG_PATTERNS
  - cloud_evolve.py が生成時に、cloud_post.py が投稿直前に、両方でこれを通す
    （生成時だけだと既存キュー585本が素通りする。実際に違反が残っていた）

使い方:
  python3 x_post_guard.py                     # posts/twitter_posts.json を全走査
  python3 x_post_guard.py --unposted          # まだ投稿されていない分だけ走査
  python3 x_post_guard.py --file path.json    # 別のキューを走査
  python3 x_post_guard.py --strict            # 違反が1件でもあれば exit 1
"""

import argparse
import json
import os
import re
import sys

from facts_patterns import (
    line_link_violations,
    money_violations,
    ratio_violations,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSTS_FILE = os.path.join(BASE_DIR, "posts", "twitter_posts.json")
RECENT_IDS_FILE = os.path.join(BASE_DIR, "data", "recent_post_ids.txt")

# ── X投稿本文の禁止パターン ───────────────────────────────────
# 旧値ではなく「フィールド」で組む
# （2026-07-29 の教訓: `150名` を狙うと `50名` を取りこぼす）
NG_PATTERNS = [
    (r"所属(?:ライバー)?\s*(?!200\s*[名人])[0-9]{1,4}\s*[名人]", "所属数が200名以外"),
    (r"(?:累計|総勢|延べ)\s*[0-9]{1,4}\s*[名人]", "所属数の旧表記（累計/総勢）"),
    (r"統括|傘下", "代理店の関係が「提携」でない（統括/傘下）"),
    (r"現役(?:プレイヤー|ライバー)", "代表は「元」Pococha S帯（現役表記はbioと矛盾）"),
    # [[feedback_no_fee_free_claim]] 報酬は「還元率100%+α」とだけ書く。
    # 「他社は手数料を引く」という比較も含めて単語ごと使わない。
    (r"手数料", "禁止語「手数料」"),
    (r"マージン\s*[0０]\s*[%％]|マージン(?:ゼロ|なし|無し|0円)|ノーマージン",
     "「マージンゼロ」＝手数料なしの同義語"),
    # [[feedback_no_free_exit_claim]] 2年契約があるので契約期間自体も書かない
    (r"違約金(?:なし|無し|[0０])|いつでも(?:解約|退所|辞め|契約解除)|契約期間",
     "「いつでも退所」「違約金なし」系／契約期間への言及"),
    (r"還元率\s*100\s*[%％](?!\s*\+\s*α)", "還元率が「100%+α」になっていない"),
    (r"還元率\s*(?!100)[0-9]{2,3}\s*[%％]", "還元率が確定値でない"),
    # [[feedback_note_target_platforms]] 取扱は Pococha・TikTok LIVE・17LIVE の3つ
    (r"IRIAM|イリアム|SHOWROOM|ショールーム|ふわっち|REALITY", "取扱外プラットフォーム"),
    (r"他アプリ(?:も)?多数", "取扱は Pococha・TikTok LIVE・17LIVE の3つで統一"),
    # [[feedback_leadmagnet_first]] 導線は特典PDF→LINE登録に統一
    (r"DM(?:で|を)?(?:ご相談|ください|下さい|お待ち)|お気軽にDM|DMお願い",
     "CTAがDM誘導（導線は特典PDF→LINE登録に統一）"),
    (r"オンライン無料相談", "「オンライン無料相談」は使わない"),
    (r"カーブアウト|ccarveout", "使用禁止ブランド（TAITAN PROで統一）"),
    (r"Pococha新人期スタートダッシュ", "旧・特典PDF名"),
    (r"lit\.link", "リンクが lit.link（公式LINEでない）"),
    # [[feedback_listener_san]] 全文面でリスナーは「リスナーさん」
    (r"リスナー(?!さん)", "リスナーの呼び捨て"),
    (r"絶対稼げ|確実に稼|必ず月|保証", "断定・保証表現"),
    (r"不労所得|権利収入", "マルチ的表現"),
    # [[feedback_dont_make_up_numbers]]
    (r"多数輩出|多くの実績|続々と|数百人|何百人|数千", "根拠なしの実績誇張"),
]


def post_body(post):
    """キューの1件から検品対象の本文を取り出す（スレッドは全ツイート連結）。"""
    if post.get("thread"):
        return "\n".join(post["thread"])
    return post.get("text", "") or ""


def violations(text):
    """投稿1本の違反ラベルのリストを返す。空なら合格。"""
    if not text:
        return []
    # 「9 割」「9　割」のような空白挿入で逃げられないよう、詰めた文字列でも当てる
    flat = re.sub(r"\s+", "", text)
    out = []

    for pat, label in NG_PATTERNS:
        if re.search(pat, text) or re.search(pat, flat):
            out.append(label)

    for reason, _hit in ratio_violations(text) or ratio_violations(flat):
        out.append(reason)
    for reason, _hit in money_violations(text):
        out.append(reason)
    for reason, _hit in line_link_violations(text):
        out.append(reason)

    return out


def details(text):
    """違反ラベルと該当箇所の組を返す（監査レポート用）。"""
    if not text:
        return []
    flat = re.sub(r"\s+", "", text)
    out = []
    for pat, label in NG_PATTERNS:
        m = re.search(pat, text) or re.search(pat, flat)
        if m:
            out.append((label, m.group(0)[:40]))
    out += ratio_violations(text) or ratio_violations(flat)
    out += money_violations(text)
    out += line_link_violations(text)
    return out


def _load_recent_ids():
    if not os.path.exists(RECENT_IDS_FILE):
        return set()
    with open(RECENT_IDS_FILE, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def audit(path=POSTS_FILE, unposted_only=False):
    """キューを走査して違反件数を返す。"""
    with open(path, encoding="utf-8") as f:
        posts = json.load(f)

    recent = _load_recent_ids() if unposted_only else set()
    bad = 0
    for p in posts:
        pid = p.get("id", "?")
        if unposted_only and (pid in recent or p.get("posted")):
            continue
        d = details(post_body(p))
        if not d:
            continue
        bad += 1
        state = "投稿済(今周回)" if pid in recent else "未投稿"
        head = post_body(p).split("\n")[0][:34]
        print(f"[NG] {pid} {state} :: {', '.join(lbl for lbl, _ in d)}")
        print(f"     {head}")
        for lbl, hit in d:
            print(f"       └ {lbl}: {hit!r}")

    scope = "未投稿分" if unposted_only else "全件"
    print(f"\n{os.path.basename(path)} {len(posts)}本中 {bad}本が現在の基準に不適合（{scope}）")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=POSTS_FILE)
    ap.add_argument("--unposted", action="store_true",
                    help="data/recent_post_ids.txt に無いものだけ走査")
    ap.add_argument("--strict", action="store_true", help="違反があれば exit 1")
    args = ap.parse_args()

    bad = audit(args.file, unposted_only=args.unposted)
    if bad and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
