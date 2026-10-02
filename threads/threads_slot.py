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

# ■ 早着なら待つ（2026-10-02 追加）
# cron は30分おき(1日48回)に置いているが、GitHub は高頻度 schedule を間引くので
# 実際に起動するのは1日4〜7回・3〜5時間おきだった。幅1時間50分の night 枠は
# この間隔だと素通りされ、9/20〜10/2 の13日で night 枠に出せたのは6日だけ。
# しかも 9/10以降の実測は night の story 中央118views / morning の story 33 と
# 夜のほうが3倍以上強い ＝ いちばん効く枠ばかり取りこぼしていた。
# 対策: 枠の開始前 WAIT_LOOKAHEAD_MIN 以内に起動した回は、ジョブ内で
# WAIT_TARGET まで sleep してから投稿する（PUBLICリポなので待ち時間も無料）。
# ホストランナーのジョブ上限は6時間なので、待ちは5時間半までに抑える。
WAIT_TARGET = {
    "morning": "09:05",  # 9時台 中央43 / 10時台 26
    "night": "22:00",    # 22時台 中央64 / 21時台 25
}
WAIT_LOOKAHEAD_MIN = 330


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


def plan_wait(posts=None, now_jst=None):
    """枠外に起動した回が「待てば次の枠に間に合う」なら (slot, 待ち秒数) を返す。

    待つ対象は、今日まだ消化していない枠のうち開始前 WAIT_LOOKAHEAD_MIN 以内の
    もの。日付をまたぐ待ち（23:40以降→翌朝）は、翌朝の判定が「今日」基準で
    ずれるので扱わない（00:00以降に起動した回が拾う）。
    """
    posts = load_posts() if posts is None else posts
    now_jst = now_jst or jst_now()
    done = posted_today(posts, now_jst)
    if len(done) >= MAX_PER_DAY:
        return None, 0
    used = {s for s, _dt in done}
    for slot, target in WAIT_TARGET.items():
        if slot in used:
            continue
        hh, mm = map(int, target.split(":"))
        at = now_jst.replace(hour=hh, minute=mm, second=0, microsecond=0)
        wait = (at - now_jst).total_seconds()
        if 0 < wait <= WAIT_LOOKAHEAD_MIN * 60:
            return slot, int(wait)
    return None, 0


def main():
    ap = argparse.ArgumentParser(description="Threads 投稿ウィンドウ判定")
    ap.add_argument("--check", action="store_true", help="判定結果を表示")
    ap.add_argument("--github-output", action="store_true",
                    help="GITHUB_OUTPUT に should_post / slot を書く")
    ap.parse_args()

    posts = load_posts()
    should, slot, reason = decide(posts)
    wait_sec = 0
    if not should and slot is None:
        wslot, wait_sec = plan_wait(posts)
        if wslot:
            should, slot = True, wslot
            reason += f" → {wslot}枠の {WAIT_TARGET[wslot]} まで {wait_sec // 60}分待って投稿"
    print(f"[GATE] should_post={str(should).lower()} slot={slot or '-'} :: {reason}")

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"should_post={str(should).lower()}\n")
            f.write(f"slot={slot or ''}\n")
            f.write(f"wait_sec={wait_sec}\n")
            f.write(f"reason={reason}\n")


if __name__ == "__main__":
    main()
