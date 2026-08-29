#!/usr/bin/env python3
"""content_facts_guard.py — 公開コンテンツ（LP・特典PDF・記事）の確定ファクト番犬
==============================================================================
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

2026-08-12（同日追記）— 記事も同じ死角にあった:
  上の番犬を立てた直後に、**同じ穴がもう1つ残っている**ことが分かった。
  blog/articles/*.md と blog/articles_note/*.md（Note公開記事の原稿・149本）は、
  link_guard.py の CONTENT_GLOBS には入っているが、それは**リンクの生死を見るだけ**で、
  文面の中身はやはり誰も見ていなかった。実際 blog/articles/work-from-home-sidejob.md に
  禁止語「挫折率」が生き残っていた（一度も検知されたことがない）。
  記事は公開コンテンツの中で**最も文量が多く、最も読み返されない**場所なので、
  ここを外したままだと「LPは緑、記事は野放し」になる。走査対象に加える。

  ただし記事は LP・特典PDF と**判定の物差しが違う**（下の ARTICLE_WARN_LABELS 参照）。
  事務所選びの解説記事は「違約金の有無を確認しましょう」「『絶対稼げる』と断言する
  事務所は危険」のように、**禁止語を引用・注意喚起として使うのが記事の中身そのもの**。
  生成側と同じ物差しで全部赤にすると、番犬が永久に鳴きやまなくなる。

この番犬が見る4軸:
  1. 禁止パターン走査 — 確定ファクト（[[project_taitan_pro_note_facts]] の常設grep）を
     LP・特典HTML原稿・**配布PDFの抽出テキスト**・**Note記事の原稿**に当てる。
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
  - WARN = 主語や文脈で可否が変わり、公開済み長文では人が判断する話なので赤にしない
           （[[feedback_watchdog_autoclose]] 永久に鳴きやむことのない番犬にしない）
           LP・特典PDF … facts_patterns.AUDIT_WARN_LABELS（少額表記・実績誇張・他社比較）
           記事       … 上に ARTICLE_WARN_LABELS を足した集合（下の定義にある理由つき）

使い方:
  python3 content_facts_guard.py              # 全チェック
  python3 content_facts_guard.py --repo-only  # jsDelivr への実アクセスなし（ローカル用）
  python3 content_facts_guard.py --warn       # WARN の全件を出す（既定は先頭20件）

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
from facts_patterns import (  # noqa: E402
    AUDIT_WARN_LABELS, CONTRACT_AXIS_LABEL, common_violations)

REPORT_FILE = os.path.join(BASE_DIR, "data", "content_facts_guard_report.json")

# ── 記事だけ「検知はする／赤にはしない」に落とすルール ──────────────
# 2026-08-12 に blog/ 149本へ当てて実測した結果から決めている。数字は実測の箇所数。
# 共通のAUDIT_WARN_LABELS（少額表記・実績誇張・他社比較）に、記事特有の4本を足す。
#
# 記事は「事務所選びの解説」「アプリ比較」が中身の中心で、禁止語を
# **悪い例の引用・読者への注意喚起・第三者の事実**として使うのが正しい書き方になる。
# LP・特典PDFでは同じ語が自社の主張になるので、そちらは赤のまま据え置く。
# だからこの集合は記事にしか適用しない（LP側に持ち込むと京都コレクションの再来になる）。
ARTICLE_WARN_LABELS = frozenset({
    # 68箇所。大半が「『絶対稼げる』と断言する事務所は危険」という**悪質事務所の引用**
    # （17記事の危険サインチェックリストがこの形）。一方「この通りに走れば
    # ほぼ確実にC1〜B3に到達できます」のような自社の約束は本物の違反で、
    # 機械には区別がつかない。人が読んで消す。
    "断定・保証表現",
    # 64箇所。[[feedback_no_free_exit_claim]] が禁じているのは
    # **TAITAN PROについて**「いつでも退所」「違約金なし」と書くこと。
    # 「違約金の有無を契約前に必ず確認しましょう」は読者への正しい助言で、
    # これを消すと事務所選び記事が成立しない。
    #
    # ⚠ ただしこのWARNは「語が出たか」しか見ていない。**判断軸が自社と矛盾する**形
    # （「最低契約期間が1年以上は悪質」＝TAITAN PROは2年なので自分を撃つ）は
    # facts_patterns.contract_axis_violations が別ラベルで**赤**にする。
    # そちらをこの集合に足してはいけない。足すと2026-08-12の12箇所が
    # またWARNの山（64件）に埋もれて、誰も気づけない状態に戻る。
    "「いつでも退所」「違約金なし」系／契約期間への言及",
    # 52箇所。[[feedback_no_fee_free_claim]] が禁じているのは自社の報酬説明で
    # 「手数料なし」と書くこと。記事側の実体は Pococha の振込手数料330円、
    # 勘定科目の「支払手数料」、源泉徴収との区別など**第三者の事実**が中心。
    "禁止語「手数料」",
    # 68箇所。[[feedback_note_target_platforms]] が禁じているのは
    # SHOWROOM/IRIAM/ふわっちの**単体記事を書くこと**であって、
    # アプリ比較表や市場俯瞰で名前を挙げること自体ではない。
    "取扱外プラットフォーム",
    # 9箇所。「数万円」「お小遣い程度」は、自社の収入目安として書けば違反だが、
    # 他の副業との対比や「そこで満足しないために」の文脈では成立する。
    # 金額そのものの下限違反（月15万）は共通のWARNラベル側で拾う。
    "少額表記（数万円/お小遣い程度）",
    # 4箇所。2026-08-24 に自社導線から「オンライン面談」を全廃したが
    # [[feedback_no_online_meeting_wording]]、禁じているのは**自社の導線**を
    # そう呼ぶこと。記事側の実体は「他社を含めて3社の面談を受けて比較しよう」
    # （65_TikTokライバー事務所選び方）のような**読者への助言**。
    # 自社を指す用法との区別は機械にはつかないので、人が読んで消す。
    # 2026-08-28: 42_スカウト術の「ステップ3：オンライン面談を提案」も
    # ここに含めて据え置いていたが、ユーザー指示で「LINE通話での面談を提案」へ変更した
    # （note_facts_fix_20260828.py。原稿・公開本文の両方）。
    # ※「無料面談」のほうは一般論でも使わないので、あえてここに足していない。
    "自社導線は「LINE通話で相談」（オンライン面談は使わない）",
})

# 判断軸の矛盾だけは、記事でも**赤**のまま通す。
# 上の集合に足せば番犬はすぐ静かになるが、それは2026-08-12に12箇所が
# 64件のWARNに埋もれて誰も気づかなかった状態そのものなので、機械で塞いでおく。
# WARN に落としたい衝動が湧いたら、まず記事の判断軸を直す（長さ→明記・説明）。
assert CONTRACT_AXIS_LABEL not in (AUDIT_WARN_LABELS | ARTICLE_WARN_LABELS), (
    f"{CONTRACT_AXIS_LABEL} はWARNに落としてはいけない（赤のまま出す）")

# ── 走査対象 ────────────────────────────────────────────────
# 「読者・見込み客の目に直接触れる長文」だけを入れる。
CONTENT_GLOBS = [
    "lead_magnet/*.html",   # 特典PDFの原稿
    "lp/**/*.html",         # 公開LP（Netlify配信）
]
# 記事（Note公開記事の原稿）。CONTENT_GLOBS と分けているのは走査の有無ではなく
# **WARN の物差しが違う**から（ARTICLE_WARN_LABELS）。ここに足すだけでは
# 記事に LP と同じ厳しさが当たってしまい、番犬が鳴きやまなくなる。
ARTICLE_GLOBS = [
    "blog/articles/*.md",       # 自社ブログ記事
    "blog/articles_note/*.md",  # Note公開記事の原稿（108本が note 上で公開中）
]
# Note公開記事の原稿だけを対象にする構造チェック用（本文インライン #タグ）。
# ARTICLE_GLOBS には自社ブログ（blog/articles/*.md）も入っているが、そちらは
# note に載らないので「本文に # を書くと勝手にタグ化する」問題は起きない。
NOTE_ARTICLE_GLOB = "blog/articles_note/*.md"

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
def scan_text(text, where, warn_labels=AUDIT_WARN_LABELS):
    """[(赤にするもの), (報告だけするもの)] を返す。

    warn_labels は「検知はするが赤にはしない」ラベルの集合。
    LP・特典PDFは既定（AUDIT_WARN_LABELS）、記事はそれを広げた集合を渡す。
    """
    ng, warn = [], []
    for reason, hit in common_violations(text):
        item = {"where": where, "reason": reason, "hit": hit[:80]}
        (warn if reason in warn_labels else ng).append(item)
    return ng, warn


# ── 1'''. Note記事 本文インライン #タグ（publish画面が記事タグへ勝手に昇格させる）──
# editor.note.com の publish バンドルは、本文中の「空白 or 行頭の直後に来る半角 #語」を
# 記事のハッシュタグ（hashtag_notes）へ自動マージする。
# 2026-08-28 実測（公開記事のライブなタグと本文の突合）:
#   - 記事#42「代理店スカウト術」本文の  `#在宅ワーク #ライバー気になる`（半角スペース直後）
#       → 記事の中身（代理店向け）と無関係なのにタグとして混入していた
#   - 同じ行の `：#副業探し`（全角コロン直後＝直前が非空白）は昇格しなかった
#   - 記事#127 の `（#9110`（全角括弧直後）も昇格しなかった
#   ⇒ 昇格条件は「半角 # かつ 直前が 空白/全角空白/行頭」。全角＃や『：#』は拾われない。
# 末尾に1行だけ置くタグ行（記事78-93・98・108 の運用）はこの仕組みを意図的に使うものなので
# 許容する。それ以外の場所に出てきたら「意図しないタグ混入」としてNG（exit 1）。
# タグ本体に使える文字＝「空白でも区切り記号でもない字」の連なり。
# note が語の切れ目とみなす記号（和欧の約物・スラッシュ・コロン等）で止める。
_TAG_BODY = r"[^\s#＃、。，．・…！!?？「」『』（）()\[\]【】／/:：;；|｜=＝＊*＋<>＜＞\"'’”“～〜]+"
_INLINE_HASHTAG = re.compile(r"(?:^|(?<=\s))#(?=" + _TAG_BODY + r")" + _TAG_BODY)


def _is_dedicated_tagline(line):
    """行全体が `#タグ #タグ …`（4個以上）だけで構成されているか。"""
    toks = line.strip().split()
    return len(toks) >= 4 and all(
        re.fullmatch(r"#" + _TAG_BODY, t) for t in toks
    )


def scan_note_inline_hashtags(path):
    """Note記事の原稿から、記事タグへ勝手に昇格する本文インライン #語 を拾う。"""
    out = []
    lines = open(path, encoding="utf-8").read().split("\n")
    nonempty = [i for i, l in enumerate(lines) if l.strip()]
    # 末尾の非空行が「専用タグ行」なら、その1行だけは意図的な運用として除外する
    allowed = set()
    if nonempty and _is_dedicated_tagline(lines[nonempty[-1]]):
        allowed.add(nonempty[-1])
    for i, line in enumerate(lines):
        if i in allowed:
            continue
        for m in _INLINE_HASHTAG.finditer(line):
            out.append({
                "where": f"{rel(path)}:{i + 1}",
                "reason": "本文インライン #タグ（note が記事タグへ勝手に昇格させる）",
                "hit": (m.group(0) + "  ← 行: " + line.strip())[:80],
            })
    return out


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

    # 1''. 記事（Note公開記事の原稿）。物差しだけ ARTICLE_WARN_LABELS に差し替える。
    # Markdown はタグを剥がさずそのまま当てる。禁止語は本文中の日本語なので、
    # 記法（**強調** や表の | ）はパターンの当たりに影響しない。
    article_files = iter_files(ARTICLE_GLOBS)
    for p in article_files:
        ng, wn = scan_text(open(p, encoding="utf-8").read(), rel(p),
                           warn_labels=AUDIT_WARN_LABELS | ARTICLE_WARN_LABELS)
        violations += ng
        warns += wn

    # 1'''. Note記事の本文インライン #タグ（publish画面が記事タグへ勝手に昇格させる）
    note_article_files = iter_files([NOTE_ARTICLE_GLOB])
    for p in note_article_files:
        violations += scan_note_inline_hashtags(p)

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
                               "pdf": [rel(p) for p in pdf_files],
                               "article": [rel(p) for p in article_files]}},
                  f, ensure_ascii=False, indent=1)

    print(f"[走査] HTML {len(html_files)}本 / PDF {len(pdf_files)}本 "
          f"/ 記事 {len(article_files)}本")
    # 記事は149本あるので個別には並べない（ログが埋まって肝心の違反が見えなくなる）。
    # 全件は data/content_facts_guard_report.json の scanned.article に載る。
    for p in html_files + pdf_files:
        print(f"   - {rel(p)}")
    print(f"\n[結果] 違反={len(violations)} 警告(判断保留)={len(warns)} → {rel(REPORT_FILE)}")
    for v in violations:
        print(f"  ❌ {v['where']}: {v['reason']}" + (f"\n     → {v['hit']}" if v["hit"] else ""))

    # WARN は記事を入れて三桁になりうる。既定は要約＋先頭だけ出し、全件は --warn で。
    show_all_warns = "--warn" in sys.argv
    by_reason = {}
    for w in warns:
        by_reason.setdefault(w["reason"], []).append(w)
    for reason, items in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        print(f"  ⚠️ [{len(items)}件] {reason}")
        for w in (items if show_all_warns else items[:3]):
            print(f"       - {w['where']}: {w['hit']}")
        if not show_all_warns and len(items) > 3:
            print(f"       …ほか {len(items) - 3} 件（--warn で全件表示）")

    if violations:
        return 1
    print("\nLP・特典HTML・配布PDF・記事に確定ファクト違反なし ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
