#!/usr/bin/env bash
# Fly.io デプロイ ガード（x_app / liver_app の deploy.sh から source して使う）
#
# 背景（2026-08-01 の事故）:
#   worktree から x_app を deploy した直後、別の並行セッションが main
#   （こちらの修正を含まない状態）から同じ app を deploy したため、本番の
#   /app/db.py が修正前に巻き戻った。両方の deploy が success で終わるため、
#   本番 DB を直読みするまで誰も気づかなかった。
#   この環境は main を共有する worktree が 20 個以上並行で動いている。
#
# 提供する関数:
#   fly_guard_precheck            … デプロイ前。HEAD と main の分岐を検査し確認を求める
#   fly_guard_verify APP_NAME     … デプロイ後。ローカルと本番 /app/*.py の md5 を照合
#
# 環境変数:
#   DEPLOY_GUARD=0        … ガードを完全に無効化（非推奨）
#   DEPLOY_GUARD_ACK=1    … 事前チェックの警告を承知の上で続行（非対話実行用）
#   FLY_API_TOKEN         … 未設定なら ~/.fly/config.yml から自動で読む

_dg_say()  { printf "\033[1;36m==>\033[0m %s\n" "$*"; }
_dg_ok()   { printf "\033[1;32m✓\033[0m %s\n" "$*"; }
_dg_warn() { printf "\033[1;33m!\033[0m %s\n" "$*"; }
_dg_err()  { printf "\033[1;31m✗\033[0m %s\n" "$*" >&2; }

# Dockerfile の COPY 行から本番 /app に入る .py を拾う。
# 明示リストを持たずに済むので Dockerfile を直したときに勝手に追随する。
# bash 3.2（macOS 標準）は $( ) の中のヒアドキュメントを解析できないため、
# python は必ず python3 -c 'シングルクォート文字列' で渡す（python 側は " のみ使う）。
_dg_target_files() {
  local dockerfile="${1:-Dockerfile}"
  [[ -f "$dockerfile" ]] || return 0
  python3 -c 'import re, sys
files = []
for line in open(sys.argv[1], encoding="utf-8"):
    if not re.match(r"^\s*COPY\s", line):
        continue
    for tok in line.split()[1:]:
        if tok.endswith(".py"):
            files.append(tok)
seen = set()
print("\n".join(f for f in files if not (f in seen or seen.add(f))))' "$dockerfile"
}

# ---------------------------------------------------------------- 事前チェック

fly_guard_precheck() {
  if [[ "${DEPLOY_GUARD:-1}" == "0" ]]; then
    _dg_warn "DEPLOY_GUARD=0 のため事前チェックをスキップ"
    return 0
  fi
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    _dg_warn "git リポジトリ外のため事前チェックをスキップ"
    return 0
  fi

  # flyctl が ~/.fly/config.yml を拾えない環境（サンドボックス実行など）だと
  # deploy.sh のログイン確認でブラウザが開いて止まるので、先に token を渡しておく
  _dg_ensure_token

  local branch head problems=()
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
  head=$(git rev-parse --short HEAD 2>/dev/null || echo "?")
  _dg_say "デプロイ元: ブランチ $branch @ $head"

  # 1. 本番に載るファイルに未コミットの変更がないか
  #    （コミットされていない変更は、他セッションが main からデプロイした瞬間に消える）
  #    ログ等は対象外にしたいので、アプリ配下丸ごとではなく実際に COPY される
  #    ファイルだけを見る。
  local shipped=(Dockerfile requirements.txt static)
  local sf
  while IFS= read -r sf; do
    if [[ -n "$sf" ]]; then shipped+=("$sf"); fi
  done < <(_dg_target_files Dockerfile)

  if ! git diff --quiet -- "${shipped[@]}" 2>/dev/null \
     || ! git diff --cached --quiet -- "${shipped[@]}" 2>/dev/null; then
    problems+=("本番に載るファイルに未コミットの変更がある（他セッションが main からデプロイすると即座に巻き戻る）")
    git status --short -- "${shipped[@]}" | sed 's/^/      /'
  fi

  # 2. 比較対象の main を決める（origin/main 優先、無ければローカル main）
  GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=10" \
    git fetch --quiet origin main 2>/dev/null \
    || _dg_warn "origin/main の取得に失敗（ローカルの情報で判定します）"
  local main_ref=""
  if git rev-parse --verify --quiet origin/main >/dev/null 2>&1; then
    main_ref="origin/main"
  elif git rev-parse --verify --quiet main >/dev/null 2>&1; then
    main_ref="main"
  fi

  if [[ -z "$main_ref" ]]; then
    _dg_warn "main が見つからないため分岐チェックをスキップ"
  else
    # main にあって HEAD に無いコミット → デプロイすると main の作業が落ちる
    if ! git merge-base --is-ancestor "$main_ref" HEAD 2>/dev/null; then
      local n
      n=$(git rev-list --count "HEAD..$main_ref" 2>/dev/null || echo "?")
      problems+=("$main_ref が HEAD より $n コミット進んでいる（デプロイすると main 側の変更を含まない版が本番に載る）")
      git log --oneline --no-decorate -5 "HEAD..$main_ref" -- . 2>/dev/null | sed 's/^/      /'
    fi
    # HEAD にあって main に無いコミット → 他セッションの main デプロイで巻き戻る
    if ! git merge-base --is-ancestor HEAD "$main_ref" 2>/dev/null; then
      local n
      n=$(git rev-list --count "$main_ref..HEAD" 2>/dev/null || echo "?")
      problems+=("HEAD の $n コミットが $main_ref に未マージ（他セッションが main からデプロイすると本番が巻き戻る）")
      git log --oneline --no-decorate -5 "$main_ref..HEAD" -- . 2>/dev/null | sed 's/^/      /'
    fi
  fi

  if [[ ${#problems[@]} -eq 0 ]]; then
    _dg_ok "HEAD と ${main_ref:-main} は同期済み"
    return 0
  fi

  echo
  _dg_warn "デプロイ前の警告:"
  local p
  for p in "${problems[@]}"; do
    printf "    - %s\n" "$p"
  done
  echo
  echo "  推奨: 先に main へマージ（またはローカルを main に追随）してからデプロイしてください。"
  echo

  if [[ "${DEPLOY_GUARD_ACK:-0}" == "1" ]]; then
    _dg_warn "DEPLOY_GUARD_ACK=1 のため警告を承知で続行します"
    return 0
  fi
  if [[ ! -t 0 ]]; then
    _dg_err "非対話実行のため中止しました。承知の上で進めるなら DEPLOY_GUARD_ACK=1 ./deploy.sh"
    exit 1
  fi
  local ans
  read -r -p "  それでもデプロイしますか? [y/N] " ans
  case "$ans" in
    y|Y|yes|YES) _dg_warn "続行します" ;;
    *) _dg_err "中止しました"; exit 1 ;;
  esac
}

# ---------------------------------------------------------------- 事後チェック

_dg_ensure_token() {
  if [[ -n "${FLY_API_TOKEN:-}" ]]; then
    return 0
  fi
  local tok
  tok=$(python3 -c 'import os
p = os.path.expanduser("~/.fly/config.yml")
try:
    raw = open(p, encoding="utf-8").read()
except OSError:
    raise SystemExit(1)
tok = ""
try:
    import yaml
    tok = (yaml.safe_load(raw) or {}).get("access_token") or ""
except Exception:
    pass
if not tok:
    for line in raw.splitlines():
        if line.startswith("access_token:"):
            tok = line.split(":", 1)[1].strip().strip(chr(34)).strip(chr(39))
            break
print(tok)' 2>/dev/null) || true
  if [[ -n "$tok" ]]; then export FLY_API_TOKEN="$tok"; fi
  return 0
}

# fly_guard_verify APP_NAME [FLY_BIN]
#   ローカルの主要ソースと本番 /app/*.py の md5 を突き合わせる。
#   1つでも食い違えば非ゼロ終了（＝デプロイは失敗扱い）。
fly_guard_verify() {
  local app_name="$1"
  local fly_bin="${2:-flyctl}"

  if [[ "${DEPLOY_GUARD:-1}" == "0" ]]; then
    _dg_warn "DEPLOY_GUARD=0 のため本番照合をスキップ"
    return 0
  fi

  local files=()
  while IFS= read -r f; do
    if [[ -n "$f" ]]; then files+=("$f"); fi
  done < <(_dg_target_files Dockerfile)
  if [[ ${#files[@]} -eq 0 ]]; then
    for f in db.py app.py; do
      if [[ -f "$f" ]]; then files+=("$f"); fi
    done
  fi
  if [[ ${#files[@]} -eq 0 ]]; then
    _dg_warn "照合対象のファイルが特定できないためスキップ"
    return 0
  fi

  _dg_say "本番との照合: ${files[*]}"
  _dg_ensure_token

  # マシン ID は毎回動的に引く（ハードコードしない）
  local machines
  machines=$($fly_bin status -a "$app_name" --json 2>/dev/null \
    | python3 -c 'import sys,json;print("\n".join(m["id"] for m in (json.load(sys.stdin).get("Machines") or [])))' 2>/dev/null || true)
  if [[ -z "$machines" ]]; then
    _dg_err "マシン一覧を取得できませんでした（$app_name）。照合できないので失敗扱いにします。"
    return 1
  fi

  # auto_stop で止まっていることがあるので公開 URL を 1 回叩いて起こす
  curl -s -o /dev/null --max-time 60 "https://${app_name}.fly.dev/" >/dev/null 2>&1 || true

  # ローカル側の md5
  local local_sums
  local_sums=$(python3 -c 'import hashlib, sys
for f in sys.argv[1:]:
    print(hashlib.md5(open(f, "rb").read()).hexdigest(), f)' "${files[@]}") \
    || { _dg_err "ローカルの md5 計算に失敗"; return 1; }

  local remote_paths=""
  local f
  for f in "${files[@]}"; do remote_paths+=" /app/$f"; done

  local ok_all=1
  local mid
  for mid in $machines; do
    local remote_raw="" attempt
    for attempt in 1 2 3; do
      remote_raw=$($fly_bin machine exec "$mid" -a "$app_name" \
        "sh -c 'md5sum$remote_paths'" 2>/dev/null || true)
      if [[ -n "$remote_raw" ]]; then break; fi
      sleep 5
    done
    if [[ -z "$remote_raw" ]]; then
      _dg_err "machine $mid から md5 を取得できませんでした"
      ok_all=0
      continue
    fi

    local mismatched=0
    while read -r lsum lfile; do
      [[ -z "$lfile" ]] && continue
      local rsum
      rsum=$(printf '%s\n' "$remote_raw" | awk -v p="/app/$lfile" '$2 == p {print $1}' | head -1)
      if [[ -z "$rsum" ]]; then
        _dg_err "  $lfile : 本番に存在しない（machine $mid）"
        mismatched=1
      elif [[ "$rsum" != "$lsum" ]]; then
        _dg_err "  $lfile : 不一致 local=$lsum remote=$rsum（machine $mid）"
        mismatched=1
      else
        _dg_ok "  $lfile : 一致 ($lsum)"
      fi
    done <<< "$local_sums"

    if [[ $mismatched -eq 1 ]]; then ok_all=0; fi
  done

  if [[ $ok_all -ne 1 ]]; then
    local here
    here=$(basename "$PWD")
    echo
    _dg_err "本番のソースがローカルと一致しません。"
    _dg_err "並行セッションが同じ app を別のコミットからデプロイした可能性があります。"
    _dg_err "  1) git log origin/main -- $here で他セッションのデプロイ内容を確認"
    _dg_err "  2) main へマージして最新の main から再デプロイ"
    return 1
  fi
  _dg_ok "本番のソースはローカルと一致しています"
  return 0
}
