"""
リード管理モジュール

leads.csv のステータス管理、統計表示、フォローアップ対象の抽出を行う。
"""

import argparse
import csv
import os
from collections import Counter
from datetime import datetime, timedelta

import config


def load_leads():
    """全リードを読み込む"""
    if not os.path.exists(config.LEADS_CSV):
        print("leads.csv が見つかりません。")
        return []

    with open(config.LEADS_CSV, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def show_stats():
    """リード統計を表示"""
    leads = load_leads()
    if not leads:
        return

    total = len(leads)
    status_counts = Counter(l["status"] for l in leads)
    platform_counts = Counter(l["platform"] for l in leads)
    type_counts = Counter(l["target_type"] for l in leads)

    print(f"\n{'='*50}")
    print(f"  リード統計  (合計: {total}件)")
    print(f"{'='*50}")

    print("\n■ ステータス別:")
    for status in config.LEAD_STATUSES:
        count = status_counts.get(status, 0)
        bar = "█" * count
        print(f"  {status:<10} {count:>4}件  {bar}")

    print("\n■ プラットフォーム別:")
    for p, count in platform_counts.items():
        print(f"  {p:<12} {count:>4}件")

    print("\n■ ターゲットタイプ別:")
    for t, count in type_counts.items():
        label = {"beginner": "未経験者", "existing": "既存ライバー", "agency": "代理店"}.get(t, t)
        print(f"  {label:<12} {count:>4}件")

    # 変換率
    dm_sent = status_counts.get("DM送信済", 0) + status_counts.get("返信あり", 0) + \
              status_counts.get("面談予定", 0) + status_counts.get("面談済", 0) + \
              status_counts.get("契約", 0)
    replied = status_counts.get("返信あり", 0) + status_counts.get("面談予定", 0) + \
              status_counts.get("面談済", 0) + status_counts.get("契約", 0)
    contracted = status_counts.get("契約", 0)

    print(f"\n■ 変換率:")
    if dm_sent > 0:
        print(f"  返信率:   {replied/dm_sent*100:.1f}% ({replied}/{dm_sent})")
    if replied > 0:
        print(f"  契約率:   {contracted/replied*100:.1f}% ({contracted}/{replied})")
    print()


def show_followup():
    """フォローアップ対象を表示（DM送信後3日以上返信なし）"""
    leads = load_leads()
    today = datetime.now()
    followup_days = 3

    print(f"\n{'='*50}")
    print(f"  フォローアップ対象 ({followup_days}日以上返信なし)")
    print(f"{'='*50}\n")

    count = 0
    for lead in leads:
        if lead["status"] != "DM送信済":
            continue
        if not lead.get("dm_sent_date"):
            continue

        try:
            sent_date = datetime.strptime(lead["dm_sent_date"], "%Y-%m-%d")
        except ValueError:
            continue

        if (today - sent_date).days >= followup_days:
            count += 1
            days_ago = (today - sent_date).days
            print(f"  [{count}] {lead['name']} (@{lead['username']})")
            print(f"      {lead['platform']} | {lead['target_type']}")
            print(f"      DM送信: {lead['dm_sent_date']} ({days_ago}日前)")
            print(f"      {lead['profile_url']}")
            print()

    if count == 0:
        print("  フォローアップ対象はありません。")
    else:
        print(f"  合計: {count}件")


def update_status(username, new_status):
    """リードのステータスを更新"""
    if new_status not in config.LEAD_STATUSES:
        print(f"[ERROR] 無効なステータス: {new_status}")
        print(f"  有効なステータス: {', '.join(config.LEAD_STATUSES)}")
        return

    rows = []
    updated = False
    with open(config.LEADS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if row["username"] == username:
                old_status = row["status"]
                row["status"] = new_status
                updated = True
                print(f"更新: @{username} のステータスを '{old_status}' → '{new_status}' に変更")
            rows.append(row)

    if not updated:
        print(f"@{username} が見つかりません。")
        return

    with open(config.LEADS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def list_leads(status=None, platform=None, limit=20):
    """リード一覧を表示"""
    leads = load_leads()

    if status:
        leads = [l for l in leads if l["status"] == status]
    if platform:
        leads = [l for l in leads if l["platform"] == platform]

    print(f"\n{'='*70}")
    print(f"  リード一覧 ({len(leads)}件)")
    print(f"{'='*70}\n")

    for i, lead in enumerate(leads[:limit], 1):
        print(f"  [{i}] {lead['name']} (@{lead['username']})")
        print(f"      {lead['platform']} | {lead['target_type']} | {lead['status']}")
        print(f"      {lead['profile_url']}")
        if lead.get("notes"):
            print(f"      メモ: {lead['notes']}")
        print()

    if len(leads) > limit:
        print(f"  ... 他 {len(leads) - limit}件")


def export_json():
    """リードデータをJSON形式で出力（ダッシュボード用）"""
    leads = load_leads()

    status_counts = Counter(l["status"] for l in leads)
    platform_counts = Counter(l["platform"] for l in leads)
    type_counts = Counter(l["target_type"] for l in leads)

    import json
    data = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(leads),
        "status_counts": dict(status_counts),
        "platform_counts": dict(platform_counts),
        "type_counts": dict(type_counts),
        "leads": leads,
    }

    output_path = "data/dashboard_data.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"ダッシュボードデータを {output_path} に出力しました。")


def main():
    parser = argparse.ArgumentParser(description="リード管理")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("stats", help="統計表示")
    sub.add_parser("followup", help="フォローアップ対象表示")
    sub.add_parser("export", help="ダッシュボード用JSON出力")

    list_parser = sub.add_parser("list", help="リード一覧")
    list_parser.add_argument("--status", help="ステータスでフィルタ")
    list_parser.add_argument("--platform", choices=["twitter", "instagram"])
    list_parser.add_argument("--limit", type=int, default=20)

    update_parser = sub.add_parser("update", help="ステータス更新")
    update_parser.add_argument("username", help="ユーザー名")
    update_parser.add_argument("status", help="新しいステータス")

    args = parser.parse_args()

    if args.command == "stats":
        show_stats()
    elif args.command == "followup":
        show_followup()
    elif args.command == "list":
        list_leads(status=args.status, platform=args.platform, limit=args.limit)
    elif args.command == "update":
        update_status(args.username, args.status)
    elif args.command == "export":
        export_json()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
