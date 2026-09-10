"""
Threads 投稿の「着弾時刻」ゲート

■ なぜ必要か（2026-09-10 に判明した実害）
GitHub Actions の schedule は指定時刻ちょうどには走らない。とくに毎時0分は
混雑してキューイングされる。threads_post.yml は JST 9:00 / 22:00 を狙って
UTC 0:00 / 13:00 に cron を置いていたが、実際の着弾は次のようにズレていた:

  8/26まで  JST 09:45 / 22:50 前後（遅延45〜50分）  → views 中央値 60前後
  8/27以降  JST 11:10 / 翌02:00 前後（遅延2〜4時間）→ views 中央値 24

data/threads_insights.csv の時刻別（JST・全期間）の中央値は
  9時 44.0 / 10時 24.0 / 22時 64.0 / 23時 56.0
に対して
  8時 16.5 / 11時 22.5 / 深夜1〜2時 33.5
なので、遅延によって「いちばん読まれない時間帯」に毎日2本とも落ちていた。
9月の中央値24は、この時刻崩れとほぼ完全に同期している。

■ 対策の考え方
cron の時刻を前倒ししても遅延幅が日によって2〜4時間変わるので制御できない。
そこで **cron は30分おきに終日打ち、投稿するかどうかはこのモジュールが
JSTの実時刻で決める**。遅延が何時間だろうと、ウィンドウ内に着弾する回が
必ず存在する。ウィンドウ外の回は数秒で何もせず終わる（PUBLICリポなので
Actions の実行時間課金はない）。

このモジュールは標準ライブラリだけで動く。ワークフローの最初のステップで
pip install より前に実行して、ウィンドウ外なら以降のステップを丸ごと飛ばす。

使い方:
  python threads/threads_slot.py --check        # 判定結果を表示（exit 0）
  python threads/threads_slot.py --check --github-output   # GITHUB_OUTPUT に書く
"""

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POSTS_FILE = os.path.join(SCRIPT_DIR, "threads_posts.json")

# 投稿を着地させたいJSTの時間帯。中心（9〜10時 / 22〜23時）が実測でいちばん強く、
# 端は「遅延で中心を外したときにここまでなら許容する」範囲。
# 8時台・11時台・21時台は実測で中央値が半分以下になるので入れない。
SLOTS = {
    "morning": ("09:00", "10:59"),
    "night": ("21:50", "23:40"),
}

# 1日に出す本数の上限。ウィンドウ判定をすり抜けて手動投稿した日でも
# 出しすぎないための最後の歯止め。
MAX_PER_DAY = 2


def jst_now():
    return datetime.now(timezone.utc).astimezone(JST)


def slot_of(dt_jst):
    """JSTのdatetimeがどのスロットに入るか。どこにも入らなければ None。"""
    hm = dt_jst.strftime("%H:%M")
    for name, (start, end) in SLOTS.items():
        if start <= hm <= end:
            return name
    return None


def _to_jst(value):
    """ISO8601文字列を JST の aware datetime にする。

    既存ログの posted_at は datetime.now().isoformat() で書かれた naive 値で、
    実体は GitHub ランナーの UTC。tzinfo が無いものは UTC とみなす。

    Graph API が返す timestamp は "+0000"（コロンなし）で、Python 3.11 未満の
    fromisoformat はこれを解釈できない。手元は3.9・CIは3.11なので、
    どちらでも同じ結果になるよう先に正規化する。
    """
    if not value:
        return None
    s = str(value).strip().replace("Z", "+00:00")
    s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(JST)


def load_posts(path=POSTS_FILE):
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def posted_today(posts, now_jst=None):
    """今日(JST)すでに投稿した本投稿の [(slot, JST時刻)] を返す。

    CTA返信は reply_media_id にしか記録されないので、ここには入らない
    （＝返信のせいで枠を消費したと誤判定することはない）。
    """
    now_jst = now_jst or jst_now()
    out = []
    for p in posts:
        dt = _to_jst(p.get("posted_at"))
        if dt is None or dt.date() != now_jst.date():
            continue
        out.append((slot_of(dt), dt))
    return out


def decide(posts=None, now_jst=None):
    """投稿してよいか判定して (should_post, slot, reason) を返す。"""
    posts = load_posts() if posts is None else posts
    now_jst = now_jst or jst_now()
    slot = slot_of(now_jst)
    stamp = now_jst.strftime("%Y-%m-%d %H:%M JST")

    if slot is None:
        windows = " / ".join(f"{k} {v[0]}-{v[1]}" for k, v in SLOTS.items())
        return False, None, f"{stamp} は投稿ウィンドウ外（{windows}）"

    done = posted_today(posts, now_jst)
    if len(done) >= MAX_PER_DAY:
        return False, slot, f"本日すでに{len(done)}本投稿済み（上限{MAX_PER_DAY}本）"

    used = [s for s, _dt in done]
    if slot in used:
        when = next(dt for s, dt in done if s == slot)
        return False, slot, f"{slot}枠は本日消化済み（{when:%H:%M} に投稿）"

    return True, slot, f"{stamp} は {slot} 枠（本日{len(done)}本投稿済み）"


def main():
    ap = argparse.ArgumentParser(description="Threads 投稿ウィンドウ判定")
    ap.add_argument("--check", action="store_true", help="判定結果を表示")
    ap.add_argument("--github-output", action="store_true",
                    help="GITHUB_OUTPUT に should_post / slot を書く")
    ap.parse_args()

    should, slot, reason = decide()
    print(f"[GATE] should_post={str(should).lower()} slot={slot or '-'} :: {reason}")

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"should_post={str(should).lower()}\n")
            f.write(f"slot={slot or ''}\n")
            f.write(f"reason={reason}\n")


if __name__ == "__main__":
    main()
