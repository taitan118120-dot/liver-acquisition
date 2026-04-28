#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# venv作成・依存インストール（初回のみ）
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi

# SQLite初期化（冪等）
.venv/bin/python db.py 2>/dev/null || true
.venv/bin/python -c "import db; db.init_db(); print('DB initialized at', db.DB_PATH)"

# Flask起動 (port 5051: liver_app=5050 と衝突回避)
PORT="${PORT:-5051}"
export PORT

echo ""
echo "======================================================"
echo "  TAITAN PRO X DM アプリを起動中..."
echo "  ローカル:   http://localhost:$PORT"
echo "  LAN内共有: http://$(ipconfig getifaddr en0 2>/dev/null || echo "<your-ip>"):$PORT"
echo "======================================================"
echo ""

exec .venv/bin/python app.py
