#!/bin/bash
# ============================================================
# Instagram自動投稿 セットアップスクリプト
#
# APIキーを対話的に入力 → GitHub Secretsに設定
# gh CLIが使えない場合はキーを表示してWeb UIで手動設定
# ============================================================

set -e

REPO="taitan118120-dot/liver-acquisition"

echo "============================================"
echo "  Instagram自動投稿 セットアップ"
echo "============================================"
echo ""

# gh CLI利用可能チェック
USE_GH=false
if command -v gh &> /dev/null && gh auth status &> /dev/null 2>&1; then
    USE_GH=true
    echo "✓ gh CLI認証済み → Secretsを自動設定します"
else
    echo "⚠ gh CLI未認証 → キーを入力後、手動でGitHub Secretsに設定してください"
    echo "  設定先: https://github.com/$REPO/settings/secrets/actions"
fi
echo ""

SECRETS=()

# --- 1. Gemini API Key ---
echo "━━━ 1/4 Gemini APIキー ━━━"
echo "取得先: https://aistudio.google.com/apikey"
echo "  → Googleログイン → 「APIキーを作成」"
read -p "GEMINI_API_KEY: " GEMINI_KEY
if [ -n "$GEMINI_KEY" ]; then
    if $USE_GH; then
        echo "$GEMINI_KEY" | gh secret set GEMINI_API_KEY --repo "$REPO"
        echo "  ✓ GitHub Secretに設定完了"
    else
        SECRETS+=("GEMINI_API_KEY=$GEMINI_KEY")
        echo "  ✓ 記録しました"
    fi
else
    echo "  - スキップ"
fi
echo ""

# --- 2. imgBB API Key ---
echo "━━━ 2/4 imgBB APIキー ━━━"
echo "取得先: https://api.imgbb.com/"
echo "  → アカウント作成（Googleログイン可）→ APIキーをコピー"
read -p "IMGBB_API_KEY: " IMGBB_KEY
if [ -n "$IMGBB_KEY" ]; then
    if $USE_GH; then
        echo "$IMGBB_KEY" | gh secret set IMGBB_API_KEY --repo "$REPO"
        echo "  ✓ GitHub Secretに設定完了"
    else
        SECRETS+=("IMGBB_API_KEY=$IMGBB_KEY")
        echo "  ✓ 記録しました"
    fi
else
    echo "  - スキップ"
fi
echo ""

# --- 3. Instagram Access Token ---
echo "━━━ 3/4 Instagram アクセストークン（後でもOK）━━━"
echo "取得先: https://developers.facebook.com/"
echo "  → アプリ作成 → Graph APIエクスプローラー → トークン取得"
read -p "INSTAGRAM_ACCESS_TOKEN (スキップはEnter): " IG_TOKEN
if [ -n "$IG_TOKEN" ]; then
    if $USE_GH; then
        echo "$IG_TOKEN" | gh secret set INSTAGRAM_ACCESS_TOKEN --repo "$REPO"
        echo "  ✓ GitHub Secretに設定完了"
    else
        SECRETS+=("INSTAGRAM_ACCESS_TOKEN=$IG_TOKEN")
        echo "  ✓ 記録しました"
    fi
else
    echo "  - スキップ（後で設定可能）"
fi
echo ""

# --- 4. Instagram Business Account ID ---
echo "━━━ 4/4 Instagram ビジネスアカウントID（後でもOK）━━━"
echo "取得方法: Graph APIエクスプローラーで GET /me/accounts"
read -p "INSTAGRAM_BUSINESS_ID (スキップはEnter): " IG_BIZ_ID
if [ -n "$IG_BIZ_ID" ]; then
    if $USE_GH; then
        echo "$IG_BIZ_ID" | gh secret set INSTAGRAM_BUSINESS_ID --repo "$REPO"
        echo "  ✓ GitHub Secretに設定完了"
    else
        SECRETS+=("INSTAGRAM_BUSINESS_ID=$IG_BIZ_ID")
        echo "  ✓ 記録しました"
    fi
else
    echo "  - スキップ（後で設定可能）"
fi
echo ""

# --- 完了 ---
echo "============================================"
echo "  セットアップ完了！"
echo "============================================"
echo ""

if ! $USE_GH && [ ${#SECRETS[@]} -gt 0 ]; then
    echo "以下のキーをGitHub Secretsに手動で設定してください:"
    echo "  https://github.com/$REPO/settings/secrets/actions"
    echo ""
    for s in "${SECRETS[@]}"; do
        NAME="${s%%=*}"
        echo "  Name: $NAME"
        echo "  Value: ${s#*=}"
        echo ""
    done
fi

echo "次のステップ:"
echo "  1. コンテンツ生成テスト:"
echo "     GEMINI_API_KEY=xxx python instagram/ig_content_generator.py --dry-run"
echo ""
echo "  2. 手動で投稿テスト:"
echo "     GitHub → Actions → Instagram自動投稿 → Run workflow"
echo ""
