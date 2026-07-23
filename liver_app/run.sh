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

# 既存CSVからの移行（一回でOK、冪等）
if [ -f ../data/leads.csv ] && [ ! -f .migrated ]; then
  .venv/bin/python migrate.py
  touch .migrated
fi

# Flask起動
echo ""
echo "======================================================"
echo "  TAITAN PRO DM アプリを起動中..."
echo "  ローカル:   http://localhost:5050"
echo "  LAN内共有: http://\$(ipconfig getifaddr en0):5050"
echo "======================================================"
echo ""

exec .venv/bin/python app.py
