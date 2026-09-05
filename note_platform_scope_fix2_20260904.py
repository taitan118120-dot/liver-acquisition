#!/usr/bin/env python3
"""公開中のnote記事から「取扱外プラットフォームへの誘導」を消す・第2弾（2026-09-04）。

note_platform_scope_fix_20260904.py は IRIAM / イリアム / SHOWROOM / ふわっち /
REALITY しか見ていなかった。そのため、同じ「おすすめ度つきで取扱外アプリへ読者を
送る」形が、パターン外の名前（TwitCasting・Bigo Live・ミラティブ・Hakuna・Mildom）
では素通りしていた。1弾の docstring 末尾「意図的に直していないもの」に実例が残って
いる。今回 facts_patterns.COMMON_NG_PATTERNS の取扱外パターンにこの5つを足したので、
実際に鳴った公開本文を1弾と同じ作法で直す。

対象4本（すべて1弾で IRIAM 分は直済み。残った非IRIAMの名前を今回落とす）:
  (a) 推奨・誘導＝直す
    - n56e9a993492d #1「ライバーの始め方」
        「おすすめ配信アプリ5選」の4番目に「TwitCasting（ツイキャス）… おすすめ度★★★☆☆」。
        1〜3番が Pococha / 17LIVE / TikTok LIVE（取扱3つ）で埋まっているので、
        4番の節を丸ごと落として見出しを「3選」に直す。
    - n4857a2f79084 #41「40代・50代」
        「最適な配信アプリ3選」の第3位が「ツイキャス」。見出しが3選なので枠は残し、
        取扱内の TikTok LIVE に差し替える（第1位 Pococha・第2位 17LIVE は1弾で確定済み）。
    - n6b2f4704cdcc #34「容姿」
        戦略1（ラジオ配信）の本文が「TwitCastingやHakunaなど、音声配信がメインの
        アプリもあります」。Pococha のラジオ配信に寄せる（1弾の #26/#10 と同じ言い換え）。
    - ndce8a9117fa4 #56「副業ライバーおすすめ」
        プラットフォーム比較の箇条書きに「Bigo Live: … 一気に稼ぎやすい」。
        導入文は1弾で Pococha・TikTok LIVE・17LIVE に直済みなので、箇条書きも
        その行を落として取扱3つに揃える。

  (b) 触らない（1弾の KEEP_AS_IS と同じ基準。比較表・一般論で名前が出るだけ）:
    - #33 ライブ配信アプリ徹底比較10選（記事の主題＋末尾に取扱3つの但し書きあり）
      … Mildom / BIGO LIVE / Hakuna の個別解説はここでは残す
    - #48 Pococha始め方（「17LIVEやIRIAM、ミラティブなど数ある…」の例示＋但し書きあり）
    - #60 スカウトDM運用（媒体別の文体表。ライバー誘導ではない）
    - #40 事務所の仕組み（「配信プラットフォーム（Pococha、17LIVE、IRIAMなど）」の例示）
    - #61 #53 #50 #23 #9（取扱3つの但し書きあり／#9 は正本）

作法は note_platform_scope_fix_20260904.py と同一:
  - 公開本文（HTML）とローカル原稿（Markdown）の両方に当てる。
  - 置換は完全一致・出現1回。要素ごと削る場合だけ cut_element / cut_span。
  - PUT の前に元本文を data/note_body_backup/<key>.json に退避。
  - 反映確認はログアウト状態の公開API（Cache-Control: no-cache）。PUT:200 は証拠にならない。

使い方:
  python3 note_platform_scope_fix2_20260904.py --plan     # 差分を出すだけ（GETのみ）
  python3 note_platform_scope_fix2_20260904.py --local    # ローカル原稿だけ直す
  python3 note_platform_scope_fix2_20260904.py --apply    # 公開本文を直す（PUT）
  python3 note_platform_scope_fix2_20260904.py --apply <key>…
  python3 note_platform_scope_fix2_20260904.py --verify   # 公開APIで再検品
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
LOG_FILE = os.path.join(BASE_DIR, "data", "note_platform_scope2_log.json")
ARTICLE_DIR = os.path.join(BASE_DIR, "blog", "articles_note")

PUBLIC_API = "https://note.com/api/v3/notes/{key}"
PUBLIC_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "application/json",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

BATCH = 8
BATCH_SLEEP = 25

# ── 差し替え表 ─────────────────────────────────────────────
# 形式は note_platform_scope_fix_20260904.py の FIXES と同じ。
#   html … 公開本文に当てる (旧, 新)。タグ属性を含まない部分文字列で書く
#   cut  … 要素ごと削る。("elem", アンカー, タグ名) / ("span", 先頭, 終端)
#   text … ローカル原稿（Markdown）に当てる
FIXES = {
    # ── #1 ライバーの始め方 ───────────────────────────────────
    # 「おすすめ配信アプリ5選」＝実体は4本（1 Pococha / 2 17LIVE / 3 TikTok LIVE /
    # 4 TwitCasting）。1〜3で取扱3つが埋まっているので、4番の節を丸ごと落として
    # 見出しを「3選」に直す。※3は1弾で IRIAM から差し替え済み。
    "n56e9a993492d": {
        "md": "01_ライバー始め方.md",
        "html": [("おすすめ配信アプリ5選【2026年版】", "おすすめ配信アプリ3選【2026年版】")],
        "cut": [("span",
                 "■ 4. TwitCasting（ツイキャス）— ラジオ配信・声だけOK",
                 "という方はここから。</p>")],
        "text": [
            ("## おすすめ配信アプリ5選【2026年版】", "## おすすめ配信アプリ3選【2026年版】"),
            ("### 4. TwitCasting（ツイキャス）— ラジオ配信・声だけOK\n\n"
             "**おすすめ度: ★★★☆☆**\n\n"
             "音声のみの配信でも人気を集められるプラットフォーム。"
             "「顔も出したくないし、イラストもない」という方はここから。\n\n", ""),
        ],
    },
    # ── #41 40代・50代からライバー ────────────────────────────
    # 「最適な配信アプリ3選」の第3位がツイキャス（第1位 Pococha・第2位 17LIVE は
    # 1弾で確定）。見出しが3選なので枠は残し、取扱内の TikTok LIVE に差し替える。
    # ツイキャス固有の売り（長時間トーク文化・機械が苦手でも安心）は TikTok LIVE の
    # 事実（拡散・フォロワー1,000人条件）に置き換える。
    "n4857a2f79084": {
        "md": "41_40代50代ライバー始め方.md",
        "html": [
            ("■ 第3位：ツイキャス | トーク力で勝負したい方向け",
             "■ 第3位：TikTok LIVE | 拡散力で新しいリスナーさんに届けたい方向け"),
            ("<strong>雑談・トーク配信</strong>に強みがある方はツイキャスもおすすめ。",
             "<strong>動画の拡散から配信を見てもらいたい方</strong>には"
             "TikTok LIVEが向いています。"),
            ("<strong>長時間トーク配信</strong>の文化がある",
             "<strong>ショート動画からLIVEへ</strong>人を呼び込める"),
            ("リスナーさんとの距離が近く、<strong>常連ファン</strong>ができやすい",
             "配信外でも投稿が積み上がり、"
             "<strong>過去の動画から新しいリスナーさんが来る</strong>"),
            ("操作がシンプルで<strong>機械が苦手な方でも安心</strong>",
             "配信の開始には<strong>フォロワー1,000人などの条件</strong>がある"),
        ],
        "text": [
            ("### 第3位：ツイキャス | トーク力で勝負したい方向け",
             "### 第3位：TikTok LIVE | 拡散力で新しいリスナーさんに届けたい方向け"),
            ("**雑談・トーク配信**に強みがある方はツイキャスもおすすめ。",
             "**動画の拡散から配信を見てもらいたい方**にはTikTok LIVEが向いています。"),
            ("- **長時間トーク配信**の文化がある",
             "- **ショート動画からLIVEへ**人を呼び込める"),
            ("- リスナーさんとの距離が近く、**常連ファン**ができやすい",
             "- 配信外でも投稿が積み上がり、**過去の動画から新しいリスナーさんが来る**"),
            ("- 操作がシンプルで**機械が苦手な方でも安心**",
             "- 配信の開始には**フォロワー1,000人などの条件**がある"),
        ],
    },
    # ── #34 ライバーに容姿は関係ない ──────────────────────────
    # 戦略1（ラジオ配信）の本文が「TwitCastingやHakunaなど、音声配信がメインの
    # アプリもあります」。Pococha のラジオ配信に寄せる（1弾の #26/#10 と同じ言い換え）。
    "n6b2f4704cdcc": {
        "md": "34_ライバー容姿関係ない.md",
        "html": [("Pocochaでは申請すればラジオ配信が可能です。"
                  "TwitCastingやHakunaなど、音声配信がメインのアプリもあります。",
                  "Pocochaでは申請すればラジオ配信（音声のみ）が可能です。"
                  "顔を映さずに声だけで活動できます。")],
        "text": [("Pocochaでは申請すればラジオ配信が可能です。"
                  "TwitCastingやHakunaなど、音声配信がメインのアプリもあります。",
                  "Pocochaでは申請すればラジオ配信（音声のみ）が可能です。"
                  "顔を映さずに声だけで活動できます。")],
    },
    # ── #56 副業ライバーおすすめ ──────────────────────────────
    # プラットフォーム比較の箇条書きに「Bigo Live: … 一気に稼ぎやすい」。導入文は
    # 1弾で Pococha・TikTok LIVE・17LIVE に直済みなので、その行を落として揃える。
    "ndce8a9117fa4": {
        "md": "56_副業ライバーおすすめ.md",
        "html": [],
        "cut": [("elem",
                 "<strong>Bigo Live</strong>: グローバルなリスナーさんが多く、"
                 "一気に稼ぎやすい反面、競争も激しい。", "li")],
        "text": [("*   **Bigo Live**: グローバルなリスナーさんが多く、"
                  "一気に稼ぎやすい反面、競争も激しい。\n", "")],
    },
}

# 触らないと決めた記事（1弾 KEEP_AS_IS と同じ基準）。--verify がここを鳴らしても正常。
KEEP_AS_IS = {
    "ne57e6ea14042": "#33 アプリ比較10選（記事の主題）＋取扱3つの但し書きあり",
    "n6194f89cb2aa": "#48 「17LIVEやIRIAM、ミラティブなど数ある…」の例示＋但し書きあり",
    "nfde7bf8ebf40": "#60 代理店向けスカウトDM実務。媒体別の文体表でライバー誘導ではない",
    "n9bf9cb3baed8": "#40 「配信プラットフォーム（Pococha、17LIVE、IRIAMなど）」＝例示",
    "n5fa353fd8dd4": "#61 代表の経歴（渡り歩いた媒体）＋取扱3つの但し書きあり",
    "ne8d3dbf2befc": "#53 取扱3つ／自力運用が前提 明記",
    "nadf7bf475ea9": "#50 4プラットフォーム比較表＋取扱3つの但し書きあり",
    "ncb75e31303b6": "#23 メタバース配信のトレンド例示＋取扱3つの但し書きあり",
    "n79d526cf01a9": "#9 顔出しなしルート③に「サポートしていないので自力運用」明記（正本）",
}

# facts_patterns.COMMON_NG_PATTERNS の取扱外パターンと同じ顔ぶれ（残数カウント用）。
PLATFORM_RE = re.compile(
    r"IRIAM|イリアム|SHOWROOM|ショールーム|ふわっち|REALITY"
    r"|TwitCasting|ツイキャス|[Bb]igo ?[Ll]ive|BIGO ?LIVE|ビゴライブ"
    r"|ミラティブ|Mirrativ|Hakuna|ハクナ|Mildom|ミルダム")
# note が保存のたびに振り直す name/id。目視用に落とすだけ。
ATTR_RE = re.compile(r' (?:name|id)="[0-9a-f-]+"')


def public_note(key, session=None):
    s = session or requests
    r = None
    for attempt in range(3):
        r = s.get(PUBLIC_API.format(key=key), headers=PUBLIC_HEADERS, timeout=30)
        if r.status_code == 200:
            return r.json()["data"]
        time.sleep(1 + attempt)
    raise RuntimeError(f"{key}: HTTP {r.status_code if r else '?'}")


def _already(new, text):
    """new が（見た目は変わらない形で）既に text に入っているか。"""
    probe = re.sub(r"<[^>]+>", "", new).lstrip("・*-  　").strip()
    return bool(probe) and probe in re.sub(r"<[^>]+>", "", text)


def apply_pairs(text, pairs, where):
    """(旧, 新) を完全一致・出現1回で当てる。旧が0回でも新が既にあれば飛ばす。"""
    out = text
    for old, new in pairs:
        n = out.count(old)
        if n == 0 and (new == "" or _already(new, out)):
            continue
        if n != 1:
            raise RuntimeError(f"{where}: 『{old[:44]}』の出現が {n} 回（1回のはず）")
        out = out.replace(old, new)
    return out


def cut_element(html, anchor, tag, where):
    """anchor を含む <tag>…</tag> を丸ごと削る。(新html, 削った塊) を返す。"""
    n = html.count(anchor)
    if n == 0:
        return html, None  # 反映済み
    if n != 1:
        raise RuntimeError(f"{where}: アンカー『{anchor[:40]}』の出現が {n} 回（1回のはず）")
    i = html.index(anchor)
    start = html.rfind(f"<{tag}", 0, i)
    if start < 0:
        raise RuntimeError(f"{where}: <{tag}> の開始タグが見つからない")
    close = f"</{tag}>"
    j = html.find(close, i)
    if j < 0:
        raise RuntimeError(f"{where}: {close} が見つからない")
    end = j + len(close)
    removed = html[start:end]
    if removed.count(f"<{tag}") != 1:
        raise RuntimeError(f"{where}: <{tag}> が入れ子で、意図より広い塊を消そうとしている")
    return html[:start] + html[end:], removed


def cut_span(html, head, tail, where):
    """head を含む要素の開始タグから、その後の tail の直後までを丸ごと削る。"""
    n = html.count(head)
    if n == 0:
        return html, None  # 反映済み
    if n != 1:
        raise RuntimeError(f"{where}: アンカー『{head[:40]}』の出現が {n} 回（1回のはず）")
    i = html.index(head)
    start = html.rfind("<", 0, i)
    if start < 0:
        raise RuntimeError(f"{where}: 開始タグが見つからない")
    j = html.find(tail, i)
    if j < 0:
        raise RuntimeError(f"{where}: 終端『{tail}』が見つからない")
    end = j + len(tail)
    return html[:start] + html[end:], html[start:end]


def apply_cuts(html, cuts, where, show=False):
    out = html
    for op in cuts:
        kind = op[0]
        if kind == "elem":
            out, removed = cut_element(out, op[1], op[2], where)
        elif kind == "span":
            out, removed = cut_span(out, op[1], op[2], where)
        else:
            raise RuntimeError(f"{where}: 未知の cut 種別 {kind}")
        if show and removed:
            print("     ✂ 削除: " + ATTR_RE.sub("", removed)[:240])
    return out


def fix_html(key, body, show=False):
    spec = FIXES[key]
    out = apply_pairs(body, spec.get("html", []), f"{key}(html)")
    out = apply_cuts(out, spec.get("cut", []), f"{key}(cut)", show=show)
    return re.sub(r"<p[^>]*></p>", "", out)


def md_path(key):
    return os.path.join(ARTICLE_DIR, FIXES[key]["md"])


def fix_local(keys):
    changed = 0
    for key in keys:
        path = md_path(key)
        if not os.path.exists(path):
            print(f"  ✗ 原稿なし {os.path.basename(path)}")
            continue
        src = open(path, encoding="utf-8").read()
        new = apply_pairs(src, FIXES[key]["text"], f"{key}(md)")
        if new == src:
            print(f"  変更なし {os.path.basename(path)}")
            continue
        open(path, "w", encoding="utf-8").write(new)
        print(f"  ✓ {os.path.basename(path)}  {len(src)} -> {len(new)}字")
        changed += 1
    print(f"\nローカル原稿: {changed} 本を更新")
    return changed


def backup(key, note):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"{key}.json")
    if os.path.exists(path):
        return path  # 最初の1回だけ残す（1弾が既に取ってあれば上書きしない）
    json.dump({"key": key, "title": note["name"], "body": note["body"],
               "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")},
              open(path, "w"), ensure_ascii=False, indent=1)
    return path


def plan(keys, session, show=True):
    ok = []
    for key in keys:
        d = public_note(key, session)
        try:
            new = fix_html(key, d["body"], show=show)
        except RuntimeError as e:
            print(f"  ✗ {key} {d['name'][:30]}\n     {e}")
            continue
        spec = FIXES[key]
        n = len(spec.get("html", [])) + len(spec.get("cut", []))
        left = len(PLATFORM_RE.findall(re.sub(r"<[^>]+>", "", new)))
        print(f"  ✓ {key} {d['name'][:36]}  body {len(d['body'])} -> {len(new)}字 "
              f"（{n}箇所／残り取扱外 {left}）")
        ok.append(key)
        time.sleep(0.4)
    print(f"\n変換可能: {len(ok)} / {len(keys)} 本")
    return ok


def apply(keys):
    from note_leadmagnet_publish import publish_one
    log = json.load(open(LOG_FILE)) if os.path.exists(LOG_FILE) else {}
    ok = skip = fail = 0
    for i, key in enumerate(keys, 1):
        d = public_note(key)
        print(f"\n[{i}/{len(keys)}] {key} {d['name'][:36]}", flush=True)
        print(f"  backup → {os.path.basename(backup(key, d))}")

        def _t(_key, live_html, _k=key):
            new = fix_html(_k, live_html)
            return None if new == live_html else new  # 反映済みなら PUT しない

        try:
            r = publish_one(key, _t, expect_marker=None)
            log[key] = r
            ok += 1 if r == "ok" else 0
            skip += 1 if r == "skip" else 0
        except Exception as e:
            print(f"  !! 失敗: {e}", flush=True)
            log[key] = f"error: {e}"
            fail += 1
        json.dump(log, open(LOG_FILE, "w"), ensure_ascii=False, indent=1)
        time.sleep(BATCH_SLEEP if i % BATCH == 0 else 3)
    print(f"\n完了 ok={ok} skip={skip} fail={fail}")
    return fail


def verify(keys):
    """ログアウト状態の公開APIで実測する。PUT:200 は反映の証拠にならない。"""
    s = requests.Session()
    ng = 0
    for key in keys:
        d = public_note(key, s)
        text = re.sub(r"<[^>]+>", "", d["body"] or "")
        hits = sorted(set(PLATFORM_RE.findall(d["name"] + "\n" + text)))
        stale = [old[:30] for old, _ in FIXES[key].get("html", []) if old in d["body"]]
        stale += [op[1][:30] for op in FIXES[key].get("cut", []) if op[1] in d["body"]]
        bad = []
        if hits:
            bad.append("取扱外が残存 " + " / ".join(hits))
        if stale:
            bad.append("旧文字列が残存 " + " / ".join(stale))
        if not d.get("eyecatch"):
            bad.append("eyecatchなし")
        tags = len(d.get("hashtag_notes") or [])
        if tags < 10:
            bad.append(f"タグ{tags}")
        ng += 1 if bad else 0
        print(f"  {'NG ' + ' ／ '.join(bad) if bad else 'ok'}  {key} {d['name'][:34]}")
        time.sleep(0.8)
    print(f"\n検証: NG {ng} 本 / {len(keys)} 本")
    return ng


def main():
    args = sys.argv[1:]
    explicit = [a for a in args if a.startswith("n") and not a.startswith("--")]
    keys = explicit or list(FIXES)
    unknown = [k for k in keys if k not in FIXES]
    if unknown:
        raise SystemExit(f"差し替え表に無いキー: {unknown}")

    if "--verify" in args:
        sys.exit(1 if verify(keys) else 0)
    if "--local" in args:
        sys.exit(0 if fix_local(keys) is not None else 1)

    session = requests.Session()
    if "--plan" in args:
        plan(keys, session)
        return
    if "--apply" in args:
        ok = plan(keys, session, show=False)
        if len(ok) != len(keys):
            raise SystemExit("変換できない記事がある。先に差し替え表を直すこと")
        sys.exit(1 if apply(ok) else 0)
    raise SystemExit(__doc__.split("使い方:")[-1])


if __name__ == "__main__":
    main()
