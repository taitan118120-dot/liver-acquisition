#!/usr/bin/env python3
"""公開中のnote記事から「ギフトと結びついた罰ゲーム・体を張る企画」を外す（2026-10-23）。

■ なぜ
  TikTok LIVE 公式の「LIVE収益化ガイドライン」は、ギフトのための危険な行為・物の破壊・
  屈辱的な行為や、「ギフトをくれたら◯◯する」という取引を収益化制限の対象にしている
  （正本 data/tiktok_live_guidelines.md）。次の2本はそれを盛り上げのコツとして勧めていた。

■ 直す箇所（ユーザー指示 2026-10-23）
  #99  ndb871675e2fa  参加型企画のリスト「数字で罰ゲーム」「数字に応じて腕立て。体を張ると
                      盛り上がる」、所属特典の箇条書き「罰ゲーム・チャレンジ企画を投げ銭
                      （ギフト）につなげる仕込み方」。企画のコツの直後にTikTokの注意を1段落足す
  #181 neaf9e8873dd9  バトル予告の例文「負けても罰ゲームは軽めです」

  #99 の「爆発チャレンジ」は取引でも屈辱的な行為でもないので残す。

使い方:
  python3 note_gift_penalty_fix_20261023.py --dry-run   # 置換結果を出す（GETのみ）
  python3 note_gift_penalty_fix_20261023.py --bodies    # 公開本文を直す
  python3 note_gift_penalty_fix_20261023.py --verify    # 公開API（非ログイン）で確認
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
LOG_FILE = os.path.join(BASE_DIR, "data", "note_gift_penalty_fix_log.json")

# 検証は**ログアウト状態の公開API**で見る（cookie付きGETは下書き側を混ぜて返す）。
PUBLIC_API = "https://note.com/api/v3/notes/{key}"
PUBLIC_HEADERS = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache",
                  "Pragma": "no-cache"}

# note は保存のたびに段落へ name/id を振り直し、強調は <strong> と ** で揺れる。
TAG = r"(?:</?[a-zA-Z][^>]*>|\*\*)*"


def _rx(*parts):
    return re.compile("".join(parts))


_NOTE_P = ("<p name=\"7c1e5a3e-2b8d-4f0a-9a61-3d2f8e0b9c41\" "
           "id=\"7c1e5a3e-2b8d-4f0a-9a61-3d2f8e0b9c41\">"
           "ひとつ注意です。TikTok LIVEでは、ギフトと引き換えの罰ゲームや、ギフトのために"
           "体を張る・恥をかくような企画は、公式のLIVE収益化ガイドラインに触れることがあります。"
           "企画はギフトの見返りではなく、<strong>その場のみんなで楽しむもの</strong>"
           "として組んでください。</p>")

RULES = {
    # ── #99 枠を盛り上げる技術 ─────────────────────────────
    "ndb871675e2fa": [
        (_rx(r"<strong>数字で罰ゲーム</strong>：目標数字に届いたら（or 届かなかったら）"
             r"配信者が罰ゲーム。「達成したら〇〇やります」"),
         "<strong>みんなで目指す目標</strong>：その日の目標を最初に共有して、"
         "届いたら一緒にお祝いする。届かなくても「また次回」で明るく終える"),
        (_rx(r"<strong>筋トレ・エクササイズ</strong>：数字に応じて腕立て。体を張ると盛り上がる"),
         "<strong>一緒にストレッチ</strong>：休憩がてら、リスナーさんと同じ動きを1〜2分。"
         "ギフトの数とは結びつけない"),
        # 企画のコツの段落の直後に注意を1段落足す（2回当てないよう、未挿入のときだけ）
        (_rx(r"(あなたが何もしなくても枠が回り始めます。</p>)(?!<p name=\"7c1e5a3e)"),
         r"\1" + _NOTE_P),
        (_rx(r"罰ゲーム・チャレンジ企画を", TAG, r"投げ銭（ギフト）につなげる", TAG, r"仕込み方"),
         "チャレンジ企画を<strong>リスナーさんが自分から参加したくなる形</strong>に組み立てる仕込み方"),
    ],
    # ── #181 TikTok LIVE バトルで負けが続くとき ────────────────
    "neaf9e8873dd9": [
        (_rx(r"「今日は1回だけ対戦します。負けても罰ゲームは軽めです」"),
         "「今日は1回だけ対戦します。勝っても負けても、終わったらゆっくり話しましょう」"),
    ],
}

# 反映確認に使う「もう本文に出てはいけない」文字列（記事ごと）。
LEFTOVERS = {
    "ndb871675e2fa": ["数字で罰ゲーム", "数字に応じて腕立て", "体を張ると盛り上がる",
                      "投げ銭（ギフト）につなげる"],
    "neaf9e8873dd9": ["罰ゲームは軽め"],
}

# 足した段落が入っていること（記事ごと）。
MUST = {
    "ndb871675e2fa": ["公式のLIVE収益化ガイドラインに触れることがあります"],
    "neaf9e8873dd9": ["終わったらゆっくり話しましょう"],
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
    return ([w for w in LEFTOVERS[key] if w in text]
            + [f"(欠落){w}" for w in MUST[key] if w not in text])


def _load(path):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except Exception:
            pass
    return {}


def backup(key, note, tag="pre_gift_penalty_20261023"):
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
