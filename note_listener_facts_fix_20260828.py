#!/usr/bin/env python3
"""公開中のnote記事に残っていた確定ファクト違反を一括で直す（2026-08-28）。

note_live_facts_guard.py（公開本文＝読者が実際に読んでいる側の番犬）が
140本中 **69件の違反** を出した。全件が drift＝ローカル原稿では既に直って
いるのに note 側だけ古い、という形で、content_facts_guard.py は構造上ずっと緑。

内訳（違反の数え方は「番犬が鳴いた記事数」。番犬はパターンごとに先頭1件しか
返さないので、実際の出現箇所はもっと多い）:
  リスナーの呼び捨て          55本 / 実出現 405箇所  [[feedback_listener_san]]
  出典なしの割合統計          10本                    [[feedback_dont_make_up_numbers]]
  「現役ライバー」             3本                    （代表は「元」Pococha S帯）
  「傘下」                     1本                    （代理店の関係は「提携」）

■ タイトルも直す（本文の再公開だけでは直らない）
  note_leadmagnet_publish.publish_one は `title = d["name"]` で**現在のタイトルを
  そのまま通す**ので、本文をいくら直してもタイトルは変わらない。呼び捨てが
  タイトルに残っていたのは3本:
    #77 n393f5e092338 初見リスナーを常連化する第一歩
    #74 ne31d02263e2f 「リスナーが集まる時間帯」
    #70 na0a86db07e89 配信中リスナー0人の時の対処法
  これは二重に効く。note_internal_links_publish.related_html は
    f'<li><a href="…">{catalog[k]["title"]}</a></li>'
  と**他記事のタイトルをリンク文言として本文へコピーする**ので、違反タイトルを
  放置すると「あわせて読みたい」経由で他記事の本文へ増殖する（実測 n3eef71e830e8）。
  そこで publish_one に title_fn を足して、タイトルを先に直す。

■ 「リスナー」→「リスナーさん」の当て方
  番犬の物差しは `リスナー(?!さん)` なので機械的には全部に「さん」を足せば緑に
  なるが、複合名詞は日本語が壊れる（「リスナー層」→「リスナーさん層」）。
  実際の405箇所の後続文字を数えて、助詞が続く大多数は素の挿入で足り、
  複合名詞だけ COMPOUND_RULES で先に処理すれば足りることを確認した。

■ 直さなかったもの（＝番犬の誤検知。本文のほうが正しい）
  #51 ライバー経費 …「所得税率が10%の人（課税所得195〜330万円帯）」は税法の
    事実であって出典なしの統計ではない。RATIO_SUBJECT が `N%の人` に当たるだけ。
    数字を書き換えると嘘になるので、文型のほうを「10%の場合」に変えて逃がす。
  #48 /#29 の「現役ライバーマネージャー」「現役ライバー事務所」は
    `現役(?:プレイヤー|ライバー)` が後ろの「マネージャー」「事務所」を見られない
    ための誤検知で、代表を現役ライバーだと言ってはいない。ただ紛らわしいので
    「現役」を落として曖昧さごと消す（意味は変わらない）。

使い方:
  python3 note_listener_facts_fix_20260828.py --dry-run   # 置換結果を全件出す（GETのみ）
  python3 note_listener_facts_fix_20260828.py --md        # ローカル原稿だけ直す
  python3 note_listener_facts_fix_20260828.py --titles     # タイトル3本だけ直す
  python3 note_listener_facts_fix_20260828.py --bodies     # 本文を直す（長い）
  python3 note_listener_facts_fix_20260828.py <key> ...    # 個別
  python3 note_listener_facts_fix_20260828.py --verify     # ログアウト公開APIで検証
"""
import glob
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
ARTICLE_DIR = os.path.join(BASE_DIR, "blog", "articles_note")
LOG_FILE = os.path.join(BASE_DIR, "data", "note_listener_fix_log.json")

# 検証は**ログアウト状態の公開API**で見る。cookie付きGETは下書き側を混ぜて返す
# ことがあり「読者に何が見えているか」の担保にならない。CDN越しなので no-cache 必須。
PUBLIC_API = "https://note.com/api/v3/notes/{key}"
PUBLIC_HEADERS = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache",
                  "Pragma": "no-cache"}

# note の連投検知を避ける。note_boost_publish と同じ刻み。
BATCH = 8
BATCH_SLEEP = 25
STEP_SLEEP = 3


# ── 「リスナー」→「リスナーさん」 ───────────────────────────────
# 複合名詞。素の「さん」挿入だと日本語が壊れるものだけをここに置く。
# 順番に意味がある（長い綴りが先。「リスナー数」より先に「コアリスナー化」等）。
COMPOUND_RULES = [
    # 「コアリスナー化」は「さん」を挟むと語として成立しないので文ごと言い換える
    ("コアリスナー化動線", "コアリスナーさんになってもらう動線"),
    ("コアリスナー化が進みます", "コアリスナーさんになってくれます"),
    ("リスナー経験のあるライバー", "リスナーさんとしての経験があるライバー"),
    ("リスナー友達", "リスナーさんのお友達"),
    ("貢献したリスナー上位", "貢献したリスナーさんの上位"),
    ("リスナーサポート", "リスナーさんのサポート"),
    # 「リスナーさん数」「リスナーさん層」は不自然。「の」を補う
    ("リスナー数", "リスナーさんの数"),
    ("リスナー層", "リスナーさんの層"),
    ("リスナー流入", "リスナーさんの流入"),
    ("リスナー定着", "リスナーさんの定着"),
    ("リスナー音声", "リスナーさんの音声"),
]

# 上の複合名詞を先に潰したあと、残り（助詞・数詞が続く大多数）に素で「さん」を足す。
GENERIC_RULE = (re.compile(r"リスナー(?!さん)"), "リスナーさん")


# ── 記事個別の言い換え ──────────────────────────────────────
# (旧, 新)。公開本文とローカル原稿の両方に当てる。どちらも冪等。
# 旧は str（そのまま置換）か、コンパイル済み正規表現でもよい。
#
# 正規表現が要る理由: note の本文は強調が <strong> で、ローカル原稿は ** で入る。
# 直したい文の**途中に**それが挟まっている箇所があり（#14）、素の固定文字列だと
# 必ず外れる。実際この3本は最初 str で書いて --dry-run で外れているのを検出した。
# 下の TAG は「<strong>… / **… のどちらでも、無くてもよい」を表す。
TAG = r"(?:</?[a-zA-Z][^>]*>|\*\*)*"

PER_KEY_RULES = {
    # ── 出典なしの割合統計 [[feedback_dont_make_up_numbers]] ──
    "nf4cc6b26f530": [  # #76 月収100万円ライバーの共通点
        ("9割が再現可能な", "再現可能な"),
        # 本文では <strong>9割は再現可能</strong>です。強調タグの内側だけを直す
        ("9割は再現可能", "再現可能"),
    ],
    "nfde7bf8ebf40": [  # #60 スカウトDM返信率
        ("相談の9割は", "相談の多くは"),
    ],
    "ndce8a9117fa4": [  # #56 副業ライバーおすすめ
        ("成否の8割が決まる", "成否の大部分が決まる"),
    ],
    "n205ef04edcbb": [  # #51 ライバー経費完全リスト
        ("質問の9割は", "質問の多くは"),
        ("8割が「経費の取りこぼし", "多くの方が「経費の取りこぼし"),
        # 税率は事実。数字ではなく文型を変えて誤検知から抜ける（上の docstring 参照）
        ("所得税率が10%の人（", "所得税率が10%の場合（"),
        ("所得税率が20%の人（", "所得税率が20%の場合（"),
    ],
    "ndb58de31b4de": [  # #47 副業月5万在宅
        ("9割がハマります", "たいてい落とし穴があります"),
    ],
    "n29aafb234cec": [  # #46 ライバー向いてる人
        ("8割が、配信後に", "多くが、配信後に"),
    ],
    "n0144caabbb73": [  # #59 ライバーなるには
        # 「およそ30%」は裏が取れない。伝聞であることだけ残す（強調タグの内側）
        ("およそ30%のライバーが、事務所との契約で何らかのトラブルを経験している",
         "事務所との契約で何らかのトラブルを経験したライバーもいる"),
    ],
    "nf58c6a743c2a": [  # #54 ライブ配信緊張克服
        ("99%の人が", "ほとんどの人が"),
    ],
    "na4971c6d00a7": [  # #14 ライバー辞めたい
        # 「TAITAN PROのデータでも約80%が…」は**自社の内部データを装った数字**で、
        # 裏付けが無い [[feedback_dont_make_up_numbers]]。数字を薄めるだけでは
        # 足りないので主張ごと落とす。文の途中に <strong> が2回挟まるので正規表現。
        (re.compile(r"実際にTAITAN\s*PRO（" + TAG + r"200名のライバーが所属" + TAG +
                    r"）のデータでも、辞めたいと感じた時期を乗り越えたライバーの" + TAG +
                    r"約80%がその後に収入アップ" + TAG + r"を実現しています。"),
         "実際に、辞めたいと感じた時期を乗り越えてから収入が伸びたライバーもいます。"),
    ],

    # ── 「現役」表記（代表は「元」Pococha S帯） ──
    "n6006676b8d6e": [  # #65 TikTokライバー事務所選び方
        ("実際に所属している現役ライバーからの紹介",
         "実際に所属しているライバーからの紹介"),
    ],
    "n6194f89cb2aa": [  # #48 Pococha始め方（誤検知だが紛らわしいので「現役」を落とす）
        ("現役ライバーマネージャーの視点", "ライバーマネージャーの視点"),
    ],
    "na737000db46a": [  # #29 怪しい事務所の見分け方（同上）
        ("現役ライバー事務所TAITAN PRO代表", "ライバー事務所TAITAN PRO代表"),
    ],

    # ── 代理店の関係は「提携」[[feedback_no_carveout_partner]] ──
    "n4ca1ae7bdc7c": [  # #78 事務所メリットデメリット
        ("傘下のライバーをサポート", "提携するライバーをサポート"),
    ],
}

# ── タイトル（本文の再公開では直らない。publish_one(title_fn=…) で直す）──
TITLE_RULES = {
    "n393f5e092338": ("初見リスナーを常連化する", "初見リスナーさんを常連化する"),
    "ne31d02263e2f": ("「リスナーが集まる時間帯」", "「リスナーさんが集まる時間帯」"),
    "na0a86db07e89": ("配信中リスナー0人の時の対処法", "配信中リスナーさん0人の時の対処法"),
}


def transform_text(key, text):
    """公開本文HTML／ローカル原稿mdの共通変換。変化がなければ None（＝skip）。

    <a href="…">タイトル</a> のリンク文言にも「リスナー」が入っている
    （「あわせて読みたい」が他記事のタイトルをコピーしている）が、これは
    本文として読まれる文字列なので一緒に直してよい。実測で140本すべて、
    タグの**属性値**に「リスナー」を含むものは0件（属性は name/id=UUID だけ）。
    """
    out = text
    for old, new in PER_KEY_RULES.get(key, []):
        out = old.sub(new, out) if hasattr(old, "sub") else out.replace(old, new)
    for old, new in COMPOUND_RULES:
        out = out.replace(old, new)
    out = GENERIC_RULE[0].sub(GENERIC_RULE[1], out)
    return None if out == text else out


def transform_title(key, title):
    rule = TITLE_RULES.get(key)
    if not rule:
        return None
    new = title.replace(*rule)
    return None if new == title else new


def leftovers(key, text):
    """直したあとに残っていてはいけないものを [(ラベル, 該当), …] で返す。

    物差しは番犬と同じ facts_patterns.common_violations を使う（コピーを持たない）。
    ただしこのスクリプトが担当するラベルだけに絞る。
    """
    mine = ("リスナーの呼び捨て", "出典なしの割合統計", "代表は「元」Pococha",
            "代理店の関係が「提携」でない")
    return [(reason, hit) for reason, hit in common_violations(text)
            if reason.startswith(mine)]


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


# ── ローカル原稿 ──────────────────────────────────────────
def fix_md():
    """blog/articles_note/*.md にも同じ変換を当てる。

    2026-08-28 の実測では呼び捨ては原稿側 0箇所（＝全部 drift）だが、割合統計や
    「傘下」は原稿にも残っている可能性があるので、番号で引いて当てる。
    """
    km = load_keymap()
    n = 0
    for key in set(PER_KEY_RULES) | set(TITLE_RULES) | set(km):
        num = km.get(key)
        if not num:
            continue
        for p in glob.glob(os.path.join(ARTICLE_DIR, f"{num}_*.md")):
            src = open(p, encoding="utf-8").read()
            new = transform_text(key, src)
            if new is None:
                continue
            with open(p, "w", encoding="utf-8") as f:
                f.write(new)
            print(f"  updated {os.path.relpath(p, BASE_DIR)} {len(src)} -> {len(new)}")
            n += 1
    print(f"  ローカル原稿 {n} 本を更新")


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

    if args[0] == "--md":
        fix_md()
        raise SystemExit(0)
    if args[0] == "--titles":
        raise SystemExit(1 if run(list(TITLE_RULES), with_body=False) else 0)

    keys = explicit or targets_from_live()
    if args[0] == "--dry-run":
        dry_run(keys, show_every="--all" in args)
        raise SystemExit(0)
    if args[0] == "--verify":
        raise SystemExit(0 if verify(keys) else 1)
    if args[0] == "--bodies":
        raise SystemExit(1 if run(keys) else 0)
    raise SystemExit(1 if run(explicit) else 0)
