#!/usr/bin/env python3
"""公開済みnote記事から禁止表現「いつでも退所OK／違約金なし」系を外科的に除去する。

note_auto_poster.py --update はローカルmdとタイトル完全一致で突合するため、
note上でタイトルが変わった記事・ローカルmdが削除済みの記事は更新できない。
それらの取りこぼしを、公開HTMLを直接書き換えることで修正する。

機構は note_leadmagnet_publish.py と同じ（Chrome cookie + Playwright + reCAPTCHA + PUT）。
PUTでタグが消えるため、publish_one 側で ensure_tags による復元が走る。

使い方:
  python3 note_exitclaim_fix.py --dry-run <key> [<key> ...]
  python3 note_exitclaim_fix.py <key> [<key> ...]
"""
import re
import sys

from note_cta_publish import get_note, req_session
from note_leadmagnet_publish import publish_one

# 長いパターンから順に適用（前のルールの結果に後のルールが噛まないよう順序が重要）
RULES = [
    # --- CTA末尾の定型文（TAITAN PROが主語）---
    ("TAITAN PROはノルマ・違約金・初期費用すべて0円。",
     "TAITAN PROはノルマなし・初期費用0円。"),
    ("ノルマ0・違約金0・初期費用0", "ノルマ0・初期費用0"),

    # --- 特徴リストの箇条書き ---
    ("<strong>いつでも退所OK</strong>（<strong>違約金なし</strong>）",
     "<strong>ノルマなし</strong>（配信頻度・時間は自由）"),
    ("・いつでも退所OK（違約金なし）", "・ノルマなし（配信頻度・時間は自由）"),
    ("・退所：いつでもOK（違約金なし）", "・契約条件：面談時にすべて説明し、書面でも明示"),

    # --- 事務所選びのチェック項目（一般論だが自社基準を示唆する表現）---
    ("<strong>いつでも退所できるか（違約金なし</strong>）",
     "<strong>退所条件が契約書に明記されているか</strong>"),
    ("良い事務所は「いつでも退所OK、違約金なし」が基本です。",
     "良い事務所は「退所条件を契約書に明記し、面談でも隠さず説明する」のが基本です。"),
    ("「いつでも退所できるか」は必ず確認。",
     "「辞めたいときにどういう手続き・条件になるか」は必ず確認。"),
    ("「合わなければ退所OK」と言ってくれます",
     "契約期間や退所条件を聞く前から自分から説明してくれます"),
    ("<strong>確認ポイント:</strong> いつでも辞められるか、辞める際の条件は何か",
     "<strong>確認ポイント:</strong> 辞めるときの手続きと条件はどうなっているか"),
    ("1ヶ月前にメールまたはLINEで通知すれば退所可能、<strong>違約金なし</strong>",
     "1ヶ月前にメールまたはLINEで通知すれば退所可能と<strong>契約書に明記されている</strong>"),
    ("<strong>良い例:</strong> <strong>違約金なし</strong>",
     "<strong>良い例:</strong> <strong>違約金の有無と金額が契約書に明記されている</strong>"),
    ("いつでも退所できるか → 違約金がある事務所は避ける",
     "退所条件が明確か → 条件を説明しない事務所は避ける"),
    ("初期費用ゼロ・いつでも辞められることも伝えましょう。",
     "初期費用ゼロ・ノルマなしで自分のペースでできることも伝えましょう。"),

    # --- 業界標準の説明（違約金への言及を落とす）---
    ("ノルマ・違約金・初期費用", "ノルマ・初期費用"),

    # --- 旧所属数（事務所の人数を指す文脈のみ。リスナー数の「150名」は対象外）---
    ("うちの事務所150人の", "うちの事務所200名の"),
    ("150人の実データ", "200名の実データ"),
    ("150人の中で", "200名の中で"),
]

# 変換後に残っていたら異常とみなすパターン
BANNED = re.compile(r"退所OK|違約金なし|違約金0|いつでも退所|いつでも辞められ|違約金・初期費用")


def transform(key, html):
    new = html
    for old, rep in RULES:
        new = new.replace(old, rep)
    if new == html:
        return None  # 変更なし＝済み
    left = BANNED.findall(re.sub(r"<[^>]+>", "", new))
    if left:
        raise ValueError(f"未処理の禁止表現が残存 (key={key}): {sorted(set(left))}")
    return new


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    keys = [a for a in args if not a.startswith("--")]
    if not keys:
        print(__doc__)
        return 1
    s = req_session()
    fails = []
    for i, key in enumerate(keys, 1):
        d = get_note(s, key, draft=False)
        print(f"[{i}/{len(keys)}] {key} {d['name'][:44]}")
        try:
            new = transform(key, d["body"])
        except ValueError as e:
            print(f"  !! {e}")
            fails.append(key)
            continue
        if new is None:
            print("  skip（該当表現なし＝対応済み）")
            continue
        print(f"  変換OK: {len(d['body'])} -> {len(new)} bytes")
        if dry:
            continue
        try:
            publish_one(key, transform_fn=transform)
        except Exception as e:
            print(f"  !! PUT失敗: {e}")
            fails.append(key)
    if fails:
        print(f"\n要対応: {fails}")
        return 1
    print("\n全件OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
