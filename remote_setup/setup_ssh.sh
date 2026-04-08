#!/bin/bash
# =============================================================
# SSH Remote Access Setup Script for Mac
# iPhone から SSH 接続するための Mac 側セットアップ
# =============================================================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "========================================="
echo "  SSH Remote Access Setup"
echo "========================================="
echo ""

# 1. リモートログインの状態を確認
echo -e "${GREEN}[1/3]${NC} リモートログインの状態を確認中..."
REMOTE_LOGIN=$(sudo systemsetup -getremotelogin 2>/dev/null)
echo "  現在の状態: $REMOTE_LOGIN"
echo ""

if echo "$REMOTE_LOGIN" | grep -qi "off"; then
    echo -e "${YELLOW}[ACTION]${NC} リモートログインを有効にしますか？ (y/n)"
    read -r answer
    if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
        sudo systemsetup -setremotelogin on
        echo -e "${GREEN}[OK]${NC} リモートログインを有効にしました。"
    else
        echo "  スキップしました。手動で有効にしてください:"
        echo "  システム設定 > 一般 > 共有 > リモートログイン"
    fi
    echo ""
fi

# 2. ローカル IP の表示
echo -e "${GREEN}[2/3]${NC} ネットワーク情報..."
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null)
if [ -z "$LOCAL_IP" ]; then
    LOCAL_IP=$(ipconfig getifaddr en1 2>/dev/null)
fi

if [ -n "$LOCAL_IP" ]; then
    echo "  ローカル IP:  $LOCAL_IP"
    echo ""
    echo "  iPhone の SSH アプリで以下を入力:"
    echo "    ホスト:     $LOCAL_IP"
    echo "    ユーザー:   $(whoami)"
    echo "    ポート:     22"
else
    echo -e "${RED}[ERROR]${NC} IP アドレスを取得できません。Wi-Fi に接続されていますか？"
fi
echo ""

# 3. SSH 接続テスト用コマンドの表示
echo -e "${GREEN}[3/3]${NC} 接続テスト"
echo "  同じネットワーク上の別の端末から以下で接続テスト:"
echo "    ssh $(whoami)@${LOCAL_IP}"
echo ""
echo "  接続後に Claude Code を起動:"
echo "    cd ~/ライバー獲得 && claude"
echo ""
echo "========================================="
echo ""
echo "完了！iPhone の SSH アプリ（Termius 推奨）から接続してください。"
echo ""
