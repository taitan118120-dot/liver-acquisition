"""要サポート・アラート監視 → 声かけリスト生成.

蓄積データから「いま声をかけるべきライバー」を深刻度順に洗い出す。
coach.py の取得・配信集計ロジックを再利用し、アラートを構造化（カテゴリ・深刻度・
理由・声かけの方向性）して出力する。定期実行してリスト化する用途。

使い方:
    python3 alerts.py            # 深刻度順の声かけリスト
    python3 alerts.py --json     # 機械可読JSON
    python3 alerts.py --all      # アラートが無いライバーも「健全」として表示

補足: 運営の /publishers/need_cares は「直近14日のランク履歴」で未配信マイナス回数
を絞る公式リストだが、事務所歴14日未満やランク履歴不足のライバーは対象外（新人は
出てこない）。本ツールはそれを待たず手元データで先回りして検知する。

方針: 捏造しない。閾値はデータから読み取れる事実ベースのみ。ダイヤ急落・配信上限接近は
複数日のスナップショットが溜まってから有効化（現状は配信空き・降格・習慣を中心に判定）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from db import connect
from coach import load_liver, analyze_streams

SEV_ORDER = {"high": 0, "mid": 1, "low": 2}
SEV_MARK = {"high": "🔴", "mid": "🟡", "low": "⚪"}

RANK_TIER = "ESDCBA"  # 左ほど下位（頭文字のみのざっくり判定）


def _tier(rank):
    return RANK_TIER.find((rank or "")[0]) if rank else -1


def build_alerts(data):
    """1ライバー分のアラート配列を返す。各要素 {sev, cat, why, action}."""
    lv = data["liver"]
    st = analyze_streams(data["streams"])
    rh = data["rank_hist"]
    cur = data["snaps"][-1] if data["snaps"] else None
    out = []

    # 1) 配信が空いている（離脱リスク）
    if st and st["last_gap_days"] is not None:
        g = st["last_gap_days"]
        if g >= 5:
            out.append({"sev": "high", "cat": "離脱リスク",
                        "why": f"最終配信から {g} 日（最後: {st['last_started']}）",
                        "action": "まず体調・状況の確認。無理のない範囲で短時間でも復帰枠を一緒に設定"})
        elif g >= 3:
            out.append({"sev": "mid", "cat": "配信間隔",
                        "why": f"最終配信から {g} 日空いている",
                        "action": "軽い声かけで近況確認。次の配信予定を一緒に決める"})

    # 2) 配信習慣の低下
    if st and st["recent7_active_days"] <= 2 and (st["last_gap_days"] or 0) >= 1:
        out.append({"sev": "mid", "cat": "配信習慣",
                    "why": f"直近7日の配信日数 {st['recent7_active_days']} 日",
                    "action": "固定枠の曜日・時間を決めて週の配信日数を増やす提案"})

    # 3) ランク降格・メーターマイナス
    if rh:
        latest = rh[0]
        if _tier(latest["after_rank"]) < _tier(latest["before_rank"]):
            out.append({"sev": "high", "cat": "ランク降格",
                        "why": f"{latest['before_rank']} → {latest['after_rank']}（{latest['change_date']}）",
                        "action": "落ち込みやすいタイミング。前向きな声かけ＋立て直しの具体策を一緒に"})
        elif latest["meter_delta"] is not None and latest["meter_delta"] < 0:
            out.append({"sev": "mid", "cat": "メーター低下",
                        "why": f"直近メーター増減 {latest['meter_delta']}",
                        "action": "コア来場の維持と配信時間の確保を確認"})

    # 4) 5分未満NG配信の連発
    if st and st["ng_n"] >= 2:
        out.append({"sev": "low", "cat": "NG配信",
                    "why": f"5分未満で終了した支払対象外配信が {st['ng_n']} 件",
                    "action": "開始即終了の癖を確認。配信前の準備を整えてから開始するよう助言"})

    # 5) 運営同意が未取得
    if cur and cur["agreed"] == 0:
        out.append({"sev": "mid", "cat": "未同意",
                    "why": "運営同意フラグ=NO",
                    "action": "同意取得の案内（成績・コメント取得や各種運用に必要）"})

    return out


def liver_score(alerts):
    """ソート用スコア（high=100, mid=10, low=1 の合計）。"""
    w = {"high": 100, "mid": 10, "low": 1}
    return sum(w[a["sev"]] for a in alerts)


def main():
    as_json = "--json" in sys.argv[1:]
    show_all = "--all" in sys.argv[1:]

    conn = connect()
    ids = [r["user_id"] for r in conn.execute("SELECT user_id FROM livers ORDER BY user_id")]
    rows = []
    for uid in ids:
        data = load_liver(conn, uid)
        alerts = build_alerts(data)
        if not alerts and not show_all:
            continue
        alerts.sort(key=lambda a: SEV_ORDER[a["sev"]])
        rows.append({"user_id": uid, "name": data["liver"]["name"],
                     "score": liver_score(alerts), "alerts": alerts})
    conn.close()
    rows.sort(key=lambda r: -r["score"])

    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    if not rows:
        print("声かけが必要なライバーはいません（全員健全）。")
        return
    n_high = sum(1 for r in rows for a in r["alerts"] if a["sev"] == "high")
    print(f"━━━ 声かけリスト（{len(rows)}名 / 🔴重要 {n_high}件）━━━\n")
    for r in rows:
        if not r["alerts"]:
            print(f"✅ {r['name']}  — 健全\n")
            continue
        top = SEV_MARK[r["alerts"][0]["sev"]]
        print(f"{top} {r['name']}  (user_id={r['user_id']})")
        for a in r["alerts"]:
            print(f"   {SEV_MARK[a['sev']]} [{a['cat']}] {a['why']}")
            print(f"      → {a['action']}")
        print()


if __name__ == "__main__":
    main()
