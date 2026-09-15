"""X API のクレジット枯渇（HTTP 402 Payment Required / "credits depleted"）の扱い。

この1本を正本にして、X を叩くスクリプト全部が同じ判定・同じ終了コードを使う。

背景（2026-09-06）: 2026-08-23 から14日間、全ランがこの402で赤くなり続けていた。
クレジットは課金しないと戻らないので、再実行しても別の投稿候補に変えても絶対に直らない。
それでも「投稿できなかった＝赤」で扱っていたため、1日3回の失敗メールに加えて
auto_retry の再実行と auto_fix の再発コメントまで積み上がり、Issue #45 はコメント81件になった。
コード側は正常で、直せるのは課金だけ。だから「一時的に投稿できない既知の状態」として
専用コードで区別し、ワークフロー側は赤にせず Issue 1本に集約する（auto_post.yml 参照）。
75 は sysexits.h の EX_TEMPFAIL（一時的な失敗）に合わせた。

追記（2026-09-16）: 402を「検索結果0件」として飲み込んでいた2本をここに合流させた。
`x_reply_digest.py` と `cloud_list_add.py` は検索の失敗を握りつぶして exit 0 で終わるため、
2026-08-23以降**CIが緑のまま、リプ候補Issueが1本も出ていない**状態が3週間続いていた
（実測: run 34912969025 は全8クエリが402、run 34915986059 は全31キーワードが402、どちらも success）。
「良い候補が無くて0件」と「APIが死んでいて0件」は意味が正反対なので、
呼び出し側は必ず is_credits_depleted() で分岐し、後者は EXIT_CREDITS_DEPLETED で抜けること。

判定は**実際の応答を見て**行う（手動の停止フラグを持たない）。
課金が戻った回は自動的に通常動作へ復帰するので、フラグの戻し忘れという死角が生まれない。
"""

EXIT_CREDITS_DEPLETED = 75

# 残クレジットとプランの確認先
PORTAL_URL = "https://developer.x.com/en/portal/dashboard"


def is_credits_depleted(exc) -> bool:
    """例外が X API のクレジット枯渇(402)なら True。

    tweepy は 402 に専用の例外クラスを持たない（403/429/5xx と同じ HTTPException の
    仲間として飛んでくる）ので、レスポンスのステータスコードで見る。
    except 節を書く順番に依存しないよう、汎用の except からも呼べる形にしてある。
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status == 402


def print_halt(what: str) -> None:
    """クレジット枯渇で処理を打ち切るときの定型メッセージ。

    what … 止まった処理の名前（例: "リプ候補の抽出"）
    """
    print("[HALT] X API のクレジットが枯渇しています (402 Payment Required)。")
    print(f"  {what}はクレジットが回復するまで何も産みません。")
    print("  クレジットはアカウント全体に効くので、クエリを変えても再実行しても同じ結果になります。")
    print(f"  → {PORTAL_URL} で残クレジットとプランを確認してください。")
