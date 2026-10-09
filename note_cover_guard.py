#!/usr/bin/env python3
"""note_cover_guard.py
Note記事のカバー画像（アイキャッチ）付け忘れを push 時点で検知する番犬。

背景:
  blog/articles_note/ に記事(.md)を追加したとき、対応する
  blog/images/{番号}_*.png を付け忘れると、note_auto_poster.py が
  「カバー画像なし」で公開を中止し exit 3 で失敗する。
  ただしこの失敗は「翌日の自動投稿ジョブ」まで顕在化しないため、
  原因コミットから時間が経ってから気づくことになっていた（#120-122で発生）。

動作:
  blog/articles_note/ の全記事番号について blog/images/{番号}_*.png の
  存在を照合し、欠落があれば一覧を出して exit 1（CIを赤くする）。
  カバー解決は note_set_eyecatch.resolve_image を流用（poster と同じ判定）。

  2026-08-18追記: ローカルに画像があっても「note上のアイキャッチが空のまま
  公開されている」ことがある（note editor のUI変更で自動設定が5日間失敗し、
  #137-141 がカバー無しで公開されていた）。ローカル照合だけでは気づけないので
  --published で公開中の記事のeyecatchも実際に叩いて確認する。

  2026-10-09追記: カバー下部のバッジには確定ファクトの所属数が**画像として焼き込まれる**。
  2026-10-02 に 200名→300名へ更新したあとも、それ以前に作ったカバー（公開51本＋在庫19本）は
  「所属200名」のまま公開され続けていた（テキストしか見ない番犬では見えない）。
  そこでカバー画像のバッジ文言も照合する（仕組みは note_cover_badge.py）。
    - ローカル: 全記事のカバーPNG（未投稿在庫を含む）。毎回
    - 公開中:   --published のとき、公開中の全記事のeyecatchを実際にダウンロードして照合
  バッジの正本は facts_patterns.NOTE_COVER_BADGE。照合の基準
  data/note_cover_badge_ref.json の文言がそれと食い違っていたら「基準が古い」で赤にする。

使い方:
  python3 note_cover_guard.py              # ローカル照合のみ。欠落あれば exit 1
  python3 note_cover_guard.py --json       # 結果を data/note_cover_guard_report.json にも出力
  python3 note_cover_guard.py --published  # 公開中の記事のeyecatchもnote APIで確認
"""
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import note_cover_badge
import note_set_eyecatch
from facts_patterns import NOTE_COVER_BADGE

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTICLES_DIR = os.path.join(BASE_DIR, "blog", "articles_note")
REPORT_PATH = os.path.join(BASE_DIR, "data", "note_cover_guard_report.json")
KEY_MAP_PATH = os.path.join(BASE_DIR, "data", "note_key_map.json")

NOTE_URLNAME = "taitan_118"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
MAX_PAGES = 200  # 1ページ6件
PAGE_CAP_HIT = False

# 記事ファイル名の先頭番号を取る（例: 120_xxx.md → 120）
NUM_RE = re.compile(r"^(\d+)_")


def list_articles():
    """(番号, ファイル名) のリストを番号順で返す。"""
    out = []
    for path in glob.glob(os.path.join(ARTICLES_DIR, "*.md")):
        name = os.path.basename(path)
        m = NUM_RE.match(name)
        if not m:
            # 番号なしファイルは投稿対象外とみなしスキップ（例: README等）
            continue
        out.append((int(m.group(1)), name))
    return sorted(out, key=lambda x: x[0])


def check():
    """カバー欠落記事の一覧を返す。"""
    missing = []
    articles = list_articles()
    for num, name in articles:
        # poster と完全に同じ解決ロジックで判定する
        if not note_set_eyecatch.resolve_image(num):
            missing.append({"num": num, "article": name})
    return articles, missing


def check_published():
    """公開中の記事を note の公開APIで舐めて、eyecatchが空のものを返す。

    戻り値 (notes, missing, unchecked)。ネットワークが死んでいるときは
    unchecked=True にして「欠落0」と誤判定しないようにする。
    """
    # 2026-10-09: 上限が page<=20（=120本）で、公開が120本を超えた時点から古い記事を
    # 黙って見なくなっていた（179本中59本が未検査）。上限に当たったら
    # ネットワーク失敗（unchecked＝緑のまま）とは分けて赤にする（見ていない範囲を緑に数えない）。
    global PAGE_CAP_HIT
    notes, page = [], 1
    while True:
        if page > MAX_PAGES:
            PAGE_CAP_HIT = True
            break
        url = (f"https://note.com/api/v2/creators/{NOTE_URLNAME}"
               f"/contents?kind=note&page={page}")
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))["data"]
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as e:
            print(f"  ⚠️ 公開記事の取得に失敗（page {page}）: {str(e)[:80]}")
            return notes, [], True
        notes.extend(data.get("contents", []))
        if data.get("isLastPage"):
            break
        page += 1
        time.sleep(0.4)

    missing = [{"key": n["key"], "title": (n.get("name") or "")[:60],
                "published_at": (n.get("publishAt") or "")[:10]}
               for n in notes if not n.get("eyecatch")]
    return notes, missing, False


def badge_ref_problem():
    """照合の基準が使えないときは理由を返す（使えるなら None）。"""
    try:
        ref = note_cover_badge.load_ref()
    except (OSError, ValueError) as e:
        return None, f"基準 data/note_cover_badge_ref.json を読めない: {e}"
    if note_cover_badge.badge_text(ref) != NOTE_COVER_BADGE:
        return None, (f"基準の文言「{note_cover_badge.badge_text(ref)}」が "
                      f"facts_patterns.NOTE_COVER_BADGE「{NOTE_COVER_BADGE}」と違う")
    return ref, None


def check_badges_local(articles, ref):
    """ローカルのカバーPNG（未投稿在庫を含む全記事）でバッジ文言が古いものを返す。"""
    stale = []
    for num, name in articles:
        path = note_set_eyecatch.resolve_image(num)
        if not path:
            continue  # 欠落は check() 側で赤にしている
        r = note_cover_badge.inspect_path(path, ref)
        if r["state"] == "stale":
            stale.append({"num": num, "image": os.path.basename(path),
                          "worst_char": r["worst_char"], "worst_iou": r["worst_iou"]})
    return stale


def check_badges_published(notes, ref):
    """公開中の記事のeyecatchを実際にダウンロードしてバッジ文言を照合する。
    戻り値 (stale, unchecked_keys)。取得失敗は「古い」と誤判定せず unchecked に分ける。"""
    try:
        with open(KEY_MAP_PATH, encoding="utf-8") as f:
            key_to_num = {v["key"]: int(k) for k, v in json.load(f).items()}
    except (OSError, ValueError):
        key_to_num = {}
    from io import BytesIO
    from PIL import Image
    stale, unchecked = [], []
    for n in notes:
        url = n.get("eyecatch")
        if not url:
            continue  # 空は check_published 側で赤にしている
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=30) as r:
                img = Image.open(BytesIO(r.read()))
                img.load()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"  ⚠️ eyecatch取得失敗 {n['key']}: {str(e)[:60]}")
            unchecked.append(n["key"])
            continue
        res = note_cover_badge.inspect(img, ref)
        if res["state"] == "stale":
            stale.append({"key": n["key"], "num": key_to_num.get(n["key"]),
                          "title": (n.get("name") or "")[:60],
                          "worst_char": res["worst_char"], "worst_iou": res["worst_iou"]})
        time.sleep(0.2)
    return stale, unchecked


def main():
    args = sys.argv[1:]
    write_json = "--json" in args
    with_published = "--published" in args

    articles, missing = check()
    print(f"Note カバー画像 番犬: 記事{len(articles)}本を検査")

    ref, ref_problem = badge_ref_problem()
    stale_local = check_badges_local(articles, ref) if ref else []
    if ref:
        print(f"カバーのバッジ文言（{NOTE_COVER_BADGE}）を照合: 古い{len(stale_local)}本")

    pub_total, pub_missing, pub_unchecked = 0, [], False
    pub_stale, pub_badge_unchecked = [], []
    if with_published:
        notes, pub_missing, pub_unchecked = check_published()
        pub_total = len(notes)
        state = "確認できず" if pub_unchecked else f"欠落{len(pub_missing)}本"
        print(f"公開中の記事{pub_total}本のアイキャッチを確認: {state}")
        if ref and not pub_unchecked:
            pub_stale, pub_badge_unchecked = check_badges_published(notes, ref)
            print(f"公開中のアイキャッチのバッジ文言を照合: 古い{len(pub_stale)}本"
                  + (f"（取得失敗{len(pub_badge_unchecked)}本）" if pub_badge_unchecked else ""))

    if write_json:
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump({"total": len(articles), "missing": missing,
                       "published_total": pub_total,
                       "published_missing": pub_missing,
                       "published_unchecked": pub_unchecked,
                       "badge_text": NOTE_COVER_BADGE,
                       "badge_ref_problem": ref_problem,
                       "stale_local": stale_local,
                       "published_stale": pub_stale,
                       "published_badge_unchecked": pub_badge_unchecked},
                      f, ensure_ascii=False, indent=2)

    if missing:
        print(f"\n❌ カバー画像が欠落している記事 {len(missing)}本:")
        for m in missing:
            print(f"  - #{m['num']}  {m['article']}")
            print(f"      → blog/images/{m['num']}_*.png を追加してください")
        print("\n対処:")
        print("  1. python3 note_cover_make.py {番号} でカバーを作る")
        print("     （写真＋大きな見出しの合成。文字だけのカードは禁止）")
        print("  2. python3 note_cover_guard.py がローカルで緑になることを確認")

    if pub_missing:
        print(f"\n❌ 公開中なのにアイキャッチが空の記事 {len(pub_missing)}本:")
        for m in pub_missing:
            print(f"  - {m['key']} ({m['published_at']}) {m['title']}")
        print("\n対処: python3 note_set_eyecatch.py {記事番号} {note_key}")

    if ref_problem:
        print(f"\n❌ カバーのバッジ照合ができない: {ref_problem}")
        print("対処: mac で python3 note_cover_make.py --ref-only を実行して基準を作り直し、")
        print("      文言が変わったなら全カバーを作り直す（下の「古い」の対処）")

    if stale_local:
        nums = " ".join(str(m["num"]) for m in stale_local)
        print(f"\n❌ バッジ文言が古いカバー（ローカル） {len(stale_local)}本:")
        for m in stale_local:
            print(f"  - #{m['num']}  {m['image']}（「{m['worst_char']}」がずれ {m['worst_iou']}）")
        print(f"\n対処: python3 note_cover_make.py {nums} --no-bg")

    if pub_stale:
        print(f"\n❌ バッジ文言が古いアイキャッチ（公開中） {len(pub_stale)}本:")
        for m in pub_stale:
            print(f"  - #{m['num']} {m['key']} {m['title']}（「{m['worst_char']}」がずれ {m['worst_iou']}）")
        pairs = " ".join(f"{m['num']}:{m['key']}" for m in pub_stale if m["num"])
        print("\n対処: ローカルを作り直してから python3 note_cover_refresh.py " + pairs)

    if PAGE_CAP_HIT:
        print(f"\n❌ 公開記事が {MAX_PAGES} ページ（{MAX_PAGES * 6}本）を超えて全数を見られない。"
              "MAX_PAGES を上げてください")

    if missing or pub_missing or ref_problem or stale_local or pub_stale or PAGE_CAP_HIT:
        sys.exit(1)

    print("✅ ローカル・公開中ともにカバー画像あり（バッジ文言も最新）" if with_published
          else "✅ 全記事にカバー画像あり（バッジ文言も最新）")
    sys.exit(0)


if __name__ == "__main__":
    main()
