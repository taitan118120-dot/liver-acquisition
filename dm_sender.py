"""
DM自動送信モジュール

leads.csv のリードに対してテンプレートDMを送信する。
--dry-run でDMテキスト生成のみ（実際の送信なし）。
--copy-mode でコピペ用のDMテキストをターミナルに出力。
"""

import argparse
import csv
import os
import time
from datetime import datetime

import config


def load_template(target_type):
    """ターゲットタイプに応じたDMテンプレートを読み込む"""
    template_map = {
        "beginner": "templates/dm_beginner.txt",
        "existing": "templates/dm_existing.txt",
        "agency": "templates/dm_agency.txt",
    }
    path = template_map.get(target_type, template_map["beginner"])

    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def personalize_dm(template, lead):
    """テンプレートをリード情報でパーソナライズ"""
    return template.format(
        name=lead.get("name", ""),
        office_name=config.OFFICE_NAME,
        office_url=config.OFFICE_URL,
        contact_line=config.CONTACT_LINE,
    )


def get_unsent_leads(platform=None):
    """DM未送信のリードを取得"""
    if not os.path.exists(config.LEADS_CSV):
        print("leads.csv が見つかりません。先に lead_finder.py を実行してください。")
        return []

    leads = []
    with open(config.LEADS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["status"] == "未接触" and not row.get("dm_sent_date"):
                if platform and row["platform"] != platform:
                    continue
                leads.append(row)
    return leads


def update_lead_status(lead_id, status, dm_sent_date=None):
    """リードのステータスを更新"""
    rows = []
    with open(config.LEADS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if row["id"] == lead_id:
                row["status"] = status
                if dm_sent_date:
                    row["dm_sent_date"] = dm_sent_date
            rows.append(row)

    with open(config.LEADS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def log_dm(lead, message, platform, success):
    """DM送信ログを記録"""
    os.makedirs(os.path.dirname(config.DM_LOG_CSV), exist_ok=True)

    write_header = not os.path.exists(config.DM_LOG_CSV)
    with open(config.DM_LOG_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["timestamp", "lead_id", "username", "platform",
                             "target_type", "success", "message_preview"])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            lead["id"],
            lead["username"],
            platform,
            lead["target_type"],
            success,
            message[:100].replace("\n", " "),
        ])


# ============================================================
# コピペモード（API不要）
# ============================================================
def copy_mode(platform=None, limit=10):
    """DMテキストをターミナルに出力（手動送信用）"""
    leads = get_unsent_leads(platform)
    if not leads:
        print("送信対象のリードがありません。")
        return

    print(f"\n{'='*60}")
    print(f"  コピペ用DMテキスト ({len(leads[:limit])}件)")
    print(f"{'='*60}\n")

    for i, lead in enumerate(leads[:limit], 1):
        template = load_template(lead["target_type"])
        message = personalize_dm(template, lead)

        print(f"--- [{i}] {lead['name']} (@{lead['username']}) ---")
        print(f"プラットフォーム: {lead['platform']}")
        print(f"プロフィール: {lead['profile_url']}")
        print(f"タイプ: {lead['target_type']}")
        print(f"\n{message}")
        print(f"\n{'='*60}\n")


# ============================================================
# X (Twitter) DM送信
# ============================================================
def send_twitter_dm(lead, message, dry_run=False):
    """TwitterでDMを送信"""
    if dry_run:
        print(f"[DRY RUN] Twitter DM → @{lead['username']}")
        print(f"  メッセージ: {message[:80]}...")
        return True

    if not config.TWITTER_API_KEY:
        print("[ERROR] Twitter APIキーが設定されていません。")
        return False

    import tweepy

    auth = tweepy.OAuth1UserHandler(
        config.TWITTER_API_KEY,
        config.TWITTER_API_SECRET,
        config.TWITTER_ACCESS_TOKEN,
        config.TWITTER_ACCESS_TOKEN_SECRET,
    )
    api = tweepy.API(auth)

    try:
        # ユーザーIDを取得
        user_id = lead["id"].replace("tw_", "")
        api.send_direct_message(recipient_id=user_id, text=message)
        print(f"[Twitter] DM送信成功 → @{lead['username']}")
        return True
    except Exception as e:
        print(f"[Twitter] DM送信エラー → @{lead['username']}: {e}")
        return False


# ============================================================
# Instagram DM送信
# ============================================================
def send_instagram_dm(lead, message, dry_run=False, ig_client=None):
    """InstagramでDMを送信"""
    if dry_run:
        print(f"[DRY RUN] Instagram DM → @{lead['username']}")
        print(f"  メッセージ: {message[:80]}...")
        return True

    if not ig_client:
        if not config.INSTAGRAM_USERNAME:
            print("[ERROR] Instagram認証情報が設定されていません。")
            return False

        from instagrapi import Client
        ig_client = Client()
        ig_client.login(config.INSTAGRAM_USERNAME, config.INSTAGRAM_PASSWORD)

    try:
        user_id = lead["id"].replace("ig_", "")
        ig_client.direct_send(message, [int(user_id)])
        print(f"[Instagram] DM送信成功 → @{lead['username']}")
        return True
    except Exception as e:
        print(f"[Instagram] DM送信エラー → @{lead['username']}: {e}")
        return False


# ============================================================
# メイン送信ロジック
# ============================================================
def send_dms(platform=None, dry_run=False, limit=None):
    """リードにDMを送信"""
    leads = get_unsent_leads(platform)
    if not leads:
        print("送信対象のリードがありません。")
        return

    rate = config.DM_RATE_LIMIT
    sent_count = {"twitter": 0, "instagram": 0}

    ig_client = None

    for lead in leads:
        if limit and sum(sent_count.values()) >= limit:
            print(f"\n送信上限 ({limit}件) に達しました。")
            break

        p = lead["platform"]
        if sent_count[p] >= rate[p]["per_hour"]:
            print(f"[{p}] 1時間あたりの送信上限に達しました。")
            continue

        template = load_template(lead["target_type"])
        message = personalize_dm(template, lead)

        if p == "twitter":
            success = send_twitter_dm(lead, message, dry_run)
        elif p == "instagram":
            success = send_instagram_dm(lead, message, dry_run, ig_client)
        else:
            continue

        if success:
            sent_count[p] += 1
            now = datetime.now().strftime("%Y-%m-%d")
            if not dry_run:
                update_lead_status(lead["id"], "DM送信済", now)
            log_dm(lead, message, p, True)

        # レート制限: 送信間隔を空ける
        if not dry_run:
            interval = rate[p]["interval_sec"]
            print(f"  次の送信まで {interval}秒 待機...")
            time.sleep(interval)

    print(f"\n=== 送信結果 ===")
    print(f"Twitter: {sent_count['twitter']}件")
    print(f"Instagram: {sent_count['instagram']}件")


def main():
    parser = argparse.ArgumentParser(description="DM自動送信")
    parser.add_argument("--dry-run", action="store_true", help="送信せずにテスト実行")
    parser.add_argument("--copy-mode", action="store_true", help="コピペ用DM出力（API不要）")
    parser.add_argument("--platform", choices=["twitter", "instagram"], help="対象プラットフォーム")
    parser.add_argument("--limit", type=int, help="送信件数の上限")
    args = parser.parse_args()

    if args.copy_mode:
        copy_mode(platform=args.platform, limit=args.limit or 10)
    else:
        send_dms(platform=args.platform, dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
