#!/usr/bin/env python3
"""公開済みnote記事から「17LIVEの取り扱い」記述を落とす一括更新（2026-09-20・一度きり）。

ユーザー指示「17ライブの取り扱いをやめる／17単体だけ消して、あとは書き換え」。
17LIVE単体記事3本（116/117/119）は note_delete_articles.py で削除済み。
本スクリプトは**残った公開記事の本文**を、ローカルmdに入れた修正とまったく同じ形で直す。

設計:
  ローカル md の before/after（作業前コミット d0f354d ↔ 現在）を difflib で行単位に割り、
  - 1行→1行 … 変わった**最小部分文字列**だけを公開HTMLの該当要素内で置換
  - 行の削除  … その行に対応する <p>/<li> 要素ごと削除
  にして当てる。行まるごとの置換にしないのは、公開側だけに入っている
  CTA・内部リンク・表→箇条書き変換（`項目: 対応 ／ TAITAN PRO: …`）を壊さないため。

  **「比較・市場紹介としての17LIVE」は残す**（ユーザー判断 2026-09-20／IRIAM等と同じ扱い）。
  だからブランケットな正規表現は使わず、ローカルで実際に直した箇所しか触らない。

使い方:
  python3 note_drop17live_20260920.py --dry-run   # GETのみ。当たらなかった行を全部出す
  python3 note_drop17live_20260920.py --all       # 順次更新（再開可能・logに記録）
  python3 note_drop17live_20260920.py --verify <key>
"""
import difflib
import html as _html
import json
import os
import re
import subprocess
import sys
import time

from note_cta_publish import get_note, req_session
import note_leadmagnet_publish as _lm

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_COMMIT = "d0f354d"
ARTICLES = os.path.join(BASE_DIR, "blog", "articles_note")
LOG_FILE = os.path.join(BASE_DIR, "data", "drop17live_update_log.json")

SKIP_KEYS = set()

# タイトルを変えた記事（公開側のタイトルも差し替える）
TITLE_MAP = {
    "nd60f3b2578d1": "ライブ配信アプリの掛け持ちはアリ？ナシ？｜Pococha・TikTok LIVEを併用する前に読む記事【2026年版】",
    "nb7bd24410450": "PocochaとTikTok LIVEどっちが向いてる？性格と生活リズムで選ぶ配信アプリ診断【2026年】",
}

# 118 は「3アプリの適性比較」→「2アプリの適性比較」の全面改稿。
# ローカルmdは作り直したので行単位の差分が取れない。公開本文に当てる手を直接書く。
MANUAL_OPS = {
    "nb7bd24410450": {
        "reps": [
            ("「ライブ配信を始めたいけど、17LIVE・Pococha・TikTok LIVEのどれがいいの？」",
             "「ライブ配信を始めたいけど、PocochaとTikTok LIVEのどっちがいいの？」"),
            ("17LIVE・Pococha・TikTok LIVEの3つを「どんな人に向いているか」で比較します。",
             "PocochaとTikTok LIVEを「どんな人に向いているか」で比較します。"
             "収入の条件や換金の仕組みではなく、性格・生活リズムからの適性にしぼって整理します。"),
            ("3アプリの特徴を一言でいうと", "2アプリの特徴を一言でいうと"),
            ("17LIVE: イベントで勝負する枠 ／ ", ""),
            ("17LIVE: ギフト ／ ", ""),
            ("17LIVE: イベントが豊富／ファンクラブ文化「アーミー」 ／ ", ""),
            ("17LIVE: 目標に向かって燃えるタイプ ／ ", ""),
            ("まとまった時間は取れないが動画なら隙間で作れるならTikTok型。イベント期に集中して燃えられるなら17LIVE型。",
             "まとまった時間は取れないが動画なら隙間で作れるならTikTok型。"),
            ("目標達成型→17LIVE／習慣型→Pococha", "習慣型→Pococha"),
            ("実際に3つともリスナーさんとして見てみる", "実際に両方ともリスナーさんとして見てみる"),
            ("「どのアプリが合うか」の相談から乗れる", "「どちらのアプリが合うか」の相談から乗れる"),
            ("のが、3つとも扱っている事務所の強みです。", "のが、両方とも扱っている事務所の強みです。"),
            ("「どれが合うか、話を聞くだけ」で大丈夫。", "「どちらが合うか、話を聞くだけ」で大丈夫。"),
        ],
        "dels": [
            ["17LIVEが向いている人：「イベントで勝負して駆け上がりたい」"],
            ["17LIVE（イチナナ）は世界中で使われている大手配信アプリです。特徴は2つ。"],
            ["イベントが豊富：上位入賞から一気に知名度を上げるチャンスがある"],
            ["ファンクラブ文化「アーミー」：リスナーさんとの絆が深く、「推しを支えるコミュニティ」が育ちやすい"],
            ["収入の中心はギフトで、イベントを頑張るほど伸びるタイプのアプリです。"
             "「目標があった方が燃える」「リスナーさんと一緒にお祭りを戦いたい」という人に向いています。"],
            ["逆に、イベントのたびに全力を出すのがしんどい人・淡々とマイペースにやりたい人には、"
             "次のPocochaの方が合うかもしれません。"],
        ],
    },
}

# 削除した17LIVE単体記事。「あわせて読みたい」に残っていると死にリンクになる。
DEAD_KEYS = ("n4bf4792f76c2", "n09c4354eb7b4", "n7a5a2ec349cf")

# 公開側にだけ入っている定型（事務所情報の表・CTA前の断り書き）。
# note_cta_publish 等が公開時に足しているのでローカルmdの差分には出てこない。
# どれも「TAITAN PROが17LIVEを扱っている」という主張そのものなので全記事に当てる。
GLOBAL_REPS = [
    ("項目: 対応 ／ TAITAN PRO: Pococha・TikTok LIVE・17LIVE",
     "項目: 対応 ／ TAITAN PRO: Pococha・TikTok LIVE"),
    ("項目: 対応プラットフォーム ／ TAITAN PRO: Pococha・TikTok LIVE・17LIVE",
     "項目: 対応プラットフォーム ／ TAITAN PRO: Pococha・TikTok LIVE"),
    ("項目: 対応プラットフォーム ／ TAITAN PRO: TikTok LIVE・Pococha・17LIVE",
     "項目: 対応プラットフォーム ／ TAITAN PRO: TikTok LIVE・Pococha"),
    ("項目: 得意分野 ／ TAITAN PRO: Pococha・TikTok LIVE・17LIVE",
     "項目: 得意分野 ／ TAITAN PRO: Pococha・TikTok LIVE"),
    ("取り扱っているのは Pococha・TikTok LIVE・17LIVE の3つ", "取り扱っているのは Pococha・TikTok LIVE の2つ"),
    ("取り扱っているのは、Pococha・TikTok LIVE・17LIVEの3つ", "取り扱っているのは、Pococha・TikTok LIVEの2つ"),
    ("取り扱っているのはPococha・TikTok LIVE・17LIVEの3つ", "取り扱っているのはPococha・TikTok LIVEの2つ"),
    ("取り扱うのはPococha・TikTok LIVE・17LIVEの3つ", "取り扱うのはPococha・TikTok LIVEの2つ"),
    ("取り扱うのはPococha・TikTok LIVE・17LIVEです", "取り扱うのはPococha・TikTok LIVEです"),
    ("サポートできるのは、Pococha・TikTok LIVE・17LIVEの3つ", "サポートできるのは、Pococha・TikTok LIVEの2つ"),
    ("サポートできるのは前者（Pococha）と、TikTok LIVE・17LIVEになります",
     "サポートできるのは前者（Pococha）と、TikTok LIVEになります"),
    ("Pococha・TikTok LIVE・17LIVE専門", "Pococha・TikTok LIVE専門"),
    ("Pococha・TikTok LIVE・17LIVE対応：どれでも専門サポート可能",
     "Pococha・TikTok LIVE対応：どちらでも専門サポート可能"),
    ("対応しているアプリを書く（Pococha・TikTok LIVE・17LIVE）", "対応しているアプリを書く（Pococha・TikTok LIVE）"),
    ("対応アプリ（Pococha・TikTok LIVE・17LIVE）", "対応アプリ（Pococha・TikTok LIVE）"),
    ("取り扱いはPococha・TikTok LIVE・17LIVE", "取り扱いはPococha・TikTok LIVE"),
    ("Pococha・TikTok LIVE・17LIVEの攻略法", "Pococha・TikTok LIVEの攻略法"),
    ("TAITAN PRO の場合はPococha・TikTok LIVE・17LIVEの3つを扱っているので、この3つの間",
     "TAITAN PRO の場合はPococha・TikTok LIVEの2つを扱っているので、この2つの間"),
    ("TAITAN PRO は Pococha・TikTok LIVE・17LIVE を扱っているため、この3つの間",
     "TAITAN PRO は Pococha・TikTok LIVE を扱っているため、この2つの間"),
    ("サポートを受けながら始めたい方は、この3つの中から選ぶ", "サポートを受けながら始めたい方は、この2つの中から選ぶ"),
    ("サポートを受けながら始めたい方はこの3つから選ぶ", "サポートを受けながら始めたい方はこの2つから選ぶ"),
    ("アプリ選びの時点で迷っている（Pococha／TikTok LIVE／17LIVE）",
     "アプリ選びの時点で迷っている（Pococha／TikTok LIVE）"),
]

# 内部リンクのアンカーテキスト（記事タイトル）。タイトルを変えた2本はリンク側も直す。
TITLE_FIXES = [
    ("ライブ配信アプリの掛け持ちはアリ？ナシ？｜Pococha・TikTok LIVE・17LIVEを併用する前に読む記事",
     "ライブ配信アプリの掛け持ちはアリ？ナシ？｜Pococha・TikTok LIVEを併用する前に読む記事"),
    ("17LIVE・Pococha・TikTok LIVEどれがいい？性格と目的で選ぶ配信アプリ比較【2026年】",
     "PocochaとTikTok LIVEどっちが向いてる？性格と生活リズムで選ぶ配信アプリ診断【2026年】"),
]


# ── md 1行 → 公開本文での素テキスト ───────────────────────────
def md_text(line, keep_number=False):
    s = re.sub(r"^#{1,6}\s*", "", line)
    s = re.sub(r"^[-*]\s+", "", s)
    s = re.sub(r"^\s*\*\s+", "", s)
    if not keep_number:
        s = re.sub(r"^\d+\.\s+", "", s)
    s = s.replace("**", "")
    return s.strip()


def minimal_diff(a, b):
    """a→b で実際に変わった最小部分を (before, after) で返す。"""
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    j = 0
    while j < min(len(a), len(b)) - i and a[len(a) - 1 - j] == b[len(b) - 1 - j]:
        j += 1
    return a[i:len(a) - j], b[i:len(b) - j]


def table_pub_text(lines, i):
    """md のテーブル行 i を、note公開側の `見出し1: セル1 ／ 見出し2: セル2` 形に直す。"""
    if not lines[i].strip().startswith("|"):
        return None
    head = None
    for j in range(i - 1, -1, -1):
        l = lines[j].strip()
        if not l.startswith("|"):
            break
        if re.fullmatch(r"\|[\s:|-]+\|", l):          # |---|---| の1つ上がヘッダ
            head = lines[j - 1] if j > 0 else None
            break
    if not head:
        return None
    cells = lambda l: [c.strip().replace("**", "") for c in l.strip().strip("|").split("|")]
    h, c = cells(head), cells(lines[i])
    if len(h) != len(c):
        return None
    return " ／ ".join(f"{a}: {b}" for a, b in zip(h, c) if a or b)


def pub_candidates(lines, i):
    """md 1行 → 公開本文でありうる素テキストの候補（先に来るものを優先）"""
    raw = lines[i]
    t = md_text(raw)
    out = []
    tb = table_pub_text(lines, i)
    if tb:
        out.append(tb)
    if raw.lstrip().startswith("###"):
        out.append("■ " + md_text(raw, keep_number=True))
        out.append("■ " + t)
    out.append(md_text(raw, keep_number=True))
    out.append(t)
    return [x for x in out if x]


_OPS_CACHE = {}


def build_ops():
    """{note_key: {"file":…, "reps":[(before,after)…], "dels":[[候補…]…]}}"""
    if _OPS_CACHE:
        return _OPS_CACHE
    km = json.load(open(os.path.join(BASE_DIR, "data", "note_key_map.json"), encoding="utf-8"))
    num2key = {str(int(k)) if k.isdigit() else k: v["key"] for k, v in km.items()}
    changed = subprocess.run(
        ["git", "diff", "--name-only", BASE_COMMIT, "HEAD", "--", "blog/articles_note/"],
        capture_output=True, text=True, cwd=BASE_DIR).stdout.split("\n")
    ops = {}
    for f in changed:
        if not f.endswith(".md"):
            continue
        path = os.path.join(BASE_DIR, f)
        if not os.path.exists(path):
            continue                      # 削除した記事
        num = os.path.basename(f).split("_")[0]
        num = str(int(num)) if num.isdigit() else num
        key = num2key.get(num)
        if not key or key in SKIP_KEYS:
            continue
        old_all = subprocess.run(["git", "show", f"{BASE_COMMIT}:{f}"],
                                 capture_output=True, text=True, cwd=BASE_DIR).stdout.split("\n")
        new_all = open(path, encoding="utf-8").read().split("\n")
        oi = [i for i, l in enumerate(old_all) if l.strip()]
        ni = [i for i, l in enumerate(new_all) if l.strip()]
        old = [old_all[i] for i in oi]
        new = [new_all[i] for i in ni]
        reps, dels = [], []

        def add_rep(a_raw, b_raw):
            bef, aft = minimal_diff(md_text(a_raw), md_text(b_raw))
            if bef:
                reps.append((bef, aft))

        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            A_idx, B_idx = oi[i1:i2], ni[j1:j2]
            A = [old_all[i] for i in A_idx]
            B = [new_all[i] for i in B_idx]
            if len(A) == len(B):
                for a_raw, b_raw in zip(A, B):
                    add_rep(a_raw, b_raw)
                continue
            # 行数が変わるブロック：似ている行どうしを先に対応づけ、余ったa行を削除にする
            used = set()
            for b_raw in B:
                best, best_r = None, 0.0
                for k, a_raw in enumerate(A):
                    if k in used:
                        continue
                    r = difflib.SequenceMatcher(None, md_text(a_raw), md_text(b_raw)).ratio()
                    if r > best_r:
                        best, best_r = k, r
                if best is not None and best_r >= 0.6:
                    used.add(best)
                    if md_text(A[best]) != md_text(b_raw):
                        add_rep(A[best], b_raw)
            for k, a_raw in enumerate(A):
                if k not in used:
                    dels.append(pub_candidates(old_all, A_idx[k]))
        # 長い置換から先に当てる（短い汎用ルールに食われないように）／重複は落とす
        seen = set()
        reps = [r for r in sorted(reps, key=lambda r: -len(r[0]))
                if not (r in seen or seen.add(r))]
        if reps or dels:
            ops[key] = {"file": os.path.basename(f), "num": num, "reps": reps, "dels": dels}
    # ローカル差分が無くても、公開側の定型と死にリンクで直る記事があるので全記事を対象にする
    for num, v in km.items():
        k = v["key"]
        if k in SKIP_KEYS:
            continue
        ops.setdefault(k, {"file": f"(公開のみ) {v.get('title','')[:24]}", "num": num,
                           "reps": [], "dels": []})
    for k, mo in MANUAL_OPS.items():
        if k in ops:
            ops[k]["reps"] = mo["reps"] + ops[k]["reps"]
            ops[k]["dels"] = mo["dels"] + ops[k]["dels"]
    _OPS_CACHE.update(ops)
    return ops


# ── 公開HTMLへの適用 ────────────────────────────────────
RE_EL = re.compile(r"<(?:p|h2|h3)\b[^>]*>.*?</(?:p|h2|h3)>", re.S)
RE_TAG = re.compile(r"<[^>]+>")


def replace_in_html(body, bef, aft):
    """HTMLタグを無視した素テキスト上で bef→aft を置換する。

    note の本文は `<strong>Pococha・TikTok LIVE・17LIVE</strong>の3つ` のように
    直したい範囲がタグをまたぐ。素の str.replace では当たらないので、
    テキスト片だけを連結した view の上で探し、**最後にかかった片へ aft を寄せる**
    （↑の例なら strong の中は `Pococha・TikTok LIVE`、外が `の2つ` になる）。
    """
    hits = 0
    while True:
        parts, pos = [], 0
        for m in RE_TAG.finditer(body):
            if m.start() > pos:
                parts.append([False, body[pos:m.start()]])
            parts.append([True, m.group(0)])
            pos = m.end()
        if pos < len(body):
            parts.append([False, body[pos:]])
        spans, o = [], 0
        for i, pr in enumerate(parts):
            if pr[0]:
                continue
            spans.append((o, o + len(pr[1]), i))
            o += len(pr[1])
        plain = "".join(pr[1] for pr in parts if not pr[0])
        k = plain.find(bef)
        if k < 0:
            return body, hits
        end = k + len(bef)
        aff = [(a, b, i) for (a, b, i) in spans if b > k and a < end]
        for n, (a, b, i) in enumerate(aff):
            txt = parts[i][1]
            lo, hi = max(k, a) - a, min(end, b) - a
            ins = aft if n == len(aff) - 1 else ""
            parts[i][1] = txt[:lo] + ins + txt[hi:]
        body = "".join(pr[1] for pr in parts)
        hits += 1


def _plain(el):
    return _html.unescape(re.sub(r"<[^>]+>", "", el)).strip()


def apply_ops(body, op, report=None):
    new = body
    # 1) 削除：候補のどれかと素テキストが一致する要素（包む <li> があればそれごと）を落とす
    for cands in op["dels"]:
        hit = None
        for m in RE_EL.finditer(new):
            if _plain(m.group(0)) in cands:
                hit = m
                break
        if not hit:
            if report is not None:
                report.append(("del-miss", cands[0]))
            continue
        st, en = hit.span()
        li = new.rfind("<li", 0, st)
        if li != -1 and new[li:st].strip().startswith("<li") and new[en:en + 5] == "</li>":
            st, en = li, en + 5
        new = new[:st] + new[en:]
    # 2) 置換：記事ごとの最小差分 → 公開側だけにある定型 の順に当てる
    for bef, aft in op["reps"]:
        new, n = replace_in_html(new, bef, aft)
        if n == 0 and report is not None:
            report.append(("rep-miss", bef))
    for bef, aft in GLOBAL_REPS:      # 当たらないのが普通なので miss は報告しない
        new, _ = replace_in_html(new, bef, aft)
    # 3) 削除した記事への内部リンクを <li> ごと落とす
    for dk in DEAD_KEYS:
        while True:
            m = re.search(r"<li>(?:(?!</li>).)*?/n/" + dk + r"(?:(?!</li>).)*?</li>", new, re.S)
            if not m:
                break
            new = new[:m.start()] + new[m.end():]
    # 4) 内部リンクのアンカーテキスト（タイトルを変えた2本）
    for bef, aft in TITLE_FIXES:
        new = new.replace(bef, aft)
    # 5) 空になった <li>/<ul> の掃除
    new = re.sub(r"<li>\s*</li>", "", new)
    new = re.sub(r"<ul[^>]*>\s*</ul>", "", new)
    new = re.sub(r"<strong>\s*</strong>", "", new)
    if report is not None:
        t = re.sub(r"<[^>]+>", "", new)
        for m in re.finditer(r"[^。<>]{0,45}17LIVE[^。<>]{0,45}", t):
            h = m.group(0)
            if re.search(r"取り扱|取扱|対応|サポートできる|専門|扱って", h):
                report.append(("own-left", re.sub(r"\s+", " ", h)[:110]))
        for dk in DEAD_KEYS:
            if dk in new:
                report.append(("dead-left", dk))
    return new


def transform(key, body, _ops_cache={}):
    if not _ops_cache:
        _ops_cache.update(build_ops())
    op = _ops_cache.get(key)
    if not op:
        return None
    new = apply_ops(body, op)
    # 本文が同じでも、タグから17LIVE系を外したときは出し直す必要がある
    if new == body and not _TAGS_CHANGED["flag"]:
        return None
    return new


# 公開側のハッシュタグにも 17LIVE 系が残る。publish_one は「いま付いているタグ」を
# そのまま再送するので、get_note を包んで取り除き、足りない枠は中立な語で埋める。
TAG_NG = re.compile(r"^#?(17\s?live|17ライブ|１７ライブ|イチナナ|いちなな)$", re.I)
TAG_FILL = ["配信アプリ", "ライブ配信", "ライバー", "配信初心者"]


_TAGS_CHANGED = {"flag": False}


def _strip_ng_tags(d):
    hs = d.get("hashtag_notes") or []
    kept = [h for h in hs if not TAG_NG.match(h["hashtag"]["name"])]
    if len(kept) == len(hs):
        return d
    _TAGS_CHANGED["flag"] = True
    have = {h["hashtag"]["name"].lstrip("#") for h in kept}
    for f in TAG_FILL:
        if len(kept) >= len(hs):
            break
        if f not in have:
            kept.append({"hashtag": {"name": f}})
            have.add(f)
    print(f"  tags: 17LIVE系を除去 {len(hs)} -> {len(kept)}")
    d["hashtag_notes"] = kept
    return d


def publish_one(key):
    orig = _lm.verify
    orig_get = _lm.get_note
    _TAGS_CHANGED["flag"] = False
    _lm.get_note = lambda *a, **k: _strip_ng_tags(orig_get(*a, **k))

    def _verify(k):
        """公開しなおした本文にもう一度 apply_ops を当てて「もう変わらない」ことを見る。

        置換前の文字列を探す方式は使えない。残す方針の比較文（例: 37 の
        「ギフトで跳ねる（TikTok LIVE・17LIVE）」）が置換キーと部分一致して
        毎回falseで落ちるため。冪等かどうかで見るのがいちばん素直で漏れない。
        """
        d = orig(k)
        op = build_ops().get(k)
        if op and apply_ops(d["body"], op) != d["body"]:
            raise RuntimeError("verify失敗: まだ当てられる差分が残っている")
        left = [dk for dk in DEAD_KEYS if dk in d["body"]]
        if left:
            raise RuntimeError(f"verify失敗: 削除した記事へのリンクが残存 {left}")
        tags = [h["hashtag"]["name"] for h in d.get("hashtag_notes", [])]
        ng = [t for t in tags if TAG_NG.match(t)]
        if ng:
            raise RuntimeError(f"verify失敗: 17LIVE系タグが残存 {ng}")
        return d

    _lm.verify = _verify
    try:
        return _lm.publish_one(key, transform, expect_marker=None,
                               title_fn=lambda k, t: TITLE_MAP.get(k))
    finally:
        _lm.verify = orig
        _lm.get_note = orig_get


def dry_run():
    ops = build_ops()
    s = req_session()
    miss_total = 0
    print(f"対象 {len(ops)} 本\n")
    for i, (key, op) in enumerate(ops.items(), 1):
        try:
            d = get_note(s, key, draft=False)
        except Exception as e:
            print(f"[{i}] {key} GET失敗: {e}")
            continue
        report = []
        new = apply_ops(d["body"], op, report)
        n = len(op["reps"]) + len(op["dels"])
        tag = "変更なし" if new == d["body"] else f"置換{len(op['reps'])} 削除{len(op['dels'])}"
        print(f"[{i:>3}] {op['num']:>3} {key} {tag}  {d['name'][:34]}")
        for kind, t in report:
            miss_total += 1
            print(f"        ⚠ {kind}: {t[:100]}")
        time.sleep(0.35)
    print(f"\n当たらなかった箇所: {miss_total}")


def _log():
    return json.load(open(LOG_FILE, encoding="utf-8")) if os.path.exists(LOG_FILE) else {}


def run_all():
    ops = build_ops()
    log = _log()
    ok = skip = fail = 0
    keys = list(ops)
    for i, key in enumerate(keys, 1):
        if log.get(key) in ("ok", "skip"):
            continue
        print(f"[{i}/{len(keys)}] {key} ({ops[key]['file']})")
        try:
            log[key] = publish_one(key)
            ok += log[key] == "ok"
            skip += log[key] == "skip"
        except Exception as e:
            print(f"  [FAIL] {e}")
            log[key] = f"fail: {e}"
            fail += 1
        json.dump(log, open(LOG_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        time.sleep(8)
    print(f"[DONE] ok={ok} skip={skip} fail={fail}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__); raise SystemExit(1)
    if a[0] == "--dry-run":
        dry_run()
    elif a[0] == "--all":
        run_all()
    elif a[0] == "--verify":
        print(json.dumps(_lm.verify(a[1]), ensure_ascii=False)[:400])
    else:
        print(__doc__); raise SystemExit(1)
