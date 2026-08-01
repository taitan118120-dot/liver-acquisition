#!/usr/bin/env bash
# Fly.io ワンショットデプロイ
#   ./deploy.sh   ← これだけ。
#
# 自動で:
#   1. flyctl ログイン（未ログインならブラウザ起動）
#   2. アプリ作成（冪等）
#   3. APP_PASSWORD 解決（既存を絶対に作り替えない。詳細は該当ブロックのコメント）
#   4. ボリューム / シークレット 作成（冪等）
#   5. デプロイ
#   6. data.sqlite があればボリュームへ転送（初回のみ）
#   7. URL とパスワードを表示

set -euo pipefail

cd "$(dirname "$0")"

# --- デプロイガード読み込み（2026-08-01 の巻き戻し事故対策） ---
GUARD="$(git rev-parse --show-toplevel 2>/dev/null)/scripts/fly_deploy_guard.sh"
if [[ -f "$GUARD" ]]; then
  # shellcheck source=../scripts/fly_deploy_guard.sh
  source "$GUARD"
else
  echo "⚠️  scripts/fly_deploy_guard.sh が見つかりません。ガードなしで続行します。" >&2
  fly_guard_precheck() { :; }
  fly_guard_verify()   { :; }
fi

APP_NAME="${FLY_APP:-taitan-pro-dm}"
REGION="${FLY_REGION:-nrt}"
VOLUME_NAME="liver_data"
PW_FILE=".app_password"
DB_MARK=".db_uploaded"

FLY=/opt/homebrew/bin/flyctl
command -v "$FLY" >/dev/null 2>&1 || FLY=flyctl

say() { printf "\033[1;36m==>\033[0m %s\n" "$*"; }
ok()  { printf "\033[1;32m✓\033[0m %s\n" "$*"; }
err() { printf "\033[1;31m✗\033[0m %s\n" "$*" >&2; }

# git worktree から実行された場合、メインチェックアウト側の .app_password を探す。
# .app_password は .gitignore 済みなので worktree には存在せず、これが無いと
# 「パスワード未設定」と誤判定して本番パスワードを作り替えてしまう。
find_main_pw_file() {
  local common_dir main_root prefix cand
  common_dir=$(git rev-parse --git-common-dir 2>/dev/null) || return 1
  [[ -n "$common_dir" ]] || return 1
  common_dir=$(cd "$common_dir" 2>/dev/null && pwd -P) || return 1
  main_root=$(dirname "$common_dir")
  prefix=$(git rev-parse --show-prefix 2>/dev/null) || return 1
  cand="$main_root/${prefix}$PW_FILE"
  [[ -f "$cand" ]] || return 1
  printf '%s' "$cand"
}

# Fly secrets に APP_PASSWORD が登録済みか。値は取得できないので存在チェックのみ。
#   0 = 登録済み / 1 = 未登録 / 2 = 判定不能（API エラー・認証切れ等）
# 「判定不能」を「未登録」に丸めると本番パスワードを作り替えるので必ず区別する。
fly_has_app_password() {
  local out
  out=$($FLY secrets list -a "$APP_NAME" --json 2>/dev/null) || return 2
  [[ -n "$out" ]] || return 2
  printf '%s' "$out" | python3 -c 'import sys, json
try:
    items = json.load(sys.stdin)
except Exception:
    sys.exit(2)
if not isinstance(items, list):
    sys.exit(2)
for it in items:
    if not isinstance(it, dict):
        continue
    for k, v in it.items():
        if str(k).lower() == "name" and v == "APP_PASSWORD":
            sys.exit(0)
sys.exit(1)'
}

gen_password() { python3 -c "import secrets; print(secrets.token_urlsafe(18))"; }

save_password() {
  printf '%s' "$1" > "$PW_FILE"
  chmod 600 "$PW_FILE"
}

# 0. 事前チェック: HEAD と main の分岐（並行 worktree による巻き戻しを防ぐ）
fly_guard_precheck

say "flyctl: $($FLY version)"

# 1. ログイン
if ! $FLY auth whoami >/dev/null 2>&1; then
  say "flyctl ログインを開始（ブラウザが開きます）"
  $FLY auth login
fi
ok "ログイン済: $($FLY auth whoami)"

# 2. アプリ（パスワード解決より先。「アプリが無い＝正真正銘の初回」の判定に使う）
if ! $FLY status -a "$APP_NAME" >/dev/null 2>&1; then
  say "アプリ作成: $APP_NAME"
  $FLY apps create "$APP_NAME" --org personal
  APP_EXISTS=0
else
  ok "アプリ既存: $APP_NAME"
  APP_EXISTS=1
fi

# 3. パスワード解決
#
#   ここは本番の owner 認証トークンそのもの。作り替えると iPhone の PWA に
#   保存されたログインが即座に無効になり、ユーザーが締め出される。
#   この環境は main を共有する worktree が 20 個以上並行で動いており、
#   .gitignore 済みの .app_password は worktree には存在しないので、
#   「ファイルが無い＝新規生成」にすると簡単に事故る。
#
#   優先順位:
#     1) 環境変数 APP_PASSWORD          … 明示指定
#     2) このツリーの .app_password
#     3) メインチェックアウトの .app_password … worktree から実行した場合
#     4) Fly secrets に登録済み          … 生成も上書きもせず既存値を維持
#     5) 上記すべて無し                  … 正真正銘の初回だけ新規生成
#   4) と 5) を区別できないとき（API エラー等）は生成せず中止する。
PW_KEEP_EXISTING=0
PW_SOURCE=""
MAIN_PW_FILE=""

if [[ -n "${APP_PASSWORD:-}" ]]; then
  save_password "$APP_PASSWORD"
  PW_SOURCE="環境変数 APP_PASSWORD（$PW_FILE に保存）"
elif [[ -f "$PW_FILE" ]]; then
  APP_PASSWORD=$(cat "$PW_FILE")
  PW_SOURCE="$PW_FILE"
elif MAIN_PW_FILE=$(find_main_pw_file); then
  APP_PASSWORD=$(cat "$MAIN_PW_FILE")
  PW_SOURCE="$MAIN_PW_FILE（メインチェックアウトから流用）"
  ok "worktree 実行を検出: メインチェックアウトの $PW_FILE を流用します"
elif [[ "$APP_EXISTS" == "1" ]]; then
  PW_RC=0
  fly_has_app_password || PW_RC=$?
  case "$PW_RC" in
    0)
      APP_PASSWORD=""
      PW_KEEP_EXISTING=1
      PW_SOURCE="Fly secrets の既存値（継続・表示不可）"
      ok "手元に $PW_FILE はありませんが Fly secrets に APP_PASSWORD が既にあります"
      ok "→ 新規生成せず既存パスワードを維持します（PWA のログインは無効になりません）"
      ;;
    1)
      APP_PASSWORD=$(gen_password)
      save_password "$APP_PASSWORD"
      PW_SOURCE="新規生成 → $PW_FILE（Fly secrets 未登録のため）"
      ;;
    *)
      err "Fly secrets の APP_PASSWORD 有無を確認できませんでした（$APP_NAME）。"
      err "ここで新規生成すると本番パスワードを作り替えて PWA から締め出すため中止します。"
      err "  対処 1: flyctl auth login でログイン状態を確認して再実行"
      err "  対処 2: APP_PASSWORD=<既知のパスワード> ./deploy.sh で明示指定"
      exit 1
      ;;
  esac
else
  APP_PASSWORD=$(gen_password)
  save_password "$APP_PASSWORD"
  PW_SOURCE="新規生成 → $PW_FILE（初回デプロイ）"
fi
ok "パスワード: $PW_SOURCE"

# 4. ボリューム
if ! $FLY volumes list -a "$APP_NAME" 2>/dev/null | grep -q "$VOLUME_NAME"; then
  say "ボリューム作成: $VOLUME_NAME (1GB / $REGION)"
  $FLY volumes create "$VOLUME_NAME" -a "$APP_NAME" -r "$REGION" -s 1 --yes
else
  ok "ボリューム既存: $VOLUME_NAME"
fi

# 5. シークレット
if [[ "$PW_KEEP_EXISTING" == "1" ]]; then
  ok "APP_PASSWORD は Fly secrets の既存値を継続（上書きしません）"
else
  say "APP_PASSWORD を Fly secrets に登録"
  $FLY secrets set APP_PASSWORD="$APP_PASSWORD" -a "$APP_NAME" --stage >/dev/null
fi

# 6. デプロイ
say "デプロイ実行"
$FLY deploy -a "$APP_NAME" --ha=false

# 6b. 本番検証: 本番 /app/*.py がいま deploy したソースと一致するか
#     （並行セッションが別コミットからデプロイしていると不一致になる）
if ! fly_guard_verify "$APP_NAME" "$FLY"; then
  err "デプロイ後の検証に失敗しました。本番は意図した内容になっていません。"
  exit 1
fi

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
if [[ "$PW_KEEP_EXISTING" == "1" ]]; then
  echo "    PW:   （既存のパスワードを継続。$PW_FILE が無いため表示できません）"
else
  echo "    PW:   $APP_PASSWORD"
fi
echo
echo " iPhone Safari で開く → ログイン → ホーム画面に追加"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
