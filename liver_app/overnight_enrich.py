"""寝てる間用: 未qualified IGリードのプロフィールをAPIで取得し、bioを補填してauto-qualify"""
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import ig_api
from qualify import qualify_profile


DELAY = 1.2  # BAN避けのため控えめ
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overnight_log.txt")


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    cfg = db.all_settings()
    manual_cookie = cfg.get("ig_cookie_raw") or ""

    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT id, username, bio, target_type FROM leads
               WHERE status='未接触' AND qualified=0
               ORDER BY followers ASC"""
        ).fetchall()
    targets = [dict(r) for r in rows]
    log(f"開始: 対象 {len(targets)}件、delay={DELAY}s")

    fetched = 0
    qualified_count = 0
    errors = 0

    for i, lead in enumerate(targets, 1):
        username = lead["username"]
        # HTML モード優先（内部 API より rate limit に強い）、失敗時は内部 API にフォールバック
        try:
            profile = ig_api.fetch_profile_html(username)
            if not profile:
                profile = ig_api.fetch_profile(username, manual_cookie=manual_cookie)
        except ig_api.IGAuthError as e:
            log(f"認証エラーで中断: {e}")
            break
        except Exception as e:
            log(f"[{i}/{len(targets)}] @{username} エラー: {e}")
            errors += 1
            time.sleep(DELAY)
            continue

        if not profile:
            log(f"[{i}/{len(targets)}] @{username} プロフィール取得不可")
            time.sleep(DELAY)
            continue

        fetched += 1
        ttype = lead.get("target_type") or "beginner"
        passed, reasons = qualify_profile(profile, cfg, target_type=ttype)

        with db.get_conn() as conn:
            conn.execute(
                """UPDATE leads SET bio=?, followers=?, following=?,
                                    qualified=?, qualified_reasons=?
                   WHERE id=?""",
                (
                    (profile.get("biography") or "")[:500],
                    profile.get("followers"),
                    profile.get("following"),
                    1 if passed else 0,
                    json.dumps(reasons, ensure_ascii=False),
                    lead["id"],
                ),
            )
            conn.commit()

        if passed:
            qualified_count += 1

        if i % 10 == 0:
            log(f"進捗 {i}/{len(targets)} - 取得{fetched} 通過{qualified_count} エラー{errors}")

        time.sleep(DELAY)

    log(f"完了: 取得{fetched} 通過{qualified_count} エラー{errors} / 対象{len(targets)}")


if __name__ == "__main__":
    main()
