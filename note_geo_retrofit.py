#!/usr/bin/env python3
"""公開済みnote記事に「要点サマリー（定義文＋箇条書き）」と「よくある質問」を後付けする。

なぜ上位記事だけを直すのか:
  2026-09-04 の実測で、8/28→9/4 の全期間PV +563 のうち **新記事7本の寄与は 15（2.7%）**、
  残り 97.3% は既存記事の検索流入の積み上がりだった（8/10→8/28 も 95%）。記事を足しても
  その月の伸びには効かない。伸びているのは既存記事で、全期間PV上位30本が全PVの 62.5%。

なぜこの2ブロックなのか:
  2026-08-10 の構造比較（上位15本 vs 下位15本）で、検索に効いていたのは**具体数値の量**
  だけだった。その結果を `note_article_generator` のプロンプトへ反映（箇条書き3〜5箇所必須・
  1文定義必須）したが、**既存記事は古い構造のまま**で未着手だった。2026-09-04 に上位30本を
  公開APIで実測すると:
    - 29/30 が `<ul>` 1個・`<li>` 3個 = 「あわせて読みたい」の内部リンクだけ。**本文の箇条書きは0**
    - 30/30 が `<table>` 0個
    - 15/30 が「〇〇とは…です」型の定義文なし
  検索エンジンもAIも「答えが先に、箇条書きで、質問の形で」書かれた記事を引く。それを
  **本文にすでに書いてある事実だけ**で後付けするのがこのスクリプト。

安全側の作り:
  - 生成は本文限定。**新しい事実は足させない**（プロンプト＋機械検品の二重）
  - 11 より大きい数値が生成文に出たら、**その数字が元本文に存在しない限り却下**する
    （捏造の実害はほぼ金額・人数・％なので、「3つ」のような列挙の小数字だけ通す）
  - `facts_patterns.common_violations` を通す（確定ファクト・LINEリンク・判断軸）
  - 「リスナー」の呼び捨てを弾く
  - 2ブロックは**1回のPUTにまとめる**（別々に回すと同じ記事へPUTが2回飛ぶ）

2通りの作り方:
  (a) `--dump` で対象記事の本文を書き出し、**人間かClaudeが書いて** `--from` で流し込む（推奨）
      GEMINI_API_KEY はローカルに無く GitHub secrets にしか置いていない。Google APIの
      予算も絞っているので、既定はこちら。
  (b) `--gemini` で Gemini に生成させる（キーがある環境だけ）
  どちらも同じ `check()` を通る。検品に落ちた記事は**書き換えない**。

使い方:
  python3 note_geo_retrofit.py --dump --top 30            # 本文をJSONに書き出す（GETのみ）
  python3 note_geo_retrofit.py --from blocks.json --plan  # 検品だけ流す（書き込みなし）
  python3 note_geo_retrofit.py --from blocks.json         # 反映
  python3 note_geo_retrofit.py --gemini --plan --top 30   # Geminiで生成して中身を出す
  python3 note_geo_retrofit.py --verify --top 30          # 反映後の位置検証（公開API・GETのみ）
"""
import json
import os
import re
import sys
import time

import requests

import facts_patterns
from note_cta_publish import req_session
from note_internal_links_publish import RELATED_MARK, find_insert_pos
from note_early_cta_publish import EARLY_MARK

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "data", "note_geo_log.json")

MARK_POINTS = "この記事の要点"
MARK_FAQ = "よくある質問"

# 属性を許す正規表現でしか見てはいけない。note は保存時に見出しへ name/id を
# 振り直すので、"<h3>この記事の要点" のような固定文字列は次に読むとマッチせず、
# 同じブロックを二重挿入する（[[project-note-pv-stats]] で実測済みの罠）。
POINTS_RE = re.compile(r"<h[1-6][^>]*>[^<]*" + MARK_POINTS)
FAQ_RE = re.compile(r"<h[1-6][^>]*>[^<]*" + MARK_FAQ)
REL_RE = re.compile(r"<h[1-6][^>]*>\s*" + re.escape(RELATED_MARK) + r"\s*</h[1-6]>")

BATCH = 8
BATCH_SLEEP = 25

# 列挙の「3つ」「5選」のような小さい数字は本文照合を免除する。
# 捏造の実害が出るのは金額・人数・％・年で、いずれも12以上になる。
NUM_FREE_MAX = 11


# ─── 生成 ───────────────────────────────────────────────

PROMPT = """あなたはSEO/GEO（AI検索最適化）の編集者です。
すでに公開されている記事の本文を渡します。**本文に書かれている内容だけ**を使って、
記事の冒頭に置く「要点サマリー」と、末尾に置く「よくある質問」を作ってください。

【記事タイトル】
{title}

【厳守】
- 本文に書かれていない事実・数値・固有名詞を**絶対に足さない**。推測で補わない
- 数値は**本文に出てくる数値だけ**を使う（金額・％・人数・年数すべて）
- リスナーは必ず「リスナーさん」と書く（呼び捨て禁止）
- 「手数料なし」「違約金なし」「いつでも退所」「契約期間」は書かない
- 月収の目安を書くなら本文の表記をそのまま使う（勝手に別の額に置き換えない）
- 断定を避けた曖昧な言い回し（「かもしれません」「人によります」）にしない。本文の結論を言う

【出力】JSONだけを返す。前後に説明やコードフェンスを付けない。
{{
  "definition": "記事の主題を1文で定義する。『〇〇とは、…です。』の形。40〜90字",
  "points": [
    "この記事の結論を先に言う箇条書き。1本30〜70字。可能なら本文の具体数値を入れる",
    "（4本ちょうど。内容が重複しないこと）"
  ],
  "faqs": [
    {{"q": "この記事を検索する人が実際に打ちそうな質問。20〜40字。末尾は「？」",
      "a": "本文の内容で答える。結論を最初の1文で言い切る。60〜140字"}}
  ]
}}
points は4本、faqs は3本ちょうど。

【本文】
{body}
"""


def strip_html(html):
    t = re.sub(r"<[^>]+>", "", html or "")
    return re.sub(r"[ \t]+", " ", t)


def numbers_in(text):
    z = str.maketrans("０１２３４５６７８９", "0123456789")
    return re.findall(r"\d+", text.translate(z).replace(",", ""))


def generate(api_key, title, body_html):
    from google import genai

    src = strip_html(body_html)[:14000]
    client = genai.Client(api_key=api_key)
    prompt = PROMPT.format(title=title, body=src)
    last = None
    for model in ("gemini-2.5-flash", "gemini-2.0-flash"):
        for attempt in range(3):
            try:
                r = client.models.generate_content(model=model, contents=prompt)
                txt = (r.text or "").strip()
                txt = re.sub(r"^```(?:json)?|```$", "", txt, flags=re.M).strip()
                return json.loads(txt)
            except Exception as e:  # 503/429 と JSON崩れの両方
                last = e
                time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"生成に失敗: {type(last).__name__}: {last}")


def check(data, body_html):
    """生成結果を機械検品して問題のリストを返す（空なら合格）。"""
    problems = []
    if not isinstance(data, dict):
        return ["JSONがdictでない"]
    d = (data.get("definition") or "").strip()
    pts = [str(p).strip() for p in (data.get("points") or [])]
    faqs = [f for f in (data.get("faqs") or []) if isinstance(f, dict)]

    if not (20 <= len(d) <= 140):
        problems.append(f"definition の長さ {len(d)}")
    if "とは" not in d:
        problems.append("definition が定義文の形になっていない")
    if len(pts) != 4:
        problems.append(f"points が {len(pts)} 本")
    if any(not (15 <= len(p) <= 120) for p in pts):
        problems.append("points の長さが範囲外")
    if len(pts) != len(set(pts)):
        problems.append("points が重複")
    # 上位30本を実測すると 26本は既に「よくある質問」の節を持っている（2026-09-04）。
    # そこへFAQを足す必要はないので、既にある記事は faqs 空を許す。
    if FAQ_RE.search(body_html or ""):
        if faqs:
            problems.append("この記事には既に「よくある質問」がある（faqs は空にする）")
    elif len(faqs) != 3:
        problems.append(f"faqs が {len(faqs)} 本")
    for f in faqs:
        q, a = (f.get("q") or "").strip(), (f.get("a") or "").strip()
        if not q.endswith(("？", "?")):
            problems.append(f"質問が疑問形でない: {q[:20]}")
        if not (10 <= len(q) <= 60) or not (30 <= len(a) <= 220):
            problems.append(f"FAQ の長さが範囲外: q{len(q)} a{len(a)}")

    text = "\n".join([d] + pts + [f.get("q", "") + f.get("a", "") for f in faqs])

    # ① 数値の捏造。本文に無い 12 以上の数字は通さない
    src_nums = set(numbers_in(strip_html(body_html)))
    for n in numbers_in(text):
        if int(n) > NUM_FREE_MAX and n not in src_nums:
            problems.append(f"本文に無い数値: {n}")
    # ② 確定ファクト・LINEリンク・判断軸
    for reason, hit in facts_patterns.common_violations(text):
        problems.append(f"確定ファクト違反[{reason}]: {hit}")
    # ③ リスナーの呼び捨て
    m = re.search(r"リスナー(?!さん)", text)
    if m:
        problems.append("「リスナー」の呼び捨て")
    return sorted(set(problems))


# ─── 挿入 ───────────────────────────────────────────────

def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def points_html(data):
    lis = "".join(f"<li>{esc(p.strip())}</li>" for p in data["points"])
    return (f"<h3>📌 {MARK_POINTS}</h3>"
            f"<p><strong>{esc(data['definition'].strip())}</strong></p>"
            f"<ul>{lis}</ul>")


def faq_html(data):
    out = [f"<h2>❓ {MARK_FAQ}</h2>"]
    for f in data["faqs"]:
        out.append(f"<h3>{esc(f['q'].strip())}</h3><p>{esc(f['a'].strip())}</p>")
    return "".join(out)


def points_pos(html):
    """要点ブロックを入れる位置。冒頭CTAの直後 → 最初の見出しの直前 → 3つめの <p> の前。

    冒頭CTAより前に入れてはいけない。CTAの位置(%)は note_funnel_guard が
    40%以内で見ているので、CTAは常に本文の先頭側に残す。
    """
    i = html.find(EARLY_MARK)
    if i >= 0:
        e = html.find("</p>", i)
        if e >= 0:
            return e + 4
    m = re.search(r"<h[1-4][\s>]", html)
    if m and m.start() / max(1, len(html)) * 100 <= 40:
        return m.start()
    starts = [m2.start() for m2 in re.finditer(r"<p[\s>]", html)]
    if not starts:
        return None
    return starts[2] if len(starts) > 2 else starts[-1]


def faq_pos(html):
    """FAQ を入れる位置。「あわせて読みたい」の直前 → 末尾CTAの直前。

    読み順を 本文 → FAQ → 関連記事 → 特典CTA にしたいので関連ブロックより前に入れる。
    """
    m = REL_RE.search(html)
    if m:
        return m.start()
    p = find_insert_pos(html)
    return len(html) if p is None else p


def make_transform(data):
    def _t(key, html):
        out = html
        if data.get("faqs") and not FAQ_RE.search(out):
            p = faq_pos(out)
            if p is None:
                print("  skip（FAQの挿入位置が無い）")
            else:
                out = out[:p] + faq_html(data) + out[p:]
        if not POINTS_RE.search(out):
            p = points_pos(out)
            if p is None:
                print("  skip（要点の挿入位置が無い）")
            else:
                out = out[:p] + points_html(data) + out[p:]
        return None if out == html else out
    return _t


# ─── 対象の選定 ─────────────────────────────────────────

def public_body(key, session=None):
    s = session or requests.Session()
    s.headers.setdefault("User-Agent", "Mozilla/5.0")
    d = s.get(f"https://note.com/api/v3/notes/{key}",
              headers={"Cache-Control": "no-cache"}, timeout=25).json()["data"]
    return d


def targets(top):
    """最新のPV CSVから全期間PV降順で上位 top 本を返す（公開中のみ）。"""
    import csv
    import glob
    files = sorted(glob.glob(os.path.join(BASE_DIR, "data", "note_pv_*.csv")))
    if not files:
        raise SystemExit("data/note_pv_*.csv が無い。先に python3 note_pv_report.py")
    path = files[-1]
    rows = list(csv.DictReader(open(path)))
    rows.sort(key=lambda r: -int(r["pv_all"]))
    print(f"対象の母集団: {os.path.basename(path)}（{len(rows)}本）")
    return [(r["key"], r["title"], int(r["pv_all"])) for r in rows[:top]]


def load_log():
    if os.path.exists(LOG_FILE):
        try:
            return json.load(open(LOG_FILE))
        except Exception:
            return {}
    return {}


# ─── 検証 ───────────────────────────────────────────────

def verify_positions(top):
    """公開APIで反映後の構造と位置を実測する。

    一括処理のあと「PUT:200 / marker=True / ログok」はどれも位置の正しさを
    保証しない（2026-08-29 の教訓）。割合で見るまで終わりではない。
    """
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    ng = 0
    for key, title, pv in targets(top):
        d = public_body(key, s)
        b = d.get("body") or ""
        n = max(1, len(b))
        def pct(rx):
            m = rx.search(b) if hasattr(rx, "search") else None
            return None if not m else round(m.start() / n * 100, 1)
        p_pt, p_faq, p_rel = pct(POINTS_RE), pct(FAQ_RE), pct(REL_RE)
        i = b.find(EARLY_MARK)
        p_cta = None if i < 0 else round(i / n * 100, 1)
        ul = len(re.findall(r"<ul", b))
        bad = []
        if p_pt is None:
            bad.append("要点なし")
        elif p_pt > 40:
            bad.append(f"要点が{p_pt}%")
        if p_faq is None:
            bad.append("FAQなし")
        elif p_faq < 40:
            bad.append(f"FAQが{p_faq}%")
        if p_cta is None or p_cta > 40:
            bad.append(f"冒頭CTA={p_cta}")
        if p_rel is None:
            bad.append("関連なし")
        if not d.get("eyecatch"):
            bad.append("eyecatchなし")
        if len(d.get("hashtag_notes") or []) < 10:
            bad.append(f"タグ{len(d.get('hashtag_notes') or [])}")
        ng += 1 if bad else 0
        flag = "NG " + " / ".join(bad) if bad else "ok"
        print(f"  {pv:>4}PV CTA{str(p_cta):>5}% 要点{str(p_pt):>5}% FAQ{str(p_faq):>5}% "
              f"関連{str(p_rel):>5}% ul{ul:>2}  {flag}  {title[:30]}")
        time.sleep(1.0)
    print(f"\n検証: NG {ng} 本 / {top} 本")
    return ng


# ─── main ───────────────────────────────────────────────

def apply_all(plans, log):
    """検品を通ったブロックを1本ずつ1回のPUTで反映する。"""
    from note_leadmagnet_publish import publish_one
    ok = skip = fail = 0
    keys = list(plans)
    for i, key in enumerate(keys, 1):
        title, data = plans[key]
        print(f"\n[{i}/{len(keys)}] {key} {title[:30]}", flush=True)
        try:
            r = publish_one(key, make_transform(data), expect_marker=MARK_POINTS)
            log[key] = r
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


def collect(items, session):
    """まだブロックが入っていない記事だけを (key, title, pv, body) で返す。"""
    todo = []
    for key, title, pv in items:
        d = public_body(key, session)
        if d.get("status") != "published":
            print(f"  skip（未公開） {title[:30]}")
            continue
        body = d.get("body") or ""
        if POINTS_RE.search(body) and FAQ_RE.search(body):
            print(f"  済み {title[:36]}")
            continue
        todo.append((key, d["name"], pv, body))
        time.sleep(0.6)
    return todo


def main():
    args = sys.argv[1:]
    plan_only = "--plan" in args
    top = 30
    if "--top" in args:
        top = int(args[args.index("--top") + 1])
    explicit = [a for a in args if a.startswith("n") and not a.startswith("--")]

    if "--verify" in args:
        sys.exit(1 if verify_positions(top) else 0)

    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"
    log = load_log()

    if explicit:
        items = [(k, public_body(k, session)["name"], 0) for k in explicit]
    else:
        items = targets(top)

    # --dump: 本文を書き出して人間/Claudeに書かせる（既定の入り口）
    if "--dump" in args:
        out = args[args.index("--dump") + 1] if len(args) > args.index("--dump") + 1 \
            and not args[args.index("--dump") + 1].startswith("--") else "geo_bodies.json"
        todo = collect(items, session)
        payload = [{"key": k, "title": t, "pv_all": pv, "text": strip_html(b)}
                   for k, t, pv, b in todo]
        json.dump(payload, open(out, "w"), ensure_ascii=False, indent=1)
        print(f"\n{len(payload)} 本を {out} に書き出した")
        return

    # --from: 書いたブロックを流し込む
    if "--from" in args:
        src = args[args.index("--from") + 1]
        blocks = json.load(open(src))
        if isinstance(blocks, list):
            blocks = {b["key"]: b for b in blocks}
        plans = {}
        for key, data in blocks.items():
            d = public_body(key, session)
            title = d["name"]
            body = d.get("body") or ""
            # 要点が入っていて、FAQも「要らない or 既にある」なら何もすることが無い。
            # ここを `要点 and FAQ` で見ると、FAQを既に持つ記事（上位30本中26本）が
            # 要点を入れる前に「済み」で落ちる。
            faq_done = (not data.get("faqs")) or bool(FAQ_RE.search(body))
            if POINTS_RE.search(body) and faq_done:
                print(f"  済み {title[:36]}")
                continue
            problems = check(data, body)
            if problems:
                print(f"  ✗ 検品NG（書き換えない） {title[:32]}")
                for p in problems:
                    print(f"      - {p}")
                log[key] = "reject: " + "; ".join(problems)[:300]
                continue
            plans[key] = (title, data)
            print(f"  ✓ {title[:44]}")
            time.sleep(0.4)
        json.dump(log, open(LOG_FILE, "w"), ensure_ascii=False, indent=1)
        print(f"\n検品を通ったのは {len(plans)} / {len(blocks)} 本")
        if plan_only:
            print("--plan のため書き込みなし。")
            return
        return apply_all(plans, log)

    if "--gemini" not in args:
        raise SystemExit("--dump / --from / --gemini / --verify のどれかを指定する")

    from note_article_generator import get_gemini_api_key
    api_key = get_gemini_api_key()
    if not api_key:
        raise SystemExit("GEMINI_API_KEY が無い（--dump → --from を使う）")

    todo = collect(items, session)
    print(f"\n生成対象 {len(todo)} 本")
    plans = {}
    for i, (key, title, pv, body) in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] {pv:>4}PV {title[:40]}", flush=True)
        try:
            data = generate(api_key, title, body)
        except Exception as e:
            print(f"  !! 生成失敗: {e}")
            log[key] = f"gen-error: {e}"
            continue
        problems = check(data, body)
        if problems:
            print("  ✗ 検品NG（この記事は書き換えない）")
            for p in problems:
                print(f"      - {p}")
            log[key] = "reject: " + "; ".join(problems)[:300]
            continue
        plans[key] = (title, data)
        print(f"  定義: {data['definition']}")
        for p in data["points"]:
            print(f"    ・{p}")
        for f in data["faqs"]:
            print(f"    Q {f['q']}")
            print(f"    A {f['a'][:70]}")

    json.dump(log, open(LOG_FILE, "w"), ensure_ascii=False, indent=1)
    print(f"\n検品を通ったのは {len(plans)} / {len(todo)} 本")
    if plan_only:
        print("--plan のため書き込みなし。")
        return
    apply_all(plans, log)
    print("→ python3 note_geo_retrofit.py --verify --top", top)


if __name__ == "__main__":
    main()
