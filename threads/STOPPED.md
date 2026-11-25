# Threads自動投稿 停止中（2026-11-25〜）

ユーザー判断で停止。スクリプト・キュー・ワークフローは消していない（無効化のみ）。

## 経緯
- 2026-11-13ごろ、キュー補充用の Gemini API が 402（`prepayment credits are depleted`、前払いクレジット切れ）になった。
  補充が毎回0本のまま空のキューで回り続け、11/12 09:05 JST を最後に投稿が出ていなかった（ワークフローは緑のまま）。
- 11/25 に手書きの22本をキューに入れて復旧を試みた（commit 552657c5）が、そのあと停止することにした。
  理由：10/24〜11/22 の公式LINEクリック（`data/threads_account.csv` の line_clicks_7d）が計1回、フォロワーが95人で横ばい。
  チャージして続ける価値が低い。
- 未投稿キューには、この手書き22本がそのまま残っている。

## 無効化したワークフロー（GitHub上で disabled_manually）
- `threads_post.yml`（自動投稿）
- `threads_post_watchdog.yml`（停止検知）
- `threads_insights.yml`（インサイト集計）
- `threads_token_refresh.yml`（トークン更新）

`social_pinned_publish.yml`（固定ポスト差し替え）は手動起動だけなので、有効のまま残している。

## 再開するとき
1. トークンの更新も止めているので、`THREADS_ACCESS_TOKEN` が切れていないか確認する。
   切れていれば再発行して secret を差し替える（`threads/SETUP_GUIDE.md`）。
2. Gemini で補充するなら、AI Studio で前払いクレジットが残っているか確認する。
   残っていなければ、手書き分のキューだけで回す（そのぶん持ちが短くなる）。
3. `gh workflow enable` で上の4本を戻し、`gh workflow run threads_post.yml -f dry_run=true` で投稿内容を確認する。
