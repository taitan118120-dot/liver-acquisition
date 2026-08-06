#!/usr/bin/env python3
"""公開キー台帳 data/published_note_keys.json の「静かな巻き戻し」を git だけで検知する。

note の公開APIは一切叩かない（軽い・速い・毎push実行できる）。見るのは
「台帳からキーが消えたとき、それを消したコミットが本当に取り下げ作業だったか」だけ。

正当な減り方は2通りしかない:
  - note_unpublish_articles.py が下書きに戻し、blog/articles_note_unpublished/ に退避した
  - note_delete_articles.py が削除した
どちらも note_keys_registry.remove() 経由で台帳が縮む。人手で減らすことは想定していない。

危険なのは「誰も消していないのにマージ結果として消える」パターン。
2026-08-05、台帳98件の古いブランチ claude/adoring-greider-7df689 をそのまま
マージすると main の108件が13件巻き戻る状態だった（data/branch_close_*.md）。
並行 worktree が10本以上あるので同じ事故は繰り返し起こりうる。

そこで「消えたキーごとに、どのコミットで消えたか」を辿って犯人を特定する。
マージコミット自身が第1親（＝取り込み先のブランチ）に対してキーを落としていたら、
それは誰の取り下げ作業でもない巻き戻しなので赤にする。

使い方:
  python3 note_keys_shrink_guard.py                      # HEAD~1..HEAD
  python3 note_keys_shrink_guard.py --base A --head B
  python3 note_keys_shrink_guard.py --base A --head B --json
"""
import argparse
import json
import os
import re
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEYS_PATH = "data/published_note_keys.json"
REPORT_FILE = os.path.join(BASE_DIR, "data", "note_keys_shrink_report.json")

# 取り下げ作業のコミットだと認める手掛かり（コミットメッセージ）。
# 目的は「静かな」巻き戻しを捕まえることなので、意図が読み取れれば通す方に倒す。
TAKEDOWN_RE = re.compile(
    r"note_unpublish_articles|note_delete_articles|note_keys_registry"
    r"|非公開|下書き|削除|除去|取り下げ|unpublish|delete",
    re.IGNORECASE,
)
# 下書き化の退避先。ここに触っていれば取り下げ作業の物証になる。
TAKEDOWN_PATHS = ("blog/articles_note_unpublished/",)


def git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=BASE_DIR,
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def rev_exists(rev):
    if not rev or set(rev) == {"0"}:
        return False
    return subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"],
                          cwd=BASE_DIR, capture_output=True).returncode == 0


def keys_at(rev):
    """指定リビジョン時点の台帳のキー集合。台帳が無ければ None。"""
    r = subprocess.run(["git", "show", f"{rev}:{KEYS_PATH}"],
                       cwd=BASE_DIR, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        return set(json.loads(r.stdout))
    except json.JSONDecodeError:
        return None


def parents(commit):
    return git("rev-list", "--parents", "-n", "1", commit).split()[1:]


def blame_removals(base, head, removed):
    """消えたキーそれぞれについて「どのコミットで消えたか」を割り出す。

    各コミットを第1親と比べる。マージコミットなら第1親＝取り込み先の枝なので、
    「マージした結果その枝から消えた」ものがそのまま出てくる。
    """
    commits = git("rev-list", "--reverse", f"{base}..{head}").split()
    culprits = {}   # key -> [commit, ...]
    info = {}       # commit -> dict
    for c in commits:
        ps = parents(c)
        before = keys_at(ps[0]) if ps else set()
        after = keys_at(c)
        if before is None or after is None:
            continue
        dropped = (before - after) & removed
        if not dropped:
            continue
        subject = git("log", "-1", "--format=%s%n%b", c).strip()
        touched = git("show", "--pretty=format:", "--name-only", c).split()
        info[c] = {
            "commit": c[:12],
            "subject": subject.splitlines()[0] if subject else "",
            "is_merge": len(ps) > 1,
            "keys": sorted(dropped),
            # マージコミットは「誰も消していないのに消える」経路なので無条件に疑う。
            "explained": len(ps) == 1 and (
                bool(TAKEDOWN_RE.search(subject))
                or any(t.startswith(p) for t in touched for p in TAKEDOWN_PATHS)
            ),
        }
        for k in dropped:
            culprits.setdefault(k, []).append(c)
    return culprits, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="HEAD~1")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--json", action="store_true",
                    help=f"{REPORT_FILE} にレポートを書く")
    a = ap.parse_args()

    report = {"base": a.base, "head": a.head, "skipped": None,
              "before": 0, "after": 0, "removed": [], "added": [],
              "unexplained": [], "culprits": []}

    def finish(code, msg):
        print(msg)
        if a.json:
            with open(REPORT_FILE, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        raise SystemExit(code)

    if not rev_exists(a.base):
        report["skipped"] = f"base {a.base} が存在しない（新規ブランチ/force-push等）"
        finish(0, f"スキップ: {report['skipped']}")

    before = keys_at(a.base)
    after = keys_at(a.head)
    if before is None or after is None:
        report["skipped"] = "台帳が読めない時点がある"
        finish(0, f"スキップ: {report['skipped']}")

    removed = before - after
    report.update(before=len(before), after=len(after),
                  removed=sorted(removed), added=sorted(after - before))
    print(f"台帳: {len(before)}件 ({a.base[:12]}) → {len(after)}件 ({a.head[:12]})")

    if not removed:
        finish(0, "OK: 減っていない")

    culprits, info = blame_removals(a.base, a.head, removed)
    report["culprits"] = list(info.values())

    unexplained = sorted(
        k for k in removed
        if not culprits.get(k) or not all(info[c]["explained"] for c in culprits[k])
    )
    report["unexplained"] = unexplained

    for d in info.values():
        mark = "OK  " if d["explained"] else "NG  "
        kind = "merge" if d["is_merge"] else "commit"
        print(f"  {mark}{kind} {d['commit']} -{len(d['keys'])}件  {d['subject'][:60]}")
    orphan = [k for k in removed if k not in culprits]
    if orphan:
        print(f"  NG  消えた経緯を特定できないキー {len(orphan)}件")

    if not unexplained:
        finish(0, f"OK: 減った{len(removed)}件はすべて取り下げ作業による")

    finish(1, f"NG: 取り下げ作業に紐づかない減少 {len(unexplained)}件 "
              f"[{', '.join(unexplained[:10])}]")


if __name__ == "__main__":
    main()
