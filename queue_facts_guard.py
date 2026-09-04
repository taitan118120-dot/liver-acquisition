#!/usr/bin/env python3
"""queue_facts_guard.py — 生成キューの「見えない欠品」番犬
========================================================
X (`posts/twitter_posts.json`) と Threads (`threads/threads_posts.json`) の
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

  x_purge_violations.yml は **公開済みポスト**（タイムライン）を見る別物で、
  未投稿のキューはスコープ外。だからキュー側にはこの番犬が要る。

動作:
  各キューの未投稿分だけを、それぞれの正本の検品にかける:
    - X       … x_post_guard.details()      （data/recent_post_ids.txt に無い分）
    - Threads … threads_content._violations()（"posted" が真でない分）
  1件でも違反が残っていれば exit 1 で赤くし、Issue で通知する。
  両方0件に戻ったら Issue は自動クローズされる
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


def scan_x():
    """X キューの未投稿分を x_post_guard の検品にかける。

    「未投稿」の判定は cloud_post.py と同じ: data/recent_post_ids.txt に
    ID が無い分。違反投稿は recent_ids に入らないので、ここに残り続ける。
    """
    sys.path.insert(0, BASE_DIR)
    import x_post_guard

    with open(x_post_guard.POSTS_FILE, encoding="utf-8") as f:
        posts = json.load(f)
    recent = x_post_guard._load_recent_ids()

    unposted = 0
    bad = []
    for p in posts:
        pid = p.get("id", "?")
        if pid in recent or p.get("posted"):
            continue
        unposted += 1
        d = x_post_guard.details(x_post_guard.post_body(p))
        if not d:
            continue
        bad.append({
            "id": pid,
            "head": x_post_guard.post_body(p).split("\n")[0][:60],
            "labels": [lbl for lbl, _hit in d],
        })
    return {
        "file": _rel(x_post_guard.POSTS_FILE),
        "queue_total": len(posts),
        "unposted": unposted,
        "violations": bad,
    }


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

    x = scan_x()
    threads = scan_threads()
    total = len(x["violations"]) + len(threads["violations"])

    report = {
        "total_violations": total,
        "x": x,
        "threads": threads,
    }
    if args.json:
        os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        print(f"→ {_rel(REPORT_FILE)} に保存\n")

    _print_section("X", x)
    _print_section("Threads", threads)

    if total:
        print(f"\n❌ 未投稿キューに確定ファクト違反が {total}本 残っています。"
              f" 直さない限り在庫に数えられるだけで一生投稿されません。")
        return 1
    print("\n✅ 未投稿キューに確定ファクト違反はありません")
    return 0


if __name__ == "__main__":
    sys.exit(main())
