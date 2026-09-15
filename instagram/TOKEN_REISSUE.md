# Instagram トークン再発行手順（インサイト権限つき）

> ## ⚠️ まずここを読む：再発行しても直らない型がある（2026-09-15）
>
> `Unsupported get/post request. Object with ID '...' does not exist, cannot be
> loaded due to missing permissions, or does not support this operation`
> （**code=100 / error_subcode=33**）が出ているときは、**この手順をやっても直らない。**
>
> このエラーは次の5つの、どれでもまったく同じ文面で返る。
>
> | # | 原因 | 再発行で直るか |
> |---|---|---|
> | a | `INSTAGRAM_BUSINESS_ID` が別アカウントのIDになっている | ❌ |
> | b | トークンが別のFacebookユーザー／別アプリのもの | ✅ |
> | c | Facebookページ ↔ IGビジネスアカウントの連携が切れた | ❌ |
> | d | トークン生成時にそのページを許可しなかった | ✅ |
> | e | **IGアカウント自体が消えた／停止された** | ❌（復旧不能） |
>
> 先に切り分ける。**Actions → 「Instagram API 診断」を手動実行するだけ**。
>
> ```bash
> gh workflow run instagram_diagnose.yml
> ```
>
> 正本は `instagram/ig_diagnose.py`。トークンは出力せず、`INSTAGRAM_BUSINESS_ID`
> も指紋と一致判定だけを出すので、ログが公開されても安全。
>
> 読み方:
>
> - `3. /me/accounts` に対象ページが出ていて、`5.` が ✅ → 正常
> - `7. 判定` に**候補IDが出ている**のに Secrets と不一致 → **(a)**。Secretsを差し替える
> - `1. debug_token` の `user_id` が想定と違う → **(b)**。正しいFBアカウントで取り直す
> - `granular_scopes` の `target_ids` が0件 → **(d)**。生成時にページを選び直す
> - 候補が0件＋`/me/accounts` も0件 → **(c)** か **(e)**。次の節へ
>
> ### アカウント到達不能のとき（(c) / (e) の切り分け）
>
> APIを使わずに、**ログアウト状態のブラウザで公開URLを直接開く**のが一番速い。
>
> 1. `https://www.instagram.com/<ユーザー名>/`
> 2. 過去投稿の permalink（`data/ig_insights.csv` の `permalink` 列から1つ）
>
> - どちらも普通に表示される → アカウントは生きている＝**(c)**。
>   IGアプリ → 設定 → アカウントの種類とツール → プロフェッショナルアカウント／
>   Facebookページの連携を張り直し、そのうえで下の手順1からトークンを取り直す。
> - **「Profileは利用できません」「Postは利用できません」** → **(e)**。
>   アカウントが削除または停止されている。APIでは何をしても復旧しない。
>   IGアプリに該当アカウントでログインして、停止通知と異議申し立て導線を確認する。
>   ※ ログイン壁と混同しないよう、必ず**生きている別アカウントで対照実験**する
>   （例: `@taitanblog` が同じログアウト状態で見えるかどうか）。
>
> ### 実例: 2026-09-12〜15 の停止
>
> **原因は (e)。`@taitan_pro7` が Instagram 上から消滅していた。**
>
> - トークンは正常（`is_valid=true` / 期限 2026-11-10 / 必要な6スコープすべて granted）
> - `INSTAGRAM_BUSINESS_ID` も変更なし
> - 消滅した時刻は **2026-09-11 14:08〜20:46 JST の間**
>   （05:08 UTC の番犬ランでは `GET` が成功、11:46 UTC の投稿ランで subcode 33）
> - ログアウト状態で `@taitanblog`・`@taitan_pro` は表示されるのに
>   `@taitan_pro7` と、その投稿 permalink 2本は「利用できません」
> - 09-11 の再発行はこの件と無関係（再発行の前後どちらでも同じIDが見えていた）
>
> **再発行を4日繰り返しても直らなかったのは、原因がトークンではなかったから。**

---

## ⏸ 2026-09-15：IG自動化は「一旦畳む」状態にしてある

ユーザー判断で停止した。**放置ではなく、再開条件つきで止めてある。**
今このリポジトリでIG関連が緑／静かなのは、直ったからではなく**見るのをやめたから**。

### 止めたもの

| 対象 | どう止めたか | 戻し方 |
|---|---|---|
| `instagram_post.yml`（30分おき起動） | `gh workflow disable` | `gh workflow enable instagram_post.yml` |
| `instagram_insights.yml`（週次） | 同上 | `gh workflow enable instagram_insights.yml` |
| `instagram_token_refresh.yml`（毎日） | 同上 | `gh workflow enable instagram_token_refresh.yml` |
| `instagram_post_watchdog.yml`（毎日） | 同上 | `gh workflow enable instagram_post_watchdog.yml` |
| `social_profile_guard.py` のIG走査 | `config.OFFICE_INSTAGRAM_SUSPENDED` を見て**対象から外す**（`--require-live` でも赤にしない。停止中の媒体として毎ラン表示は続く） | フラグを `""` に |
| `content_facts_guard.py` のIG実物走査（Graph API） | 同フラグでスキップ | フラグを `""` に |
| `content_facts_guard.py` の投稿済みIG記録走査 | 同フラグで**赤→警告**に降格（記録は消さない） | フラグを `""` に |
| Issue #55（投稿ウォッチドッグ） | クローズ | 再開後に再発すれば番犬が立て直す |

**止めていないもの**: `instagram_diagnose.yml`（手動実行専用なので空回りしない。
下の再開判定にそのまま使う）。

### 再開条件

次の**どちらか**が満たされたときだけ再開する。思いつきで戻さない。

1. **`@taitan_pro7` が復活した**
   異議申し立てが通り、ログアウト状態のブラウザで
   `https://www.instagram.com/taitan_pro7/` が普通に表示される。
2. **別アカウントで運用し直すと決めた**
   `@taitan_pro`（フォロワー11人）などに切り替える判断をした。
   ※ ただし IG実測ベースライン（92本）の結論は「**リーチの天井はフォロワー数**」で、
   15人 → 11人は**届く人が減る**乗り換えになる。決め打ちで動かないこと。

### 再開手順

1. `gh workflow run instagram_diagnose.yml` を回し、`7. 判定` が ✅ になることを確認する
   （ここが ✅ にならないうちは、下をやっても全部同じところで落ちる）
2. 別アカウントに変えた場合のみ:
   - GitHub Secrets の `INSTAGRAM_BUSINESS_ID` を差し替え
   - `config.py` の `OFFICE_INSTAGRAM` を新ハンドルに
   - `marketing/social_profiles.md`（正本）の Instagram 節を新アカウントに寄せる
   - `social_profile_guard.py` は `config.OFFICE_INSTAGRAM` から引くので**修正不要**
3. `config.py` の `OFFICE_INSTAGRAM_SUSPENDED` を `""` にする
4. 上の表の4本を `gh workflow enable` で戻す
5. `python3 content_facts_guard.py` と `python3 social_profile_guard.py --require-live` を
   手元で回し、**赤が戻ってくること**を確認する
   （緑のままなら降格が解除できていない＝また何も見ていない状態）

> ⚠️ 手順3をやらずに4だけ戻すと、**投稿は再開するのに番犬は黙ったまま**という
> 一番まずい状態になる。必ずフラグを先に戻すこと。

### 再開しないと決めたとき

`instagram/` 一式と上のワークフロー、`config.OFFICE_INSTAGRAM` 系の参照を消す。
そのときは `marketing/social_profiles.md` の Instagram 節と
`data/sns_recruitment_posts.md` の IG 節も一緒に畳む（片方だけ残すと、
次に読んだ人が「まだIG運用している」と誤読する）。


Metaの管理画面操作とFacebookのパスワード入力が要るので、**この作業だけは人間がやる**。
所要10分。終わったら「やった」と言ってもらえれば、あとの確認は自動で回せる。

---

## いつこの手順を使うか

次のどれかが起きたとき。

- `instagram_token_refresh.yml` が赤（`Session has expired` / `有効期限が延びていません`）
- `instagram_insights.yml` が赤で `(#10) Application does not have permission for this action`
- IG自動投稿が出ない（`instagram_post_watchdog.yml` が missed を検知）

**ただし上のバナーのとおり、`code=100 / subcode=33` のときは先に診断を回すこと。**
この手順（再発行）で直るのは (b)(d) だけで、(a)(c)(e) は直らない。

---

## 何が起きていたか（2026-09-11 時点の状況）

1. **トークンが失効している。**
   `INSTAGRAM_ACCESS_TOKEN` は 2026-09-09 00:38 JST（PDT 09-08 08:38）に切れた。
   以降 IG投稿も止まっていて、9/9（水）の回が丸ごと落ちている。

2. **自動更新は当てにならない。**
   `fb_exchange_token` は「すでに長期トークン」を渡すと、新しい文字列は返すのに
   有効期限を延ばさないことがある。2026-08-10〜09-07 は毎日「更新成功」と出ながら
   期限がずっと 09-08 のままだった。
   → だから下の **手順3（無期限のページトークンにする）を推奨**する。

3. **インサイトの権限が最初から無い。**
   今のトークンのスコープは
   `pages_show_list, instagram_basic, instagram_content_publish, pages_read_engagement, public_profile`
   で、`instagram_manage_insights` が入っていない。
   これが 2026-08-16 以降インサイト集計が毎週失敗している直接の原因。

---

## 手順

対象アプリ: **TAITAN PRO AutoPost**（App ID `26047190251647863`）
対象IG: **@taitan_pro7**

### 1. インサイト権限つきのユーザートークンを作る

1. https://developers.facebook.com/tools/explorer/ を開く（Facebookログイン）
2. 右上の **Metaアプリ** を `TAITAN PRO AutoPost` にする
3. **ユーザーまたはページ** → `ユーザートークン` を選ぶ
4. **アクセス許可** に次の5つが入っている状態にする（`instagram_manage_insights` が今回の追加分）
   - `instagram_basic`
   - `instagram_manage_insights` ← **これが今回の本命**
   - `instagram_content_publish`
   - `pages_show_list`
   - `pages_read_engagement`
5. **「アクセストークンを生成」** → Facebookのログイン確認 → ビジネス／ページを選んで続行
6. 出てきたトークンをコピーしておく

> **`instagram_manage_insights` が一覧に出てこないとき**
> アプリダッシュボード → `アプリの審査` → `アクセス許可と機能` で
> `instagram_manage_insights` を探して **標準アクセスをリクエスト**。
> 自分が管理者のアプリ＋自分が持っているIGアカウントなので、
> 審査申請（Advanced Access）は不要で、標準アクセスのまま使える。

### 2. 長期トークン（60日）に延長する

1. https://developers.facebook.com/tools/debug/accesstoken/ を開く
2. 手順1のトークンを貼って **「デバッグ」**
3. `instagram_manage_insights` がスコープ一覧に出ていることをここで必ず確認する
4. 下の **「アクセストークンを延長」** を押す → 60日の長期トークンが出る

### 3. 無期限のページトークンに変える（推奨・ここまでやると再発しない）

ページアクセストークンは「長期ユーザートークン」から取ると**期限が無い**。
毎月の自動更新が空振りする問題ごと消えるので、ここまでやるのが良い。

1. Graph APIエクスプローラーに戻る
2. アクセストークン欄に **手順2の長期トークン** を貼る
3. リクエスト欄を `GET` / `me/accounts` にして送信
4. 返ってきたJSONから、対象ページ（@taitan_pro7 を紐づけているFacebookページ）の
   `access_token` の値をコピーする ← **これが無期限トークン**
5. 念のため https://developers.facebook.com/tools/debug/accesstoken/ に貼って
   `有効期限: 受け取らない` / `データアクセスの有効期限` とスコープを確認する

### 4. GitHub Secrets を差し替える

1. https://github.com/taitan118120-dot/liver-acquisition/settings/secrets/actions
2. `INSTAGRAM_ACCESS_TOKEN` の **Update** に、手順3（取れなければ手順2）のトークンを貼る

### 5. 動いたか確かめる

```bash
gh workflow run instagram_insights.yml -f limit=200
```

期待する出力:

```
[INFO] トークン権限: ..., instagram_manage_insights, ...   ← WARNが消えていること
[INFO] 投稿 91 件を取得。インサイトを 2.0 秒間隔で取得します
[INFO] CAROUSEL_ALBUM で取得できる指標: reach, views, saved, likes, ...
[OK] data/ig_insights.csv に今回 91 件取得
```

`(#10) Application does not have permission for this action` が出たら、
手順1のアクセス許可か、手順4の貼り付け先を間違えている。

---

## そのあと（自動でやる分）

`data/ig_insights.csv` が実データで埋まれば、着弾時刻の実測ができる。

```bash
python instagram/ig_insights.py --slots-only
```

投稿ごとの reach / views は生涯値なので、**新しく2〜3週ぶん貯めなくても、
すでに投稿済みの91本だけで時刻別の比較ができる**。
Actionsの遅延で着弾が JST 20時台〜翌6時台までバラけているぶんが、そのまま
サンプルになっている。この表を根拠に `instagram/ig_slot.py` の `WINDOW`
（今は実測ではなく一般論で置いた暫定値）を決め直す。
曜日（月/水/金）と1日1本は変えない（[[feedback_ig_post_safety]]）。
