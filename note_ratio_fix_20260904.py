#!/usr/bin/env python3
"""公開中のnote記事から「出典のない割合統計（後置形）」を落とす（2026-09-04）。

■ なぜ今まで見つからなかったか
  facts_patterns.ratio_violations は割合を3系統で見ていたが、
  **割合が主語の後ろに来る形**（「利用者の約40%は25〜35歳」）はどれにも当たらない:
    ① 離脱/成功語の近接 … 近くに「辞め/消え/成功」等が無いと出ない
    ② RATIO_SUBJECT     … `N%の(ライバー|人|…)` ＝割合が主語の**前**しか見ない
    ③ RATIO_PREDICATE   … 「割」限定
  投稿済みIG ig_auto_021 の本文がこの形で素通りしていたのが発端。
  同じコミットで facts_patterns に RATIO_POSTFIX を足したところ、
  公開中のNote記事5本が新たに赤になった（＝ずっと出典なしで公開されていた）。

■ 直す6箇所（ユーザー承認済み 2026-09-04）
  #45 n72ac7218ef26  「全体の12%だけ」「残りの88%は時給1,000円を切る」
  #46 n29aafb234cec  「200名中、上位層の43%は人見知り」
  #51 n205ef04edcbb  「税務調査で揉めるライバーの99%は」
  #54 nf58c6a743c2a  「コメントの99%は応援、1%が攻撃」「練習配信を5回した人の95%が」
  #77 n393f5e092338  「C帯から抜けられない人の99%は」

  #45 と #46 は **自社の内部データ**（「うちの事務所200名を集計した」）だが、
  読者からは裏が取れず集計方法も公開していないので、他の捏造数字と同じ扱いに
  する——とユーザーが判断（[[feedback_dont_make_up_numbers]]）。

■ ついでに直したもの（番犬は当たらないが同種）
  #54「95%の不安は実害がほぼない」…`の`が前に無いので RATIO_POSTFIX には
  当たらないが、同じ記事の中で片方だけ数字を残すと不整合になる。
  #54「人間の脳は1%のネガティブを99%のポジティブの100倍記憶」も同様に落とす。

使い方:
  python3 note_ratio_fix_20260904.py --dry-run   # 置換結果を出す（GETのみ）
  python3 note_ratio_fix_20260904.py --bodies    # 公開本文を直す
  python3 note_ratio_fix_20260904.py --verify    # 公開API（非ログイン）で確認
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

BACKUP_DIR = os.path.join(BASE_DIR, "data", "note_body_backup")
LOG_FILE = os.path.join(BASE_DIR, "data", "note_ratio_fix_log.json")

# 検証は**ログアウト状態の公開API**で見る（cookie付きGETは下書き側を混ぜて返す）。
PUBLIC_API = "https://note.com/api/v3/notes/{key}"
PUBLIC_HEADERS = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache",
                  "Pragma": "no-cache"}

# note は保存のたびに段落へ name/id を振り直し、強調は <strong> と ** で揺れる。
TAG = r"(?:</?[a-zA-Z][^>]*>|\*\*)*"


def _rx(*parts):
    return re.compile("".join(parts))


RULES = {
    # ── #45 ライバーの時給 ─────────────────────────────────
    # 「12%」「88%」は事務所の内部集計。読者から検証できないので数字を落とし、
    # 「ごく一部」「大半」という状態の記述に寄せる（主張の向きは変わらない）。
    "n72ac7218ef26": [
        (_rx(r"時給3,000円のライバーは、実在します。でも全体の12%だけでした"),
         "時給3,000円のライバーは、実在します。でも、そこに届いている人は"
         "ごく一部です"),
        (_rx(r"うちの事務所200名の配信時間と報酬を全部集計して出した数字です。"
             r"残りの88%は時給1,000円を切るか、そもそもゼロでした。"),
         "うちの事務所200名の配信時間と報酬を見てきた実感です。"
         "大半は時給1,000円を切るか、そもそもゼロでした。"),
    ],
    # ── #46 1年続くライバーに共通する性格 ────────────────────
    "n29aafb234cec": [
        (_rx(r"A. 200名中、上位層の43%は「人見知り」と自己申告していました。"),
         "A. うちの事務所でも、上位層に「人見知り」と自己申告する人は"
         "珍しくありません。"),
    ],
    # ── #51 ライバー経費完全リスト75項目 ─────────────────────
    "n205ef04edcbb": [
        (_rx(r"税務調査で揉めるライバーの99%は、"),
         "税務調査で揉めるライバーは、たいてい"),
    ],
    # ── #54 緊張克服メンタル術 ───────────────────────────────
    # 見出しの「99:1の法則」は数字そのものが名前になっているので見出しごと変える。
    "nf58c6a743c2a": [
        (_rx(r"「99:1の法則」を覚えておく"), "「ほとんどは応援」だと覚えておく"),
        (_rx(r"コメントの99%は応援、1%が攻撃", TAG,
             r"。それなのに、", TAG,
             r"人間の脳は1%のネガティブを99%のポジティブの100倍記憶", TAG,
             r"します（ネガティビティ・バイアス）。"),
         "コメントのほとんどは応援で、攻撃はごく一部</strong>。それなのに、"
         "<strong>人間の脳はネガティブなひと言のほうを強く記憶</strong>します"
         "（ネガティビティ・バイアス）。"),
        # 上の置換で「99人の応援者」だけが残ると数字の出どころが消える
        (_rx(r"画面を一度引いて「99人の応援者」を可視化"),
         "画面を一度引いて「応援してくれている人たち」を可視化"),
        (_rx(r"95%の不安は「実害がほぼない」ことに気づきます"),
         "ほとんどの不安は「実害がほぼない」ことに気づきます"),
        (_rx(r"「練習配信」を5回した人の95%が本配信に進めて"),
         "「練習配信」を何回か重ねた人は、そのまま本配信に進めて"),
        # 記事末尾のまとめリストにも見出し名が引用されている（本文だけ直すと残る）
        (_rx(r"。99:1の法則を忘れない"), "。ほとんどは応援だと忘れない"),
    ],
    # ── #77 C帯御新規攻略 ────────────────────────────────────
    "n393f5e092338": [
        (_rx(r"C帯から抜けられない人の99%は、"),
         "C帯から抜けられない人のほとんどは、"),
    ],
}

# 反映確認に使う「もう本文に出てはいけない」文字列（記事ごと）。
LEFTOVERS = {
    "n72ac7218ef26": ["全体の12%", "残りの88%"],
    "n29aafb234cec": ["上位層の43%"],
    "n205ef04edcbb": ["ライバーの99%"],
    "nf58c6a743c2a": ["コメントの99%", "99:1の法則", "95%の不安", "人の95%が",
                      "99人の応援者"],
    "n393f5e092338": ["ない人の99%"],
}


def fetch_public(key):
    r = requests.get(PUBLIC_API.format(key=key), headers=PUBLIC_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()["data"]


def transform(key, html):
    """RULES を順に当てる。1つも当たらなければ None（＝publish_one が skip する）。"""
    if html is None:
        return None
    out, hit = html, 0
    for rx, repl in RULES[key]:
        out, n = rx.subn(repl, out)
        hit += n
    return out if hit else None


def rule_hits(key, html):
    return [(rx.pattern[:46], len(rx.findall(html))) for rx, _ in RULES[key]]


def leftovers(key, text):
    return [w for w in LEFTOVERS[key] if w in text]


def _load(path):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except Exception:
            pass
    return {}


def backup(key, note, tag="pre_ratio_20260904"):
    """PUT前の本文を退避する（既存のバックアップは上書きしない）。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"{key}.{tag}.json")
    if not os.path.exists(path):
        json.dump({"key": key, "title": note["name"], "body": note["body"],
                   "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                  open(path, "w"), ensure_ascii=False, indent=1)
    return path


def dry_run():
    for key in RULES:
        d = fetch_public(key)
        body = d["body"]
        new = transform(key, body)
        print(f"\n=== {key} {d['name'][:40]}")
        for pat, n in rule_hits(key, body):
            print(f"  [{'OK ' if n else 'MISS'}] x{n}  {pat}")
        print(f"  body {len(body)} -> {len(new) if new else '(変更なし)'}")
        print(f"  残存: {leftovers(key, new if new else body) or 'なし'}")


def publish(key):
    from note_leadmagnet_publish import publish_one

    d = fetch_public(key)
    print(f"  backup: {os.path.relpath(backup(key, d), BASE_DIR)}")
    r = publish_one(key, transform, expect_marker=None)
    if r == "skip":
        print("  変更なし（既に修正済み）")
        return r
    # publish_one の verify は cookie 付きGET。読者が見るのはログアウト側。
    for attempt in range(4):
        time.sleep(6)
        dv = fetch_public(key)
        left = leftovers(key, dv["body"])
        tags = len(dv.get("hashtag_notes", []))
        print(f"  [公開API {attempt + 1}] 残存={left or 'なし'} tags={tags} "
              f"eyecatch={'OK' if dv.get('eyecatch') else 'MISSING!'}")
        if not left:
            if tags == 0:
                raise RuntimeError("タグが0のまま（note_tag_guard.ensure_tags 要確認）")
            return r
    raise RuntimeError(f"公開APIで確認できない（残={left}）")


def verify():
    bad = 0
    for key in RULES:
        d = fetch_public(key)
        left = leftovers(key, d["body"])
        tags = len(d.get("hashtag_notes", []))
        print(f"  {key} {'OK' if not left else f'NG {left}'}  tags={tags} "
              f"eyecatch={'OK' if d.get('eyecatch') else 'MISSING!'} "
              f"{d['name'][:30]}")
        bad += bool(left)
    print(f"\n違反が残っている記事: {bad} 本")
    return bad


def main():
    args = sys.argv[1:]
    if "--verify" in args:
        sys.exit(1 if verify() else 0)
    if "--bodies" in args or [a for a in args if a.startswith("n")]:
        keys = [a for a in args if a.startswith("n") and not a.startswith("--")] \
            or list(RULES)
        log = _load(LOG_FILE)
        for i, key in enumerate(keys):
            print(f"\n=== [{i + 1}/{len(keys)}] {key}")
            try:
                log[key] = publish(key)
            except Exception as e:
                log[key] = f"error: {type(e).__name__}: {e}"
                print(f"  !! {log[key]}")
            json.dump(log, open(LOG_FILE, "w"), ensure_ascii=False, indent=1)
            time.sleep(3)
        print("\n", json.dumps(log, ensure_ascii=False, indent=1))
        return
    dry_run()


if __name__ == "__main__":
    main()
