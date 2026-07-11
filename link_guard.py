#!/usr/bin/env python3
"""link_guard.py — 死にリンクを構造的に検知する番犬
====================================================
背景（2026-07-12）: 公開Note記事5本が404の旧LINEリンク lin.ee/816qtxyj を
使い続けており、読者を長期間404に誘導していた。リンクは「書いた時点で正しい」
だけでは足りず、切れた瞬間に気づける仕組みが必要。

3層のチェック:
  1. LINEリンク許可リスト — lin.ee のURLは LINE_ALLOWED 以外が
     リポジトリ内・公開記事内のどこかに現れたら即エラー（typo・旧リンク混入防止）
  2. リポジトリ内コンテンツのURL実チェック — 読者の目に触れるファイル群から
     URLを抽出してGETし、404/410 を検知
  3. 公開Note全記事のURL実チェック — 公開APIで全記事本文を取得して同様に検知
     （公開版とリポジトリの乖離も拾える）

判定ポリシー:
  - DEAD  = 404/410、または許可リスト外の lin.ee URL → exit 1（Actionsが赤くなる）
  - WARN  = 403/405/429/5xx/タイムアウト等（bot拒否の可能性が高い）→ 報告のみ
  - SKIP  = botを全面ブロックするSNSドメイン（誤検知源なので見ない）

使い方:
  python3 link_guard.py              # 全チェック（リポジトリ＋公開Note）
  python3 link_guard.py --repo-only  # ネット越しのNote取得なし（ローカル用・高速）

レポートは data/link_guard_report.json に保存される。
"""
import glob
import json
import os
import re
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_FILE = os.path.join(BASE_DIR, "data", "link_guard_report.json")

NOTE_CREATOR = "taitan_118"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# ── 1. LINEリンク許可リスト ──
# 正しい公式LINEはこれだけ。新アカウントを作ったらここに追加する。
LINE_ALLOWED = {"https://lin.ee/xchCfdn"}
# 過去に事故を起こした既知の死にリンク（検出したら必ずエラー）
KNOWN_DEAD = ["lin.ee/816qtxyj"]

# ── 読者の目に触れるコンテンツファイル ──
CONTENT_GLOBS = [
    "blog/articles_note/*.md",
    "posts/*.json",
    "posts/*.txt",
    "threads/threads_posts.json",
    "instagram/ig_posts.json",
    "lp/**/*.html",
    "line_bot/messages.py",
    "line_bot/config.py",
    "config.py",
    "note_article_generator.py",
    "threads/threads_content.py",
    "cloud_post.py",
    "instagram/ig_viral_generator.py",
]

# botを全面ブロックしていて実チェックが誤検知になるドメイン
SKIP_DOMAINS = (
    "x.com", "twitter.com", "instagram.com", "facebook.com", "tiktok.com",
    "threads.net", "localhost", "127.0.0.1", "example.com",
    "api.line.me", "notify-api.line.me",  # API系はGETで判定できない
)

# 読者が踏むリンクではないURL（preconnectヒント・JSON-LDの@context等）
SKIP_EXACT = {
    "https://fonts.googleapis.com",
    "https://fonts.gstatic.com",
    "https://schema.org",
}

URL_RE = re.compile(r"https?://[^\s\"'<>\\){}\]｝】、。」「『』（）【　]+")


def _clean(url):
    return url.rstrip(".,;:!?*_~`)»›」')")


def extract_repo_urls():
    """コンテンツファイルから URL → 出現ファイル一覧 を集める"""
    found = {}
    for pattern in CONTENT_GLOBS:
        for fp in glob.glob(os.path.join(BASE_DIR, pattern), recursive=True):
            try:
                with open(fp, encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, IsADirectoryError):
                continue
            rel = os.path.relpath(fp, BASE_DIR)
            for m in URL_RE.findall(text):
                url = _clean(m)
                # f-string分割等で途切れた断片は除外（実URLはランタイム構築側で取得）
                if url.endswith("@") or url in SKIP_EXACT:
                    continue
                found.setdefault(url, set()).add(rel)

    # ランタイム構築される重要URL（特典PDFのjsDelivr URL＝SHA固定）
    try:
        sys.path.insert(0, os.path.join(BASE_DIR, "line_bot"))
        from messages import GUIDE_URL
        found.setdefault(GUIDE_URL, set()).add("line_bot/messages.py(GUIDE_URL)")
    except Exception as e:
        print(f"[WARN] GUIDE_URLのimport失敗: {e}")
    return found


def fetch_note_urls():
    """公開Note全記事の本文からURLを集める（公開API・cookie不要）"""
    found = {}
    keys = []
    page = 1
    while True:
        r = requests.get(
            f"https://note.com/api/v2/creators/{NOTE_CREATOR}/contents?kind=note&page={page}",
            headers={"User-Agent": UA}, timeout=20)
        d = r.json()["data"]
        keys += [c["key"] for c in d["contents"]]
        if d.get("isLastPage"):
            break
        page += 1
        time.sleep(0.5)
    print(f"公開Note記事: {len(keys)}本")
    for k in keys:
        try:
            r = requests.get(f"https://note.com/api/v3/notes/{k}",
                             headers={"User-Agent": UA}, timeout=20)
            body = r.json()["data"].get("body", "")
        except Exception as e:
            print(f"  [WARN] {k} 本文取得失敗: {e}")
            continue
        for m in re.findall(r'href="([^"]+)"', body) + URL_RE.findall(body):
            url = _clean(m)
            if url.startswith("http"):
                found.setdefault(url, set()).add(f"note:{k}")
        time.sleep(0.6)
    return found


def check_url(url):
    """URLの生死判定。('dead'|'warn'|'ok', 詳細) を返す"""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15,
                         allow_redirects=True, stream=True)
        code = r.status_code
        r.close()
    except requests.RequestException as e:
        return "warn", f"接続エラー: {type(e).__name__}"
    if code in (404, 410):
        return "dead", f"HTTP {code}"
    if code >= 400:
        return "warn", f"HTTP {code}（bot拒否の可能性）"
    return "ok", f"HTTP {code}"


def main():
    repo_only = "--repo-only" in sys.argv

    urls = extract_repo_urls()
    if not repo_only:
        for url, srcs in fetch_note_urls().items():
            urls.setdefault(url, set()).update(srcs)

    dead, warns = [], []

    # 1. 許可リスト外の lin.ee / 既知の死にリンク
    for url, srcs in sorted(urls.items()):
        if "lin.ee" in url and url not in LINE_ALLOWED:
            dead.append({"url": url, "reason": "許可リスト外のLINEリンク",
                         "sources": sorted(srcs)})
        elif any(bad in url for bad in KNOWN_DEAD):
            dead.append({"url": url, "reason": "既知の死にリンク",
                         "sources": sorted(srcs)})

    # 2. 実チェック
    flagged = {d["url"] for d in dead}
    targets = [(u, s) for u, s in sorted(urls.items())
               if u not in flagged and not any(d in u for d in SKIP_DOMAINS)]
    print(f"チェック対象URL: {len(targets)}件（全抽出 {len(urls)}件）")
    for url, srcs in targets:
        status, detail = check_url(url)
        mark = {"ok": "  ", "warn": "⚠️", "dead": "❌"}[status]
        print(f" {mark} {detail:28s} {url[:90]}")
        entry = {"url": url, "reason": detail, "sources": sorted(srcs)}
        if status == "dead":
            dead.append(entry)
        elif status == "warn":
            warns.append(entry)
        time.sleep(0.4)

    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump({"checked": len(targets), "dead": dead, "warn": warns},
                  f, ensure_ascii=False, indent=1)

    print(f"\n[結果] dead={len(dead)} warn={len(warns)} → {REPORT_FILE}")
    for d in dead:
        print(f"  ❌ {d['url']}")
        print(f"     理由: {d['reason']}")
        print(f"     出現: {', '.join(d['sources'][:6])}"
              + (f" ほか{len(d['sources'])-6}件" if len(d["sources"]) > 6 else ""))
    if dead:
        sys.exit(1)
    print("死にリンクなし ✅")


if __name__ == "__main__":
    main()
