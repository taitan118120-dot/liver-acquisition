"""
リード検索・抽出モジュール

X(Twitter) と Instagram からライバー候補を検索し、leads.csv に保存する。
--dry-run オプションでAPI呼び出しなしのテスト実行が可能。
"""

import argparse
import csv
import os
from datetime import datetime

import config


def init_leads_csv():
    """leads.csv が存在しなければヘッダー付きで作成"""
    os.makedirs(os.path.dirname(config.LEADS_CSV), exist_ok=True)
    if not os.path.exists(config.LEADS_CSV):
        with open(config.LEADS_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "id", "name", "username", "platform", "profile_url",
                "bio", "followers", "target_type", "gender", "status",
                "found_date", "dm_sent_date", "likes_sent", "notes"
            ])


def load_existing_ids():
    """既存リードのIDセットを返す（重複チェック用）"""
    if not os.path.exists(config.LEADS_CSV):
        return set()
    with open(config.LEADS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["id"] for row in reader}


LEADS_CSV_FIELDS = [
    "id", "name", "username", "platform", "profile_url",
    "bio", "followers", "target_type", "gender", "status",
    "found_date", "dm_sent_date", "likes_sent", "notes",
]


def save_leads(leads):
    """リードをCSVに追記（ヘッダー14列に完全一致）"""
    existing_ids = load_existing_ids()
    new_leads = [l for l in leads if l["id"] not in existing_ids]

    if not new_leads:
        print("新規リードはありませんでした。")
        return 0

    with open(config.LEADS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LEADS_CSV_FIELDS, extrasaction="ignore")
        for lead in new_leads:
            # 欠けているカラムは空文字で埋める
            row = {k: lead.get(k, "") for k in LEADS_CSV_FIELDS}
            writer.writerow(row)

    print(f"{len(new_leads)}件の新規リードを保存しました。")
    return len(new_leads)


def is_agency_member(bio):
    """事務所所属ライバーかどうか判定（所属中ならTrue → DM対象外）"""
    if not bio:
        return False
    bio_lower = bio.lower()
    skip_keywords = [
        "所属", "事務所所属", "専属", "公式ライバー",
        "〇〇事務所", "ライバー事務所", "マネジメント契約",
        "nextwave", "321", "ベガプロ", "ライバージャパン",
        "prime", "エベレスト", "ワンカラット", "viiibar",
    ]
    for kw in skip_keywords:
        if kw in bio_lower:
            return True
    return False


def classify_target(bio):
    """プロフィールからターゲットタイプを推定（ライバー向けフロー）"""
    bio_lower = bio.lower() if bio else ""

    agency_keywords = ["代理店", "エージェント", "マネジメント", "事務所", "プロダクション", "法人"]
    for kw in agency_keywords:
        if kw in bio_lower:
            return "agency"

    existing_keywords = ["配信中", "ライバー", "配信者", "pococha", "17live", "showroom",
                         "イチナナ", "ポコチャ", "配信", "ライブ"]
    for kw in existing_keywords:
        if kw in bio_lower:
            return "existing"

    return "beginner"


def classify_agency_prospect(bio):
    """代理店志望者かどうかを簡易判定して target_type を返す

    - 副業・脱サラ・起業・独立・フリーランス・営業など、AGENCY_TARGET_BIO_KEYWORDS
      にヒットした場合は "agency_prospect_hot"（本命）
    - ヒットしなければ "agency_prospect"（キーワード検索に引っかかった広義の候補）
    """
    if not bio:
        return "agency_prospect"
    bio_lower = bio.lower()
    for kw in getattr(config, "AGENCY_TARGET_BIO_KEYWORDS", []):
        if kw.lower() in bio_lower:
            return "agency_prospect_hot"
    return "agency_prospect"


# ============================================================
# X (Twitter) 検索
# ============================================================
def search_twitter(dry_run=False, target="liver"):
    """Xでキーワード検索してリード候補を取得

    target="liver"  : ライバー候補を探す（既存フロー）
    target="agency" : 代理店パートナー候補（副業・独立志向の人）を探す
    """
    if dry_run:
        print(f"[DRY RUN] Twitter検索をシミュレート (target={target})")
        if target == "agency":
            return [
                {
                    "id": "tw_demo_agency_001",
                    "name": "テスト副業ユーザー",
                    "username": "test_sidejob_1",
                    "platform": "twitter",
                    "profile_url": "https://x.com/test_sidejob_1",
                    "bio": "副業で月10万目指してます。独立したい30代",
                    "followers": 420,
                    "target_type": "agency_prospect_hot",
                    "status": "未接触",
                    "found_date": datetime.now().strftime("%Y-%m-%d"),
                    "dm_sent_date": "",
                    "notes": "キーワード: 副業 月10万 (agency)",
                },
                {
                    "id": "tw_demo_agency_002",
                    "name": "テスト営業マン",
                    "username": "test_sales_2",
                    "platform": "twitter",
                    "profile_url": "https://x.com/test_sales_2",
                    "bio": "営業12年目。ストック収入ほしい",
                    "followers": 1200,
                    "target_type": "agency_prospect_hot",
                    "status": "未接触",
                    "found_date": datetime.now().strftime("%Y-%m-%d"),
                    "dm_sent_date": "",
                    "notes": "キーワード: ストック収入 (agency)",
                },
            ]
        return [
            {
                "id": "tw_demo_001",
                "name": "テストユーザー1",
                "username": "test_user_1",
                "platform": "twitter",
                "profile_url": "https://x.com/test_user_1",
                "bio": "ライブ配信に興味あります！",
                "followers": 150,
                "target_type": "beginner",
                "status": "未接触",
                "found_date": datetime.now().strftime("%Y-%m-%d"),
                "dm_sent_date": "",
                "notes": "キーワード: ライブ配信 興味",
            },
            {
                "id": "tw_demo_002",
                "name": "テストユーザー2",
                "username": "test_liver_2",
                "platform": "twitter",
                "profile_url": "https://x.com/test_liver_2",
                "bio": "Pocochaで毎日配信中！",
                "followers": 2300,
                "target_type": "existing",
                "status": "未接触",
                "found_date": datetime.now().strftime("%Y-%m-%d"),
                "dm_sent_date": "",
                "notes": "キーワード: Pococha 配信",
            },
        ]

    if not config.TWITTER_BEARER_TOKEN:
        print("[ERROR] Twitter APIキーが設定されていません。config.py を確認してください。")
        return []

    import tweepy

    client = tweepy.Client(bearer_token=config.TWITTER_BEARER_TOKEN)
    leads = []

    if target == "agency":
        keywords = getattr(config, "AGENCY_TWITTER_KEYWORDS", [])
        # 代理店志望者を探すフローでは「ライバー事務所所属者スキップ」は不要
        # （むしろライバー経験者は代理店として強い）
        skip_agency_members = False
    else:
        keywords = getattr(config, "TWITTER_SEARCH_KEYWORDS", [])
        skip_agency_members = True

    if not keywords:
        print(f"[Twitter] 検索キーワードが設定されていません (target={target})")
        return []

    for keyword in keywords:
        try:
            response = client.search_recent_tweets(
                query=f"{keyword} -is:retweet lang:ja",
                max_results=20,
                tweet_fields=["author_id", "created_at"],
                user_fields=["name", "username", "description", "public_metrics"],
                expansions=["author_id"],
            )

            if not response.data:
                continue

            users = {u.id: u for u in (response.includes.get("users", []))}

            for tweet in response.data:
                user = users.get(tweet.author_id)
                if not user:
                    continue

                # 事務所所属ライバーはスキップ（ライバー勧誘時のみ、法的リスク回避）
                if skip_agency_members and is_agency_member(user.description or ""):
                    print(f"  [スキップ] @{user.username} - 事務所所属の可能性あり")
                    continue

                if target == "agency":
                    target_type = classify_agency_prospect(user.description or "")
                    note_suffix = " (agency)"
                else:
                    target_type = classify_target(user.description or "")
                    note_suffix = ""

                leads.append({
                    "id": f"tw_{user.id}",
                    "name": user.name,
                    "username": user.username,
                    "platform": "twitter",
                    "profile_url": f"https://x.com/{user.username}",
                    "bio": (user.description or "")[:200],
                    "followers": user.public_metrics.get("followers_count", 0),
                    "target_type": target_type,
                    "status": "未接触",
                    "found_date": datetime.now().strftime("%Y-%m-%d"),
                    "dm_sent_date": "",
                    "notes": f"キーワード: {keyword}{note_suffix}",
                })

            print(f"[Twitter] '{keyword}' で {len(response.data)} 件取得")

        except Exception as e:
            print(f"[Twitter] '{keyword}' の検索でエラー: {e}")

    return leads


# ============================================================
# Instagram 検索
# ============================================================
def search_instagram(dry_run=False, target="liver"):
    """Instagramでハッシュタグ検索してリード候補を取得

    target="liver"  : ライバー候補（既存フロー、INSTAGRAM_HASHTAGS を使用）
    target="agency" : 代理店パートナー候補（AGENCY_INSTAGRAM_HASHTAGS を使用）
    """
    if dry_run:
        print(f"[DRY RUN] Instagram検索をシミュレート (target={target})")
        if target == "agency":
            return [
                {
                    "id": "ig_demo_agency_001",
                    "name": "副業準備中のテスト",
                    "username": "ig_sidejob_test",
                    "platform": "instagram",
                    "profile_url": "https://instagram.com/ig_sidejob_test",
                    "bio": "副業女子｜在宅ワークで月10万目指す",
                    "followers": 680,
                    "target_type": "agency_prospect_hot",
                    "status": "未接触",
                    "found_date": datetime.now().strftime("%Y-%m-%d"),
                    "dm_sent_date": "",
                    "notes": "ハッシュタグ: #副業女子 (agency)",
                },
            ]
        return [
            {
                "id": "ig_demo_001",
                "name": "IGテストユーザー",
                "username": "ig_test_user",
                "platform": "instagram",
                "profile_url": "https://instagram.com/ig_test_user",
                "bio": "配信者になりたい！",
                "followers": 500,
                "target_type": "beginner",
                "status": "未接触",
                "found_date": datetime.now().strftime("%Y-%m-%d"),
                "dm_sent_date": "",
                "notes": "ハッシュタグ: #ライバー募集",
            },
        ]

    if not config.INSTAGRAM_USERNAME or not config.INSTAGRAM_PASSWORD:
        print("[ERROR] Instagram認証情報が設定されていません。config.py を確認してください。")
        return []

    from instagrapi import Client

    cl = Client()
    try:
        cl.login(config.INSTAGRAM_USERNAME, config.INSTAGRAM_PASSWORD)
    except Exception as e:
        print(f"[Instagram] ログインエラー: {e}")
        return []

    leads = []

    if target == "agency":
        hashtags = getattr(config, "AGENCY_INSTAGRAM_HASHTAGS", [])
    else:
        hashtags = getattr(config, "INSTAGRAM_HASHTAGS", [])

    if not hashtags:
        print(f"[Instagram] ハッシュタグが設定されていません (target={target})")
        return []

    for hashtag in hashtags:
        try:
            medias = cl.hashtag_medias_recent(hashtag, amount=20)

            seen_users = set()
            for media in medias:
                user_id = media.user.pk
                if user_id in seen_users:
                    continue
                seen_users.add(user_id)

                try:
                    user_info = cl.user_info(user_id)
                except Exception:
                    continue

                if target == "agency":
                    target_type = classify_agency_prospect(user_info.biography or "")
                    note_suffix = " (agency)"
                else:
                    target_type = classify_target(user_info.biography or "")
                    note_suffix = ""

                leads.append({
                    "id": f"ig_{user_id}",
                    "name": user_info.full_name or user_info.username,
                    "username": user_info.username,
                    "platform": "instagram",
                    "profile_url": f"https://instagram.com/{user_info.username}",
                    "bio": (user_info.biography or "")[:200],
                    "followers": user_info.follower_count,
                    "target_type": target_type,
                    "status": "未接触",
                    "found_date": datetime.now().strftime("%Y-%m-%d"),
                    "dm_sent_date": "",
                    "notes": f"ハッシュタグ: #{hashtag}{note_suffix}",
                })

            print(f"[Instagram] '#{hashtag}' で {len(seen_users)} 件取得")

        except Exception as e:
            print(f"[Instagram] '#{hashtag}' の検索でエラー: {e}")

    return leads


def main():
    parser = argparse.ArgumentParser(description="ライバー・代理店パートナー候補リード検索")
    parser.add_argument("--dry-run", action="store_true", help="APIを呼ばずにテスト実行")
    parser.add_argument("--twitter-only", action="store_true", help="Twitterのみ検索")
    parser.add_argument("--instagram-only", action="store_true", help="Instagramのみ検索")
    parser.add_argument(
        "--target",
        choices=["liver", "agency", "both"],
        default="liver",
        help="検索対象: liver=ライバー候補(デフォルト), agency=代理店志望者, both=両方",
    )
    args = parser.parse_args()

    init_leads_csv()

    targets = ["liver", "agency"] if args.target == "both" else [args.target]
    all_leads = []

    for t in targets:
        print(f"\n########## target={t} ##########")

        if not args.instagram_only:
            print(f"=== X (Twitter) 検索開始 [{t}] ===")
            tw_leads = search_twitter(dry_run=args.dry_run, target=t)
            all_leads.extend(tw_leads)
            print(f"Twitter[{t}]: {len(tw_leads)}件のリード候補")

        if not args.twitter_only:
            print(f"\n=== Instagram 検索開始 [{t}] ===")
            ig_leads = search_instagram(dry_run=args.dry_run, target=t)
            all_leads.extend(ig_leads)
            print(f"Instagram[{t}]: {len(ig_leads)}件のリード候補")

    print(f"\n=== 合計: {len(all_leads)}件のリード候補 ===")
    saved = save_leads(all_leads)
    print(f"新規保存: {saved}件")


if __name__ == "__main__":
    main()
