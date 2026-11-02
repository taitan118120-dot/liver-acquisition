#!/usr/bin/env python3
"""queue_facts_guard.py — 生成キューの「見えない欠品」番犬
========================================================
Threads (`threads/threads_posts.json`) の
**まだ投稿していない**キューに、確定ファクト違反の投稿が残っていないかを毎週見る。

背景（2026-09-04）:
  posts/twitter_posts.json に確定ファクト違反の投稿が5本
  （g39 / g40 / g_follow10 / evo_397 / evo_564）残っていた。
  cloud_post.py は投稿直前に x_post_guard.violations() で候補から除外するので、
  これらは **在庫としては数えられるのに一生投稿されない**「見えない欠品」になる。
  在庫を「キュー本数 − 投稿済みID数」で数えると、その分だけ多く見積もってしまう。

  同じ構造は Threads にもある。threads_content.generate() は _violations() で
  違反を弾いてからキューに入れるが、**基準を後から厳しくした分**は
  既存のキューに残る（cloud_post.py と同じ「生成時ゲートだけでは既存分が素通り」）。

2026-09-05 に Instagram を走査対象へ足したが、2026-09-16 に外した
（[[project_ig_retired]]）。@taitan_pro7 の消滅でIG自動投稿を恒久停止し、
ig_poster.py ごと撤去したため、IGには「一生投稿されないキュー」という概念が
無くなった（instagram/ig_posts.json は記録として残してあるだけで、
投稿する側がもう居ない）。再開するなら投稿経路を作り直す時に一緒に戻す。

X も 2026-11-02 に外した。X APIのクレジット切れ（402）で9/15から投稿が止まっていて、
ユーザー判断でX自動化を全部撤去した（x_content/RETIRED.md）。キュー
posts/twitter_posts.json も検品の正本 x_post_guard.py も一緒に削除したので、
いまの対象は Threads だけ。

動作:
  各キューの未投稿分だけを、それぞれの正本の検品にかける:
    - Threads   … threads_content._violations()（"posted" が真でない分）
  1件でも違反が残っていれば exit 1 で赤くし、Issue で通知する。
  全部0件に戻ったら Issue は自動クローズされる
  （[[feedback_watchdog_autoclose]] 「直ったら閉じる」までが番犬）。

使い方:
  python3 queue_facts_guard.py           # 検査して結果を表示
  python3 queue_facts_guard.py --json    # レポートJSONも書き出す
"""

import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_FILE = os.path.join(BASE_DIR, "data", "queue_facts_guard_report.json")


def _rel(path):
    return os.path.relpath(path, BASE_DIR)


def scan_threads():
    """Threads キューの未投稿分を threads_content._violations() にかける。"""
    threads_dir = os.path.join(BASE_DIR, "threads")
    sys.path.insert(0, threads_dir)
    import threads_content

    with open(threads_content.POSTS_FILE, encoding="utf-8") as f:
        posts = json.load(f)

    unposted = 0
    bad = []
    for i, p in enumerate(posts):
        if p.get("posted"):
            continue
        unposted += 1
        v = threads_content._violations(p.get("text", ""), p.get("angle", "liver"))
        if not v:
            continue
        bad.append({
            "idx": i,
            "angle": p.get("angle", "liver"),
            "head": p.get("text", "").split("\n")[0][:60],
            "labels": v,
        })
    return {
        "file": _rel(threads_content.POSTS_FILE),
        "queue_total": len(posts),
        "unposted": unposted,
        "violations": bad,
    }


def _print_section(name, sec):
    print(f"[{name}] {sec['file']} — 未投稿 {sec['unposted']}本 / "
          f"違反 {len(sec['violations'])}本")
    for v in sec["violations"]:
        ident = v.get("id", f"#{v.get('idx')}")
        print(f"   - {ident} :: {', '.join(v['labels'])}")
        print(f"     {v['head']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="レポートJSONを書き出す")
    args = ap.parse_args()

    threads = scan_threads()
    total = len(threads["violations"])

    report = {
        "total_violations": total,
        "threads": threads,
    }
    if args.json:
        os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        print(f"→ {_rel(REPORT_FILE)} に保存\n")

    _print_section("Threads", threads)

    if total:
        print(f"\n❌ 未投稿キューに確定ファクト違反が {total}本 残っています。"
              f" 直さない限り在庫に数えられるだけで一生投稿されません。")
        return 1
    print("\n✅ 未投稿キューに確定ファクト違反はありません")
    return 0


if __name__ == "__main__":
    sys.exit(main())
