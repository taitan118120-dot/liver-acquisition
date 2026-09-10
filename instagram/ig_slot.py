"""
Instagram 投稿の「着弾時刻」ゲート

■ なぜ必要か（2026-09-11 に確認した実害）
instagram_post.yml の cron は `0 11 * * 1,3,5`（JST 月/水/金 20:00 狙い）だが、
GitHub Actions の schedule 遅延が 2026-08-27 以降に一気に伸びて、実際の着弾は
深夜0時前後に固定されていた。ラン作成時刻(JST)の実測:

  08-17 Mon 20:22 / 08-19 Wed 20:22 / 08-21 Fri 20:22 / 08-24 Mon 20:25
  08-26 Wed 20:26   ←ここまで遅延22〜26分。狙いどおり20時台に着弾していた
  08-29 Sat 06:18（Fri分・遅延10h18m）
  09-01 Tue 02:52（Mon分・遅延6h52m）
  09-02 Wed 23:57（遅延3h57m）
  09-04 Fri 23:46（遅延3h46m）
  09-08 Tue 01:16（Mon分・遅延5h16m）
  09-10 Thu 00:00（Wed分・遅延4h00m）

同じ悪化が Threads 側でも起きていて、そちらは時刻別の実測でリーチ中央値が
3倍近く違った（[[project_threads_automation]] / threads/threads_slot.py 参照）。

■ 狙う時間帯の根拠（重要・暫定値）
Instagram には時刻別リーチの実測がまだ無い。
  - data/ig_insights.csv は 2026-08-10 に「全指標0」で削除済み（権限不足で
    reach=0 が書かれていたため。commit 4b0a870）
  - 以降 instagram_insights.yml は毎週失敗し続けている
    （`(#10) Application does not have permission for this action`
      ＝ instagram_manage_insights の権限が付いていない）
したがって現時点の窓は **実測ではなく一般的なゴールデンタイム(JST 20-22時)** と、
元の cron が狙っていた 20:00 に合わせた暫定値である。
instagram_manage_insights を付与して data/ig_insights.csv が貯まったら、
Threads と同じように時刻別の中央値を出して WINDOW を測り直すこと。

■ 対策の考え方（Threads と同じ）
cron の時刻を前倒ししても遅延幅が日によって 22分〜10時間と変わるので制御できない。
そこで **cron は30分おきに終日打ち、投稿するかどうかはこのモジュールが
JSTの実時刻で決める**。遅延が何時間だろうと、ウィンドウ内に着弾する回が必ず出る。
ウィンドウ外の回は数秒で何もせず終わる（PUBLICリポなので実行時間課金はない）。

このモジュールは標準ライブラリだけで動く。ワークフローの最初のステップで
pip install より前に実行して、ウィンドウ外なら以降のステップを丸ごと飛ばす。

※ threads/threads_slot.py とは意図的に別ファイルにしてある。共通なのは JST 変換
   まわりの数十行だけで、判定ルール自体は別物（Threads=1日2枠、IG=曜日指定で
   1日1本）。稼働中の Threads 側を触るリスクの方が大きいので共通化していない。

使い方:
  python3 instagram/ig_slot.py --check     # 今投稿してよいか判定
  python3 instagram/ig_slot.py --missed    # 投稿を落とした投稿曜日を列挙（番犬用）
  どちらも GITHUB_OUTPUT があれば自動で書き出す
"""

import argparse
import json
import os
import re
from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POSTS_FILE = os.path.join(SCRIPT_DIR, "ig_posts.json")

# 投稿する曜日（JST）。Python の weekday() は 月=0 … 日=6。
# 元の cron `0 11 * * 1,3,5`（月/水/金）を維持する。
# IGからのセキュリティ警告を受けて週3回に落とした経緯があるので増やさないこと
# （2026-05-16 / [[feedback_ig_post_safety]]）。
POST_WEEKDAYS = (0, 2, 4)
WEEKDAY_JA = ("月", "火", "水", "木", "金", "土", "日")

# 投稿を着地させたいJSTの時間帯。
#
# 頭を 19:50 にしているのは、20:00 ちょうどを狙うと 19:5x に着弾した回を
# 捨てることになるため。頭はこれ以上早めないこと（もっと早い時刻に着弾した回が
# その日の枠を取ってしまい、ゴールデンタイムを外す）。
#
# 尻が 23:40 なのは「保険」で、狙いは今も20〜22時台。
# 2026-09-11 に cron を30分おきにして実測したところ、GitHub は30分ごとには
# 起動してくれない。**scheduleランの実配信間隔は 149分 / 163分**だった
#   IG      19:04:45 → 21:34:24 UTC（149分）
#   Threads 18:29:02 → 21:12:45 UTC（163分）
# 遅延したランがキューに残ると後続の schedule イベントが捨てられるため。
# （cron を変えてから最初のランまでは3時間半かかったが、これは cron の拾い上げ
#   待ちで、定常状態の間隔ではない。）
# つまり窓が2時間40分だと最悪の間隔(163分)を下回るので、その日どのランも
# 窓に入らず0本になる日が出る。窓を3時間50分(230分)取れば、実測の最大間隔でも
# 必ず1回は窓の中に着弾する。
# 「窓の中に入った最初の1回だけ投稿する」ルールなので、尻を伸ばしても
# 20:30 に着弾した日はちゃんと20:30に出る。尻が効くのは
# 「22:30までに1回も来なかった日」だけ＝取りこぼしの保険としてだけ働く。
# 日付をまたがせない（跨ぐと翌日の枠を食う）ため 23:40 で止める。
WINDOW = ("19:50", "23:40")

# 1日（JST）に出す上限。ログのpushに失敗した直後の回で二重投稿しないための歯止め。
MAX_PER_DAY = 1

# このゲートが効き始めた日（JST）。番犬がこれより前の日を「投稿を落とした日」と
# 数えないようにするための線引き。切替前は遅延したぶん深夜に着弾していただけで
# 投稿自体は出ているので、過去分を欠けとして数えると初回から誤検知になる。
EFFECTIVE_FROM = date(2026, 9, 11)


def jst_now():
    return datetime.now(timezone.utc).astimezone(JST)


def in_window(dt_jst):
    """JSTのdatetimeが投稿ウィンドウの時刻帯に入っているか。"""
    hm = dt_jst.strftime("%H:%M")
    return WINDOW[0] <= hm <= WINDOW[1]


def _to_jst(value):
    """ISO8601文字列を JST の aware datetime にする。

    ig_posts.json の posted_at は `datetime.now().astimezone().isoformat()` で
    書かれる（CIでは +00:00、手元実行では +09:00）。念のため tzinfo が無い値は
    UTC とみなす（CIで書かれた古い形式に合わせる）。

    "+0000"（コロンなし）は Python 3.11 未満の fromisoformat が解釈できない。
    手元は3.9・CIは3.11なので、どちらでも同じ結果になるよう先に正規化する。
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
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def posted_datetimes(posts):
    """実際に投稿が成立した時刻(JST)を新しい順で返す。

    posted_at は ig_poster.post_next が投稿成功時にだけ書く値なので、
    「生成しただけ」「投稿に失敗した」分がここに混ざることはない。
    """
    out = []
    for p in posts:
        dt = _to_jst(p.get("posted_at"))
        if dt is not None:
            out.append(dt)
    return sorted(out, reverse=True)


def posted_on(posts, date_jst):
    """指定したJSTの日付に投稿した時刻の一覧。"""
    return [dt for dt in posted_datetimes(posts) if dt.date() == date_jst]


def decide(posts=None, now_jst=None):
    """投稿してよいか判定して (should_post, slot, reason) を返す。"""
    posts = load_posts() if posts is None else posts
    now_jst = now_jst or jst_now()
    stamp = f"{now_jst:%Y-%m-%d %H:%M} JST({WEEKDAY_JA[now_jst.weekday()]})"
    days = "/".join(WEEKDAY_JA[w] for w in POST_WEEKDAYS)

    if now_jst.weekday() not in POST_WEEKDAYS:
        return False, None, f"{stamp} は投稿曜日ではない（{days}のみ）"

    if not in_window(now_jst):
        return False, None, f"{stamp} は投稿ウィンドウ外（{WINDOW[0]}-{WINDOW[1]}）"

    done = posted_on(posts, now_jst.date())
    if len(done) >= MAX_PER_DAY:
        when = ", ".join(f"{dt:%H:%M}" for dt in done)
        return False, "regular", f"本日の枠は消化済み（{when} に投稿・上限{MAX_PER_DAY}本）"

    return True, "regular", f"{stamp} は投稿ウィンドウ内（{WINDOW[0]}-{WINDOW[1]}）"


def missed_days(posts=None, now_jst=None, lookback_days=7):
    """直近 lookback_days 日で「投稿すべきだったのに0本だった日」を古い順に返す。

    番犬用。判定対象は **今日より前** の投稿曜日だけにする。今日の分はまだ
    ウィンドウが閉じていない可能性があるうえ、番犬自身も schedule 遅延で何時に
    走るか分からないため、今日を数に入れると誤検知する。
    EFFECTIVE_FROM より前の日も対象外（このゲートが無かった期間なので）。
    """
    posts = load_posts() if posts is None else posts
    now_jst = now_jst or jst_now()
    today = now_jst.date()

    posted_dates = {dt.date() for dt in posted_datetimes(posts)}
    missed = []
    for back in range(lookback_days, 0, -1):
        d = today - timedelta(days=back)
        if d < EFFECTIVE_FROM:
            continue
        if d.weekday() not in POST_WEEKDAYS:
            continue
        if d not in posted_dates:
            missed.append(d)
    return missed


def _write_github_output(pairs):
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    with open(out, "a", encoding="utf-8") as f:
        for k, v in pairs:
            f.write(f"{k}={v}\n")


def main():
    ap = argparse.ArgumentParser(description="Instagram 投稿ウィンドウ判定")
    ap.add_argument("--check", action="store_true", help="今投稿してよいか判定（既定）")
    ap.add_argument("--missed", action="store_true",
                    help="投稿を落とした投稿曜日を列挙（番犬用）")
    ap.add_argument("--lookback", type=int, default=7,
                    help="--missed で遡る日数（既定7日）")
    args = ap.parse_args()

    posts = load_posts()

    if args.missed:
        missed = missed_days(posts, lookback_days=args.lookback)
        listed = ",".join(d.isoformat() for d in missed)
        if missed:
            pretty = ", ".join(f"{d.isoformat()}({WEEKDAY_JA[d.weekday()]})" for d in missed)
            print(f"[WATCH] missed_count={len(missed)} :: "
                  f"直近{args.lookback}日で投稿0本の投稿曜日: {pretty}")
        else:
            print(f"[WATCH] missed_count=0 :: "
                  f"直近{args.lookback}日の投稿曜日はすべて投稿済み")
        # 今日が投稿曜日なら、番犬が慌てて臨時投稿を撃たなくてもこのあとの
        # ウィンドウで通常投稿が出る。撃つと今日の枠を悪い時刻で潰してしまうので、
        # 自己回復トリガーを撃つかどうかの判断材料として渡す。
        today_is_post_day = jst_now().weekday() in POST_WEEKDAYS
        print(f"[WATCH] today_is_post_day={str(today_is_post_day).lower()}")
        _write_github_output([
            ("missed_count", len(missed)),
            ("missed", listed),
            ("today_is_post_day", str(today_is_post_day).lower()),
        ])
        return

    should, slot, reason = decide(posts)
    print(f"[GATE] should_post={str(should).lower()} slot={slot or '-'} :: {reason}")
    _write_github_output([
        ("should_post", str(should).lower()),
        ("slot", slot or ""),
        ("reason", reason),
    ])


if __name__ == "__main__":
    main()
