#!/bin/bash
# ============================================================
# Instagram自動投稿 セットアップスクリプト
#
# APIキーを対話的に入力 → GitHub Secretsに自動設定
# ============================================================

set -e

REPO="taitan118120-dot/liver-acquisition"

echo "============================================"
echo "  Instagram自動投稿 セットアップ"
echo "============================================"
echo ""

# gh CLIチェック
if ! command -v gh &> /dev/null; then
    echo "[ERROR] gh CLI がインストールされていません。"
    echo "  brew install gh && gh auth login"
    exit 1
fi

# 認証チェック
if ! gh auth status &> /dev/null 2>&1; then
    echo "[ERROR] GitHub未認証です。先に gh auth login を実行してください。"
    exit 1
fi

echo "各APIキーを入力してください。"
echo "（まだ取得していないものはEnterでスキップできます）"
echo ""

# --- 1. Gemini API Key ---
echo "━━━ 1/6 Gemini APIキー ━━━"
echo "取得先: https://aistudio.google.com/apikey"
echo "  → Googleログイン → 「APIキーを作成」"
read -p "GEMINI_API_KEY: " GEMINI_KEY
if [ -n "$GEMINI_KEY" ]; then
    echo "$GEMINI_KEY" | gh secret set GEMINI_API_KEY --repo "$REPO"
    echo "  ✓ 設定完了"
else
    echo "  - スキップ"
fi
echo ""

# --- 2. imgBB API Key ---
echo "━━━ 2/6 imgBB APIキー ━━━"
echo "取得先: https://api.imgbb.com/"
echo "  → アカウント作成 → APIキーをコピー"
read -p "IMGBB_API_KEY: " IMGBB_KEY
if [ -n "$IMGBB_KEY" ]; then
    echo "$IMGBB_KEY" | gh secret set IMGBB_API_KEY --repo "$REPO"
    echo "  ✓ 設定完了"
else
    echo "  - スキップ"
fi
echo ""

# --- 3. Instagram Access Token ---
echo "━━━ 3/6 Instagram アクセストークン ━━━"
echo "取得先: https://developers.facebook.com/"
echo "  → マイアプリ → アプリ作成 → Graph APIエクスプローラー"
echo "  → 権限: instagram_basic, instagram_content_publish, pages_show_list"
echo "  → 「アクセストークンを取得」"
read -p "INSTAGRAM_ACCESS_TOKEN: " IG_TOKEN
if [ -n "$IG_TOKEN" ]; then
    echo "$IG_TOKEN" | gh secret set INSTAGRAM_ACCESS_TOKEN --repo "$REPO"
    echo "  ✓ 設定完了"
else
    echo "  - スキップ"
fi
echo ""

# --- 4. Instagram Business Account ID ---
echo "━━━ 4/6 Instagram ビジネスアカウントID ━━━"
echo "取得方法: Graph APIエクスプローラーで以下を実行"
echo "  GET /me/accounts → ページID取得"
echo "  GET /{ページID}?fields=instagram_business_account → IDを確認"
read -p "INSTAGRAM_BUSINESS_ID: " IG_BIZ_ID
if [ -n "$IG_BIZ_ID" ]; then
    echo "$IG_BIZ_ID" | gh secret set INSTAGRAM_BUSINESS_ID --repo "$REPO"
    echo "  ✓ 設定完了"
else
    echo "  - スキップ"
fi
echo ""

# --- 5. Meta App ID ---
echo "━━━ 5/6 Meta App ID ━━━"
echo "取得先: https://developers.facebook.com/apps/ → アプリの設定 → 基本"
read -p "META_APP_ID: " META_ID
if [ -n "$META_ID" ]; then
    echo "$META_ID" | gh secret set META_APP_ID --repo "$REPO"
    echo "  ✓ 設定完了"
else
    echo "  - スキップ"
fi
echo ""

# --- 6. Meta App Secret ---
echo "━━━ 6/6 Meta App Secret ━━━"
echo "取得先: 同上 → App Secret の「表示」をクリック"
read -sp "META_APP_SECRET: " META_SECRET
echo ""
if [ -n "$META_SECRET" ]; then
    echo "$META_SECRET" | gh secret set META_APP_SECRET --repo "$REPO"
    echo "  ✓ 設定完了"
else
    echo "  - スキップ"
fi
echo ""

# --- 完了 ---
echo "============================================"
echo "  セットアップ完了！"
echo "============================================"
echo ""
echo "設定済みのSecrets:"
gh secret list --repo "$REPO" 2>/dev/null || echo "  (確認にはgh auth loginが必要)"
echo ""
echo "次のステップ:"
echo "  1. コンテンツ生成テスト:"
echo "     cd ~/ライバー獲得"
echo "     GEMINI_API_KEY=xxx python instagram/ig_content_generator.py --dry-run"
echo ""
echo "  2. 初回トークン交換（短期→長期）:"
echo "     python instagram/ig_token_refresh.py --exchange"
echo ""
echo "  3. 手動で投稿テスト:"
echo "     GitHub → Actions → Instagram自動投稿 → Run workflow"
echo ""
