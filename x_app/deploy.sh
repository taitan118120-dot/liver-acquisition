#!/usr/bin/env bash
# Fly.io ワンショットデプロイ
#   ./deploy.sh   ← これだけ。
#
# 自動で:
#   1. flyctl ログイン（未ログインならブラウザ起動）
#   2. APP_PASSWORD 生成 + .app_password 保存（既存なら再利用）
#   3. アプリ / ボリューム / シークレット 作成（冪等）
#   4. デプロイ
#   5. data.sqlite があればボリュームへ転送（初回のみ）
#   6. URL とパスワードを表示

set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="${FLY_APP:-taitan-pro-x-dm}"
REGION="${FLY_REGION:-nrt}"
VOLUME_NAME="x_data"
PW_FILE=".app_password"
DB_MARK=".db_uploaded"

FLY=/opt/homebrew/bin/flyctl
command -v "$FLY" >/dev/null 2>&1 || FLY=flyctl

say() { printf "\033[1;36m==>\033[0m %s\n" "$*"; }
ok()  { printf "\033[1;32m✓\033[0m %s\n" "$*"; }
err() { printf "\033[1;31m✗\033[0m %s\n" "$*" >&2; }

say "flyctl: $($FLY version)"

# 1. ログイン
if ! $FLY auth whoami >/dev/null 2>&1; then
  say "flyctl ログインを開始（ブラウザが開きます）"
  $FLY auth login
fi
ok "ログイン済: $($FLY auth whoami)"

# 2. パスワード（既存ファイル優先 / env 上書き可 / 無ければ生成）
if [[ -n "${APP_PASSWORD:-}" ]]; then
  echo -n "$APP_PASSWORD" > "$PW_FILE"
elif [[ -f "$PW_FILE" ]]; then
  APP_PASSWORD=$(cat "$PW_FILE")
else
  APP_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(18))")
  echo -n "$APP_PASSWORD" > "$PW_FILE"
  chmod 600 "$PW_FILE"
  ok "パスワードを自動生成 → $PW_FILE に保存"
fi

# 3. アプリ
if ! $FLY status -a "$APP_NAME" >/dev/null 2>&1; then
  say "アプリ作成: $APP_NAME"
  $FLY apps create "$APP_NAME" --org personal
else
  ok "アプリ既存: $APP_NAME"
fi

# 4. ボリューム
if ! $FLY volumes list -a "$APP_NAME" 2>/dev/null | grep -q "$VOLUME_NAME"; then
  say "ボリューム作成: $VOLUME_NAME (1GB / $REGION)"
  $FLY volumes create "$VOLUME_NAME" -a "$APP_NAME" -r "$REGION" -s 1 --yes
else
  ok "ボリューム既存: $VOLUME_NAME"
fi

# 5. シークレット
say "APP_PASSWORD を Fly secrets に登録"
$FLY secrets set APP_PASSWORD="$APP_PASSWORD" -a "$APP_NAME" --stage >/dev/null

# 6. デプロイ
say "デプロイ実行"
$FLY deploy -a "$APP_NAME" --ha=false

# 7. 既存 DB 転送（初回のみ）
# Fly の sftp put は既存ファイルを上書きしないので、
# rm + base64 pipe 方式で確実に転送する
if [[ -f data.sqlite && ! -f "$DB_MARK" ]]; then
  say "data.sqlite をボリュームへアップロード（初回）"
  MACHINE_ID=$($FLY machines list -a "$APP_NAME" --json | python3 -c 'import sys,json; print(json.load(sys.stdin)[0]["id"])')
  base64 < data.sqlite | $FLY ssh console -a "$APP_NAME" \
    -C "bash -c 'rm -f /data/data.sqlite; base64 -d > /data/data.sqlite'"
  $FLY machine restart "$MACHINE_ID" -a "$APP_NAME"
  date > "$DB_MARK"
  ok "DB 移行完了"
else
  ok "DB 転送スキップ（${DB_MARK} 存在 or data.sqlite なし）"
fi

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " ✅ デプロイ完了"
echo
echo "    URL:  https://$APP_NAME.fly.dev"
echo "    PW:   $APP_PASSWORD"
echo
echo " iPhone Safari で開く → ログイン → ホーム画面に追加"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
