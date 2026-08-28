#!/usr/bin/env python3
"""公開済みnote記事（代理店2本）に残っていた確定ファクト違反を外科的に直す（2026-08-28）。

見つかった経緯:
  facts_patterns.common_violations を **公開本文（live body）** に当てて分かった。
  content_facts_guard.py は blog/articles_note/*.md（ローカル原稿）しか見ていないので、
  「原稿は直っているのに note 側が古いまま」というズレは誰も見ていなかった
  （→ この穴は note_live_facts_guard.py で塞いだ）。実際この2本がまさにそれで、
  25 の「リスナーさん」は原稿では既に直っていたのに公開本文には反映されていない。

対象（いずれも公開本文に1箇所ずつ。実測で確認済み。draft body も同一）:
  n2a16d2f925ce #42 ライバー代理店のスカウト術（代理店記事で最多PV: 月106PV / 通算209PV）
    - 「オンライン面談」  [[feedback_no_online_meeting_wording]]
    - 「リスナー」呼び捨て [[feedback_listener_san]]
    - 「何百人」          [[feedback_dont_make_up_numbers]]
  ne7911c5b9ce9 #25 ライバーマネージャーとは？（通算86PV）
    - 「リスナー」呼び捨て

「オンライン面談」の扱いについて（前回の判断からの変更）:
  note_meeting_wording_fix_20260824.py は「ステップ3：オンライン面談を提案」を
  KEEP_CONTEXTS に入れて**意図的に残していた**（自社導線ではなく、読者＝代理店が
  自分の見込み客に提案する手順だから）。2026-08-28 にユーザー指示で方針変更し、直す。
  すぐ下のDM例文が既に「LINEのビデオ通話でOKです」なので、見出しだけが
  「オンライン面談」で、記事の中で表記が割れていた。素の「面談」は
  リッチメニューのボタン名＝送信キーワードなので今までどおり触らない。
  → note_meeting_wording_fix_20260824.KEEP_CONTEXTS と
    content_facts_guard.ARTICLE_WARN_LABELS のコメントも合わせて更新済み。

「何百人」は「リスナーさんが何百人もいるインフルエンサー」で、自社の輩出実績の主張では
  ないが裏の取れない数字ではあるので「大勢」に置換する（AUDIT_WARN_LABELS 側の扱い）。

機構は note_meeting_wording_fix_20260824.py と同じで、公開は
  note_leadmagnet_publish.publish_one(key, transform, expect_marker=...) に任せる
  （draft_save → reCAPTCHA v3 verifications → PUT status=published、
   公開PUTがタグを0にする既知問題の復元まで内蔵）[[project_note_tag_guard]]。

使い方:
  python3 note_facts_fix_20260828.py --scan      # 公開本文を読むだけ（書き込みなし）
  python3 note_facts_fix_20260828.py --md        # ローカル原稿だけ直す
  python3 note_facts_fix_20260828.py --all       # ローカル原稿＋公開本文を直す
  python3 note_facts_fix_20260828.py <key> ...   # 公開本文を個別に直す
  python3 note_facts_fix_20260828.py --verify    # ログアウト状態の公開APIで検証
"""
import glob
import os
import re
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 検証は**ログアウト状態の公開API**で見る。エディタ画面やcookie付きGETは
# 下書き側を混ぜて返すことがあり、「読者に何が見えているか」の担保にならない。
PUBLIC_API = "https://note.com/api/v3/notes/{key}"
PUBLIC_HEADERS = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"}

# (旧, 新)。**公開本文とローカル原稿の両方に当てる**ので、両者でズレている
# 表現はペアを2本並べる（下の1本目は公開本文用、2本目はローカル原稿用）。
# どちらも冪等（当たらなければ何もしない）。
REPLACEMENTS = {
    "n2a16d2f925ce": [
        # 呼び捨てと「何百人」が同じ一文にあるので1手で直す。
        # 公開本文はまだ呼び捨て。ローカル原稿は「リスナーさん」まで直っている。
        ("リスナーが何百人もいるインフルエンサーほど",
         "リスナーさんが大勢いるインフルエンサーほど"),
        ("リスナーさんが何百人もいるインフルエンサーほど",
         "リスナーさんが大勢いるインフルエンサーほど"),
        # 見出しだけが「オンライン面談」。直下のDM例文は既に「LINEのビデオ通話でOK」。
        # ステップ4以降の素の「面談」は残す（禁止語ではない）。
        ("ステップ3：オンライン面談を提案", "ステップ3：LINE通話での面談を提案"),
    ],
    "ne7911c5b9ce9": [
        # ローカル原稿の表記に合わせる（原稿は既にこの形）
        ("ターゲットリスナー層の分析", "ターゲットリスナーさんの層の分析"),
    ],
}

# 反映確認に使うマーカー。note は保存のたびに見出し・段落へ name/id 属性を振り直すので、
# タグを含む固定文字列は使わない（属性が入って必ず外れる）。素の本文だけを見る。
MARKERS = {
    "n2a16d2f925ce": "リスナーさんが大勢いるインフルエンサーほど",
    "ne7911c5b9ce9": "ターゲットリスナーさんの層の分析",
}

# 直したあとに1つも残っていてはいけないもの（公開本文・ローカル原稿の両方に当てる）
FORBIDDEN = {
    "n2a16d2f925ce": [
        (r"オンライン(?:で)?(?:個別)?面談", "オンライン面談"),
        (r"リスナー(?!さん)", "リスナーの呼び捨て"),
        (r"何百人|数百人", "根拠なしの実績誇張"),
    ],
    "ne7911c5b9ce9": [
        (r"リスナー(?!さん)", "リスナーの呼び捨て"),
    ],
}

# ローカル原稿。番号プレフィクスで引く（data/note_key_map.json の番号）
LOCAL_MD = {
    "n2a16d2f925ce": "blog/articles_note/42_*.md",
    "ne7911c5b9ce9": "blog/articles_note/25_*.md",
}

TITLES = {
    "n2a16d2f925ce": "#42 ライバー代理店のスカウト術",
    "ne7911c5b9ce9": "#25 ライバーマネージャーとは？",
}


def transform(key, text):
    """公開本文HTML／ローカル原稿mdの共通変換。変化がなければ None（＝skip）。"""
    out = text
    for old, new in REPLACEMENTS[key]:
        out = out.replace(old, new)
    return None if out == text else out


def leftovers(key, text):
    """まだ残っている禁止表現を [(ラベル, 該当), ...] で返す。"""
    return [(label, m.group(0))
            for pat, label in FORBIDDEN[key]
            for m in re.finditer(pat, text)]


def fetch_public(key):
    r = requests.get(PUBLIC_API.format(key=key), headers=PUBLIC_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()["data"]


# ── 走査 ───────────────────────────────────────────────────
def scan():
    ok = True
    for key in REPLACEMENTS:
        d = fetch_public(key)
        body = d["body"]
        new = transform(key, body)
        left = leftovers(key, body)
        print(f"\n[{TITLES[key]}] {key}")
        print(f"  status={d['status']} body_len={len(body)} "
              f"tags={len(d.get('hashtag_notes', []))} "
              f"eyecatch={'OK' if d.get('eyecatch') else 'MISSING!'}")
        print(f"  置換対象={'あり' if new else 'なし（済み）'}  違反={len(left)}件")
        for label, hit in left:
            print(f"    ❌ {label}: {hit}")
        ok = ok and not left
    return ok


# ── ローカル原稿 ──────────────────────────────────────────────
def fix_md(dry=False):
    for key, pattern in LOCAL_MD.items():
        paths = glob.glob(os.path.join(BASE_DIR, pattern))
        if not paths:
            print(f"  [WARN] 原稿が見つからない: {pattern}")
            continue
        for p in paths:
            src = open(p, encoding="utf-8").read()
            new = transform(key, src)
            rel = os.path.relpath(p, BASE_DIR)
            if new is None:
                left = leftovers(key, src)
                print(f"  skip（変更なし） {rel}" + (f"  ※違反{len(left)}件残" if left else ""))
                continue
            if dry:
                print(f"  [dry-run] {rel} {len(src)} -> {len(new)}")
                continue
            with open(p, "w", encoding="utf-8") as f:
                f.write(new)
            print(f"  updated {rel} {len(src)} -> {len(new)}")


# ── 公開本文 ──────────────────────────────────────────────
def publish(key):
    """note_leadmagnet_publish.publish_one に公開の3段＋タグ復元を任せる。"""
    from note_leadmagnet_publish import publish_one
    r = publish_one(key, transform, expect_marker=MARKERS[key])
    if r == "skip":
        print("  変更なし（既に修正済み）")
        return r
    # publish_one の verify は cookie 付きGET。読者が見るものはログアウト側なので
    # そちらで最終確認する（反映ラグがあるので数回リトライ）。
    for attempt in range(4):
        time.sleep(5)
        d = fetch_public(key)
        left = leftovers(key, d["body"])
        hit = MARKERS[key] in d["body"]
        print(f"  [公開API {attempt + 1}] marker={hit} 違反残={len(left)} "
              f"tags={len(d.get('hashtag_notes', []))} "
              f"eyecatch={'OK' if d.get('eyecatch') else 'MISSING!'}")
        if hit and not left:
            return r
    raise RuntimeError(f"公開APIで確認できない（marker={hit} 残={left}）")


def verify():
    ok = True
    for key in REPLACEMENTS:
        d = fetch_public(key)
        body = d["body"]
        left = leftovers(key, body)
        tags = [h["hashtag"]["name"] for h in d.get("hashtag_notes", [])]
        print(f"[{TITLES[key]}] {key}")
        print(f"  status={d['status']} marker={MARKERS[key] in body} "
              f"違反残={len(left)} tags={len(tags)} "
              f"eyecatch={'OK' if d.get('eyecatch') else 'MISSING!'}")
        if left:
            print(f"    !!! 残っている: {left}")
        if len(tags) == 0:
            print("    !!! タグが0。note_tag_guard.ensure_tags で復元すること")
        ok = ok and bool(left) is False and len(tags) > 0
    return ok


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    if args[0] == "--scan":
        raise SystemExit(0 if scan() else 1)
    if args[0] == "--verify":
        raise SystemExit(0 if verify() else 1)
    if args[0] == "--md":
        fix_md(dry="--dry-run" in args)
        raise SystemExit(0)
    if args[0] == "--all":
        print("=== ローカル原稿 ===")
        fix_md()
        print("\n=== 公開本文 ===")
        targets = list(REPLACEMENTS)
    else:
        targets = args
    fail = 0
    for key in targets:
        print(f"\n[publish {key}] {TITLES.get(key, '')}")
        try:
            publish(key)
        except Exception as e:  # noqa: BLE001 — 1本落ちても残りは処理する
            fail += 1
            print(f"  !!! 失敗: {type(e).__name__}: {e}")
        time.sleep(3)
    raise SystemExit(1 if fail else 0)
