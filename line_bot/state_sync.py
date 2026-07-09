"""GitHubプライベートリポジトリへの状態バックアップ

Render無料枠はスリープ・再デプロイでディスクが消えるため、
users.json / step_schedule.json を GitHub のプライベートリポジトリに保存し、
起動時に復元する。

GITHUB_STATE_TOKEN 未設定なら何もしない（今まで通りローカルのみで動作）。
バックアップの失敗でBotが止まることはない（ログを出して次周期に再試行）。
"""

import base64
import json
import os
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

GITHUB_STATE_TOKEN = os.environ.get("GITHUB_STATE_TOKEN", "")
STATE_REPO = os.environ.get("STATE_REPO", "taitan118120-dot/line-bot-state")
SYNC_FILES = ["users.json", "step_schedule.json"]
SYNC_INTERVAL = 10  # 秒。書き込みをまとめてpush

_dirty = set()
_lock = threading.Lock()
_sha_cache = {}
_started = False


def enabled():
    return bool(GITHUB_STATE_TOKEN)


def _api(path, method="GET", body=None):
    url = f"https://api.github.com/repos/{STATE_REPO}/{path}"
    headers = {
        "Authorization": f"Bearer {GITHUB_STATE_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "taitan-line-bot",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=15) as res:
        return json.loads(res.read().decode("utf-8"))


def pull_state(data_dir):
    """起動時にGitHubから状態を復元"""
    if not enabled():
        print("[SYNC] GITHUB_STATE_TOKEN未設定のためバックアップ無効")
        return
    for name in SYNC_FILES:
        try:
            res = _api(f"contents/{name}")
            content = base64.b64decode(res["content"])
            with open(os.path.join(data_dir, name), "wb") as f:
                f.write(content)
            _sha_cache[name] = res["sha"]
            print(f"[SYNC] Restored {name} from GitHub")
        except HTTPError as e:
            if e.code == 404:
                print(f"[SYNC] {name} はリモート未作成（初回はこれで正常）")
            else:
                print(f"[SYNC] Restore failed {name}: HTTP {e.code}")
        except Exception as e:
            print(f"[SYNC] Restore failed {name}: {e}")


def mark_dirty(path):
    """状態ファイルが保存されたらバックアップ対象に積む"""
    name = os.path.basename(path)
    if not enabled() or name not in SYNC_FILES:
        return
    with _lock:
        _dirty.add(name)


def _push(name, data_dir):
    path = os.path.join(data_dir, name)
    try:
        with open(path, "rb") as f:
            content = f.read()
    except FileNotFoundError:
        return
    body = {
        "message": f"update {name}",
        "content": base64.b64encode(content).decode("ascii"),
    }
    if name in _sha_cache:
        body["sha"] = _sha_cache[name]
    try:
        res = _api(f"contents/{name}", method="PUT", body=body)
        _sha_cache[name] = res["content"]["sha"]
    except HTTPError as e:
        if e.code in (409, 422):
            # sha不一致 → 最新shaを取り直して1回だけ再試行
            try:
                cur = _api(f"contents/{name}")
                body["sha"] = cur["sha"]
                res = _api(f"contents/{name}", method="PUT", body=body)
                _sha_cache[name] = res["content"]["sha"]
            except Exception as e2:
                print(f"[SYNC] Push retry failed {name}: {e2}")
                mark_dirty(name)
        else:
            print(f"[SYNC] Push failed {name}: HTTP {e.code}")
            mark_dirty(name)
    except Exception as e:
        print(f"[SYNC] Push failed {name}: {e}")
        mark_dirty(name)


def start_sync_loop(data_dir):
    """バックアップスレッドを起動（多重起動防止）"""
    global _started
    if not enabled() or _started:
        return
    _started = True

    def loop():
        while True:
            time.sleep(SYNC_INTERVAL)
            with _lock:
                targets = list(_dirty)
                _dirty.clear()
            for name in targets:
                _push(name, data_dir)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    print(f"[SYNC] GitHubバックアップ有効 ({STATE_REPO}, {SYNC_INTERVAL}秒間隔)")
