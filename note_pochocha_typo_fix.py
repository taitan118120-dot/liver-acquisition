#!/usr/bin/env python3
"""公開済みnote記事のプラットフォーム名誤記「Pochocha」を「Pococha」へ外科的に修正する。

2026-08-04に非ログイン公開API(/api/v3/notes/{key})で公開118本を走査し、10本・計15箇所を検出。
15箇所すべてが本文テキスト（href/id/属性値の中には一切出現しない）ことを確認済みなので、
単純な文字列置換で安全に直せる。

機構は note_exitclaim_fix.py と同じ（Chrome cookie + Playwright + reCAPTCHA + PUT + ensure_tags）。

反映確認について:
  この施策は「文字列を消す」だけなので publish_one に渡せる固有の追加マーカーが無い。
  対象10本は全て特典段落（スタートダッシュガイド）を持つことを確認済みなので、
  publish_one 既定の expect_marker をそのまま本文健全性チェックとして使い、
  「Pochochaが実際に消えたか」は本スクリプト側で非ログイン公開APIから独自に検証する。

使い方:
  python3 note_pochocha_typo_fix.py --dry-run          # 全対象を検査のみ
  python3 note_pochocha_typo_fix.py --verify           # 公開APIで現況確認のみ
  python3 note_pochocha_typo_fix.py --all              # 全10本を修正
  python3 note_pochocha_typo_fix.py <key> [<key> ...]  # 指定記事のみ
"""
import json
import re
import sys
import time
import urllib.request

from note_cta_publish import get_note, req_session
from note_leadmagnet_publish import LM_MARK, publish_one

RULES = [("Pochocha", "Pococha")]

# 変換後に残っていたら異常とみなすパターン
BANNED = re.compile(r"Pochocha")

# 2026-08-04時点の検出結果（括弧内は本文中の出現回数）
TARGET_KEYS = [
    "n80e2230642a8",  # 3
    "n8e088d985eab",  # 3
    "n5fa353fd8dd4",  # 2
    "nbc6cd81018b2",  # 1
    "nf4cc6b26f530",  # 1
    "ne31d02263e2f",  # 1
    "n2b77c40294ef",  # 1
    "na0a86db07e89",  # 1
    "n71c820dc9e48",  # 1
    "nf70121f2fda2",  # 1
]

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _in_tag_positions(html, needle):
    """needle が HTML タグの内側（<...> の中）に出現する箇所を返す。

    属性値の中を置換すると id/href が壊れるため、実行前に必ず0件であることを確かめる。
    """
    inside = []
    tag_spans = [(m.start(), m.end()) for m in re.finditer(r"<[^>]*>", html)]
    for m in re.finditer(re.escape(needle), html):
        for s, e in tag_spans:
            if s <= m.start() < e:
                inside.append(m.start())
                break
    return inside


def transform(key, html):
    """本文HTMLの誤記を置換する。変更なしなら None（＝対応済み）。"""
    new = html
    delta = 0  # 置換で見込まれる本文長の増減
    for old, rep in RULES:
        bad = _in_tag_positions(new, old)
        if bad:
            raise ValueError(
                f"『{old}』がHTMLタグ内に出現するため自動置換できない "
                f"(key={key}, pos={bad})")
        delta += new.count(old) * (len(rep) - len(old))
        new = new.replace(old, rep)
    if new == html:
        return None  # 変更なし＝済み
    left = BANNED.findall(new)
    if left:
        raise ValueError(f"未処理の誤記が残存 (key={key}): {len(left)}箇所")
    # 置換以外の変化（本文欠落など）が混ざっていないことを長さで裏取りする
    if len(new) != len(html) + delta:
        raise ValueError(
            f"置換後の本文長が想定と不一致 (key={key}): "
            f"{len(html)}{delta:+d} を期待したが {len(new)}")
    return new


def public_get(key):
    """非ログインの公開APIから記事を取得する（キャッシュ無効化つき）。"""
    req = urllib.request.Request(
        f"https://note.com/api/v3/notes/{key}?ts={int(time.time() * 1000)}",
        headers={"User-Agent": UA, "Accept": "application/json",
                 "Cache-Control": "no-cache", "Pragma": "no-cache"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)["data"]


def public_check(key, retries=3):
    """公開状態・誤記0件・タグ本数を非ログインAPIで検証する。"""
    last = None
    for attempt in range(retries):
        d = public_get(key)
        body = d["body"] or ""
        last = {
            "status": d["status"],
            "typo_body": body.count("Pochocha"),
            "typo_title": (d["name"] or "").count("Pochocha"),
            "pococha": body.count("Pococha"),
            "tags": len(d.get("hashtag_notes", [])),
            "eyecatch": bool(d.get("eyecatch")),
            "lm": LM_MARK in body,
            "body_len": len(body),
        }
        ok = (last["status"] == "published" and last["typo_body"] == 0
              and last["typo_title"] == 0 and last["tags"] > 0)
        if ok or attempt == retries - 1:
            break
        # CDNキャッシュのラグと本当の失敗を区別するため、間隔を空けて取り直す
        time.sleep(6)
    last["ok"] = (last["status"] == "published" and last["typo_body"] == 0
                  and last["typo_title"] == 0 and last["tags"] > 0)
    return last


def fmt(c):
    return (f"status={c['status']} typo={c['typo_body']}(title:{c['typo_title']}) "
            f"Pococha={c['pococha']} tags={c['tags']} "
            f"eyecatch={'OK' if c['eyecatch'] else 'MISSING!'} "
            f"lm={c['lm']} len={c['body_len']}")


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    verify_only = "--verify" in args
    keys = [a for a in args if not a.startswith("--")]
    if "--all" in args or verify_only or (dry and not keys):
        keys = keys or TARGET_KEYS
    if not keys:
        print(__doc__)
        return 1

    if verify_only:
        bad = []
        for i, key in enumerate(keys, 1):
            c = public_check(key, retries=1)
            print(f"[{i}/{len(keys)}] {key}  {fmt(c)}")
            if not c["ok"]:
                bad.append(key)
            time.sleep(1)
        print(f"\n誤記残存/異常: {bad or 'なし'}")
        return 1 if bad else 0

    s = req_session()
    fails = []
    for i, key in enumerate(keys, 1):
        d = get_note(s, key, draft=False)
        print(f"[{i}/{len(keys)}] {key} {d['name'][:44]}")
        try:
            new = transform(key, d["body"])
        except ValueError as e:
            print(f"  !! {e}")
            fails.append(key)
            continue
        if new is None:
            print("  skip（誤記なし＝対応済み）")
            continue
        n = d["body"].count("Pochocha")
        print(f"  変換OK: {n}箇所 / body {len(d['body'])} bytes")
        if dry:
            continue
        try:
            # expect_marker は既定（スタートダッシュガイド）のまま使う。
            # 対象10本は全て特典段落を持つため、本文が壊れていないことの検査になる。
            publish_one(key, transform_fn=transform)
        except Exception as e:
            print(f"  !! PUT失敗: {e}")
            fails.append(key)
            continue
        c = public_check(key)
        print(f"  公開API検証: {fmt(c)}")
        if not c["ok"]:
            print("  !! 公開側に誤記が残っている / 状態異常")
            fails.append(key)
        time.sleep(8)  # note側への負荷と連投検知を避ける

    if fails:
        print(f"\n要対応: {sorted(set(fails))}")
        return 1
    print("\n全件OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
