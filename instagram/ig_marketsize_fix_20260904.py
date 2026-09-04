#!/usr/bin/env python3
"""投稿済みInstagram 2件から「出典のない市場規模の金額」を落とす（2026-09-04）。

■ 何が残っていたか
  同日に公開Note記事3本（ncb75e31303b6 / na08ce1921eb6 / n1b4784640d76）から
  出典なしの市場規模を削った（note_marketsize_fix_20260904.py）。ところが
  **同じ原稿から作られたInstagramのキャプション2件**（2026-04-22 投稿済み）に
  同じ数字がそのまま生きていた:

    ig_auto_021 (18007874624899205, 元 22_30代ライバー.md)
      「ライブ配信市場は2026年現在、日本国内だけで約1,500億円規模に成長。」
      ＋ 出典なしの割合統計2つ（Pococha利用者の約40%が25〜35歳／
         30代の月収中央値は20代より約20%高い）
    ig_auto_022 (18076990574309849, 元 23_ライブ配信市場将来性.md)
      「国内ライブ配信市場は、2026年には約1,500億円規模に到達する見込みで、
        2020年の3倍に成長中です。」

  ユーザー確認済みで裏取りの出典は無い＝捏造 [[feedback_dont_make_up_numbers]]。

■ なぜ機械では直せないか
  Instagram Graph API に **公開済みメディアのキャプションを更新するエンドポイントは
  無い**（作成できるのは /media → /media_publish だけ）。消して再投稿すると
  いいね・保存・インサイトが全部消え、投稿日も今日に変わる。
  なので **アプリから手で直してもらう** 前提で、貼り付け用の全文をここに持つ。

■ 手順
  1. `python3 instagram/ig_marketsize_fix_20260904.py`
     → 新旧の差分と、貼り付け用のキャプション全文を出す
  2. Instagramアプリ → 該当投稿 → ⋯ → 「編集」→ キャプションを全選択して貼り替え
  3. `python3 instagram/ig_marketsize_fix_20260904.py --apply`
     → ig_posts.json のキャプションを同じ文面に更新（記録と実物を一致させる）
  4. `python3 instagram/ig_marketsize_fix_20260904.py --verify`
     → INSTAGRAM_ACCESS_TOKEN があれば Graph API で実物を取得して突合する
       （トークンはGitHub Secrets側にしか無いのでローカルでは skip になる）

■ 生成側（再発防止）
  ig_viral_generator._validate_content / ig_content_generator は既に
  facts_patterns.ng_violations を通していて、2026-09-04 に拡張した
  「根拠のない市場規模・成長率」（金額・国別順位を追加）はそこに載っている。
  つまり **今の生成経路では同じ文は作れない**。今回の2件は、その検品が入る前
  （2026-04-22、旧 ig_content_generator 時代）の在庫。
"""
import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(BASE_DIR)
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

POSTS_FILE = os.path.join(BASE_DIR, "ig_posts.json")

# ── 置換 ─────────────────────────────────────────────────────
# 段落まるごとの完全一致で持つ。部分一致や正規表現にすると、あとから
# キャプションを1文字直したときに静かに当たらなくなる（＝何も直っていないのに
# 「変更なし」と出る）ので、当たらなければ落とす。
REPLACEMENTS = {
    "ig_auto_021": [
        # ① フックの「9割が知らない」＝出典なしの割合統計。
        #    facts_patterns.RATIO_PREDICATE が実際に検知する。
        ("【30代必見】9割が知らない「今」ライバーを始めるべき理由",
         "【30代必見】意外と知られていない「今」ライバーを始めるべき理由"),
        # ② 市場規模の金額 ＋ 出典なしの割合統計2つ ＋ リスナー呼び捨て。
        #    Note側 #23 と同じ直し方（金額をやめて「何が伸びを支えているか」）に揃える。
        ("「若い子ばかり」というイメージはもう古いんです。実はライブ配信市場は2026年現在、"
         "日本国内だけで約1,500億円規模に成長。Pococha利用者の約40%は25〜35歳で、"
         "30代ライバーの月収中央値は20代より約20%も高いというデータも。"
         "リスナー側も「落ち着いた大人の配信」を求める層が増え、"
         "30代ライバーのニーズは高まる一方です。",
         "「若い子ばかり」というイメージはもう古いんです。5Gの普及、投げ銭文化の定着、"
         "企業のライブコマース参入で配信の裾野が広がり、"
         "30代のライバーもリスナーさんも増えています。"
         "「落ち着いた大人の配信」を求めるリスナーさんも多く、"
         "30代ライバーのニーズは高まる一方です。"),
        # ③ 事務所公式は @taitan_pro7（2026-08-08確定）。@taitan_pro は未運用の別垢で、
        #    この投稿は @taitan_pro7 に載っている＝読者を存在しない導線へ送っていた。
        ("プロフィール（@taitan_pro）のリンクから",
         "プロフィール（@taitan_pro7）のリンクから"),
    ],
    "ig_auto_022": [
        # ① 市場規模の金額 → 伸びの理由の説明（Note #23 の本文と同じ言い回し）。
        # ② 「初月から月20万円」…[[feedback_income_figures]] の確定レンジ
        #    （3ヶ月15〜20万 / 6ヶ月30〜40万）と食い違う未確認の数字なので落とす。
        # ③ 「続々と」…facts_patterns の「根拠なしの実績誇張」。
        # ④ リスナー呼び捨て。
        ("国内ライブ配信市場は、2026年には約1,500億円規模に到達する見込みで、"
         "2020年の3倍に成長中です。この成長を牽引しているのが、5Gの普及や"
         "投げ銭文化の定着、そしてリスナー層の多様化（30〜40代まで拡大）です。"
         "特にPocochaでは、配信するだけで報酬が発生する「時間ダイヤ」制度が"
         "確立されており、未経験からでも初月から月20万円の収入も目指せます。"
         "TAITAN PROのライバーも、質の高いサポートとノウハウで、"
         "続々と安定した収益を上げています。",
         "市場規模の金額はメディアによって数字がばらばらで、集計の範囲も書かれて"
         "いないものがほとんど。なのでここでは金額ではなく「何が伸びを支えているのか」"
         "を見ます。5Gの普及、投げ銭文化の定着、企業のライブコマース参入、そして"
         "リスナーさん層の多様化（30〜40代まで拡大）です。特にPocochaでは、"
         "配信するだけで報酬が発生する「時間ダイヤ」制度が確立されていて、"
         "未経験からでも配信時間に応じて報酬が発生しやすいのが特徴。"
         "TAITAN PROのライバーも、質の高いサポートとノウハウで安定した収益を"
         "上げています。"),
        ("プロフィール（@taitan_pro）のリンクから",
         "プロフィール（@taitan_pro7）のリンクから"),
    ],
}

# 直したあとキャプションに残っていてはいけない文字列。
LEFTOVERS = ["1,500億", "500億円", "約40%", "約20%", "9割が知らない",
             "初月から月20万", "続々と", "@taitan_pro）"]


def load_posts():
    with open(POSTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def find_post(posts, post_id):
    for i, p in enumerate(posts):
        if p.get("id") == post_id:
            return i, p
    raise KeyError(f"{post_id} が ig_posts.json に無い")


def transform(caption, rules):
    """置換を順に当てる。1つでも当たらなければ (None, 当たらなかった旧文字列) を返す。

    最後に「リスナー」→「リスナーさん」を全文に当てる。上の段落置換だけだと
    ✅の箇条書き側（「落ち着いたリスナーが集まりやすい」「リスナー層が多様化」）に
    呼び捨てが残り、貼り替えたのに検品が赤のまま、という中途半端な状態になる
    [[feedback_listener_san]]。生成側の ig_viral_generator._fix_listener_san と
    同じ式なので、直したあとの文面は今の自動投稿と揃う。
    """
    from ig_viral_generator import _fix_listener_san

    out, missed = caption, []
    for old, new in rules:
        if old not in out:
            if new in out:
                continue  # 既に適用済み
            missed.append(old[:40])
            continue
        out = out.replace(old, new)
    return (None, missed) if missed else (_fix_listener_san(out), [])


def violations(text):
    from facts_patterns import common_violations
    # リスナー呼び捨て以外の全項目を見る（呼び捨てはこの置換で直している）
    return common_violations(text)


def leftovers(text):
    return [w for w in LEFTOVERS if w in text]


def show():
    posts = load_posts()
    for post_id, rules in REPLACEMENTS.items():
        _, post = find_post(posts, post_id)
        new, missed = transform(post["caption"], rules)
        print("=" * 70)
        print(f"{post_id}  media_id={post.get('media_id')}  元記事={post.get('source_file')}")
        print("=" * 70)
        if missed:
            print(f"  !! 置換元が見つからない: {missed}")
            print("     （キャプションが既に手で変わっている可能性。差分を確認してから直すこと）")
            continue
        if new == post["caption"]:
            print("  変更なし（既に適用済み）")
            continue
        print(f"\n【今の違反】")
        for r, h in violations(post["caption"]):
            print(f"  - {r} | {h}")
        print(f"\n【直したあとの違反】")
        after = violations(new)
        for r, h in after:
            print(f"  - {r} | {h}")
        if not after:
            print("  なし")
        print(f"  残存NGワード: {leftovers(new) or 'なし'}")
        print(f"\n───── 貼り付け用キャプション全文（{len(new)}文字）─────")
        print(new)
        print("───── ここまで ─────\n")


def apply():
    posts = load_posts()
    changed = 0
    for post_id, rules in REPLACEMENTS.items():
        i, post = find_post(posts, post_id)
        new, missed = transform(post["caption"], rules)
        if missed:
            raise RuntimeError(f"{post_id}: 置換元が見つからない {missed}")
        if new == post["caption"]:
            print(f"  {post_id} 変更なし（既に適用済み）")
            continue
        left = leftovers(new)
        if left:
            raise RuntimeError(f"{post_id}: 置換後にNGワードが残っている {left}")
        posts[i]["caption"] = new
        posts[i]["caption_edited_at"] = "2026-09-04"
        posts[i]["caption_edit_reason"] = "出典のない市場規模・割合統計を削除（手動編集と同期）"
        changed += 1
        print(f"  {post_id} 更新（{len(post['caption'])} -> {len(new)}文字）")
    if changed:
        with open(POSTS_FILE, "w", encoding="utf-8") as f:
            json.dump(posts, f, ensure_ascii=False, indent=2)
        print(f"\nig_posts.json を更新（{changed}件）")
    return changed


def verify():
    """Graph API で実物のキャプションを取り、ig_posts.json と突合する。

    トークンはGitHub Secretsにしか無いので、ローカルでは skip になるのが正常。
    """
    import config

    token = config.INSTAGRAM_ACCESS_TOKEN
    if not token:
        print("INSTAGRAM_ACCESS_TOKEN が未設定 → 実物の突合はスキップ")
        print("（ローカルでは ig_posts.json 側の検品だけ行う）")
        posts = load_posts()
        bad = 0
        for post_id in REPLACEMENTS:
            _, post = find_post(posts, post_id)
            v = violations(post["caption"])
            left = leftovers(post["caption"])
            print(f"  {post_id} json: 違反={len(v)} 残存={left or 'なし'}")
            for r, h in v:
                print(f"    - {r} | {h}")
            bad += bool(v or left)
        return bad

    import requests

    bad = 0
    posts = load_posts()
    for post_id in REPLACEMENTS:
        _, post = find_post(posts, post_id)
        mid = post.get("media_id")
        r = requests.get(f"https://graph.facebook.com/v21.0/{mid}",
                         params={"fields": "caption,permalink", "access_token": token},
                         timeout=30)
        if r.status_code != 200:
            print(f"  {post_id} 取得失敗 {r.status_code} {r.text[:120]}")
            bad += 1
            continue
        live = r.json().get("caption", "")
        left = leftovers(live)
        same = live.strip() == post["caption"].strip()
        print(f"  {post_id} 実物: 残存={left or 'なし'} json一致={'OK' if same else 'ズレ'}")
        if not same:
            print(f"    live {len(live)}文字 / json {len(post['caption'])}文字")
        bad += bool(left) or (not same)
    print(f"\n未対応: {bad} 件")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="ig_posts.json のキャプションを更新（IG側を手で直したあとに実行）")
    ap.add_argument("--verify", action="store_true",
                    help="Graph API で実物と突合（トークンが無ければ json のみ検品）")
    args = ap.parse_args()

    if args.verify:
        sys.exit(1 if verify() else 0)
    if args.apply:
        apply()
        return
    show()


if __name__ == "__main__":
    main()
