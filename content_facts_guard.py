#!/usr/bin/env python3
"""content_facts_guard.py — LP・特典PDFの確定ファクト番犬
=========================================================
背景（2026-08-12 に実際に起きた取りこぼし）:
  「京都コレクションは実在しない」と 2026-08-01 に確定していたのに、
  3ヶ所で生き残っていた:
    - lp/beginner/index.html / lp/agency/index.html の #network カード
    - lead_magnet/agency_starter_guide.html P6
      → そこから焼いた **配布中の lp/shared/agency_starter_guide.pdf の実体にも**混入し、
        LINE登録した代理店希望者に実在しないイベントが配られていた

  真因は、またしても走査対象の設計だった:
    - link_guard.py の CONTENT_GLOBS は lp/**/*.html を含むが、
      **link_guard はリンクの生死しか見ず、文面の中身を一切見ない**
    - social_profile_guard.py は「京都コレクション」の禁止パターンを持っていたが、
      **走査対象がプロフィールと固定ポストだけ**だった
    - lead_magnet/*.html と lp/shared/*.pdf は **どの番犬のスコープにも入っていなかった**。
      とくにPDFはバイナリなので、普通の grep でも一生ヒットしない

この番犬が見る4軸:
  1. 禁止パターン走査 — 確定ファクト（[[project_taitan_pro_note_facts]] の常設grep）を
     LP・特典HTML原稿・**配布PDFの抽出テキスト**に当てる。
     パターンの正本は facts_patterns.py（媒体共通）。ここには一切コピーを置かない。
  2. 原稿HTML ↔ 配布PDF の同期 — PDFは原稿から焼くが、**焼き直しを忘れると中身がズレる**。
     HTMLだけ直して緑になっても、実際に配られているのはPDFなので担保にならない。
     HTML本文の各ブロックがPDFの抽出テキストに載っているかを1つずつ確認する。
  3. 配布URLのSHA固定 — 特典PDFは jsDelivr の **コミットSHA固定URL** で配られる
     （line_bot/messages.py の GUIDE_PDF_SHA / AGENCY_GUIDE_PDF_SHA）。
     PDFを差し替えてもSHAを上げ忘れると、**直したはずの旧PDFが配られ続ける**。
     ピン留めSHAのblobと作業ツリーのPDFが同一かを git で突合し、
     さらに（--repo-only でなければ）jsDelivr が実際に返すバイトまで照合する。
  4. 孤児の配布物 — lp/shared/*.pdf でリポジトリのどこからも参照されていないもの。
     参照が無い＝更新フローに乗らない＝旧ファクトが公開URLに残り続ける温床。

判定ポリシー:
  - NG   = 禁止パターン検出／HTMLとPDFの乖離／SHA固定のズレ／孤児PDF
           /pdftotext が使えず走査できなかった → exit 1（Actionsが赤くなる）
  - WARN = facts_patterns.AUDIT_WARN_LABELS のルール（少額表記・実績誇張・他社比較）。
           主語や文脈で可否が変わり、公開済み長文では人が判断する話なので赤にしない
           （[[feedback_watchdog_autoclose]] 永久に鳴きやむことのない番犬にしない）

使い方:
  python3 content_facts_guard.py              # 全チェック
  python3 content_facts_guard.py --repo-only  # jsDelivr への実アクセスなし（ローカル用）

レポートは data/content_facts_guard_report.json に保存される。
"""

import glob
import html as htmllib
import json
import os
import re
import shutil
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 禁止パターンの正本は facts_patterns.py だけ。ここに再定義すると
# 「必ずどれか1本が古くなる」に逆戻りする（まさに今回の京都コレクションがそれ）。
from facts_patterns import AUDIT_WARN_LABELS, common_violations  # noqa: E402

REPORT_FILE = os.path.join(BASE_DIR, "data", "content_facts_guard_report.json")

# ── 走査対象 ────────────────────────────────────────────────
# 「読者・見込み客の目に直接触れる長文」だけを入れる。
CONTENT_GLOBS = [
    "lead_magnet/*.html",   # 特典PDFの原稿
    "lp/**/*.html",         # 公開LP（Netlify配信）
]
PDF_GLOB = "lp/shared/*.pdf"          # LINE登録者に実際に配られる配布物
LEAD_MAGNET_DIR = "lead_magnet"       # 原稿HTMLの置き場（PDFと同名で対応させる）

# ── jsDelivr のSHA固定配布（line_bot/messages.py が正本）──────────
# (messages.py の定数名, 配布されるPDFの相対パス)
PINNED_PDFS = [
    ("GUIDE_PDF_SHA", "lp/shared/liver_starter_guide.pdf"),
    ("AGENCY_GUIDE_PDF_SHA", "lp/shared/agency_starter_guide.pdf"),
]
JSDELIVR = "https://cdn.jsdelivr.net/gh/taitan118120-dot/liver-acquisition@{sha}/{path}"

# 孤児判定のときに「参照」を探すファイル群
REFERENCE_GLOBS = [
    "*.py", "*/*.py", "*/*/*.py",
    "*.md", "*/*.md", "*/*/*.md", "*/*/*/*.md",
    "*.html", "*/*.html", "*/*/*.html",
    "*.json", "*/*.json", "*.txt", "*/*.txt", "*/*/*.txt",
    "*.yml", ".github/workflows/*.yml",
]

# HTML↔PDF 同期で比較するブロックの最小長（正規化後の文字数）。
# 短い断片は見出し記号やページ番号と衝突して意味を持たないので落とす。
MIN_BLOCK_LEN = 16
# ブロックの一致率は「部分文字列を含むか」では測れない。pdftotext は表を
# **セル単位で行方向に読む**ため、1文が列をまたぐと途中に別セルの語が割り込む
# （実測: 「ファンとの関係づくりがその（TikTokLIVE・まま収入に直結する17LIVEなど）」）。
# 完全一致にすると、PDFは正しいのに毎回赤くなる。N-gram の被覆率で測る。
GRAM_N = 5
# 現状の実測: 290ブロック中288本が 1.000、列またぎの2本が 0.789 / 0.927。
# 一方この閾値は十分に鋭い（30字のブロックで1語8字が変わると 0.5 台まで落ちる）。
BLOCK_COVERAGE_MIN = 0.75


def flat(s):
    """空白を全部落とす。HTMLのタグ由来の改行と、pdftotextの折り返しを吸収する。"""
    return re.sub(r"\s+", "", s or "")


# ── テキスト抽出 ────────────────────────────────────────────
def html_to_text(path):
    src = open(path, encoding="utf-8").read()
    # <head> ごと落とす。<title> は紙面に出ないので PDF 突合のノイズになる
    src = re.sub(r"(?is)<head\b.*?</head>", " ", src)
    src = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", src)
    src = re.sub(r"(?s)<!--.*?-->", " ", src)
    # タグは改行に落とす。あとで flat() するので語がくっつく心配はない
    src = re.sub(r"<[^>]+>", "\n", src)
    return htmllib.unescape(src)


def pdf_to_text(path):
    """pdftotext で抽出。使えないときは (None, 理由) を返して**黙って素通りさせない**。"""
    exe = shutil.which("pdftotext")
    if not exe:
        return None, ("pdftotext が無い（poppler-utils 未導入）。"
                      "PDFはバイナリなので、これが無いと配布物を一切検査できない")
    try:
        r = subprocess.run([exe, "-q", "-enc", "UTF-8", path, "-"],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"pdftotext の実行に失敗: {type(e).__name__}: {e}"[:160]
    if r.returncode != 0:
        return None, f"pdftotext が異常終了（rc={r.returncode}）: {r.stderr.strip()[:120]}"
    return r.stdout, None


def rel(path):
    return os.path.relpath(path, BASE_DIR)


def iter_files(patterns):
    seen = []
    for pat in patterns:
        for p in glob.glob(os.path.join(BASE_DIR, pat), recursive=True):
            if os.path.isfile(p) and p not in seen:
                seen.append(p)
    return sorted(seen)


# ── 1. 禁止パターン走査 ──────────────────────────────────────
def scan_text(text, where):
    """[(赤にするもの), (報告だけするもの)] を返す。"""
    ng, warn = [], []
    for reason, hit in common_violations(text):
        item = {"where": where, "reason": reason, "hit": hit[:80]}
        (warn if reason in AUDIT_WARN_LABELS else ng).append(item)
    return ng, warn


# ── 2. 原稿HTML ↔ 配布PDF の同期 ─────────────────────────────
def _grams(s, n=GRAM_N):
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def check_pdf_sync(html_path, pdf_path, pdf_text):
    """原稿HTMLと配布PDFの中身が一致しているかを2軸で見る。

    ここが本丸。**HTMLだけ直して緑になっても、配られているのはPDF**なので、
    原稿の検品は配布物の担保にならない（2026-08-12 の京都コレクションがまさにこれ）。

    (a) 焼き直し忘れ — gitのコミット時刻で、PDFより後にHTMLが変わっていないか。
        「HTMLを直したがビルドを回していない」を厳密に捕まえる。
    (b) 本文の被覆 — HTML本文の各ブロックがPDFの抽出テキストに載っているか。
        コミットを分けずに（同じコミットで）古いPDFを入れた場合はこちらで出る。

    逆向き（PDFにあってHTMLに無い）は見ない。ページ番号・ヘッダの繰り返しなど
    レンダリング由来の文字列がPDF側にだけ出るのが普通で、誤検知源にしかならない。
    """
    out = []
    where = f"{rel(html_path)} → {rel(pdf_path)}"

    html_at, _ = git("log", "-1", "--format=%ct", "--", rel(html_path))
    pdf_at, _ = git("log", "-1", "--format=%ct", "--", rel(pdf_path))
    if html_at and pdf_at and int(html_at) > int(pdf_at):
        out.append({
            "where": where,
            "reason": "原稿HTMLのほうが配布PDFより新しい＝PDFを焼き直していない"
                      "（python3 lead_magnet/build_pdf.py で再生成し、"
                      "line_bot/messages.py のSHAも上げること）",
            "hit": f"HTML {html_at} / PDF {pdf_at}（コミット時刻）"})

    pdf_grams = _grams(flat(pdf_text))
    missing = []
    for block in html_to_text(html_path).split("\n"):
        b = flat(block)
        if len(b) < MIN_BLOCK_LEN:
            continue
        g = _grams(b)
        cover = len(g & pdf_grams) / len(g)
        if cover < BLOCK_COVERAGE_MIN:
            missing.append((cover, block.strip()))
    if missing:
        missing.sort()
        out.append({
            "where": where,
            "reason": f"原稿HTMLの本文 {len(missing)} ブロックが配布PDFに載っていない"
                      f"（PDFが別バージョン／焼き直していない）",
            "hit": " ／ ".join(f"[{c:.2f}] {t[:50]}" for c, t in missing[:5])})
    return out


# ── 3. jsDelivr のSHA固定 ────────────────────────────────────
def git(*args):
    r = subprocess.run(["git", "-C", BASE_DIR, *args],
                       capture_output=True, text=True)
    return (r.stdout.strip() if r.returncode == 0 else None), r.stderr.strip()


def read_pinned_shas():
    """line_bot/messages.py から *_PDF_SHA を読む（import せず定数だけ拾う）。"""
    path = os.path.join(BASE_DIR, "line_bot", "messages.py")
    try:
        src = open(path, encoding="utf-8").read()
    except OSError as e:
        return {}, f"line_bot/messages.py を読めない: {e}"
    # 値まで検証する。「40桁のつもりが41桁」のような貼り間違いを
    # 「定数が見つからない」と混同すると、直す場所を誤らせる。
    found, malformed = {}, []
    for name, value in re.findall(r"^([A-Z_]*PDF_SHA)\s*=\s*[\"']([^\"']*)[\"']", src, re.M):
        if re.fullmatch(r"[0-9a-f]{7,40}", value):
            found[name] = value
        else:
            malformed.append(f"{name} = {value!r}")
    if malformed:
        return found, ("SHAとして読めない値がある（コミットハッシュを貼り直すこと）: "
                       + " / ".join(malformed))
    return found, None


def check_pinned(repo_only):
    out = []
    shas, err = read_pinned_shas()
    if err:
        return [{"where": "line_bot/messages.py", "reason": err, "hit": ""}]

    for const, path in PINNED_PDFS:
        where = f"配布URL {const} → {path}"
        sha = shas.get(const)
        if not sha:
            out.append({"where": where,
                        "reason": f"{const} が line_bot/messages.py に見つからない"
                                  f"（リネーム？ SHA固定運用をやめた？）", "hit": ""})
            continue

        local_blob, _ = git("hash-object", os.path.join(BASE_DIR, path))
        pinned_blob, gerr = git("rev-parse", f"{sha}:{path}")
        if pinned_blob is None:
            out.append({"where": where,
                        "reason": f"ピン留めSHA {sha[:10]} のPDFをgitから読めない"
                                  f"（浅いクローン？ そのコミットが未push？"
                                  f" CIでは fetch-depth: 0 が要る）",
                        "hit": gerr[:120]})
        elif local_blob != pinned_blob:
            out.append({"where": where,
                        "reason": f"配布URLが指すPDFと作業ツリーのPDFが別物。"
                                  f"**直したPDFは配られていない**（{const} を"
                                  f"PDF更新コミットのSHAに更新すること）",
                        "hit": f"配布中 {pinned_blob[:10]} / 手元 {local_blob[:10]}"})
            continue  # 実配信を見るまでもない

        if repo_only:
            continue
        # 実際にCDNが返すバイトまで見る。SHAは正しいのに未pushで404、というのは
        # git だけでは絶対に分からない（ローカルには当然コミットがある）
        try:
            import requests
            r = requests.get(JSDELIVR.format(sha=sha, path=path), timeout=60)
        except Exception as e:  # noqa: BLE001 — ネットワーク層は理由を問わず可視化する
            out.append({"where": where, "reason": "jsDelivr への実アクセスに失敗",
                        "hit": f"{type(e).__name__}: {e}"[:120]})
            continue
        if r.status_code != 200:
            out.append({"where": where,
                        "reason": f"配布URLが HTTP {r.status_code}"
                                  f"（コミットが未pushだと登録者にPDFが届かない）",
                        "hit": JSDELIVR.format(sha=sha, path=path)})
            continue
        # 配信バイトを同じ土俵（gitのblob hash）に乗せて手元と比べる
        h = subprocess.run(["git", "hash-object", "--stdin"], input=r.content,
                           capture_output=True)
        served = h.stdout.decode().strip() if h.returncode == 0 else ""
        if served and served != local_blob:
            out.append({"where": where,
                        "reason": "jsDelivr が配っている実体が手元のPDFと違う",
                        "hit": f"配信 {served[:10]} / 手元 {local_blob[:10]}"})
    return out


# ── 4. 孤児の配布物 ──────────────────────────────────────────
def check_orphans(pdf_paths):
    out = []
    haystack = []
    # 番犬自身と、番犬が吐くレポートは「参照」に数えない。
    # data/*_report.json には走査したファイル名がそのまま載るので、
    # これを含めると **孤児が自分のレポートに載っているせいで孤児でなくなる**
    # （実測: 初回の実行で pococha_starter_guide.pdf の検知が消えた）。
    ignore = {os.path.abspath(__file__), os.path.abspath(REPORT_FILE)}
    for p in iter_files(REFERENCE_GLOBS):
        if os.path.abspath(p) in ignore or re.search(r"_report\.json$", p):
            continue
        try:
            haystack.append(open(p, encoding="utf-8", errors="ignore").read())
        except OSError:
            continue
    blob = "\n".join(haystack)
    for p in pdf_paths:
        name = os.path.basename(p)
        if name not in blob:
            out.append({
                "where": rel(p),
                "reason": "配布物なのにリポジトリのどこからも参照されていない。"
                          "更新フローに乗らないまま公開URL（GitHub raw / jsDelivr）から"
                          "取得できる状態＝旧ファクトが残り続ける温床",
                "hit": name})
    return out


def main():
    repo_only = "--repo-only" in sys.argv
    violations, warns = [], []

    # 1. HTML（LP・特典原稿）
    html_files = iter_files(CONTENT_GLOBS)
    for p in html_files:
        ng, wn = scan_text(html_to_text(p), rel(p))
        violations += ng
        warns += wn

    # 1'. PDF（実際に配られるバイナリ）
    pdf_files = iter_files([PDF_GLOB])
    pdf_texts = {}
    for p in pdf_files:
        text, err = pdf_to_text(p)
        if err:
            violations.append({"where": rel(p), "reason": err, "hit": ""})
            continue
        pdf_texts[p] = text
        ng, wn = scan_text(text, rel(p))
        violations += ng
        warns += wn

    # 2. 原稿HTML ↔ 配布PDF
    for p in pdf_files:
        if p not in pdf_texts:
            continue
        src = os.path.join(BASE_DIR, LEAD_MAGNET_DIR,
                           os.path.basename(p)[:-4] + ".html")
        if os.path.exists(src):
            violations += check_pdf_sync(src, p, pdf_texts[p])

    # 3. 配布URLのSHA固定
    violations += check_pinned(repo_only)

    # 4. 孤児の配布物
    violations += check_orphans(pdf_files)

    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump({"violations": violations, "warn": warns,
                   "scanned": {"html": [rel(p) for p in html_files],
                               "pdf": [rel(p) for p in pdf_files]}},
                  f, ensure_ascii=False, indent=1)

    print(f"[走査] HTML {len(html_files)}本 / PDF {len(pdf_files)}本")
    for p in html_files + pdf_files:
        print(f"   - {rel(p)}")
    print(f"\n[結果] 違反={len(violations)} 警告(判断保留)={len(warns)} → {rel(REPORT_FILE)}")
    for v in violations:
        print(f"  ❌ {v['where']}: {v['reason']}" + (f"\n     → {v['hit']}" if v["hit"] else ""))
    for w in warns:
        print(f"  ⚠️ {w['where']}: {w['reason']}\n     → {w['hit']}")

    if violations:
        return 1
    print("\nLP・特典HTML・配布PDFに確定ファクト違反なし ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
