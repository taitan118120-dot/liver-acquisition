"""テンプレの近似重複を検出するツール（既定はレポートのみ・破壊的操作は明示指定が必要）

背景:
  init_db() の「デフォルトテンプレが無ければ追加」系マイグレーションが _DEFAULT_* との
  完全一致で判定していたため、既定文言を変えるたびに旧文言版とは別物として新文言版が
  追記されていた。追記そのものは 2026-08-01 の台帳(migrations_applied)で止めたが、
  既に多重化してしまった旧コピーは exact-match dedup では消えない（1行だけ違う等）。

使い方:
  # 本番(Fly.io)を確認するだけ
  python3 dedupe_templates.py --remote

  # ローカルDBを確認するだけ
  python3 dedupe_templates.py

  # 消すのはユーザー確認後。落とす要素を明示指定する（--yes 必須）
  python3 dedupe_templates.py --remote --drop beginner:2 --yes

注意: --drop はインデックス指定。レポートで出た番号を必ず目視してから使うこと。
      インデックスは同一 run のレポートに対して有効（削除は降順にまとめて適用する）。
"""
import argparse
import difflib
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
API_BASE = os.environ.get("LIVER_API", "https://taitan-pro-dm.fly.dev")
PW_FILE = os.environ.get("LIVER_APP_PASSWORD_FILE", os.path.join(BASE_DIR, ".app_password"))


def _token():
    """.app_password は gitignore されているので worktree には無い。
    LIVER_APP_PASSWORD / LIVER_APP_PASSWORD_FILE で明示指定できるようにする。"""
    raw = os.environ.get("LIVER_APP_PASSWORD")
    if raw:
        return raw.strip()
    if not os.path.exists(PW_FILE):
        sys.exit(
            f"認証トークンが見つかりません: {PW_FILE}\n"
            "LIVER_APP_PASSWORD_FILE か LIVER_APP_PASSWORD で指定してください。"
        )
    return open(PW_FILE).read().strip()


# ---------- 入出力（local / remote 共通インタフェース） ----------
def load_remote():
    import urllib.request

    token = _token()
    req = urllib.request.Request(
        f"{API_BASE}/api/settings", headers={"X-Auth-Token": token}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def save_remote(templates):
    import urllib.request

    token = _token()
    body = json.dumps({"templates": templates}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        f"{API_BASE}/api/settings",
        data=body,
        method="PUT",
        headers={"X-Auth-Token": token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def load_local():
    sys.path.insert(0, BASE_DIR)
    import db

    db.init_db()
    return db.all_settings()


def save_local(templates):
    sys.path.insert(0, BASE_DIR)
    import db

    db.set_setting("templates", templates)
    return db.all_settings()


# ---------- 検出 ----------
def find_near_dups(items, threshold):
    """(i, j, ratio) のリスト。i < j。"""
    out = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if not isinstance(a, str) or not isinstance(b, str):
                continue
            ratio = difflib.SequenceMatcher(None, a, b).ratio()
            if ratio >= threshold:
                out.append((i, j, ratio))
    return out


def head(text, n=40):
    return (text or "").split("\n")[0][:n]


def report(templates, threshold):
    found = False
    for ttype, items in templates.items():
        if not isinstance(items, list):
            continue
        print(f"\n=== {ttype} ({len(items)}件) ===")
        for i, t in enumerate(items):
            n_lines = len(t.split("\n")) if isinstance(t, str) else 0
            print(f"  [{i}] {len(t) if isinstance(t, str) else '?'}文字 / {n_lines}行  {head(t)}")
        dups = find_near_dups(items, threshold)
        for i, j, ratio in dups:
            found = True
            kind = "完全一致" if ratio == 1.0 else f"類似度 {ratio:.3f}"
            print(f"\n  ⚠ [{i}] と [{j}] が近似重複（{kind}）")
            diff = difflib.unified_diff(
                items[i].split("\n"), items[j].split("\n"),
                fromfile=f"[{i}]", tofile=f"[{j}]", lineterm="", n=1,
            )
            for line in diff:
                print("    " + line)
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--remote", action="store_true", help="本番(Fly.io)のAPI経由で見る")
    ap.add_argument("--threshold", type=float, default=0.90, help="近似判定の類似度しきい値 (既定 0.90)")
    ap.add_argument("--drop", action="append", default=[], metavar="TYPE:INDEX",
                    help="削除する要素。例 beginner:2 （複数指定可）")
    ap.add_argument("--yes", action="store_true", help="--drop を実際に適用する（未指定はdry-run）")
    args = ap.parse_args()

    settings = load_remote() if args.remote else load_local()
    templates = settings.get("templates") or {}
    where = API_BASE if args.remote else os.environ.get("LIVER_APP_DB_PATH", "(local data.sqlite)")
    print(f"対象: {where}")
    print(f"migrations_applied: {settings.get('migrations_applied')}")

    found = report(templates, args.threshold)

    if not args.drop:
        if found:
            print("\n近似重複あり。削除するなら --drop TYPE:INDEX を明示して再実行してください（--yes で確定）。")
        else:
            print("\n近似重複なし。")
        return

    # --- 削除フェーズ ---
    targets = {}
    for spec in args.drop:
        try:
            ttype, idx = spec.rsplit(":", 1)
            idx = int(idx)
        except ValueError:
            sys.exit(f"--drop の書式が不正: {spec} （例: beginner:2）")
        if not isinstance(templates.get(ttype), list):
            sys.exit(f"存在しないテンプレ種別: {ttype}")
        if not (0 <= idx < len(templates[ttype])):
            sys.exit(f"{ttype} のインデックス範囲外: {idx}")
        targets.setdefault(ttype, set()).add(idx)

    print("\n--- 削除対象 ---")
    for ttype, idxs in targets.items():
        remaining = len(templates[ttype]) - len(idxs)
        if remaining < 1:
            sys.exit(f"{ttype} が空になる削除は拒否します")
        for idx in sorted(idxs):
            print(f"  {ttype}[{idx}] ({len(templates[ttype][idx])}文字) {head(templates[ttype][idx])}")
        print(f"  → {ttype} は {len(templates[ttype])}件 から {remaining}件 になります")

    if not args.yes:
        print("\n[dry-run] --yes を付けると実際に削除します。")
        return

    for ttype, idxs in targets.items():
        templates[ttype] = [t for i, t in enumerate(templates[ttype]) if i not in idxs]

    after = save_remote(templates) if args.remote else save_local(templates)
    print("\n適用しました。現在の件数:")
    for ttype, items in (after.get("templates") or {}).items():
        print(f"  {ttype}: {len(items)}件")


if __name__ == "__main__":
    main()
