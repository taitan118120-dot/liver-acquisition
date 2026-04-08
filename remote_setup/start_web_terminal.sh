#!/bin/bash
# =============================================================
# Web Terminal Startup Script
# iPhone の Safari から Mac のターミナルにアクセスするためのスクリプト
# =============================================================

# --- 設定 (必ず変更すること) ---
WEB_USER="claude"
WEB_PASS="changeme123"
PORT=7681
# --- 設定ここまで ---

# 色付き出力
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "========================================="
echo "  Web Terminal for Claude Code"
echo "========================================="
echo ""

# ttyd がインストールされているか確認
if ! command -v ttyd &> /dev/null; then
    echo -e "${RED}[ERROR]${NC} ttyd がインストールされていません。"
    echo ""
    echo "以下のコマンドでインストールしてください:"
    echo "  brew install ttyd"
    echo ""
    echo "Homebrew がない場合は先にインストール:"
    echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    exit 1
fi

# パスワードが変更されていない場合に警告
if [ "$WEB_PASS" = "changeme123" ]; then
    echo -e "${YELLOW}[WARNING]${NC} デフォルトパスワードが使用されています！"
    echo "  start_web_terminal.sh を編集して WEB_PASS を変更してください。"
    echo ""
fi

# ローカル IP を取得
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "取得失敗")

echo -e "${GREEN}[INFO]${NC} Web ターミナルを起動します..."
echo ""
echo "  アクセス URL:  http://${LOCAL_IP}:${PORT}"
echo "  ユーザー名:    ${WEB_USER}"
echo "  パスワード:    ${WEB_PASS}"
echo ""
echo "  iPhone の Safari で上記 URL にアクセスしてください。"
echo "  停止するには Ctrl+C を押してください。"
echo ""
echo "========================================="
echo ""

# ttyd を起動（ベーシック認証付き、Claude Code を直接起動）
ttyd \
    --port "$PORT" \
    --credential "${WEB_USER}:${WEB_PASS}" \
    --writable \
    bash -c "cd ~/ライバー獲得 && echo 'Claude Code を起動するには: claude' && echo '' && exec bash"
