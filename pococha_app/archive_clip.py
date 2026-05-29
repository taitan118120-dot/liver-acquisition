"""配信アーカイブ → 切り抜き素材化.

joined_live_archiving の m3u8 から、コメント密度で検出した「盛り上がり」区間を
ffmpeg で切り出し、video_pipeline/inputs/ に mp4 として置く（任意でパイプライン実行）。
Pococha配信は元から 720x1280 の縦型なので、そのまま縦型ショート素材になる。

前提: extract_archive.js で /lives/{id} から m3u8 URL を取得し、--url で渡すか
archives テーブルに保存しておく（--save-url で保存）。

使い方:
    # m3u8をDBに保存
    python3 archive_clip.py 77987225 --url "https://.../playlist.m3u8" --save-url

    # 盛り上がり候補を表示（コメント密度ベース、ダウンロードしない）
    python3 archive_clip.py 77987225 --list

    # 上位3つの盛り上がりを各60秒で切り出し（要ffmpeg, ダウンロード発生）
    python3 archive_clip.py 77987225 --auto 3 --dur 60

    # 時刻指定で1本切り出し
    python3 archive_clip.py 77987225 --start 00:48:00 --dur 75

    # 切り出し後そのまま縦型ショート化（video_pipeline 実行）
    python3 archive_clip.py 77987225 --auto 1 --pipeline

注意: ダウンロード(ffmpeg取得)はユーザー許可のうえで実行すること。
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from db import connect

BASE = os.path.dirname(__file__)
VP_DIR = os.path.abspath(os.path.join(BASE, "..", "video_pipeline"))
VP_INPUTS = os.path.join(VP_DIR, "inputs")


def hms_to_sec(s):
    p = [int(x) for x in s.strip().split(":")]
    while len(p) < 3:
        p.insert(0, 0)
    return p[0] * 3600 + p[1] * 60 + p[2]


def sec_to_hms(t):
    t = int(t)
    return f"{t // 3600:02d}:{(t % 3600) // 60:02d}:{t % 60:02d}"


def get_url(conn, live_id, arg_url, save):
    if arg_url:
        if save:
            conn.execute(
                "INSERT INTO archives (live_id, m3u8_url) VALUES (?,?) "
                "ON CONFLICT(live_id) DO UPDATE SET m3u8_url=excluded.m3u8_url, "
                "captured_at=datetime('now','+9 hours')",
                (live_id, arg_url),
            )
            # user_id を streams から補完
            conn.execute(
                "UPDATE archives SET user_id=(SELECT user_id FROM streams WHERE stream_id=?) "
                "WHERE live_id=? AND user_id IS NULL", (live_id, live_id))
            conn.commit()
        return arg_url
    row = conn.execute("SELECT m3u8_url FROM archives WHERE live_id=?", (live_id,)).fetchone()
    return row["m3u8_url"] if row else None


def highlights(conn, live_id, win, topn):
    """コメント timing を win秒ビンに集計し、密度上位 topn 区間を返す."""
    rows = conn.execute(
        "SELECT timing, text FROM comments WHERE stream_id=? AND timing IS NOT NULL",
        (str(live_id),),
    ).fetchall()
    if not rows:
        return []
    secs = []
    for r in rows:
        try:
            secs.append((hms_to_sec(r["timing"]), r["text"]))
        except ValueError:
            continue
    if not secs:
        return []
    bins = {}
    for t, _ in secs:
        bins.setdefault(t // win, 0)
        bins[t // win] += 1
    ranked = sorted(bins.items(), key=lambda kv: -kv[1])[:topn]
    out = []
    for b, cnt in ranked:
        start = b * win
        sample = [t for t in secs if start <= t[0] < start + win][:3]
        out.append({"start": start, "count": cnt,
                    "sample": [s[1][:18] for s in sample]})
    out.sort(key=lambda h: h["start"])
    return out


def clip(url, start_sec, dur, out_path):
    """ffmpeg で m3u8 から [start, start+dur] を再エンコード切り出し."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-ss", sec_to_hms(start_sec), "-i", url, "-t", str(dur),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-movflags", "+faststart", out_path,
    ]
    print(f"  ffmpeg: {sec_to_hms(start_sec)} +{dur}s → {os.path.relpath(out_path, BASE)}")
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode(errors="replace")[-800:] + "\n")
        raise SystemExit(f"ffmpeg失敗 (code={r.returncode})")
    return out_path


def run_pipeline(mp4):
    venv_py = os.path.join(VP_DIR, ".venv", "bin", "python")
    py = venv_py if os.path.exists(venv_py) else sys.executable
    cmd = [py, os.path.join(VP_DIR, "run_all.py"), mp4, "--no-llm", "--whisper-model", "small", "--language", "ja"]
    print(f"  pipeline: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=VP_DIR)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("live_id", type=int)
    ap.add_argument("--url", help="playlist.m3u8 URL（extract_archive.js で取得）")
    ap.add_argument("--save-url", action="store_true", help="--url を archives テーブルに保存")
    ap.add_argument("--list", action="store_true", help="盛り上がり候補を表示のみ（DLしない）")
    ap.add_argument("--auto", type=int, metavar="N", help="密度上位N区間を切り出し")
    ap.add_argument("--start", help="開始時刻 HH:MM:SS（手動切り出し）")
    ap.add_argument("--dur", type=int, default=60, help="切り出し秒数（既定60）")
    ap.add_argument("--win", type=int, default=60, help="盛り上がり検出のビン秒（既定60）")
    ap.add_argument("--pipeline", action="store_true", help="切り出し後に video_pipeline を実行")
    args = ap.parse_args()

    conn = connect()
    url = get_url(conn, args.live_id, args.url, args.save_url)

    if args.list or (args.auto is None and args.start is None):
        hs = highlights(conn, args.live_id, args.win, args.auto or 5)
        if not hs:
            print(f"配信 {args.live_id}: timing付きコメントがなく盛り上がり検出不可。--start で手動指定を。")
        else:
            print(f"配信 {args.live_id} 盛り上がり候補（{args.win}秒ビン・コメント数順）:")
            for h in sorted(hs, key=lambda x: -x["count"]):
                print(f"  {sec_to_hms(h['start'])}  コメント{h['count']}件  例: {' / '.join(h['sample'])}")
        if not args.url:
            print(f"\nm3u8: {'(DB未保存)' if not url else url}")
        conn.close()
        if args.list or (args.auto is None and args.start is None):
            return

    if not url:
        raise SystemExit("m3u8 URL が無い。--url で渡すか --save-url で保存しておくこと。")

    targets = []
    if args.start:
        targets.append(hms_to_sec(args.start))
    if args.auto:
        for h in highlights(conn, args.live_id, args.win, args.auto):
            # ピークの少し手前から始めて前振りを含める
            targets.append(max(0, h["start"] - 5))
    conn.close()

    made = []
    for st in targets:
        out = os.path.join(VP_INPUTS, f"clip_{args.live_id}_{sec_to_hms(st).replace(':','')}.mp4")
        clip(url, st, args.dur, out)
        made.append(out)
    print(f"切り出し完了: {len(made)}本 → {os.path.relpath(VP_INPUTS, BASE)}/")

    if args.pipeline:
        for mp4 in made:
            run_pipeline(mp4)


if __name__ == "__main__":
    main()
