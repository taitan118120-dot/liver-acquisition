#!/usr/bin/env python3
"""#47 ndb58de31b4de を「代表の体験談」から「選び方の一般論」へ組み直す（2026-10-24）。

原稿は 2026-04-19 に反応改善プロンプトで生成されたもので、本文が
代表個人の作り話でできていた（ユーザー確認済み「作り話→一般論に組み直す」）:
  ・「本業の給料が月18万円」「5つの副業を順番に失敗」と各副業の収支
    （アンケート月1,800円／データ入力月1万2,000円／ブログ月800円／
    せどり−1万8,000円／クラウドソーシング月3〜4万円）、「約23ヶ月と25万円」
  ・代理店収入の推移「6ヶ月で月7万円、1年で月20万円、2年で月55万円」
    「月5万円を半年で達成」→ ユーザー確認「事実でない」
  ・FAQ「新人ライバーが5人育った時点で月5万を超えるケースが多い」→ 根拠なし
番犬はどれも拾わない（主語が代表個人で、金額も代理店の文脈なので免除される）。
[[feedback_dont_make_up_numbers]] の「代表の実績は確定ファクトに無いものは書かない」で処理。

■ 代理店の収入は**金額を書かない**（ユーザー選択）
  代理店LPの目安は 2026-08-02 に「1ヶ月目 月5万円〜／1〜3ヶ月 月10〜20万円」へ
  変わっていて、Note #25/#43 の「副業レンジ 月3〜10万」は古いLPの値のまま。
  #47 はどちらにも寄せず「活動状況で変わる、目安は個別に案内」に逃がす。

■ タイトルも変える。他記事6本の本文にコピーされている
  「5個失敗した私が」は代表の体験を主張する文言なので、#47 のタイトルを変えるだけでは
  他記事の「あわせて読みたい」（note_internal_links_publish.related_html が
  タイトルをリンク文言としてコピーする）に作り話が残る。リンク文言も新タイトルへ。
  #209 nd6564bef56b0 は地の文で「私が実際に失敗した副業の話は…に書きました」と
  体験談として紹介していたので、文ごと言い換える。

■ #47 本文の差し替え範囲
  冒頭〜「ここまで読んでくださり」の直前（原稿の `---` まで）を原稿から作り直す。
  それより後ろ（末尾CTA・「あわせて読みたい」・フォロー依頼）は公開側にしか無い
  施策の追加物なので、公開本文をそのまま残す。

公開の3段は note_publish_core（note_leadmagnet_publish.publish_one 経由）が正本。

使い方:
  python3 note_47_rewrite_20261024.py --dry-run   # 置換結果を出す（GETのみ）
  python3 note_47_rewrite_20261024.py --md        # ローカル原稿（#209）と key_map を直す
  python3 note_47_rewrite_20261024.py --publish   # #47 → リンク元6本の順に公開
  python3 note_47_rewrite_20261024.py --verify    # ログアウト公開APIで検証
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

KEY = "ndb58de31b4de"
MD_FILE = os.path.join(BASE_DIR, "blog", "articles_note", "47_副業月5万在宅.md")
MD_209 = os.path.join(BASE_DIR, "blog", "articles_note", "209_スマホ副業は怪しい安全な副業の見分け方.md")
KEYMAP_FILE = os.path.join(BASE_DIR, "data", "note_key_map.json")

OLD_TITLE = "「月5万円の在宅副業」で5個失敗した私が、最終的にライバー代理店に落ち着いた話【2026年版】"
NEW_TITLE = "「月5万円の在宅副業」を選ぶ前に見る3つの基準｜時間を切り売りしない副業とライバー代理店【2026年版】"

# 2026-10-24 にログアウト公開APIで全194本を走査して見つけたリンク元
INBOUND = ["ndce8a9117fa4", "nc932709431a0", "ne10b7646b37f",
           "n582be31e666b", "nd6564bef56b0", "n8289e2b831ed"]

# #209 の地の文。体験談として紹介しているので文ごと言い換える
_209_OLD = re.compile(
    r"私が実際に失敗した副業の話は(<a [^>]*ndb58de31b4de[^>]*>)在宅副業で5個失敗した私が、"
    r"最後に落ち着いた仕事の話(</a>)に書きました。")
_209_NEW = r"在宅副業を選ぶ前に見ておきたい基準は\1" + NEW_TITLE + r"\2にまとめています。"
_209_MD_OLD = ("私が実際に失敗した副業の話は[在宅副業で5個失敗した私が、最後に落ち着いた仕事の話]"
               "(https://note.com/taitan_118/n/ndb58de31b4de)に書きました。")
_209_MD_NEW = ("在宅副業を選ぶ前に見ておきたい基準は[" + NEW_TITLE +
               "](https://note.com/taitan_118/n/ndb58de31b4de)にまとめています。")

# 新本文に入っていて旧本文には無い文字列（冪等判定と反映確認の両方に使う）
NEW_MARK = "自分に合うかを見極めるための物差し"
# 消したはずの作り話。公開本文・リンク元のどこにも残っていてはいけない
GONE = ["5個失敗", "本業の給料が月18万", "月1,800円", "月1万2,000円", "月800円",
        "マイナス1万8,000円", "23ヶ月と25万円", "月7万円、1年で月20万円", "月55万",
        "半年で達成", "5人育った", "寝てても毎月"]

# 公開本文の末尾（施策の追加物）の起点。note は保存のたびに name/id を振り直すので属性は読み飛ばす
_TAIL = re.compile(r"(?:<p[^>]*><br><br></p>)?<p[^>]*>ここまで読んでくださり")

PUBLIC_API = "https://note.com/api/v3/notes/{key}"
PUBLIC_HEADERS = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache",
                  "Pragma": "no-cache"}


def new_head_html():
    """原稿のタイトル行の次〜 `---` の手前を note 用HTMLにする。"""
    from note_auto_poster import markdown_to_html
    lines = open(MD_FILE, encoding="utf-8").read().split("\n")
    assert lines[0] == "# " + NEW_TITLE, "原稿のタイトルが NEW_TITLE と一致しない"
    body = lines[1:lines.index("---")]
    return markdown_to_html("\n".join(body).strip("\n"))


def transform_47(key, html):
    if NEW_MARK in html:
        return None
    m = _TAIL.search(html)
    if not m:
        raise ValueError("末尾CTA（ここまで読んでくださり）が見つからない")
    return new_head_html() + html[m.start():]


def transform_inbound(key, html):
    out = _209_OLD.sub(_209_NEW, html)
    out = out.replace(OLD_TITLE, NEW_TITLE)
    return None if out == html else out


def transform(key, html):
    return transform_47(key, html) if key == KEY else transform_inbound(key, html)


def transform_title(key, title):
    return NEW_TITLE if key == KEY and title != NEW_TITLE else None


def problems(key, d):
    """公開側に残っていてはいけないもの。空なら合格。"""
    title, body = d.get("name", ""), d.get("body", "")
    text = title + "\n" + body
    out = [f"残存: {g}" for g in GONE if g in text]
    if key == KEY:
        if title != NEW_TITLE:
            out.append(f"タイトルが旧いまま: {title}")
        if NEW_MARK not in body:
            out.append("新本文が反映されていない")
        out += [f"{r}: {h}" for r, h in common_violations(text)]
    elif NEW_TITLE not in body:
        out.append("リンク文言が新タイトルになっていない")
    return out


def fetch_public(key):
    r = requests.get(PUBLIC_API.format(key=key), headers=PUBLIC_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()["data"]


def dry_run():
    for key in [KEY] + INBOUND:
        d = fetch_public(key)
        nb = transform(key, d["body"])
        nt = transform_title(key, d["name"])
        print(f"\n{key} {d['name'][:40]}")
        if nt:
            print(f"  [TITLE] -> {nt}")
        if nb is None:
            print("  変更なし")
            continue
        print(f"  [BODY] {len(d['body'])} -> {len(nb)}")
        left = problems(key, {"name": nt or d["name"], "body": nb})
        print("  直したあとの問題:", left or "なし")
        time.sleep(0.3)


def fix_md():
    src = open(MD_209, encoding="utf-8").read()
    if _209_MD_OLD in src:
        open(MD_209, "w", encoding="utf-8").write(src.replace(_209_MD_OLD, _209_MD_NEW))
        print(f"  updated {os.path.relpath(MD_209, BASE_DIR)}")
    km = json.load(open(KEYMAP_FILE, encoding="utf-8"))
    if km["47"]["title"] != NEW_TITLE:
        km["47"]["title"] = NEW_TITLE
        with open(KEYMAP_FILE, "w", encoding="utf-8") as f:
            json.dump(km, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("  updated data/note_key_map.json #47 title")


def publish_all():
    from note_leadmagnet_publish import publish_one
    fail = 0
    # #47 を先に。タイトルが変わってからリンク元を直す（逆だと新記事の内部リンクが旧タイトルを拾う）
    for i, key in enumerate([KEY] + INBOUND, 1):
        print(f"\n[{i}/{1 + len(INBOUND)}] {key}", flush=True)
        try:
            publish_one(key, transform, expect_marker=None, title_fn=transform_title)
        except Exception as e:  # noqa: BLE001 — 1本落ちても残りは処理する
            print(f"  !! 失敗: {type(e).__name__}: {e}", flush=True)
            fail += 1
        time.sleep(8)
    return fail


def verify():
    bad = 0
    for key in [KEY] + INBOUND:
        for attempt in range(4):
            d = fetch_public(key)
            left = problems(key, d)
            if not left:
                break
            time.sleep(6)  # CDN反映ラグ
        tags = len(d.get("hashtag_notes", []))
        ok = not left and tags > 0 and d.get("eyecatch")
        bad += not ok
        print(f"{'OK' if ok else 'NG'} {key} tags={tags} "
              f"eyecatch={'OK' if d.get('eyecatch') else 'MISSING'} {d['name'][:40]}")
        for p in left:
            print(f"   {p}")
    print(f"\n検証 {1 + len(INBOUND)} 本 / 問題 {bad} 本")
    return bad == 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--dry-run":
        dry_run()
    elif arg == "--md":
        fix_md()
    elif arg == "--publish":
        raise SystemExit(1 if publish_all() else 0)
    elif arg == "--verify":
        raise SystemExit(0 if verify() else 1)
    else:
        print(__doc__)
        raise SystemExit(1)
