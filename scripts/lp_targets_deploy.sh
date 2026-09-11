#!/usr/bin/env bash
# taitan-pro-lp-targets.netlify.app を lp/ から手動デプロイする（1コマンド）
#
# 背景（2026-09-11）:
#   LP は2つのサイトに配られている。
#     - taitan-pro-lp.netlify.app          … main への push で **自動** デプロイ
#     - taitan-pro-lp-targets.netlify.app  … **手動 zip デプロイ**（求人媒体・広告の遷移先）
#   「面談」→「お話しするとき」の置換は 4392b4f（2026-08-24）でリポジトリに入っていたが、
#   -targets 側は手動なので 2026-09-11 まで反映されず、応募者が見る面だけが3週間古かった。
#   手順が人の記憶にしか無いと、忘れたときに誰も気づけない。番犬（lp_drift_guard.py）で
#   気づけるようにしたので、復旧の手順もこのスクリプトとして残す。
#
# 使い方:
#   ./scripts/lp_targets_deploy.sh          # デプロイ → ready まで待つ → 番犬で検証
#   ./scripts/lp_targets_deploy.sh --no-verify   # 検証をスキップ
#
# トークン: ~/.netlify_token（無期限）

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE="taitan-pro-lp-targets.netlify.app"
TOKEN_FILE="${NETLIFY_TOKEN_FILE:-$HOME/.netlify_token}"
ZIP="$(mktemp -t lp_targets).zip"

say()  { printf "\033[1;36m==>\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m✓\033[0m %s\n" "$*"; }
err()  { printf "\033[1;31m✗\033[0m %s\n" "$*" >&2; }

trap 'rm -f "$ZIP"' EXIT

[ -f "$TOKEN_FILE" ] || { err "Netlifyトークンが無い: $TOKEN_FILE"; exit 1; }
TOKEN="$(cat "$TOKEN_FILE")"

say "lp/ を zip 化"
( cd "$REPO_ROOT/lp" && zip -rq "$ZIP" . -x "*.DS_Store" )
ok "$(du -h "$ZIP" | cut -f1) → $ZIP"

say "$SITE へアップロード"
# POST のレスポンスは state:"uploaded" で返る。公開が終わった状態ではないので、
# ここで検証に進むと「古い本文のまま緑/赤」を読むことになる。必ず ready まで待つ。
DEPLOY_ID="$(curl -sS -H "Content-Type: application/zip" \
  -H "Authorization: Bearer $TOKEN" \
  --data-binary "@$ZIP" \
  "https://api.netlify.com/api/v1/sites/$SITE/deploys" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
ok "deploy id: $DEPLOY_ID"

say "state:\"ready\" になるまで待機"
for _ in $(seq 1 60); do
  STATE="$(curl -sS -H "Authorization: Bearer $TOKEN" \
    "https://api.netlify.com/api/v1/deploys/$DEPLOY_ID" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("state",""), d.get("error_message") or "")')"
  printf "    %s\n" "$STATE"
  case "$STATE" in
    ready*) ok "公開完了"; break ;;
    error*) err "デプロイ失敗: $STATE"; exit 1 ;;
  esac
  sleep 5
done
case "$STATE" in ready*) ;; *) err "ready にならないままタイムアウト: $STATE"; exit 1 ;; esac

if [ "${1:-}" = "--no-verify" ]; then
  exit 0
fi

say "番犬で2サイトを突合（公開反映まで確認してから完了）"
python3 "$REPO_ROOT/lp_drift_guard.py"
