#!/usr/bin/env python3
"""ig_posts.json の契約期間の判断軸を「長さ」から「明記・説明」へ揃える（2026-08-12）。

935da09 が Note記事側で済ませた修正が、そこから生成された Instagram キャプション
には反映されていなかった。自社は2年契約（[[feedback_no_free_exit_claim]]）なのに、
キャプション側が「1年以上の最低契約期間」「2年以上の長期契約は要注意」を
悪質事務所の見分け方として読者に教えていた。この基準で面談に来られると
「御社は2年ですよね？」と自社に跳ね返る。

検出は facts_patterns.contract_axis_violations。対象は2件とも posted=true:
  idx=2  ig_auto_002 (03_事務所選び方.md)
  idx=34 ig_auto_034 (35_ライバー事務所契約書注意点.md)

判断軸は記事側と同じ「契約期間・更新・中途解約の条件が契約書に明記され、
面談でも説明されるか」に揃える。ついでに、同じキャプション内にあって
確定ファクトに反していた箇所（下の REPLACEMENTS のコメント参照）も直す。
Instagram 上の実物は Graph API では直せない（POST /{ig-media-id} は
comment_enabled のみ）ので、アプリから手で貼り直す用の本文も出力する。

  python3 instagram/ig_contract_axis_fix_20260812.py --dry-run
  python3 instagram/ig_contract_axis_fix_20260812.py
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

POSTS_FILE = os.path.join(BASE_DIR, "instagram", "ig_posts.json")

# (post_id, [(before, after, なぜ直すか), ...])
# before は完全一致。1件でも当たらなければ何も書かずに落とす（部分適用を作らない）。
REPLACEMENTS = [
    ("ig_auto_002", [
        (
            # 判断軸の本体。「長さ・違約金の有無で裁く」→「明記・説明されているか」
            "「いつでも退所OK、違約金なし」が優良事務所の基本です。"
            "1年以上の最低契約期間や高額な違約金、退所後の活動制限がある事務所は避けてください。"
            "ライバーが不満なら去れる環境を用意している事務所こそ、サポートに自信がある証拠です。",

            "見るべきは期間の長さではなく、条件が書いてあるかどうかです。"
            "契約の更新と中途解約の手続きが契約書に明記され、面談でも同じ説明が受けられるか。"
            "違約金も、金額と発生条件が書面に明記されているかを確認しましょう。"
            "ここを隠さず説明できる事務所こそ、サポートに自信がある証拠です。",

            "契約期間の長さ・違約金の有無を判断軸にしていた（自社2年と矛盾）",
        ),
        (
            # 上と同じ矛盾の言い換え。「合わなければ退所OK」を基準にすると同じく跳ね返る
            "サポート内容だけでなくデメリットも正直に話してくれます。"
            "「まず試してみて、合わなければ退所OK」と言ってくれる事務所を選びましょう。",

            "サポート内容だけでなくデメリットや契約条件も正直に話してくれます。"
            "聞いたことにその場で具体的に答えてくれる事務所を選びましょう。",

            "「合わなければ退所OK」を良い事務所の基準にしていた（同上）",
        ),
        (
            # [[feedback_no_fee_free_claim]] 報酬は「還元率100%+α」
            "✅ **還元率が100%と明示されているか💯**",
            "✅ **還元率が100%+αと明示されているか💯**",
            "還元率は「100%+α」が確定表記",
        ),
        (
            "優良事務所（TAITAN PRO含む）は、ライバーへの還元率100%で運営しています。",
            "優良事務所（TAITAN PRO含む）は、ライバーへの還元率100%+αで運営しています。",
            "還元率は「100%+α」が確定表記",
        ),
        (
            # [[feedback_income_figures]] 月15万未満の金額は書かない
            "個人で配信して月3〜5万円の壁を感じている方も、"
            "事務所のサポートがあれば月20万円以上を目指せる可能性があります✨",

            "個人で配信していて伸び悩みの壁を感じている方も、"
            "事務所のサポートがあれば月20万円以上を目指せる可能性があります✨",

            "確定レンジ未満の少額表記（月15万が下限）",
        ),
    ]),
    ("ig_auto_034", [
        (
            "また、2年以上の長期契約で身動きが取れなくなり、"
            "違約金が高額で退所できないという悲劇も。",

            "また、更新や中途解約の条件がどこにも書かれておらず、"
            "いざ辞めたいときに話が通らないという悲劇も。",

            "契約期間の長さを危険サインにしていた（自社2年と矛盾）",
        ),
        (
            "✅ 契約期間は短期（6ヶ月〜1年）を選ぶ\n"
            "2年以上の長期契約は要注意。"
            "自動更新の条件や更新拒否の期限も「更新の1ヶ月前までに書面で通知」など"
            "具体的に確認しましょう。",

            "✅ 契約期間と中途解約の条件がセットで書かれているか\n"
            "見るべきは期間の長さではなく、更新と中途解約の手続きが明記されているか。"
            "自動更新の条件や更新拒否の期限も「更新の1ヶ月前までに書面で通知」など"
            "具体的に確認しましょう。",

            "「短期を選べ／2年以上は要注意」＝業界標準から自社を外れ値にしていた",
        ),
        (
            "✅ 退所条件と違約金を必ず確認する\n"
            "「違約金なし」「1ヶ月前通知で退所可能」など、"
            "ライバーがいつでも身動き取れる条件が理想。"
            "高額な違約金や、事務所の承認が必要な退所条件は避けるべきです。",

            "✅ 退所の手続きと違約金が書面にあるか\n"
            "違約金の金額と発生条件、退所の申し出方法と期限が契約書に明記され、"
            "面談でも同じ説明が受けられるかを見ましょう。"
            "金額も条件も書かれず「辞めたら違約金がかかる」と口頭で言われるだけなら要注意です。",

            "「違約金なし」を理想として提示していた（[[feedback_no_free_exit_claim]]）",
        ),
        (
            # [[feedback_no_fee_free_claim]] 「手数料」は単語そのものが禁止
            "さらに振込手数料やサポート費が別途引かれないかまでチェックが必要です。",
            "さらに振込時の控除やサポート費が別途引かれないかまでチェックが必要です。",
            "禁止語「手数料」",
        ),
    ]),
]


def main():
    dry_run = "--dry-run" in sys.argv

    with open(POSTS_FILE, encoding="utf-8") as f:
        posts = json.load(f)
    by_id = {p["id"]: p for p in posts}

    changed = []
    for post_id, rules in REPLACEMENTS:
        post = by_id.get(post_id)
        if post is None:
            sys.exit(f"[FAIL] {post_id} が ig_posts.json にない")
        caption = post["caption"]
        for before, after, why in rules:
            if before not in caption:
                # 既に直っているのか、原文が変わったのか、人が見て判断する。
                # 黙って飛ばすと「直ったつもり」が残るので落とす。
                sys.exit(f"[FAIL] {post_id}: 置換前の文が見つからない（{why}）\n  {before[:60]}…")
            if caption.count(before) != 1:
                sys.exit(f"[FAIL] {post_id}: 置換前の文が複数ある（{why}）")
            caption = caption.replace(before, after)
            print(f"  [OK] {post_id}: {why}")
        post["caption"] = caption
        changed.append(post)

    # 直した結果が本当に検品を通るか、書き込む前に確かめる
    from facts_patterns import common_violations, contract_axis_violations
    for post in changed:
        axis = contract_axis_violations(post["caption"])
        if axis:
            sys.exit(f"[FAIL] {post['id']}: 判断軸の違反が残っている → {axis}")
        rest = common_violations(post["caption"])
        print(f"  [CHECK] {post['id']}: 判断軸 0件 / 残りの検品 {len(rest)}件")
        for reason, hit in rest:
            print(f"      - {reason} | {hit}")

    if dry_run:
        print("\n--dry-run のため書き込まない")
    else:
        with open(POSTS_FILE, "w", encoding="utf-8") as f:
            json.dump(posts, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"\n{POSTS_FILE} を更新した")

    # Graph API では公開済みキャプションを編集できないので、手で貼り直す用に出す
    out_dir = os.path.join(BASE_DIR, "data")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "ig_caption_manual_repost_20260812.txt")
    with open(out_file, "w", encoding="utf-8") as f:
        for post in changed:
            f.write(f"{'=' * 60}\n{post['id']}  media_id={post.get('media_id')}\n"
                    f"{post.get('title')}\n{'=' * 60}\n{post['caption']}\n\n\n")
    print(f"手貼り用の全文: {out_file}")


if __name__ == "__main__":
    main()
