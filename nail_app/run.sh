#!/bin/bash
# ネイル自動投稿アプリ 起動スクリプト
cd "$(dirname "$0")"

# 初回だけ仮想環境を作る
if [ ! -d ".venv" ]; then
  echo "初回セットアップ中…"
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi

exec ./.venv/bin/python app.py
