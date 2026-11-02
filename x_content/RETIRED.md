# X自動化は撤去済み（2026-11-02）

事務所X（@taitan_LIVER）の自動化は**全部撤去した**。GitHub Actions で X を叩くものはもう無い。
アカウント自体は残っている（手動で使うのは自由）。

## 経緯

| 日付 | できごと |
|---|---|
| 2026-08-23 | X API が `402 Payment Required / credits depleted` を返し始める。自動投稿もこの日で止まった（`data/recent_post_ids.txt` は373件で更新停止） |
| 2026-09-06〜16 | 402で毎日赤くなるのを止めるため、投稿・リプ候補・リスト追加を exit 75 → Issue #51 に集約（`x_credits.py`） |
| 2026-09-15 | ユーザー判断で「課金しない」。X全体が402で停止したまま |
| 2026-11-02 | 集約から漏れていた「X公開済みポストの違反走査・削除」が9週連続で失敗メールを出していたのを機に、ユーザー判断で**X自動化を全部撤去** |

フォロワーは17人前後（2026-08-08 の健康診断）で、402の2か月半でX経由の流入はゼロ。
止めて失った集客は事実上無い。

## 削除したもの

**ワークフロー**（11本。削除前に全部 `gh workflow disable` 済み）
`auto_post.yml`（自動投稿）/ `auto_evolve.yml`（投稿自動進化）/ `x_post_watchdog.yml` /
`auto_analyze.yml`（週次分析）/ `auto_list_add.yml`（リスト自動追加）/ `auto_follow.yml` /
`unfollow_bad.yml` / `x_health_check.yml` / `x_profile_update.yml` / `x_reply_digest.yml` /
`x_purge_violations.yml`

**スクリプト**
`cloud_post.py` / `cloud_evolve.py` / `cloud_analyze.py` / `cloud_list_add.py` / `cloud_follow.py` /
`cloud_unfollow_noback.py` / `cloud_engage.py` / `unfollow_bad.py` / `x_health_check.py` /
`x_profile_update.py` / `x_reply_digest.py` / `x_purge_violations.py` / `x_credits.py` /
`x_post_guard.py` / `x_queue_quarantine.py` / `.github/scripts/x_credits_issue.js` /
旧ローカルCLI（`run.py` / `engager.py` / `lead_finder.py` / `tracker.py`）

**キューと記録**
`posts/twitter_posts.json`（542本）/ `posts/twitter_posts_blocked.json` / `posts/1週間分スケジュール.txt` /
`data/` の `recent_post_ids.txt` / `posted_text_hashes.txt` / `analysis_report.json` /
`evolution_report.json` / `list_processed.json` / `unfollow_log.json` / `x_purge_report.json` /
`x_reply_digest.md` / `x_reply_seen.json`

**共用部分から外したX**
- `queue_facts_guard.py` … Xキューの走査（Threadsだけ残る）
- `social_profile_guard.py` … Xの実物取得（`fetch_x`）と402降格。Xは「手動確認」の欄に移した
- `social_pinned_publish.py` / `.yml` … `--post-x` / `--delete-x`（Threadsだけ残る）
- `config.py` … `X_API_CREDITS_DEPLETED_SUSPENDED`
- `auto_fix.yml` / `auto_retry.yml` … 監視対象からX系のワークフロー名
- `link_guard.py` … `posts/*` と `cloud_post.py` の走査

## 残したもの

| 残したもの | 理由 |
|---|---|
| `marketing/social_profiles.md` のX節（`canonical:x.*`） | アカウントは公開されたまま。番犬が正本の文面を確定ファクトで自己スキャンし続けるのと、手でプロフィールを直すときの正本として残す |
| `x_app/` と `x_content/x_posts.json` | 手動のDM・投稿ツール（PWA）。Fly.io本番は2026-09-07に撤収済みで、定期実行は無い |
| `dm_sender.py` / `config.py` のX設定 | `instagram/ig_dm_assist.py` が `dm_sender` を import している |
| GitHub Secrets の `TWITTER_*` | 消していない。再開しないと決まったら手で削除してよい |
| Issue #51（クレジット枯渇の集約Issue） | 撤去に合わせてクローズした |

## もう一度やるなら

復活させるのではなく**新しく作り直す**こと。削除したファイルは git 履歴に残っているが、
API料金（402を解くには課金が必要）と運用方針が当時と変わっている。

判断の前に確認すること:
- 2026-08-08 の健康診断では「投稿内容を改善しても流入は増えない」（抑制は無く、母数が小さいだけ）だった
- 自動リプライ・自動いいね・自動フォローは引き続きやらない（[[feedback_no_reply]] / [[feedback_no_likes]]）
- 投稿前の確定ファクト検品は `facts_patterns.py` の `COMMON_NG_PATTERNS` を使う
