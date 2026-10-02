#!/usr/bin/env python3
"""公開中のnote記事の所属数・提携代理店数を新しい確定値へ直す（2026-10-02）。

2026-10-02 ユーザー確定：所属 200名→**300名**、提携 11→**20の配信代理店**。
ローカル原稿（blog/articles_note/*.md）は commit 7682737 で一括置換済み。この
スクリプトは**公開本文そのもの**に同じ変換を当てる（--update で原稿ごと差し替えると、
ローカル原稿と公開本文が別物になっている記事 #09 型を丸ごと上書きしてしまうため、
note_listener_facts_fix_20260828.py と同じ「公開側だけ外科的に置換」の機構を使う）。

■ 変換の方針（ユーザー確定 2026-10-02）
  ① 統計・経験の**出典**としての人数（「200名の所属データ」「私が200名の実データから」
     「所属ライバー200名の平均値」等）→ **人数を外す**。200名時点で集めた数字を
     「300名のデータ」と言い換えないため。次に人数が増えても書き換え不要になる
  ② 内訳「所属ライバー200名（Pococha約100名・TikTok約50名）」→ 内訳ごと削除
     （そもそも合計が合っていなかった）
  ③ それ以外の所属数そのもの（会社概要の表・CTA・肩書き）→ 300名
  ④ 「11の配信代理店」「提携代理店11社」等 → 20。「11社の配信プラットフォーム」は
     代理店をプラットフォームと取り違えた旧表記なので「20の配信代理店」へ
  ※ 「0〜200人」「永遠に200人で止まります」のような所属数でない200は触らない
     （行に所属系の語が無いものは変えない）

使い方:
  python3 note_headcount_fix_20261002.py --dry-run [--all]   # 置換結果を全件出す（GETのみ）
  python3 note_headcount_fix_20261002.py --bodies             # 公開本文＋タイトルを直す（長い）
  python3 note_headcount_fix_20261002.py <key> ...            # 個別
  python3 note_headcount_fix_20261002.py --verify             # ログアウト公開APIで検証
"""
import json
import os
import re
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from facts_patterns import common_violations  # noqa: E402

KEYS_FILE = os.path.join(BASE_DIR, "data", "published_note_keys.json")
KEYMAP_FILE = os.path.join(BASE_DIR, "data", "note_key_map.json")
LOG_FILE = os.path.join(BASE_DIR, "data", "note_headcount_fix_log.json")

PUBLIC_API = "https://note.com/api/v3/notes/{key}"
PUBLIC_HEADERS = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache",
                  "Pragma": "no-cache"}
BATCH = 8
BATCH_SLEEP = 25
STEP_SLEEP = 3

MINE = ("所属数が300名以外", "所属数は「300名」固定", "提携代理店数が20以外",
        "代理店を「配信プラットフォーム」")

# 原稿の ** は公開本文では <strong>/<b>。どちらでも当たるように
T = r"(?:\*\*|</?(?:strong|b)>)?"

# ① 出典としての人数 → 人数を外す ／ ② 内訳を消す
ATTR = [
    (r"Pococha・TikTok合わせて200名の所属ライバーのデータ", "所属ライバーのデータ"),
    (r"200名の所属データ", "所属ライバーのデータ"),
    (r"200名の所属ライバーの実例", "所属ライバーの実例"),
    (r"200名(?:が)?所属するTAITAN PRO所属ライバー", "TAITAN PRO所属ライバー"),
    (r"私が200名の実データから", "私が所属ライバーの実データから"),
    (r"事務所200名の実データ全公開", "TikTok配信ライバー約50名の実データ全公開"),
    (r"所属ライバー200名（Pococha約100名・TikTok約50名）のうち", "所属ライバーのうち"),
    (r"所属ライバー200名（Pococha約100名・TikTok約50名）のTikTok LIVE実データ",
     "所属ライバーのTikTok LIVE実データ"),
    (r"所属ライバー200名（Pococha約100名・TikTok約50名）で実際に", "所属ライバーで実際に"),
    (r"200名の所属ライバー(?=の(?:データ|配信データ|枠|立ち上がり|過去イベントデータ|実))", "所属ライバー"),
    (r"200名が所属するTAITAN PROのライバーのデータ", "TAITAN PRO所属ライバーのデータ"),
    (r"TikTok LIVE・Pococha合わせて200名が所属するTAITAN PROの実データ", "TAITAN PRO所属ライバーの実データ"),
    (T + r"Pococha・TikTok合わせて200名" + T + r"の所属ライバーのデータ", "所属ライバーのデータ"),
    (r"うちの事務所200名の配信時間", "うちの事務所の所属ライバーの配信時間"),
    (r"Sランクライバーを200名見てきた", "所属ライバーを見てきた"),
    (r"200名見てきた中で", "所属ライバーを見てきた中で"),
    (r"所属ライバー200名（Pococha約100名・TikTok約50名）", "所属ライバー300名（Pococha・TikTok合わせて）"),
    (r"所属ライバー200名(の(?:配信時間別データ|配信データ|データ|リアル|平均値|内訳|実績))", r"所属ライバー\1"),
    (r"所属ライバー200名を見てきた", "所属ライバーを見てきた"),
    (r"私の200名中でも", "私が見てきた所属ライバーの中でも"),
    (r"これは200名見てきたデータです", "これは所属ライバーを見てきた中でのデータです"),
    (r"200名を見てきた立場から", "所属ライバーを見てきた立場から"),
    (r"200名の実データを並べて", "所属ライバーの実データを並べて"),
    (r"200名の中で早く", "所属ライバーの中で早く"),
    (r"Pococha・TikTok LIVE合わせて200名の実運用データ", "Pococha・TikTok LIVEの所属ライバーの実運用データ"),
    (r"200名を見てきた中で", "所属ライバーを見てきた中で"),
    (r"200名のライバーさんを見てきて", "所属ライバーさんを見てきて"),
    (r"Pococha歴4年・200名のライバーを見てきた中で蓄積した運用データ",
     "Pococha歴4年・所属ライバーを見てきた中で蓄積した運用データ"),
    (r"200名のライバーを見てきた中で溜まった", "所属ライバーを見てきた中で溜まった"),
    (r"TAITAN PROに所属する200名のライバー", "TAITAN PROに所属するライバー"),
    (r"実際にTAITAN PRO（" + T + r"200名のライバーが所属" + T + r"）のデータでも",
     "実際にTAITAN PRO所属ライバーのデータでも"),
]
# ④ 提携代理店数 → 20
AGENCY = [
    (r"11社の配信プラットフォームと提携し", "20の配信代理店と提携し"),
    (r"プラットフォーム最適化：11社の中から、", "プラットフォーム最適化：Pococha・TikTok LIVEから、"),
    (r"(?<![0-9])11の(配信代理店|代理店)", r"20の\1"),
    (r"(提携(?:配信)?代理店(?:パートナー)?(?:数)?(?:</th><td>|: |：|\s*)?)11社", r"\g<1>20社"),
    (r"代理店パートナー11社", "代理店パートナー20社"),
    (r"11個の代理店ネットワークを持ち", "20の配信代理店と提携し"),
    (r"(?<![0-9])11代理店(?=と)", "20の配信代理店"),
]
# ③ 所属数そのもの：上の置換のあと残った 200名/200人 を、所属系の語がある段落だけ 300 に
BLOCK_SPLIT = re.compile(r"(</p>|</li>|</h[1-6]>|</td>|</th>|<br\s*/?>|\n)")
COUNT_CTX = re.compile(r"所属|TAITAN|事務所|ライバー|在籍|育成|抱え|サポート")


def _plain(s):
    return re.sub(r"<[^>]+>", "", s)


def transform_text(key, text):
    """公開本文HTML／タイトル共通の変換。変化がなければ None（＝skip）。"""
    out = text
    for a, b in ATTR + AGENCY:
        out = re.sub(a, b, out)
    parts = BLOCK_SPLIT.split(out)
    for i, p in enumerate(parts):
        plain = _plain(p)
        if re.search(r"200\s*[名人]", plain) and COUNT_CTX.search(plain):
            parts[i] = re.sub(r"(?<![0-9,，〜~])200(\s*[名人])", r"300\1", p)
    out = "".join(parts)
    return None if out == text else out


def transform_title(key, title):
    return transform_text(key, title)


def leftovers(key, text):
    """直したあとに残っていてはいけないものを [(ラベル, 該当), …] で返す。
    物差しは番犬と同じ facts_patterns.common_violations（このスクリプトの担当ラベルだけ）。"""
    return [(reason, hit) for reason, hit in common_violations(text)
            if reason.startswith(MINE)]


def fetch_public(key):
    r = requests.get(PUBLIC_API.format(key=key), headers=PUBLIC_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()["data"]


def _load(path):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except ValueError:
            return {}
    return {}


def load_keymap():
    out = {}
    for num, rec in _load(KEYMAP_FILE).items():
        if rec.get("key"):
            out[rec["key"]] = num
    return out


# ── ドライラン ────────────────────────────────────────────
def dry_run(keys, show_every=False):
    """公開本文を読んで、置換の前後を全件出す。書き込みは一切しない。"""
    km = load_keymap()
    total = changed = 0
    for key in keys:
        try:
            d = fetch_public(key)
        except requests.RequestException as e:
            print(f"  [取得失敗] {key}: {e}")
            continue
        body, title = d.get("body", ""), d.get("name", "")
        nt = transform_title(key, title)
        nb = transform_text(key, body)
        if nt is None and nb is None:
            time.sleep(0.3)
            continue
        changed += 1
        print(f"\n#{km.get(key, '?')} {key}  {title[:44]}")
        if nt:
            print(f"  [TITLE] {title}\n       -> {nt}")
        if nb:
            diffs = _diff_spans(body, nb)
            total += len(diffs)
            print(f"  [BODY] {len(body)} -> {len(nb)}  置換 {len(diffs)}箇所")
            for a, b in (diffs if show_every else diffs[:6]):
                print(f"     - {a}\n     + {b}")
            if not show_every and len(diffs) > 6:
                print(f"     …ほか {len(diffs) - 6} 箇所（--all で全件）")
        left = leftovers(key, (nt or title) + "\n" + (nb or body))
        for reason, hit in left:
            print(f"     ❌ 直したのに残る: {reason}: {hit}")
        time.sleep(0.3)
    print(f"\n対象 {changed} 本 / 置換 {total} 箇所")


def _diff_spans(old, new):
    """置換された箇所を (旧文脈, 新文脈) で列挙する。目視レビュー用。"""
    import difflib
    out = []
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        pad = 22
        a = re.sub(r"<[^>]+>", "", old[max(0, i1 - pad):i2 + pad])
        b = re.sub(r"<[^>]+>", "", new[max(0, j1 - pad):j2 + pad])
        out.append((a, b))
    return out


# ── 公開 ──────────────────────────────────────────────
def publish(key, with_title=True, with_body=True):
    """note_leadmagnet_publish.publish_one に公開の3段＋タグ復元を委譲する。"""
    from note_leadmagnet_publish import publish_one

    tfn = (lambda k, t: transform_title(k, t)) if with_title else None
    bfn = (lambda k, h: transform_text(k, h)) if with_body else (lambda k, h: None)
    # マーカーはタグを含まない素の本文で見る。note は保存のたびに見出し・段落へ
    # name/id を振り直すので、タグ入りの固定文字列は必ず外れる。
    r = publish_one(key, bfn, expect_marker=None, title_fn=tfn)
    if r == "skip":
        print("  変更なし（既に修正済み）")
        return r

    # publish_one の verify は cookie 付きGET。読者が見るのはログアウト側なので
    # そちらで最終確認する（CDN反映ラグがあるのでリトライ）。
    #
    # 検証範囲は「この回で直した部分」だけに合わせる。--titles のように本文を
    # 触らない回でタイトル＋本文を見ると、まだ直していない本文の呼び捨てを拾って
    # 必ず失敗する（実測: タイトル3本は正しく直っているのに fail=3 になった）。
    for attempt in range(4):
        time.sleep(6)
        d = fetch_public(key)
        checked = (d.get("name", "") + "\n" + d.get("body", "")) if with_body \
            else d.get("name", "")
        left = leftovers(key, checked)
        tags = len(d.get("hashtag_notes", []))
        print(f"  [公開API {attempt + 1}] 違反残={len(left)} tags={tags} "
              f"eyecatch={'OK' if d.get('eyecatch') else 'MISSING!'}")
        if not left:
            if tags == 0:
                raise RuntimeError("タグが0のまま（note_tag_guard.ensure_tags 要確認）")
            return r
    raise RuntimeError(f"公開APIで確認できない（残={left[:3]}）")


def run(keys, with_title=True, with_body=True):
    km = load_keymap()
    log = _load(LOG_FILE)
    ok = skip = fail = 0
    for i, key in enumerate(keys, 1):
        print(f"\n[{i}/{len(keys)}] #{km.get(key, '?')} {key}", flush=True)
        try:
            r = publish(key, with_title=with_title, with_body=with_body)
            log[key] = r
            ok += r == "ok"
            skip += r == "skip"
        except Exception as e:  # noqa: BLE001 — 1本落ちても残りは処理する
            print(f"  !! 失敗: {type(e).__name__}: {e}", flush=True)
            log[key] = f"error: {e}"
            fail += 1
        json.dump(log, open(LOG_FILE, "w"), ensure_ascii=False, indent=1)
        time.sleep(BATCH_SLEEP if i % BATCH == 0 else STEP_SLEEP)
    print(f"\n完了 ok={ok} skip={skip} fail={fail}")
    return fail


# ── 検証 ──────────────────────────────────────────────
def verify(keys):
    km = load_keymap()
    bad = 0
    for key in keys:
        try:
            d = fetch_public(key)
        except requests.RequestException as e:
            print(f"  [取得失敗] {key}: {e}")
            bad += 1
            continue
        left = leftovers(key, d.get("name", "") + "\n" + d.get("body", ""))
        tags = len(d.get("hashtag_notes", []))
        if left or tags == 0:
            bad += 1
            print(f"❌ #{km.get(key, '?')} {key} tags={tags} 残={len(left)}")
            for reason, hit in left[:4]:
                print(f"     {reason}: {hit}")
        time.sleep(0.3)
    print(f"\n検証 {len(keys)} 本 / 問題 {bad} 本")
    return bad == 0


def targets_from_live():
    """公開本文を読んで、実際に直すところがある記事だけを返す。"""
    keys = json.load(open(KEYS_FILE, encoding="utf-8"))
    out = []
    for key in keys:
        try:
            d = fetch_public(key)
        except requests.RequestException:
            continue
        if transform_text(key, d.get("body", "")) or transform_title(key, d.get("name", "")):
            out.append(key)
        time.sleep(0.3)
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    explicit = [a for a in args if a.startswith("n") and not a.startswith("--")]
    if not args:
        print(__doc__)
        raise SystemExit(1)


    keys = explicit or targets_from_live()
    if args[0] == "--dry-run":
        dry_run(keys, show_every="--all" in args)
        raise SystemExit(0)
    if args[0] == "--verify":
        raise SystemExit(0 if verify(keys) else 1)
    if args[0] == "--bodies":
        raise SystemExit(1 if run(keys) else 0)
    raise SystemExit(1 if run(explicit) else 0)
