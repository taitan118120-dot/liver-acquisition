#!/usr/bin/env python3
"""公開済みnote記事の「見た目だけ箇条書き・見た目だけ表」を本物のHTML構造に直す。

これは**文言を1文字も変えない**施策。追加も削除もせず、マークアップだけを直す。

なぜ必要か（2026-09-04 実測）:
  全期間PV上位30本を公開APIで数えると、29/30 が `<ul>` 1個・`<li>` 3個しか持たない。
  その1個は「あわせて読みたい」の内部リンクで、**本文の箇条書きは0**。`<table>` は 30/30 で0。
  ところが本文には箇条書きも比較表もちゃんと書かれている。ただ全部 `<p>` で書かれている:
    <p>・収益源: ライブギフト ／ 概要: … ／ 収益化までの距離: 本命収益</p>
  上位12本で `<p>` 2,800個のうち **612個が「・」始まり**、そのうち **179個は「／」区切りの表の行**。
  読者には箇条書き・表に見えるが、検索エンジンとAIには**ただの段落の壁**にしか見えない。
  さらに `<p>&gt; …</p>` が58個あり、これは記事上で「> 」という記号が**そのまま表示されている**
  （引用にしたかったが素のテキストで入っている）。

やること:
  1. 連続する「・」段落 → `<ul><li>`
  2. 連続する「&gt;」段落 → `<blockquote>`（読者に見えている「> 」の記号も消える）

⚠️ **note は `<table>` を保存時に捨てる**（2026-09-04 に n944fb192d459 で実測）。
  捨てるだけならまだしも、セルのテキストを**1つの段落に連結して**残すので
  「パターンおすすめの枠理由一人暮らし21:00〜23:00人が多い時間。…」という
  読めない塊になる。ラベルと値の対応が完全に失われるので**表は作らない**のが正しい
  （`--table` で有効化はできるが、使ってはいけない。検証用に残しているだけ）。
  「・ラベル: 値 ／ ラベル: 値」の行は `<ul><li>` に入れる。テキストは1文字も落ちない。
  `<ul><li>` は保存後も生き残る（note 側が li の中を `<p>` で包む）。

安全側の作り:
  - **文言の同一性を機械保証**する。変換前後で「タグを除いたテキスト」から記号
    （・ / &gt; / ／ / 空白）を落としたものが一致しなければ、その記事は書き換えない
  - PUT の前に元の本文を `data/note_body_backup/<key>.json` に保存する
  - 冪等。「・」段落も「&gt;」段落も無い記事は skip

使い方:
  python3 note_geo_structure.py --plan --top 30       # 変換内容を出すだけ（GETのみ）
  python3 note_geo_structure.py --test <key>          # 1本だけ実際に反映して構造を確認
  python3 note_geo_structure.py --top 30              # 上位30本に反映
  python3 note_geo_structure.py --verify --top 30     # 反映後に公開APIで構造を実測
  python3 note_geo_structure.py --restore <key>       # data/note_body_backup から本文を戻す
"""
import json
import os
import re
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "data", "note_structure_log.json")
BACKUP_DIR = os.path.join(BASE_DIR, "data", "note_body_backup")

BATCH = 8
BATCH_SLEEP = 25

# note が保存時に name/id を振り直すので、要素の抽出は属性を許す形でしか書けない。
ELEM_RE = re.compile(r"<(p|h[1-6]|ul|ol|blockquote|figure|table|div)([^>]*)>(.*?)</\1>", re.S)

# 表として組めるのは「ラベル: 値」が「／」で並んでいる行。全角コロンも受ける。
PAIR_RE = re.compile(r"^\s*([^:：]{1,24})\s*[:：]\s*(.*)$", re.S)


def strip_tags(html):
    return re.sub(r"<[^>]+>", "", html or "")


TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.S)
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.S)


def detable(html):
    """<table> を元の「ラベル: 値 ／ ラベル: 値」の行に戻す。

    表にすると**ラベルはヘッダに1回だけ**になるので、素のテキスト比較では必ず
    食い違う（実測でここに引っかかった）。文言が保たれているかを見るには
    こうして往復させてから比べるしかない。
    """
    def _one(m):
        rows = [[strip_tags(c) for c in CELL_RE.findall(r)] for r in ROW_RE.findall(m.group(1))]
        if not rows:
            return m.group(0)
        head, body = rows[0], rows[1:]
        out = []
        for r in body:
            out.append("".join(f"{head[i] if i < len(head) else ''}:{v}"
                               for i, v in enumerate(r)))
        return "".join(out)
    return TABLE_RE.sub(_one, html)


def norm(html):
    """文言の同一性を見るための正規化。記号と空白を全部落とす。"""
    t = strip_tags(detable(html))
    t = t.replace("&nbsp;", "").replace("：", ":")
    for ch in "・／/|>＞ \t\n\r　":
        t = t.replace(ch, "")
    t = t.replace("&gt;", "")
    return t


def tokenize(body):
    """本文をトップレベル要素の並びに分解する。取りこぼしはそのまま残す。"""
    out, pos = [], 0
    for m in ELEM_RE.finditer(body):
        if m.start() > pos:
            out.append(("raw", body[pos:m.start()]))
        out.append(("el", m.group(0), m.group(1), m.group(3)))
        pos = m.end()
    if pos < len(body):
        out.append(("raw", body[pos:]))
    return out


def kind(tok):
    """要素の種類を返す: bullet / quote / spacer / other / raw"""
    if tok[0] == "raw":
        return "raw"
    tag, inner = tok[2], tok[3]
    if tag != "p":
        return "other"
    text = strip_tags(inner).strip().replace("&nbsp;", "").replace("　", " ").strip()
    if not text:
        return "spacer"
    if text.startswith("・"):
        return "bullet"
    if text.startswith("&gt;") or text.startswith(">") or text.startswith("＞"):
        return "quote"
    return "other"


def _drop_marker(inner, markers):
    """先頭の記号だけを落とす。タグ（<strong> 等）は壊さない。"""
    out = inner
    for mk in markers:
        # 先頭のタグ列を飛ばして最初のテキストの頭にある記号を1つ落とす
        m = re.match(r"^((?:\s|<[^>]+>)*)" + re.escape(mk) + r"\s*", out)
        if m:
            return out[:m.end(1)] + out[m.end():]
    return out


def table_row(inner):
    """「ラベル: 値 ／ ラベル: 値」を [(label, value), ...] にする。表にできなければ None。"""
    text = _drop_marker(inner, ["・"])
    text = strip_tags(text).replace("&nbsp;", " ").strip()
    parts = [p.strip() for p in re.split(r"[／/]", text) if p.strip()]
    if len(parts) < 2:
        return None
    pairs = []
    for p in parts:
        m = PAIR_RE.match(p)
        if not m:
            return None
        pairs.append((m.group(1).strip(), m.group(2).strip()))
    return pairs


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_table(rows):
    """ラベル列が揃った行群を <table> にする。"""
    labels = [l for l, _ in rows[0]]
    head = "".join(f"<th>{esc(l)}</th>" for l in labels)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f"<td>{esc(v)}</td>" for _, v in r) + "</tr>"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def build_ul(items):
    lis = "".join(f"<li>{_drop_marker(i, ['・']).strip()}</li>" for i in items)
    return f"<ul>{lis}</ul>"


def build_quote(items):
    inner = "<br>".join(_drop_marker(i, ["&gt;", "＞", ">"]).strip() for i in items)
    return f"<blockquote>{inner}</blockquote>"


def transform_body(body, use_table=True):
    """(新しい本文, 統計) を返す。変えるところが無ければ (None, 統計)。"""
    toks = tokenize(body)
    kinds = [kind(t) for t in toks]
    out = []
    stats = {"ul": 0, "li": 0, "table": 0, "tr": 0, "quote": 0}
    i = 0
    while i < len(toks):
        k = kinds[i]
        if k in ("bullet", "quote"):
            j = i
            while j < len(toks) and kinds[j] == k:
                j += 1
            group = [toks[x][3] for x in range(i, j)]
            if k == "quote":
                out.append(build_quote(group))
                stats["quote"] += 1
            else:
                rows = [table_row(g) for g in group]
                same = (use_table and len(rows) >= 2 and all(rows)
                        and len({tuple(l for l, _ in r) for r in rows}) == 1
                        and len(rows[0]) >= 2)
                if same:
                    out.append(build_table(rows))
                    stats["table"] += 1
                    stats["tr"] += len(rows)
                else:
                    out.append(build_ul(group))
                    stats["ul"] += 1
                    stats["li"] += len(group)
            i = j
            continue
        out.append(toks[i][1] if toks[i][0] == "el" else toks[i][1])
        i += 1
    new = "".join(out)
    if new == body:
        return None, stats
    return new, stats


def check_same_text(old, new):
    """文言が変わっていないことを機械保証する。"""
    a, b = norm(old), norm(new)
    if a == b:
        return None
    # どこで食い違ったかを出す（黙って落とさない）
    n = min(len(a), len(b))
    p = next((x for x in range(n) if a[x] != b[x]), n)
    return (f"文言が変わった（前{len(a)}字 / 後{len(b)}字、{p}字目から）\n"
            f"    前: …{a[max(0, p - 30):p + 40]}…\n"
            f"    後: …{b[max(0, p - 30):p + 40]}…")


# ─── 対象と実行 ─────────────────────────────────────────

def public_note(key, session=None):
    s = session or requests.Session()
    s.headers.setdefault("User-Agent", "Mozilla/5.0")
    return s.get(f"https://note.com/api/v3/notes/{key}",
                 headers={"Cache-Control": "no-cache"}, timeout=25).json()["data"]


def targets(top):
    import csv
    import glob
    files = sorted(glob.glob(os.path.join(BASE_DIR, "data", "note_pv_*.csv")))
    if not files:
        raise SystemExit("data/note_pv_*.csv が無い。先に python3 note_pv_report.py")
    rows = list(csv.DictReader(open(files[-1])))
    rows.sort(key=lambda r: -int(r["pv_all"]))
    print(f"対象の母集団: {os.path.basename(files[-1])}（{len(rows)}本）")
    return [(r["key"], r["title"], int(r["pv_all"])) for r in rows[:top]]


def backup(key, note):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"{key}.json")
    if os.path.exists(path):
        return path  # 最初の1回だけ残す（2回目以降は変換後で上書きしない）
    json.dump({"key": key, "title": note["name"], "body": note["body"],
               "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")},
              open(path, "w"), ensure_ascii=False, indent=1)
    return path


def load_log():
    if os.path.exists(LOG_FILE):
        try:
            return json.load(open(LOG_FILE))
        except Exception:
            return {}
    return {}


def plan(items, session, use_table=True, show=0):
    todo = []
    for key, title, pv in items:
        d = public_note(key, session)
        if d.get("status") != "published":
            print(f"  skip（未公開） {title[:30]}")
            continue
        body = d.get("body") or ""
        new, st = transform_body(body, use_table=use_table)
        if new is None:
            print(f"  変更なし {title[:36]}")
            continue
        err = check_same_text(body, new)
        if err:
            print(f"  ✗ {title[:32]}\n    {err}")
            continue
        print(f"  {pv:>4}PV ul+{st['ul']}({st['li']}項) 表+{st['table']}({st['tr']}行) "
              f"引用+{st['quote']}  {title[:34]}")
        todo.append((key, d["name"], pv, body, new, st))
        if show and len(todo) <= show:
            print("    --- 変換後の抜粋 ---")
            for m in list(re.finditer(r"<(ul|table|blockquote)[^>]*>.*?</\1>", new, re.S))[:3]:
                print("    " + m.group(0)[:400].replace("\n", " "))
        time.sleep(0.5)
    return todo


def apply(todo, log, use_table=True):
    from note_leadmagnet_publish import publish_one
    ok = skip = fail = 0
    for i, (key, title, pv, body, new, st) in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] {key} {title[:30]}", flush=True)
        d = public_note(key)
        print(f"  backup → {os.path.basename(backup(key, d))}")

        def _t(_key, live_html, _use=use_table):
            # publish_one は必ずライブ本文を取り直して渡してくる（並行セッション対策）。
            # ここで**もう一度**変換と文言照合をやる。plan 時点の本文で作った差分を
            # そのまま貼ってはいけない。
            n, _ = transform_body(live_html, use_table=_use)
            if n is None:
                return None
            e = check_same_text(live_html, n)
            if e:
                raise RuntimeError(e)
            return n

        try:
            r = publish_one(key, _t, expect_marker=None)
            log[key] = {"result": r, **st}
            ok += 1 if r == "ok" else 0
            skip += 1 if r == "skip" else 0
        except Exception as e:
            print(f"  !! 失敗: {e}", flush=True)
            log[key] = f"error: {e}"
            fail += 1
        json.dump(log, open(LOG_FILE, "w"), ensure_ascii=False, indent=1)
        time.sleep(BATCH_SLEEP if i % BATCH == 0 else 3)
    print(f"\n完了 ok={ok} skip={skip} fail={fail}")
    return ok, skip, fail


def verify(top):
    """公開APIで構造を実測する。PUT:200 は構造が入った証拠にならない。"""
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    ng = 0
    for key, title, pv in targets(top):
        d = public_note(key, s)
        b = d.get("body") or ""
        ul = len(re.findall(r"<ul", b))
        li = len(re.findall(r"<li", b))
        tb = len(re.findall(r"<table", b))
        bq = len(re.findall(r"<blockquote", b))
        naka = len([t for t in re.findall(r"<p[^>]*>(.*?)</p>", b, re.S)
                    if strip_tags(t).strip().startswith("・")])
        bad = []
        if naka:
            bad.append(f"「・」段落が{naka}個 残り")
        if ul <= 1:
            bad.append("本文の箇条書きが無い")
        if not d.get("eyecatch"):
            bad.append("eyecatchなし")
        if len(d.get("hashtag_notes") or []) < 10:
            bad.append(f"タグ{len(d.get('hashtag_notes') or [])}")
        ng += 1 if bad else 0
        print(f"  {pv:>4}PV ul{ul:>3} li{li:>3} 表{tb:>2} 引用{bq:>2} 「・」残{naka:>3}  "
              f"{'NG ' + ' / '.join(bad) if bad else 'ok'}  {title[:28]}")
        time.sleep(0.9)
    print(f"\n検証: NG {ng} 本 / {top} 本")
    return ng


def main():
    args = sys.argv[1:]
    top = 30
    if "--top" in args:
        top = int(args[args.index("--top") + 1])
    # 既定で表は作らない（note が保存時に捨てて段落に潰すため）。--table は検証用。
    use_table = "--table" in args

    if "--verify" in args:
        sys.exit(1 if verify(top) else 0)

    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"
    log = load_log()

    if "--restore" in args:
        key = args[args.index("--restore") + 1]
        saved = json.load(open(os.path.join(BACKUP_DIR, f"{key}.json")))
        from note_leadmagnet_publish import publish_one
        print(f"復元: {saved['title'][:40]}（{saved['saved_at']} 時点 / {len(saved['body'])}字）")
        r = publish_one(key, lambda _k, live: (None if live == saved["body"]
                                               else saved["body"]), expect_marker=None)
        print("結果:", r)
        return

    if "--test" in args:
        key = args[args.index("--test") + 1]
        d = public_note(key, session)
        items = [(key, d["name"], 0)]
        todo = plan(items, session, use_table, show=1)
        if not todo:
            return
        apply(todo, log, use_table)
        print("\n--- 反映後 ---")
        d2 = public_note(key)
        b = d2["body"]
        for tag in ("ul", "li", "table", "tr", "blockquote"):
            print(f"  <{tag}> = {len(re.findall('<' + tag, b))}")
        naka = len([t for t in re.findall(r"<p[^>]*>(.*?)</p>", b, re.S)
                    if strip_tags(t).strip().startswith("・")])
        print(f"  「・」段落の残り = {naka}")
        e = check_same_text(json.load(open(os.path.join(BACKUP_DIR, f"{key}.json")))["body"], b)
        print("  文言の同一性:", "一致" if not e else f"NG\n{e}")
        return

    explicit = [a for a in args if a.startswith("n") and not a.startswith("--")]
    items = [(k, public_note(k, session)["name"], 0) for k in explicit] if explicit \
        else targets(top)
    todo = plan(items, session, use_table, show=2 if "--plan" in args else 0)
    print(f"\n対象 {len(todo)} 本"
          f"（ul {sum(t[5]['ul'] for t in todo)} / 表 {sum(t[5]['table'] for t in todo)} "
          f"/ 引用 {sum(t[5]['quote'] for t in todo)}）")
    if "--plan" in args:
        print("--plan のため書き込みなし。")
        return
    apply(todo, log, use_table)
    print(f"→ python3 note_geo_structure.py --verify --top {top}")


if __name__ == "__main__":
    main()
