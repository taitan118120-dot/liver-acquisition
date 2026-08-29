#!/usr/bin/env python3
"""末尾CTAの「特典＋LINE」2段落が抜けている公開記事に、それだけを後付けする。

■ なぜ必要か（2026-08-29 に note_funnel_guard の残り2本を追って分かったこと）
n8e088d985eab（御新規さん→コアファン）は、末尾のCTA本文（「TAITAN PRO所属ライバー
限定で1on1で共有」「還元率100%+α」「一度話を聞きに来てください」）は持っているのに、
その後に来るはずの

  🎁 友だち追加特典：『ライバー新人期スタートダッシュガイド』…
  👉 公式LINEで無料相談：https://lin.ee/xchCfdn

の2段落だけが無く、**末尾に登録導線が1つも無いまま**公開されていた。
note_funnel_guard は本文のどこかに lin.ee があれば緑にするので、冒頭CTAの
リンクで判定を通過してしまい、ここは見えていなかった。

さらに副作用があった。note_internal_links_publish.find_insert_pos は
「TAITAN PROについて見出し → 友だち追加特典 → lin.ee」の順に挿入位置を探すので、
末尾CTAが無いと**冒頭CTAの lin.ee を rfind で拾い**、「あわせて読みたい」を
本文6%地点（＝記事の頭）に入れてしまう。先にこの2段落を入れておけば、
関連記事ブロックは本来の末尾CTA手前に入る。

note_leadmagnet_publish は「末尾側の lin.ee を含む <p> の直前」に特典段落を足すので、
lin.ee が冒頭にしか無いこの記事では同じ罠にはまり、使えない。
note_article_generator.CTA_BLOCK_LIVER は実際に公開されている末尾CTA
（auto_poster が組む「TAITAN PROについて」～「ここまで読んでくれたあなたへ」）
とは別物なので、これを貼ると他の記事と形が変わる。よって**既存140本と同一形式の
2段落だけ**を足す。文字列は note_agency_cta_publish の TAIL_GIFT_RE /
TAIL_LINE_P_RE が正規形として期待しているものと一致させてある。

使い方:
  python3 note_tailcta_fix_20260829.py --plan <key> [<key>…]   # 差分を出すだけ（GETのみ）
  python3 note_tailcta_fix_20260829.py <key> [<key>…]
"""
import re
import sys

from note_cta_publish import get_note, req_session

GIFT_MARK = "友だち追加特典"
LINE_URL = "https://lin.ee/xchCfdn"

TAIL_CTA = (
    '<p>🎁 <strong>友だち追加特典</strong>：『ライバー新人期スタートダッシュガイド』'
    '——最初の30日でやることを全部まとめた非売品PDFを、'
    'LINE登録した方全員に無料でお渡ししています。</p>'
    '<p><br></p>'
    f'<p>👉 公式LINEで無料相談：<a href="{LINE_URL}" target="_blank" '
    f'rel="nofollow noopener">{LINE_URL}</a></p>')

# 末尾の注記（「*この記事は、…をもとに再構成したものです*」）より前に入れる。
# 注記は読み終わったあとの但し書きなので、CTAはその手前に置く。
DISCLAIMER_RE = re.compile(r"<p[^>]*>\s*\*この記事は、")


def transform(key, html):
    if GIFT_MARK in html:
        return None
    m = DISCLAIMER_RE.search(html)
    pos = m.start() if m else len(html)
    return html[:pos] + TAIL_CTA + html[pos:]


def main():
    args = sys.argv[1:]
    plan_only = "--plan" in args
    keys = [a for a in args if not a.startswith("--")]
    if not keys:
        print("key を1つ以上指定してください")
        return 1

    s = req_session()
    todo = []
    for key in keys:
        d = get_note(s, key, draft=False)
        if d.get("status") != "published":
            print(f"  skip（公開中でない） {key}")
            continue
        body = d["body"]
        new = transform(key, body)
        if new is None:
            print(f"  skip（既に特典段落あり） {key} {d['name'][:36]}")
            continue
        print(f"  {key} {d['name'][:40]}  body {len(body)} -> {len(new)}")
        todo.append(key)

    if plan_only:
        print(f"\n--plan のため書き込みなし。対象 {len(todo)} 本。")
        return 0

    from note_leadmagnet_publish import publish_one
    ok = fail = 0
    for i, key in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] {key}", flush=True)
        try:
            r = publish_one(key, transform, expect_marker=GIFT_MARK)
            ok += 1 if r == "ok" else 0
        except Exception as e:
            print(f"  !! 失敗: {e}", flush=True)
            fail += 1
    print(f"\n完了 ok={ok} fail={fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
