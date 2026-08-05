#!/usr/bin/env python3
"""公開中note記事キー台帳 data/published_note_keys.json の読み書きと整合チェック。

この台帳は「いま note 上で公開中の記事キー」の一覧で、
note_leadmagnet_publish.py --all などの一括処理が全件ループする元データになる。
非公開化・削除した記事が残っていると、その分だけ無駄なリクエストと失敗が出る。

記事を公開から下ろす処理（note_unpublish_articles.py / note_delete_articles.py）は
成功時に remove() を呼んで台帳を自動で縮める。手で編集する必要はない。

整合チェック（未ログイン公開APIで全件を実際に叩く）:
  python3 note_keys_registry.py --check        # 差分を表示するだけ
  python3 note_keys_registry.py --fix          # 差分を台帳に反映する
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEYS_FILE = os.path.join(BASE_DIR, "data", "published_note_keys.json")
KEYMAP_FILE = os.path.join(BASE_DIR, "data", "note_key_map.json")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 公開APIを叩く間隔（秒）。連続アクセスで弾かれないよう余裕を持たせる。
CHECK_INTERVAL = 1.2


def load():
    with open(KEYS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save(keys):
    with open(KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(keys, f, ensure_ascii=False)


def remove(keys, reason=""):
    """台帳からキーを取り除く。既に無ければ何もしない（冪等）。"""
    if isinstance(keys, str):
        keys = [keys]
    current = load()
    drop = set(keys) & set(current)
    if not drop:
        return []
    save([k for k in current if k not in drop])
    tag = f" ({reason})" if reason else ""
    print(f"  台帳更新{tag}: -{len(drop)}件 → 残り{len(current) - len(drop)}件 "
          f"[{', '.join(sorted(drop))}]")
    return sorted(drop)


def add(keys):
    """台帳にキーを足す。既にあれば何もしない（冪等）。"""
    if isinstance(keys, str):
        keys = [keys]
    current = load()
    new = [k for k in dict.fromkeys(keys) if k not in set(current)]
    if not new:
        return []
    save(current + new)
    print(f"  台帳更新: +{len(new)}件 → 計{len(current) + len(new)}件 "
          f"[{', '.join(new)}]")
    return new


def public_status(key):
    """未ログインの公開APIで記事の到達性を見る。200=公開中 / 404=非公開or削除。"""
    req = urllib.request.Request(
        f"https://note.com/api/v3/notes/{key}", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return f"ERR {type(e).__name__}"


def _keymap_keys():
    """記事番号→key台帳から、公開キー一覧に載っていないキーを拾う。"""
    if not os.path.exists(KEYMAP_FILE):
        return []
    with open(KEYMAP_FILE, encoding="utf-8") as f:
        km = json.load(f)
    return list(dict.fromkeys(v["key"] for v in km.values() if v.get("key")))


def reconcile(apply=False):
    """台帳と note の実状態を突き合わせる。

    - 台帳にあるが公開されていない（404）→ 取り除く候補
    - note_key_map.json にあり公開中(200)だが台帳に無い → 足す候補
    """
    keys = load()
    listed = set(keys)
    print(f"台帳 {len(keys)}件を公開APIで照会中...")

    dead = []
    for i, k in enumerate(keys, 1):
        st = public_status(k)
        if st != 200:
            dead.append((k, st))
            print(f"  [{i}/{len(keys)}] {k} http={st}  ← 公開されていない")
        time.sleep(CHECK_INTERVAL)

    candidates = [k for k in _keymap_keys() if k not in listed]
    missing = []
    if candidates:
        print(f"\n台帳外のキー {len(candidates)}件を照会中...")
        for k in candidates:
            st = public_status(k)
            if st == 200:
                missing.append(k)
                print(f"  {k} http=200  ← 公開中だが台帳に無い")
            time.sleep(CHECK_INTERVAL)

    print(f"\n--- 結果 ---")
    print(f"  台帳にあるが非公開/削除: {len(dead)}件")
    print(f"  公開中だが台帳に無い    : {len(missing)}件")

    if not dead and not missing:
        print("  ズレなし")
        return {"dead": [], "missing": []}

    if apply:
        if dead:
            remove([k for k, _ in dead], reason="reconcile")
        if missing:
            add(missing)
        print(f"  → 反映後 {len(load())}件")
    else:
        print("  （--fix で台帳に反映）")

    return {"dead": [k for k, _ in dead], "missing": missing}


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    if args[0] == "--check":
        r = reconcile(apply=False)
        raise SystemExit(1 if (r["dead"] or r["missing"]) else 0)
    elif args[0] == "--fix":
        reconcile(apply=True)
    else:
        print(__doc__)
        raise SystemExit(1)
