#!/usr/bin/env python3
"""代理店記事の**ローカルmd**のCTAを、ライバー導線 → 代理店導線に貼り替える。

■ なぜ必要か（2026-09-09）
公開側は 2026-08-28 に note_agency_cta_publish.py で修正済みで、
note_funnel_guard.py も緑（公開150本 / 欠け0本 / 代理店記事0本）。
ところが**生成元の blog/articles_note/*.md は手つかず**で、代理店記事15本が
ライバー向け特典『ライバー新人期スタートダッシュガイド』を冒頭CTA・末尾CTAの
両方に抱えたままだった。

note_auto_poster.py --update / --update-all は本文をローカルmdから作り直す
（update_article() が parse_article → markdown_to_html して PUT する）ので、
一括更新を1回かけただけで**ライバー特典が代理店記事に戻り、番犬が赤に戻る**。
公開側とローカル側が黙って乖離している状態だった。

■ やること（note_funnel_guard の合格条件に合わせる）
  1. 冒頭CTA … ライバー特典 → 代理店特典。無い記事には入れる。
     文言は note_early_cta_publish.EARLY_HTML_AGENCY と同一
     （＝公開されている実物と同じ。マーカー「先に特典だけ受け取るのもOK」は
       番犬が冒頭CTAの有無を見るキーなので変えてはいけない）
  2. 末尾CTA … note_agency_cta_publish.TAIL_GIFT_NEW と同一の文へ
  3. LPリンク … LPトップ / ライバー向けLP / utm無しの /agency/ を、
     CTA_BLOCK_AGENCY と同じ「/agency/ + utm」へ統一
  4. LPリンクが本文にまったく無い記事は、末尾のLINE行の直後に足す

冪等。何度流しても2回目以降は「変更 0本」になる。

使い方:
  python3 note_agency_cta_md_fix_20260909.py            # blog/articles_note を修正
  python3 note_agency_cta_md_fix_20260909.py <dir>
"""
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ART_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    BASE_DIR, "blog", "articles_note")

AGENCY_LP = ("https://taitan-pro-lp.netlify.app/agency/"
             "?utm_source=note&utm_medium=article&utm_campaign=note_cta_agency")
LINE_URL = "https://lin.ee/xchCfdn"
LIVER_GIFT = "ライバー新人期スタートダッシュガイド"
AGENCY_GIFT = "ライバー代理店パートナー スタートガイド"

# 番犬（note_funnel_guard.EARLY_MARK）が冒頭CTAの有無を見ているキー。変更禁止。
EARLY_MARK = "先に特典だけ受け取るのもOK"
EARLY_NEW = (
    f"🎁 **{EARLY_MARK}**：代理店パートナーが何から手をつけるかをまとめた"
    f"非売品PDF『{AGENCY_GIFT}』を、[公式LINEの友だち追加]({LINE_URL})で"
    "無料でお渡ししています。")
TAIL_NEW = (
    f"🎁 **友だち追加特典**：『{AGENCY_GIFT}』——何から手をつけて、"
    "どこでつまずくのかをまとめた非売品PDFを、LINE登録した方全員に"
    "無料でお渡ししています。登録後に「代理店」と送っていただければ、"
    "代理店パートナー向けの案内をお届けします。")
LP_LINE = f"**[代理店パートナーのページを見る →]({AGENCY_LP})**"

# 代理店（＝事務所を"作る側"）記事の判定。note_funnel_guard と同じ規則。
AGENCY_WORDS = ["代理店", "開業", "スカウト術", "スカウトDM", "マネージャーとは", "スカウト"]
AGENCY_EXCLUDE = ["選び方", "口コミ", "評判", "入るべき", "やめとけ", "見分け方"]

# 冒頭CTA。手書きの揺れ（「先に代理店向けの資料だけ受け取るのもOK」＝178〜180）も
# 拾って正本の文言に寄せる。揺れたままだと番犬の EARLY_MARK に当たらず、
# 公開した瞬間に「冒頭CTAなし」で赤になる。
EARLY_ANY_RE = re.compile(r"^🎁 \*\*先に[^*]*のもOK\*\*：.*$", re.M)
TAIL_LIVER_RE = re.compile(r"^🎁 \*\*友だち追加特典\*\*：『" + LIVER_GIFT + r"』.*$", re.M)
LP_MD_RE = re.compile(
    r"\*\*\[[^\]]*→\]\(https://taitan-pro-lp\.netlify\.app"
    r"(?:/(?:beginner|liver|sidejob|agency)/?[^)]*|/?)\)\*\*")
# 134 は note から復元した記事で、LPが埋め込み figure になっている
LP_FIGURE_RE = re.compile(r'((?:href|data-src)=")https://taitan-pro-lp\.netlify\.app/?(")')
TAIL_LINE_RE = re.compile(r"^👉 公式LINEで無料相談：" + re.escape(LINE_URL) + r"$", re.M)


def is_agency(title):
    if any(w in title for w in AGENCY_EXCLUDE):
        return False
    return any(w in title for w in AGENCY_WORDS)


def insert_early(text):
    """冒頭CTAが無い記事に入れる。最初の区切り（--- か ##）の直前。"""
    lines = text.split("\n")
    pos = None
    for i, l in enumerate(lines):
        if i == 0:
            continue
        if l.strip() == "---" or l.startswith("##"):
            pos = i
            break
    if pos is None:  # 見出しが崩れている記事（134）は導入の切れ目（最初の空行）へ
        for i, l in enumerate(lines):
            if i >= 4 and l.strip() == "":
                pos = i + 1
                break
    if pos is None:
        return text
    while pos > 0 and lines[pos - 1].strip() == "":
        pos -= 1
    lines[pos:pos] = ["", EARLY_NEW]
    return "\n".join(lines)


def fix(text):
    out = text
    if EARLY_ANY_RE.search(out):
        out = EARLY_ANY_RE.sub(lambda m: EARLY_NEW, out)
    else:
        out = insert_early(out)

    out = TAIL_LIVER_RE.sub(lambda m: TAIL_NEW, out)

    out = LP_MD_RE.sub(LP_LINE, out)
    out = LP_FIGURE_RE.sub(lambda m: m.group(1) + AGENCY_LP + m.group(2), out)

    if "netlify.app/agency/" not in out:
        m = TAIL_LINE_RE.search(out)
        if m:
            out = out[:m.end()] + "\n\n" + LP_LINE + out[m.end():]
    return out


def check(text):
    """note_funnel_guard の代理店判定と同じ観点で、mdの側を先に見ておく。"""
    bad = []
    if LIVER_GIFT in text:
        bad.append("ライバー特典が残っている")
    if re.search(r"taitan-pro-lp\.netlify\.app/(?:beginner|liver|sidejob)/", text):
        bad.append("ライバーLPを指している")
    i = text.find(EARLY_MARK)
    if i < 0:
        bad.append("冒頭CTAなし")
    elif i / max(1, len(text)) * 100 > 40:
        bad.append(f"冒頭CTAが末尾寄り（{i / len(text) * 100:.0f}%地点）")
    if AGENCY_GIFT not in text:
        bad.append("代理店特典なし")
    if "netlify.app/agency/" not in text:
        bad.append("代理店LPなし")
    if "lin.ee/xchCfdn" not in text:
        bad.append("LINEリンクなし")
    return bad


def main():
    changed = ng = total = 0
    for f in sorted(os.listdir(ART_DIR)):
        if not f.endswith(".md"):
            continue
        path = os.path.join(ART_DIR, f)
        text = open(path, encoding="utf-8").read()
        m = re.search(r"^#\s+(.+)$", text, re.M)
        if not is_agency(m.group(1) if m else f):
            continue
        total += 1
        new = fix(text)
        if new != text:
            open(path, "w", encoding="utf-8").write(new)
            changed += 1
        bad = check(new)
        ng += 1 if bad else 0
        mark = "変更" if new != text else "  ・"
        print(f"  {mark}  {('NG ' + ' / '.join(bad)) if bad else 'ok':<30} {f}")
    print(f"\n代理店記事 {total}本 / 変更 {changed}本 / 未解決 {ng}本")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
