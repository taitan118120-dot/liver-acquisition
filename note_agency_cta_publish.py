#!/usr/bin/env python3
"""公開済みの「代理店（＝事務所を作る側）」記事のCTAを、代理店導線に貼り替える。

■ なぜ必要か（2026-08-28 の実測）
note_article_generator の CTA_BLOCK は長らく**カテゴリに関係なく単一**で、
  ・LPリンク  → ライバー向けの `/beginner/`（または LPトップ）
  ・特典PDF   → 『ライバー新人期スタートダッシュガイド』
を全記事の末尾に付けていた。その結果、
「会社員をしながら代理店をやる1週間の組み方」を読んだ人にも
「新人ライバーの最初の30日」PDFを差し出す、という取り違えが起きていた。

公式LINEは welcome で希望の種別を聞き分け、代理店希望者には
『ライバー代理店パートナー スタートガイド』を配る作りになっている
（line_bot/messages.py の AGENCY_GUIDE_URL）。記事側の訴求をそこへ合わせる。

生成側は note_article_generator.cta_block_for() で修正済み。これは**既に公開済み**の
記事を後追いで直すためのスクリプト。

使い方:
  python3 note_agency_cta_publish.py --plan          # 対象と差分を出すだけ（GETのみ）
  python3 note_agency_cta_publish.py --limit 5       # 全期間PV降順に5本
  python3 note_agency_cta_publish.py <key> [<key>…]  # 個別指定
"""
import json
import os
import re
import sys
import time

from note_cta_publish import req_session, get_note

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "data", "agency_cta_log.json")

AGENCY_LP = ("https://taitan-pro-lp.netlify.app/agency/"
             "?utm_source=note&utm_medium=article&utm_campaign=note_cta_agency")
LINE_URL = "https://lin.ee/xchCfdn"

LIVER_GIFT = "ライバー新人期スタートダッシュガイド"
AGENCY_GIFT = "ライバー代理店パートナー スタートガイド"
# 反映確認に使うマーカー。特典名がいちばん壊れやすい（本文2箇所に別文型で出る）
MARK = AGENCY_GIFT

# 「代理店＝作る側」の記事だけを対象にする。事務所"選び"の記事は読者がライバー志望
# なので対象外（タイトルに 選び方/口コミ/評判 を含むものは除く）。
AGENCY_WORDS = ["代理店", "開業", "スカウト術", "スカウトDM", "マネージャーとは",
                "事務所を開業", "スカウト"]
EXCLUDE_WORDS = ["選び方", "口コミ", "評判", "入るべき", "やめとけ", "見分け方"]

# 末尾CTAの特典段落（generator の CTA_BLOCK 由来）
TAIL_GIFT_RE = re.compile(
    r"🎁\s*<strong>友だち追加特典</strong>：『" + LIVER_GIFT +
    r"』——最初の30日でやることを全部まとめた非売品PDFを、"
    r"LINE登録した方全員に無料でお渡ししています。")
TAIL_GIFT_NEW = (
    "🎁 <strong>友だち追加特典</strong>：『" + AGENCY_GIFT +
    "』——何から手をつけて、どこでつまずくのかをまとめた非売品PDFを、"
    "LINE登録した方全員に無料でお渡ししています。"
    "登録後に「代理店」と送っていただければ、代理店パートナー向けの案内をお届けします。")

# 冒頭CTA（note_early_cta_publish 由来）。リンクの属性順は note が振り直すので緩く見る
EARLY_GIFT_RE = re.compile(
    r"🎁\s*<strong>先に特典だけ受け取るのもOK</strong>："
    r"配信の最初の30日でやることを全部まとめた非売品PDF『" + LIVER_GIFT +
    r"』を、(<a [^>]*>)公式LINEの友だち追加</a>で無料でお渡ししています。")


def _early_gift_new(m):
    return ("🎁 <strong>先に特典だけ受け取るのもOK</strong>："
            "代理店パートナーが何から手をつけるかをまとめた非売品PDF『" + AGENCY_GIFT +
            "』を、" + m.group(1) + "公式LINEの友だち追加</a>で無料でお渡ししています。")


# LPリンク。/agency/ 以外を指しているものだけ差し替える。
# href / data-src の両方（noteは外部リンクを figure の埋め込みカードにすることがある）
LP_HOST = "taitan-pro-lp.netlify.app"
LP_OTHER_RE = re.compile(
    r'((?:href|data-src)=")https://' + re.escape(LP_HOST) + r'(/(?:beginner|liver|sidejob)/[^"]*|/?)(")')
LP_LABEL_RE = re.compile(r"<strong>(?:Webから応募する|サイトを見る|詳しくはこちら)\s*→</strong>")

# LPリンクがまったく無い記事に足す段落
LP_PARA = (f'<p><a href="{AGENCY_LP}" target="_blank" rel="nofollow noopener">'
           f'<strong>代理店パートナーのページを見る →</strong></a></p>')
# 末尾のLINEリンク段落（この直後にLP段落を差し込む）
TAIL_LINE_P_RE = re.compile(
    r'<p[^>]*>\s*👉[^<]*<a href="' + re.escape(LINE_URL) + r'"[^>]*>[^<]*</a>\s*</p>')


def transform(key, html):
    out = html

    if LIVER_GIFT in out:
        out = TAIL_GIFT_RE.sub(lambda m: TAIL_GIFT_NEW, out)
        out = EARLY_GIFT_RE.sub(_early_gift_new, out)

    def _lp(m):
        return m.group(1) + AGENCY_LP + m.group(3)
    out = LP_OTHER_RE.sub(_lp, out)
    out = LP_LABEL_RE.sub("<strong>代理店パートナーのページを見る →</strong>", out)

    if LP_HOST not in out:
        m = TAIL_LINE_P_RE.search(out)
        if m:
            out = out[:m.end()] + LP_PARA + out[m.end():]

    return None if out == html else out


def is_agency(title):
    if any(w in title for w in EXCLUDE_WORDS):
        return False
    return any(w in title for w in AGENCY_WORDS)


def _load(path):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except Exception:
            return {}
    return {}


def main():
    args = sys.argv[1:]
    plan_only = "--plan" in args
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    explicit = [a for a in args if a.startswith("n") and not a.startswith("--")]

    s = req_session()
    from note_internal_links_publish import fetch_pv
    alltime = fetch_pv(s, "all")

    cand = []
    for key, (pv, title) in alltime.items():
        if explicit:
            if key not in explicit:
                continue
        elif not is_agency(title):
            continue
        cand.append((pv, key, title))
    cand.sort(reverse=True)

    log = _load(LOG_FILE)
    todo = []
    print("公開状態と本文を確認中…")
    for pv, key, title in cand:
        if log.get(key) == "ok":
            continue
        try:
            d = get_note(s, key, draft=False)
        except Exception as e:
            print(f"  取得失敗 {key}: {e}")
            continue
        if d.get("status") != "published":
            continue
        body = d["body"]
        new = transform(key, body)
        if new is None:
            print(f"  skip（変更なし） {pv:>4}PV {d['name'][:44]}")
            continue
        todo.append((key, d["name"], pv, len(body), len(new)))
        time.sleep(0.3)
    if limit:
        todo = todo[:limit]

    print(f"\n対象 {len(todo)} 本")
    for key, title, pv, a, b in todo:
        print(f"  {pv:>4}PV  {a}→{b}  {key}  {title[:46]}")
    if plan_only or not todo:
        return

    from note_leadmagnet_publish import publish_one
    ok = fail = 0
    for i, (key, title, pv, _a, _b) in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] {key} {title[:34]}", flush=True)
        try:
            r = publish_one(key, transform, expect_marker=MARK)
            log[key] = r
            ok += 1 if r == "ok" else 0
        except Exception as e:
            print(f"  !! 失敗: {e}", flush=True)
            log[key] = f"error: {e}"
            fail += 1
        json.dump(log, open(LOG_FILE, "w"), ensure_ascii=False, indent=1)
        # note側の連投検知を避ける。8本ごとに長めに空ける（note_boost_publish と同じ間隔）
        time.sleep(25 if i % 8 == 0 else 3)
    print(f"\n完了 ok={ok} fail={fail}")


if __name__ == "__main__":
    main()
