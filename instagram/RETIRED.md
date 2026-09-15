# Instagram自動投稿は撤去済み（2026-09-16）

事務所IGの自動化は**恒久停止**した。このディレクトリに投稿する仕組みはもう無い。

## 経緯

| 日付 | できごと |
|---|---|
| 2026-09-07 16:17 | 最後に投稿できた回（`ig_viral_024`） |
| 2026-09-08 | `INSTAGRAM_ACCESS_TOKEN` 失効。ワークフローは success のままで投稿だけ落ちる |
| 2026-09-11 | **@taitan_pro7 が Instagram 上から消滅**。トークンも `INSTAGRAM_BUSINESS_ID` も正常なのに `code=100 / subcode=33`（アカウント到達不能）。APIでは復旧不能と診断で確定 |
| 2026-09-15 | ユーザー判断で「再開条件つきで一旦畳む」。ワークフローを `disabled_manually` に |
| 2026-09-16 | ユーザー判断で**恒久停止**。ワークフロー・投稿スクリプト・番犬のIG走査を削除 |

フォロワーは最大15人、実測92本のインサイトでも**フォーマット差・時刻差ともに効果が出ていなかった**
（[[project_ig_insights_baseline]] / [[project_ig_viral_carousel]]）。止めて失った集客は事実上ゼロ。

## 削除したもの

**ワークフロー**（6本）
`instagram_post.yml` / `instagram_post_watchdog.yml` / `instagram_insights.yml` /
`instagram_token_refresh.yml` / `instagram_diagnose.yml` / `ig_profile_update.yml`

**スクリプト**
`ig_poster.py` / `ig_scheduler.py` / `ig_slot.py` / `ig_token_refresh.py` / `ig_insights.py` /
`ig_diagnose.py` / `ig_viral_generator.py` / `ig_content_generator.py` /
一回限りの修正スクリプト4本（`ig_facts_fix_*` / `ig_marketsize_fix_*` / `ig_contract_axis_fix_*`）/
`SETUP_GUIDE.md` / `TOKEN_REISSUE.md` / ルートの `ig_profile_update.py` /
`marketing/enqueue_follower_posts.py`（`ig_content_generator` に依存していた実行済みの一回限りスクリプト）

**番犬からのIG走査**
- `content_facts_guard.py` … 投稿済みキャプション（記録・Graph APIの実物）の走査
- `queue_facts_guard.py` … IGキューの確定ファクト検品
- `social_profile_guard.py` … IG媒体の取得・突合、IG生成スクリプトとキューのハンドル検査
- `link_guard.py` … `ig_posts.json` / `ig_viral_generator.py` の走査
- `auto_retry.yml` … 「Instagram自動投稿」の再実行抑制の特例
- `config.py` … `OFFICE_INSTAGRAM_SUSPENDED`（見る側が消えたのでフラグごと削除）

## 残したもの

| 残したもの | 理由 |
|---|---|
| `ig_posts.json` | 投稿89本の記録。分析の元データとして残す（投稿する側はもう無い） |
| `images/` | 上と同じく記録。一部はNote等で流用しうる |
| `fonts/NotoSansJP-VF.ttf` | `generate_note_card_images.py` が使っている（IGとは無関係） |
| `ig_dm_assist.py` | IGのDMスカウト用。自動投稿とは別系統（[[project_ig_dm_session.md]] 側の話） |
| `config.OFFICE_INSTAGRAM` | `social_profile_guard.py` が「公開テキストに撤去済みIGハンドルが残っていないか」を毎日見るための照合元。運用先としては使わない |
| `marketing/social_profiles.md` のIG節 | 過去の記録。`canonical:` の印は外してあり、番犬は読まない |

## もう一度やるなら

復活させるのではなく**新規に作り直す**こと。上の削除ファイルは git 履歴に残っているが、
前提（アカウント・トークン・Business ID・投稿枠の設計）が全部変わるので、掘り起こす価値は低い。

最低限やり直しになるもの:

1. 新しいIGアカウント＋Facebookページ連携＋Business ID の取得
2. GitHub Secrets（`INSTAGRAM_ACCESS_TOKEN` / `INSTAGRAM_BUSINESS_ID`）の再登録
   ※ 今も Secrets には古い値が残っている。使い回さず必ず入れ直す
3. 投稿ワークフローと、投稿前の確定ファクト検品（`facts_patterns.py` が正本）
4. 番犬側の再接続（`social_profile_guard.py` の `EXPECTED_FIELDS` と
   `marketing/social_profiles.md` の `canonical:` は**必ず同時に**足す。
   片方だけだと「未知の媒体キー」で毎日赤くなる）

判断の前に [[project_ig_insights_baseline]] を読み直すこと。前回は
**フォーマットも投稿時刻も効かず、天井はフォロワー数だった**という実測が出ている。

### 作り直すとき必ず引き継ぐ運用ルール（GUIDE.md から移設）

2026-05-11 にIGから警告（サイバーセキュリティ規定違反の分類）を受けた経緯があるので、
新しいアカウントでも以下は厳守する（[[feedback_ig_post_safety]]）:

- 投稿頻度は**週3回が上限**（警告履歴がある間はここで止める。増やすとしても段階的に）
- キャプションでDM誘導・LINE誘導・「無料相談」の連呼をしない
- 「最短」「即日」「絶対」「保証」等の断定・即効性表現を使わない
- ハッシュタグは毎回同じセットを使い回さない。「#副業」系タグは1投稿につき最大1個

なお**リサーチ（スクレイピング）系はこれとは別の凍結中の話**で、
[`liver_app/IG_SCRAPING_FREEZE.md`](../liver_app/IG_SCRAPING_FREEZE.md) が正本。
再開時は捨て垢必須（[[feedback_ig_research_safety]]）。
