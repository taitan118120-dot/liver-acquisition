#!/usr/bin/env python3
"""note_structure_guard.py
公開中のNote記事の本文に「見た目だけ箇条書き・見た目だけ引用」が残っていないかを
毎日見る番犬。

■ なぜ必要か（2026-09-09 に分かったこと）
note_geo_structure.py が 2026-09-04（commit 9c84751）に公開147本すべての
`<p>・…</p>` / `<p>&gt;…</p>` を本物の `<ul><li>` / `<blockquote>` に直した。
ところが**記事を作る側**の note_auto_poster.markdown_to_html は `<p>・…</p>` を
吐いたままで、直ったのは 2026-09-09（commit ce10c6a）。つまりその間、

  2026-09-04〜09-08 に公開された5本
  （n757225e527ab / n33525859b063 / n7bd7288d5b21 / n32f0c24e8d1b / nf0cf1f7d3460）

は**生まれた瞬間から壊れていた**まま、最大5日間放置された。見つかったのは人間が
たまたま聞いたからで、既存の番犬はどれもここを見ていない
（note_tag_guard=タグ/eyecatch、note_keys_guard=キー台帳、note_stock_guard=在庫、
  note_funnel_guard=内部導線、content_facts_guard=確定ファクト）。
＝**本文の構造を見る番犬が1本も無かった**。修正は commit d816721。

読者には箇条書き・引用に見えるが、検索エンジンとAIには「ただの段落の壁」にしか
見えない。AI(GEO)経由の入会が実際に発生している以上、これは静かな機会損失になる。

■ 見るもの（すべて非ログインの公開APIで確認できる）
data/published_note_keys.json のキー全件について
`https://note.com/api/v3/notes/<key>` の本文を読み、トップレベルの `<p>` のうち
note_geo_structure の分類器で bullet / quote になるものを数える。

判定は **note_geo_structure.tokenize/kind をそのまま呼ぶ**。正規表現を書き写さない。
`*` は後ろに空白がある時だけ箇条書き（「*この記事は…」は注釈で箇条書きではない）
という規則が微妙で、一度これを間違えた実績があるため、変換側と検知側で
規則が枝分かれしないようにする。tokenize を使うと、既に `<ul><li><p>…</p></li></ul>`
に直った記事の内側の `<p>` を数えずに済む（note は保存時に li の中を `<p>` で包む）。

■ 直し方は CI にやらせない
note_geo_structure.py の書き込みは note への live PUT でログインCookieが要る。
CI に browser_cookie3 は無い（note_tag_guard で既に踏んだ）。ここは**検知と通知だけ**。
直すのは人間:
  python3 note_geo_structure.py --plan <key> …   # 変換内容を見る（GETのみ）
  python3 note_geo_structure.py <key> …          # 反映

使い方:
  python3 note_structure_guard.py                  # 全件確認。残骸があれば exit 1
  python3 note_structure_guard.py --json           # data/note_structure_guard_report.json も出力
  python3 note_structure_guard.py --max-bad 3      # 許容本数（既定0）
  python3 note_structure_guard.py --keys n123 n456 # キー指定で確認
  python3 note_structure_guard.py --self-test      # 検知器が生きているかだけ確認（通信なし）
"""
import argparse
import json
import os
import sys
import time

import requests

# 検知規則は変換側の唯一の正本から借りる（BULLET_RE / QUOTE_RE を書き写さない）。
from note_geo_structure import BULLET_RE, QUOTE_RE, kind, strip_tags, tokenize

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEYS_PATH = os.path.join(BASE_DIR, "data", "published_note_keys.json")
REPORT_PATH = os.path.join(BASE_DIR, "data", "note_structure_guard_report.json")
URLNAME = "taitan_118"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

FETCH_TRIES = 3


def scan_body(body):
    """本文から「見た目だけ箇条書き／引用」を拾う。

    返り値: {"bullets": [text, ...], "quotes": [text, ...]}
    本物の <ul>/<blockquote> の中身は tokenize が丸ごと1要素として飲むので数えない。
    """
    found = {"bullets": [], "quotes": []}
    for tok in tokenize(body or ""):
        k = kind(tok)
        if k not in ("bullet", "quote"):
            continue
        text = strip_tags(tok[3]).strip().replace("&nbsp;", "").strip()
        found["bullets" if k == "bullet" else "quotes"].append(text[:80])
    return found


def load_keys():
    keys = json.load(open(KEYS_PATH))
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def fetch(session, key):
    last = None
    for attempt in range(FETCH_TRIES):
        try:
            r = session.get(f"https://note.com/api/v3/notes/{key}",
                            headers={"Cache-Control": "no-cache"}, timeout=25)
            r.raise_for_status()
            return r.json()["data"]
        except Exception as e:  # 取得できないまま緑にしないため、握りつぶさない
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def check(session, key):
    d = fetch(session, key)
    if d.get("status") != "published":
        return None
    body = d.get("body") or ""
    found = scan_body(body)
    n_b, n_q = len(found["bullets"]), len(found["quotes"])
    if not (n_b or n_q):
        return None
    problems = []
    if n_b:
        problems.append(f"見た目だけ箇条書き {n_b}個")
    if n_q:
        problems.append(f"見た目だけ引用 {n_q}個")
    return {
        "key": key,
        "title": d.get("name", ""),
        "publish_at": d.get("publishAt") or d.get("publish_at") or "",
        "bullets": n_b,
        "quotes": n_q,
        "problems": problems,
        "samples": (found["bullets"] + found["quotes"])[:5],
    }


SELF_TEST_BODY = (
    "<p>まえおき。</p>"
    "<p>・配信時間は21時から</p>"
    "<p>・週4日が目安</p>"
    "<p>&gt; ここは引用にしたかった段落</p>"
    "<p>* 空白ありのアスタリスクも箇条書き</p>"
    "<p>*この記事は注釈なので箇条書きではない</p>"
    "<ul><li><p>これは本物のリストなので数えない</p></li></ul>"
    "<blockquote>本物の引用も数えない</blockquote>"
)


def self_test():
    """検知器が生きていることを、通信せずに確かめる。

    番犬が壊れて「何も見つからない」まま緑になり続けるのが一番まずいので、
    毎ラン最初にこれを通す。
    """
    found = scan_body(SELF_TEST_BODY)
    ok = True

    def _assert(cond, msg):
        nonlocal ok
        print(("  ok   " if cond else "  NG   ") + msg)
        ok = ok and cond

    _assert(len(found["bullets"]) == 3,
            f"「・」2個＋「* 」1個 を箇条書きとして検知（実測 {len(found['bullets'])}）")
    _assert(len(found["quotes"]) == 1,
            f"「&gt;」1個 を引用として検知（実測 {len(found['quotes'])}）")
    _assert(not any("注釈" in t for t in found["bullets"]),
            "「*この記事は」（空白なし）は注釈として見逃す")
    _assert(not any("本物" in t for t in found["bullets"] + found["quotes"]),
            "本物の <ul><li> / <blockquote> の中身は数えない")
    _assert(not scan_body("<p>ふつうの段落です。</p>")["bullets"],
            "健全な本文では何も検知しない")
    # 正本の正規表現を直接叩いて、import が期待通りのものかも見る
    _assert(bool(BULLET_RE.match("・foo")) and not BULLET_RE.match("*foo")
            and bool(BULLET_RE.match("* foo")),
            "BULLET_RE は note_geo_structure のもの（`*` は空白必須）")
    _assert(bool(QUOTE_RE.match("&gt;foo")), "QUOTE_RE は note_geo_structure のもの")
    print("\n検知器テスト:", "OK" if ok else "壊れている")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true",
                    help="data/note_structure_guard_report.json を出力")
    ap.add_argument("--max-bad", type=int, default=0,
                    help="残骸がある記事を許容する本数（既定0）")
    ap.add_argument("--keys", nargs="*", help="確認するキー（既定は台帳の全件）")
    ap.add_argument("--self-test", action="store_true",
                    help="検知器の自己診断だけ行う（通信なし）")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(0 if self_test() else 1)

    keys = args.keys or load_keys()
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})

    print(f"公開記事 {len(keys)}本の本文構造を確認中…", file=sys.stderr)
    rows, errors, checked = [], [], 0
    for key in keys:
        try:
            r = check(s, key)
        except Exception as e:
            print(f"  取得失敗 {key}: {e}", file=sys.stderr)
            errors.append({"key": key, "error": str(e)})
            continue
        checked += 1
        if r:
            rows.append(r)
        time.sleep(0.3)

    rows.sort(key=lambda r: -(r["bullets"] + r["quotes"]))
    tot_b = sum(r["bullets"] for r in rows)
    tot_q = sum(r["quotes"] for r in rows)

    print(f"\n■ 確認 {checked}本 / 構造が壊れている記事 {len(rows)}本"
          f"（見た目だけ箇条書き {tot_b}個 / 見た目だけ引用 {tot_q}個）")
    for r in rows:
        print(f"  - {r['title'][:46]}")
        print(f"      {' / '.join(r['problems'])}   "
              f"https://note.com/{URLNAME}/n/{r['key']}")
        for t in r["samples"][:3]:
            print(f"        例: {t}")
    if errors:
        print(f"\n!! 取得できず未確認の記事 {len(errors)}本"
              f"（未確認のまま緑にはしない）: "
              f"{', '.join(e['key'] for e in errors)}")

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_keys": len(keys),
        "checked": checked,
        "bad": len(rows),
        "bullets": tot_b,
        "quotes": tot_q,
        "max_bad": args.max_bad,
        "items": rows,
        "errors": errors,
    }
    if args.json:
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        json.dump(report, open(REPORT_PATH, "w"), ensure_ascii=False, indent=1)
        print(f"\n保存: {REPORT_PATH}")

    if errors or len(rows) > args.max_bad:
        sys.exit(1)
    print("\nOK")


if __name__ == "__main__":
    main()
