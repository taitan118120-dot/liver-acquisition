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
  - 確定ファクトの禁止語・割合統計・収入レンジの正本は facts_patterns.py（媒体共通）
  - X投稿本文にだけ当てる禁止語はこのファイルの X_NG_PATTERNS
  - cloud_evolve.py が生成時に、cloud_post.py が投稿直前に、両方でこれを通す
    （生成時だけだと既存キュー585本が素通りする。実際に違反が残っていた）

2026-08-10 の共通化:
  ここにあった禁止語20件を精査したところ、**1件も X 固有ではなかった**
  （所属数・還元率・取扱外プラットフォーム・リスナーさん…すべて媒体を問わない
  確定ファクト）。逆に Threads にしか無かったルール（オフの日の主語・他社下げ・
  「200名以上」・数万円/お小遣い程度）はXでは素通りしていた。
  そこで全部 facts_patterns.COMMON_NG_PATTERNS に移し、X_NG_PATTERNS は
  「Xでしか意味がないルール」を入れる枠として空で残してある。
  NG_PATTERNS は共通＋X固有の合成で、cloud_evolve.check_facts_coverage が
  ラベル一覧としてこれを読むので、名前と中身（全ラベルを含むこと）は変えない。

使い方:
  python3 x_post_guard.py                     # posts/twitter_posts.json を全走査
  python3 x_post_guard.py --unposted          # まだ投稿されていない分だけ走査
  python3 x_post_guard.py --file path.json    # 別のキューを走査
  python3 x_post_guard.py --strict            # 違反が1件でもあれば exit 1
"""

import argparse
import json
import os
import sys

from facts_patterns import COMMON_NG_PATTERNS, common_violations

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSTS_FILE = os.path.join(BASE_DIR, "posts", "twitter_posts.json")
RECENT_IDS_FILE = os.path.join(BASE_DIR, "data", "recent_post_ids.txt")

# ── X固有の禁止パターン ───────────────────────────────────────
# 「Xに出すときだけ事故になる」ものだけをここに書く。
# 事務所の確定ファクト（所属数・還元率・取扱プラットフォーム・呼称など）は
# 媒体を問わないので facts_patterns.COMMON_NG_PATTERNS 側に置くこと。
# ここに書くと Threads/プロフィール側が素通りする＝この共通化で潰した事故が戻る。
#
# 2026-08-11: 並行セッションが代理店解禁に合わせてこのファイルへ直接
# DM誘導の拡張・市場規模/成長率・ロイヤリティ食い違い・不労所得の言い換えを
# 追加していた。いずれもXに限らずThreadsの代理店投稿(agency比率30%)にも
# 同じ事故が起きうる確定ファクト系のルールなので、共通化の趣旨に沿って
# facts_patterns.COMMON_NG_PATTERNS 側に統合した。
X_NG_PATTERNS = []

# 外部（cloud_evolve.check_facts_coverage）はこれを「Xで当たる全ラベル」として読む。
NG_PATTERNS = list(COMMON_NG_PATTERNS) + X_NG_PATTERNS


def post_body(post):
    """キューの1件から検品対象の本文を取り出す（スレッドは全ツイート連結）。"""
    if post.get("thread"):
        return "\n".join(post["thread"])
    return post.get("text", "") or ""


def violations(text):
    """投稿1本の違反ラベルのリストを返す。空なら合格。"""
    return [reason for reason, _hit in details(text)]


def details(text):
    """違反ラベルと該当箇所の組を返す（監査レポート用）。

    空白挿入での回避（「9 割」「手　数　料」）は common_violations 側で塞いである。
    金額は strict にしない：Xのキューには「月20万稼ぐ」「月100万」のように
    確定レンジの内側や実績の引用が37本あり、Threads と同じ
    「確定レンジ表記以外は全部NG」を当てると正常な在庫まで落ちるため。
    """
    return common_violations(text, extra_patterns=X_NG_PATTERNS)


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
