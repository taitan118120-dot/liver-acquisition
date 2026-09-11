# Instagram トークン再発行手順（インサイト権限つき）

Metaの管理画面操作とFacebookのパスワード入力が要るので、**この作業だけは人間がやる**。
所要10分。終わったら「やった」と言ってもらえれば、あとの確認は自動で回せる。

---

## いつこの手順を使うか

次のどれかが起きたとき。

- `instagram_token_refresh.yml` が赤（`Session has expired` / `有効期限が延びていません`）
- `instagram_insights.yml` が赤で `(#10) Application does not have permission for this action`
- IG自動投稿が出ない（`instagram_post_watchdog.yml` が missed を検知）

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
