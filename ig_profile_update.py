#!/usr/bin/env python3
"""ig_profile_update.py — Instagram @taitan_pro7 のプロフィールを正本へ反映（試行）
=====================================================================
背景（2026-08-09）:
  `social_profile_guard.py` が IG @taitan_pro7 の bio に確定ファクト違反4点
  （現役ライバー／累計150名の育成／傘下11代理店を統括／DMでご相談）を毎日検出している。
  これは X が 2026-08-01 に捨てた旧文面がそのまま別媒体で生き延びていたもの。

  過去メモには「Instagram Graph API はプロフィールが読み取り専用」と書かれているが、
  **実際に書き込みを試した記録が無い**（ドキュメントを読んだ結論だった）。
  「トークンが無いから無理」が誤りだった x_profile_update.py の前例があるので、
  同じ轍を踏まないよう **実際に POST を投げて結果を記録する** のがこのスクリプト。

文面の出所:
  **正本 `marketing/social_profiles.md` から直接パースする**。
  x_profile_update.py は文面をスクリプト内にも埋め込んでいるため「両方直す」必要があり、
  片方だけ直すと必ずズレる。ここでは正本1箇所だけを直せば済むようにした。

使い方:
  python3 ig_profile_update.py --dry-run   # 反映内容と文字数を出すだけ（トークン不要な部分まで）
  python3 ig_profile_update.py             # 実際に書き込みを試みる

必要な環境変数（GitHub Secrets から注入）:
  INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ID
"""

import os
import sys

import requests

from social_profile_guard import IG_GRAPH, norm, parse_canonical

CANON_KEY = "ig_taitan_pro7"
EXPECT_USERNAME = "taitan_pro7"

# 実物に書き込むフィールド → Graph API のパラメータ名
FIELD_PARAM = {"name": "name", "bio": "biography", "link": "website"}
# IG の入力欄の上限（超えるとアプリ側でも弾かれる）
FIELD_LIMIT = {"name": 30, "bio": 150}


def fetch_live(token, biz):
    r = requests.get(f"{IG_GRAPH}/{biz}",
                     params={"fields": "username,name,biography,website",
                             "access_token": token}, timeout=30)
    r.raise_for_status()
    d = r.json()
    return {"username": d.get("username", ""), "name": d.get("name", ""),
            "bio": d.get("biography", ""), "link": d.get("website", "")}


def main():
    dry = "--dry-run" in sys.argv

    canon = parse_canonical().get(CANON_KEY, {})
    if not canon:
        print(f"❌ 正本に {CANON_KEY} の節が見つかりません（見出しを変えた？）")
        return 1

    print("== 正本（marketing/social_profiles.md）==")
    for f in ("name", "bio", "link"):
        v = canon.get(f)
        if v is None:
            print(f"  [{f}] （正本に無し）")
            continue
        lim = FIELD_LIMIT.get(f)
        over = f" ⚠️ {lim}字制限オーバー" if lim and len(v) > lim else ""
        print(f"  [{f}] {len(v)}字{over}\n{v}")

    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    biz = os.environ.get("INSTAGRAM_BUSINESS_ID", "").strip()
    if not (token and biz):
        print("\n⏭ INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ID 未設定 → 書き込みは試行しません")
        return 0 if dry else 1

    live = fetch_live(token, biz)
    got = (live.get("username") or "").lstrip("@")
    if got.lower() != EXPECT_USERNAME.lower():
        # トークンが別アカウントを指したまま書き込むと、無関係なアカウントを壊す
        print(f"❌ トークンが @{got} を指しています（期待 @{EXPECT_USERNAME}）。中止します")
        return 1

    print(f"\n== 実物（@{got}）==")
    for f in ("name", "bio", "link"):
        print(f"  [{f}] {live.get(f, '')!r}")

    todo = [f for f in ("name", "bio", "link")
            if canon.get(f) is not None and norm(canon[f]) != norm(live.get(f, ""))]
    if not todo:
        print("\n✅ 実物は既に正本と一致しています（書き込み不要）")
        return 0
    print(f"\n更新が必要なフィールド: {todo}")

    if dry:
        print("--dry-run のため書き込みは行いません")
        return 0

    # Graph API に IG プロフィール更新の公式エンドポイントは見当たらないが、
    # 「無いはず」で終わらせず実際に投げて、返ってきたエラーを証拠として残す。
    attempts = [
        ("POST /{ig-user-id}（全フィールド）",
         {FIELD_PARAM[f]: canon[f] for f in todo}),
        ("POST /{ig-user-id}（biography のみ）",
         {"biography": canon["bio"]} if "bio" in todo else None),
    ]
    ok = False
    for label, params in attempts:
        if not params:
            continue
        r = requests.post(f"{IG_GRAPH}/{biz}",
                          data={**params, "access_token": token}, timeout=30)
        print(f"\n-- {label} → HTTP {r.status_code}\n   {r.text[:400]}")
        if r.status_code == 200:
            ok = True
            break

    after = fetch_live(token, biz)
    print("\n== 書き込み後に再取得 ==")
    for f in ("name", "bio", "link"):
        print(f"  [{f}] {after.get(f, '')!r}")

    remaining = [f for f in todo if norm(canon[f]) != norm(after.get(f, ""))]
    if not remaining:
        print("\n✅ 正本どおりに反映されました")
        return 0

    print(f"\n❌ 反映されませんでした（未反映: {remaining}）")
    print("   → Instagram Graph API はプロフィール（名前・bio・リンク）が読み取り専用。"
          "アプリ／Web から手動で更新してください。")
    # 「APIで直せない」ことの確認自体は成功なので、ここは 0 を返さず 2 で区別する
    return 2 if not ok else 1


if __name__ == "__main__":
    sys.exit(main())
