#!/usr/bin/env python3
"""公開済みnote記事の確定ファクト（所属人数・還元率）を新表記へ一括更新する。

2026-07-21ユーザー指示: 所属「150人以上」→「200名」／還元率「100%」→「100%+α」。
「+α」の中身は断定しない。「手数料なし」表記は引き続き禁止。

機構は note_leadmagnet_publish.py と同じ（Chrome cookie + Playwright + reCAPTCHA + PUT →
ensure_tags でタグ復元 → eyecatch検証）。公開中の本文を取得して外科的に置換するので、
ローカルmdがstaleでも公開側だけの修正は巻き戻らない。

使い方:
  python3 note_facts_publish.py --dry-run      # 置換内容の確認のみ（GETだけ）
  python3 note_facts_publish.py --all          # 対象記事を順次更新（再開可能）
  python3 note_facts_publish.py --verify <key> # 検証のみ
"""
import json
import os
import re
import sys
import time

from note_cta_publish import get_note, req_session
from note_leadmagnet_publish import publish_one, verify

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TARGETS_FILE = os.path.join(BASE_DIR, "data", "note_fact_update_targets_2026-07-21.md")
LOG_FILE = os.path.join(BASE_DIR, "data", "facts_update_log.json")

# 所属人数の置換。長い表現から順に適用する。
MEMBER_RULES = [
    (r"Pococha・TikTok合わせて150(?:人|名)以上", "Pococha・TikTok合わせて200名"),
    (r"Pococha・TikTok合わせて150名", "Pococha・TikTok合わせて200名"),
    (r"所属ライバー数\s*／\s*TAITAN PRO:\s*150(?:人|名)以上", "所属ライバー数 ／ TAITAN PRO: 200名"),
    (r"所属ライバー150(?:人|名)以上", "所属ライバー200名"),
    (r"所属ライバー150(?:人|名)", "所属ライバー200名"),
    (r"所属150(?:人|名)以上", "所属200名"),
    (r"150(?:人|名)以上が所属", "200名が所属"),
    (r"150(?:人|名)以上のライバーが所属", "200名のライバーが所属"),
    (r"150(?:人|名)以上のライバー", "200名のライバー"),
    (r"150(?:人|名)以上を(育て|抱え|見て|マネジメント)", r"200名を\1"),
    (r"150(?:人|名)所属", "200名所属"),
    (r"150名所属する", "200名所属する"),
    (r"現在150名所属", "現在200名所属"),
    (r"150(?:人|名)以上", "200名"),
]

# 還元率の置換（既に +α のものは触らない）
RATE_RULES = [
    (r"還元率は100%(?!\s*\+\s*α|＋α)", "還元率は100%+α"),
    (r"還元率100%(?!\s*\+\s*α|＋α)", "還元率100%+α"),
    (r"還元率100％(?!\s*\+\s*α|＋α)", "還元率100％+α"),
    (r"還元率が100%(?!\s*\+\s*α|＋α)", "還元率が100%+α"),
]

# 統計・サンプル数として150という数字を使っている文脈は、過去の分析実績の改ざんに
# なるため自動置換しない。該当したらレポートしてユーザー判断に回す。
STAT_CONTEXT = re.compile(
    r"(実データ|中央値|集計|横断分析|データ横断|分析した|の内訳|%|％|平均値|"
    r"リスナー|コアファン|うち月収|人中|名中|データから)"
)


def _apply(rules, text):
    hits = []
    for pat, rep in rules:
        def _sub(m):
            hits.append((m.group(0), re.sub(pat, rep, m.group(0))))
            return re.sub(pat, rep, m.group(0))
        text = re.sub(pat, _sub, text)
    return text, hits


def classify(html):
    """自動置換する箇所と、統計文脈で保留する箇所を仕分ける。"""
    text = re.sub(r"<[^>]+>", "", html)
    held = []
    for m in re.finditer(r".{0,60}150\s*(?:人|名).{0,60}", text):
        frag = m.group(0)
        # 所属数の定型表現に該当するものは自動置換対象なので保留にしない
        if re.search(r"(所属|抱え|育て|マネジメント|在籍|合わせて)", frag):
            continue
        if STAT_CONTEXT.search(frag):
            held.append(frag.replace("\n", " "))
    return held


def transform_facts(key, html):
    new, member_hits = _apply(MEMBER_RULES, html)
    new, rate_hits = _apply(RATE_RULES, new)
    if new == html:
        return None
    return new


def load_targets():
    keys = []
    with open(TARGETS_FILE, encoding="utf-8") as f:
        for line in f:
            m = re.search(r"https://note\.com/taitan_118/n/(\w+)", line)
            if m:
                keys.append(m.group(1))
    return keys


def dry_run():
    s = req_session()
    keys = load_targets()
    changed = held_articles = 0
    all_held = []
    for i, key in enumerate(keys, 1):
        try:
            d = get_note(s, key, draft=False)
        except Exception as e:
            print(f"[{i}] {key} GET失敗: {e}")
            continue
        html = d["body"]
        new = transform_facts(key, html)
        held = classify(html)
        title = d["name"][:40]
        if new:
            changed += 1
            before = re.sub(r"<[^>]+>", "", html)
            after = re.sub(r"<[^>]+>", "", new)
            n_m = len(re.findall(r"150\s*(?:人|名)", before)) - len(re.findall(r"150\s*(?:人|名)", after))
            n_r = len(re.findall(r"還元率(?:は|が)?100[%％](?!\+α)", before)) - \
                  len(re.findall(r"還元率(?:は|が)?100[%％](?!\+α)", after))
            print(f"[{i}] {key} {title} 人数{n_m}件 還元率{n_r}件")
        else:
            print(f"[{i}] {key} {title} 変更なし")
        if held:
            held_articles += 1
            all_held.append((key, d["name"], held))
        time.sleep(0.4)
    print(f"\n更新対象 {changed}本 / 保留（統計文脈）ありの記事 {held_articles}本")
    print("\n=== 統計文脈で自動置換しない箇所 ===")
    for key, name, held in all_held:
        print(f"\n- {name}\n  https://note.com/taitan_118/n/{key}")
        for h in held[:4]:
            print(f"    …{h}…")


def _load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def run_all():
    keys = load_targets()
    log = _load_log()
    ok = skip = fail = 0
    for i, key in enumerate(keys, 1):
        if log.get(key) in ("ok", "skip"):
            continue
        print(f"[{i}/{len(keys)}] {key}")
        try:
            log[key] = publish_one(key, transform_facts)
            ok += log[key] == "ok"
            skip += log[key] == "skip"
        except Exception as e:
            print(f"  [FAIL] {e}")
            log[key] = f"fail: {e}"
            fail += 1
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=1)
        time.sleep(8)
    print(f"[DONE] ok={ok} skip={skip} fail={fail}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__); raise SystemExit(1)
    if args[0] == "--dry-run":
        dry_run()
    elif args[0] == "--verify":
        for k in args[1:]:
            print(f"[verify {k}]"); verify(k)
    elif args[0] == "--all":
        run_all()
    else:
        for k in args:
            print(f"[publish {k}]"); publish_one(k, transform_facts)
