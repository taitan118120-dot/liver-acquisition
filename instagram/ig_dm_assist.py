"""
Instagram DM 半自動アシスト

Claude が claude-in-chrome MCP 経由で IG の DM画面までを自動準備し、
ユーザーは送信ボタンを押すだけ。BAN安全な半自動フロー。

=== 送信前の精査基準（全て満たすもののみ送信）===
  数値基準:
    - フォロワー < 10,000
    - 1 <= followers、1 <= following
    - max(followers, following) / min(followers, following) <= 5
  プロフィール基準（Claudeが claude-in-chrome で目視判定）:
    - アイコン or 投稿で顔が確認できる
    - 日本人（外国籍NG）
    - 推定年齢 18〜40歳（高校生NG、40代以上NG）
    - ふくよかすぎない
    - プロフィールに「カーブアウト / carveout」所属の記載がない

使い方（Claude からの呼び出し想定）:
  # === 精査フェーズ ===
  # 次に精査すべきリード（未精査）を取得
  python3 instagram/ig_dm_assist.py check-next

  # 精査結果を記録（全項目は Claude が目視判定する）
  #   --face / --foreign / --overweight / --carveout / --age-ok = yes | no
  python3 instagram/ig_dm_assist.py qualify <lead_id> \\
      --followers 3500 --following 800 \\
      --face yes --foreign no --overweight no \\
      --age-ok yes --carveout no

  # === 送信フェーズ（精査通過済みのみ対象）===
  python3 instagram/ig_dm_assist.py next
  python3 instagram/ig_dm_assist.py next --template hourly_5k
  python3 instagram/ig_dm_assist.py next --template model_scout

  python3 instagram/ig_dm_assist.py mark-sent <lead_id>

  # === スマホ運用フェーズ（精査通過済み全員分を一括出力）===
  # 精査通過・未送信のIGリード全員分のDMをmdファイルに出力。
  # Mac → スマホに AirDrop/iCloud 共有して、IGアプリで1件ずつ貼付送信。
  python3 instagram/ig_dm_assist.py queue-md
  python3 instagram/ig_dm_assist.py queue-md --limit 10 --template beginner

  # スマホ送信完了後、複数IDを一括でマーク
  python3 instagram/ig_dm_assist.py bulk-mark-sent <id1> <id2> <id3> ...

  # === その他 ===
  python3 instagram/ig_dm_assist.py status
  python3 instagram/ig_dm_assist.py skip <lead_id> [--reason "理由"]
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from dm_sender import load_template, personalize_dm, update_lead_status, log_dm


QUALIFIED_FILE = "data/ig_qualified.json"
MAX_FOLLOWERS = 10000
MAX_RATIO = 5.0


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _read_leads():
    if not os.path.exists(config.LEADS_CSV):
        return []
    with open(config.LEADS_CSV, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_leads(rows, fieldnames):
    with open(config.LEADS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _load_qualified():
    if not os.path.exists(QUALIFIED_FILE):
        return {}
    with open(QUALIFIED_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_qualified(data):
    os.makedirs(os.path.dirname(QUALIFIED_FILE), exist_ok=True)
    with open(QUALIFIED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _count_sent_today():
    return sum(1 for r in _read_leads()
               if r["platform"] == "instagram" and r.get("dm_sent_date") == _today())


def _find_lead(lead_id):
    for row in _read_leads():
        if row["id"] == lead_id:
            return row
    return None


def _profile_url(lead):
    url = lead.get("profile_url", "")
    return url if url else f"https://www.instagram.com/{lead['username']}/"


def _check_criteria(followers, following, face, foreign, overweight, age_ok, carveout):
    """精査基準を全てチェック。通れば (True, []) / 落ちれば (False, [理由...])"""
    reasons = []
    if followers is None or following is None:
        reasons.append("数値未取得")
    else:
        if followers >= MAX_FOLLOWERS:
            reasons.append(f"フォロワー{followers}人（10000超）")
        if followers <= 0 or following <= 0:
            reasons.append("フォロワー/フォロー0以下")
        elif max(followers, following) / min(followers, following) > MAX_RATIO:
            reasons.append(f"比率{max(followers, following)/min(followers, following):.1f}倍（5倍超）")
    if face != "yes":
        reasons.append("顔写真なし")
    if foreign == "yes":
        reasons.append("外国籍")
    if overweight == "yes":
        reasons.append("ふくよか過ぎる")
    if age_ok != "yes":
        reasons.append("年齢18-40範囲外")
    if carveout == "yes":
        reasons.append("カーブアウト所属")
    return (len(reasons) == 0, reasons)


def cmd_check_next(args):
    """未精査のIGリードを1件返す（Claudeが claude-in-chrome で目視確認 → qualify コマンドを呼ぶ）"""
    qualified = _load_qualified()
    for row in _read_leads():
        if row["platform"] != "instagram":
            continue
        if row["status"] != "未接触":
            continue
        if row.get("dm_sent_date"):
            continue
        if row["id"] in qualified:
            continue
        print(json.dumps({
            "status": "ok",
            "lead_id": row["id"],
            "name": row["name"],
            "username": row["username"],
            "profile_url": _profile_url(row),
            "bio": row.get("bio", ""),
            "target_type": row["target_type"],
            "followers_hint": row.get("followers", ""),
            "next_step": (
                "このプロフィールを claude-in-chrome で開き、以下を目視で確認してから "
                "qualify コマンドを呼んでください: followers/following 数値、顔写真の有無、"
                "外国籍か、年齢18-40か、ふくよか過ぎないか、カーブアウト所属か"
            ),
        }, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps({"status": "empty", "message": "未精査のIGリードがありません"},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_qualify(args):
    """Claude の目視判定結果を記録。基準を満たせば精査通過、満たさなければ 見送り"""
    lead = _find_lead(args.lead_id)
    if not lead:
        print(json.dumps({"status": "error", "message": f"lead_id {args.lead_id} not found"},
                         ensure_ascii=False))
        return 1
    passed, reasons = _check_criteria(
        args.followers, args.following,
        args.face, args.foreign, args.overweight, args.age_ok, args.carveout,
    )
    qualified = _load_qualified()
    qualified[args.lead_id] = {
        "followers": args.followers,
        "following": args.following,
        "face_verified": args.face == "yes",
        "foreign": args.foreign == "yes",
        "overweight": args.overweight == "yes",
        "age_ok": args.age_ok == "yes",
        "carveout": args.carveout == "yes",
        "passed": passed,
        "reasons": reasons,
        "checked_at": _today(),
    }
    _save_qualified(qualified)

    # 基準を落としたら leads.csv を 見送り にして今後のキューから外す
    if not passed:
        rows = _read_leads()
        if rows:
            fieldnames = rows[0].keys()
            for r in rows:
                if r["id"] == args.lead_id:
                    r["status"] = "見送り"
                    note = (r.get("notes") or "")
                    r["notes"] = (note + f" | 精査NG:{','.join(reasons)}").strip(" |")
            _write_leads(rows, fieldnames)

    print(json.dumps({
        "status": "ok",
        "lead_id": args.lead_id,
        "passed": passed,
        "reasons": reasons,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_next(args):
    sent_today = _count_sent_today()
    daily_limit = config.DM_RATE_LIMIT["instagram"]["per_day"]
    if sent_today >= daily_limit:
        print(json.dumps({
            "status": "limit_reached",
            "sent_today": sent_today,
            "daily_limit": daily_limit,
            "message": f"本日の送信上限（{daily_limit}件）に到達",
        }, ensure_ascii=False, indent=2))
        return 0

    qualified = _load_qualified()
    candidates = [r for r in _read_leads()
                  if r["platform"] == "instagram"
                  and r["status"] == "未接触"
                  and not r.get("dm_sent_date")
                  and qualified.get(r["id"], {}).get("passed") is True]
    if args.target_type:
        candidates = [l for l in candidates if l["target_type"] == args.target_type]
    if not candidates:
        print(json.dumps({
            "status": "empty",
            "message": "送信可能な精査通過リードがありません。check-next → qualify を先に実行してください。",
        }, ensure_ascii=False, indent=2))
        return 0

    lead = candidates[0]

    if args.template:
        tpl_path = f"templates/dm_{args.template}.txt"
        if not os.path.exists(tpl_path):
            print(json.dumps({"status": "error", "message": f"テンプレ不明: {tpl_path}"},
                             ensure_ascii=False, indent=2))
            return 1
        with open(tpl_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        template = load_template(lead["target_type"])
    message = personalize_dm(template, lead)

    q = qualified.get(lead["id"], {})
    print(json.dumps({
        "status": "ok",
        "lead_id": lead["id"],
        "name": lead["name"],
        "username": lead["username"],
        "profile_url": _profile_url(lead),
        "target_type": lead["target_type"],
        "followers": q.get("followers"),
        "following": q.get("following"),
        "message": message,
        "sent_today": sent_today,
        "daily_limit": daily_limit,
        "remaining": daily_limit - sent_today,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_mark_sent(args):
    lead = _find_lead(args.lead_id)
    if not lead:
        print(json.dumps({"status": "error", "message": f"lead_id {args.lead_id} not found"},
                         ensure_ascii=False))
        return 1
    if lead["platform"] != "instagram":
        print(json.dumps({"status": "error", "message": "Instagramリードではありません"},
                         ensure_ascii=False))
        return 1
    if args.template:
        tpl_path = f"templates/dm_{args.template}.txt"
        with open(tpl_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        template = load_template(lead["target_type"])
    message = personalize_dm(template, lead)
    update_lead_status(args.lead_id, "DM送信済", _today())
    log_dm(lead, message, "instagram", True)
    print(json.dumps({
        "status": "ok",
        "lead_id": args.lead_id,
        "username": lead["username"],
        "sent_today": _count_sent_today(),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_queue_md(args):
    """精査通過・未送信のIGリード全員分のDMをmdファイルに出力（スマホ貼付運用）"""
    sent_today = _count_sent_today()
    daily_limit = config.DM_RATE_LIMIT["instagram"]["per_day"]
    remaining = max(0, daily_limit - sent_today)

    qualified = _load_qualified()
    candidates = [r for r in _read_leads()
                  if r["platform"] == "instagram"
                  and r["status"] == "未接触"
                  and not r.get("dm_sent_date")
                  and qualified.get(r["id"], {}).get("passed") is True]
    if args.target_type:
        candidates = [l for l in candidates if l["target_type"] == args.target_type]

    if not candidates:
        print(json.dumps({
            "status": "empty",
            "message": "送信可能な精査通過リードがありません。",
        }, ensure_ascii=False, indent=2))
        return 0

    # 本日上限を超えないように制限
    limit = args.limit if args.limit else remaining
    limit = min(limit, remaining)
    if limit <= 0:
        print(json.dumps({
            "status": "limit_reached",
            "sent_today": sent_today,
            "daily_limit": daily_limit,
            "message": f"本日の送信上限（{daily_limit}件）に到達",
        }, ensure_ascii=False, indent=2))
        return 0

    selected = candidates[:limit]

    # テンプレ読み込み
    if args.template:
        tpl_path = f"templates/dm_{args.template}.txt"
        if not os.path.exists(tpl_path):
            print(json.dumps({"status": "error", "message": f"テンプレ不明: {tpl_path}"},
                             ensure_ascii=False, indent=2))
            return 1
        with open(tpl_path, "r", encoding="utf-8") as f:
            template_default = f.read()
    else:
        template_default = None

    # md 生成
    today = _today()
    out_path = f"data/ig_dm_queue_{today}.md"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    lines = []
    lines.append(f"# IG DM送信キュー {today}")
    lines.append("")
    lines.append(f"- 対象: {len(selected)}件 / 本日残り送信可能: {remaining}件（上限{daily_limit}）")
    lines.append(f"- 運用: 「アプリで開く」リンクをタップ→IGアプリでプロフ表示→「メッセージ」→下のコードブロック長押しコピー→貼付→送信")
    lines.append(f"- ※ アプリで開くリンクが効かない端末はブラウザURLから開いてください")
    lines.append(f"- 送信完了後、Macで以下を実行:")
    lines.append("  ```")
    lines.append("  python3 instagram/ig_dm_assist.py bulk-mark-sent " +
                 " ".join(r["id"] for r in selected))
    lines.append("  ```")
    lines.append("")
    lines.append("---")
    lines.append("")

    for i, lead in enumerate(selected, 1):
        if template_default is not None:
            template = template_default
        else:
            template = load_template(lead["target_type"])
        message = personalize_dm(template, lead)
        q = qualified.get(lead["id"], {})

        profile_url = _profile_url(lead)
        app_url = f"instagram://user?username={lead['username']}"
        lines.append(f"## {i}. [@{lead['username']}]({profile_url}) （{lead['name']}）")
        lines.append("")
        lines.append(f"- 👉 **アプリで開く**: {app_url}")
        lines.append(f"- 🌐 ブラウザ: {profile_url}")
        lines.append(f"- フォロワー/フォロー: {q.get('followers')} / {q.get('following')}")
        if lead.get("bio"):
            lines.append(f"- Bio: {lead['bio']}")
        lines.append(f"- lead_id: `{lead['id']}`")
        lines.append("")
        lines.append("**DM本文（長押しコピー）**")
        lines.append("")
        lines.append("```")
        lines.append(message)
        lines.append("```")
        lines.append("")
        lines.append("- [ ] 送信済みチェック")
        lines.append("")
        lines.append("---")
        lines.append("")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(json.dumps({
        "status": "ok",
        "count": len(selected),
        "output": out_path,
        "lead_ids": [r["id"] for r in selected],
        "bulk_mark_cmd": "python3 instagram/ig_dm_assist.py bulk-mark-sent " +
                         " ".join(r["id"] for r in selected),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_bulk_mark_sent(args):
    """複数IDを一括で送信済みマーク"""
    results = []
    for lead_id in args.lead_ids:
        lead = _find_lead(lead_id)
        if not lead:
            results.append({"lead_id": lead_id, "status": "not_found"})
            continue
        if lead["platform"] != "instagram":
            results.append({"lead_id": lead_id, "status": "not_instagram"})
            continue
        if lead.get("dm_sent_date"):
            results.append({"lead_id": lead_id, "status": "already_sent"})
            continue
        if args.template:
            tpl_path = f"templates/dm_{args.template}.txt"
            with open(tpl_path, "r", encoding="utf-8") as f:
                template = f.read()
        else:
            template = load_template(lead["target_type"])
        message = personalize_dm(template, lead)
        update_lead_status(lead_id, "DM送信済", _today())
        log_dm(lead, message, "instagram", True)
        results.append({"lead_id": lead_id, "username": lead["username"], "status": "ok"})
    print(json.dumps({
        "status": "ok",
        "results": results,
        "sent_today": _count_sent_today(),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_skip(args):
    rows = _read_leads()
    if not rows:
        print(json.dumps({"status": "error", "message": "leads.csv が空"}, ensure_ascii=False))
        return 1
    fieldnames = rows[0].keys()
    found = False
    for r in rows:
        if r["id"] == args.lead_id:
            r["status"] = "見送り"
            note = (r.get("notes") or "")
            r["notes"] = (note + f" | skip:{args.reason}").strip(" |")
            found = True
    if not found:
        print(json.dumps({"status": "error", "message": f"lead_id {args.lead_id} not found"},
                         ensure_ascii=False))
        return 1
    _write_leads(rows, fieldnames)
    print(json.dumps({"status": "ok", "lead_id": args.lead_id, "action": "skipped"},
                     ensure_ascii=False))
    return 0


def cmd_status(args):
    sent_today = _count_sent_today()
    daily_limit = config.DM_RATE_LIMIT["instagram"]["per_day"]
    qualified = _load_qualified()
    rows = _read_leads()
    unsent = [r for r in rows if r["platform"] == "instagram" and r["status"] == "未接触"]
    qualified_queue = sum(1 for r in unsent if qualified.get(r["id"], {}).get("passed") is True)
    unchecked = sum(1 for r in unsent if r["id"] not in qualified)
    disqualified = sum(1 for r in rows
                       if r["platform"] == "instagram"
                       and qualified.get(r["id"], {}).get("passed") is False)
    print(json.dumps({
        "ig_sent_today": sent_today,
        "ig_daily_limit": daily_limit,
        "ig_remaining_today": max(0, daily_limit - sent_today),
        "ig_qualified_ready_to_send": qualified_queue,
        "ig_unchecked_need_qualify": unchecked,
        "ig_disqualified_total": disqualified,
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Instagram DM 半自動アシスト")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check-next", help="次に精査すべき未チェックリードを出力")
    p_check.set_defaults(func=cmd_check_next)

    p_q = sub.add_parser("qualify", help="精査結果を記録")
    p_q.add_argument("lead_id")
    p_q.add_argument("--followers", type=int, required=True)
    p_q.add_argument("--following", type=int, required=True)
    p_q.add_argument("--face", choices=["yes", "no"], required=True,
                     help="アイコンor投稿で顔が確認できるか")
    p_q.add_argument("--foreign", choices=["yes", "no"], required=True,
                     help="外国籍か（yesならNG）")
    p_q.add_argument("--overweight", choices=["yes", "no"], required=True,
                     help="ふくよかすぎるか（yesならNG）")
    p_q.add_argument("--age-ok", choices=["yes", "no"], required=True,
                     help="推定18-40歳か（noならNG）")
    p_q.add_argument("--carveout", choices=["yes", "no"], required=True,
                     help="カーブアウト所属か（yesならNG）")
    p_q.set_defaults(func=cmd_qualify)

    p_next = sub.add_parser("next", help="次に送る（精査通過）リードを出力")
    p_next.add_argument("--template", help="テンプレ名（hourly_5k | model_scout | beginner...）")
    p_next.add_argument("--target-type", help="target_type でフィルタ")
    p_next.set_defaults(func=cmd_next)

    p_mark = sub.add_parser("mark-sent", help="送信完了をマーク")
    p_mark.add_argument("lead_id")
    p_mark.add_argument("--template", help="ログ用テンプレ名（next と揃える）")
    p_mark.set_defaults(func=cmd_mark_sent)

    p_skip = sub.add_parser("skip", help="対象外としてスキップ")
    p_skip.add_argument("lead_id")
    p_skip.add_argument("--reason", default="manual_skip")
    p_skip.set_defaults(func=cmd_skip)

    p_qmd = sub.add_parser("queue-md", help="精査通過・未送信リードをmdファイルに出力（スマホ貼付用）")
    p_qmd.add_argument("--limit", type=int, help="最大件数（省略時は本日残り送信可能数）")
    p_qmd.add_argument("--template", help="テンプレ名（beginner | hourly_5k | model_scout ...）")
    p_qmd.add_argument("--target-type", help="target_type でフィルタ")
    p_qmd.set_defaults(func=cmd_queue_md)

    p_bulk = sub.add_parser("bulk-mark-sent", help="複数IDを一括で送信済みマーク")
    p_bulk.add_argument("lead_ids", nargs="+")
    p_bulk.add_argument("--template", help="ログ用テンプレ名")
    p_bulk.set_defaults(func=cmd_bulk_mark_sent)

    p_status = sub.add_parser("status", help="精査と送信の状況")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
