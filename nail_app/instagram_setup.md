# Instagram連携セットアップ手順（アカウント作成後にやること）

アプリ本体は完成済み。**あとはお母さんのネイル用アカウントを作って、下の①〜④で得た2つの値を `.env` に貼るだけ**で自動投稿が動きます。所要 20〜30分。

自動投稿は Meta の**公式API（コンテンツ公開API）**を使います＝BAN対象外の正規ルート。非公式ツールは使いません。

---

## ① Instagramをプロアカウントにする（無料・5分）

1. ネイル用のInstagramアカウントを作る（例: `@salon_xxx_nail`）
2. アプリで **設定 → アカウントの種類とツール → プロアカウントに切り替える**
3. カテゴリは「ネイルサロン」等、種類は **ビジネス** を選ぶ

## ② Facebookページを作って連携（無料・5分）

公式APIはFacebookページとの連携が必須です。

1. facebook.com でサロン用の**Facebookページ**を1つ作る（内容は空でOK）
2. Instagramアプリのプロフィール編集 → **ページ** で、作ったFacebookページを連携

## ③ Meta開発者アプリを作る（10分）

1. https://developers.facebook.com/ にFacebookでログインしてDeveloper登録
2. **マイアプリ → アプリを作成** → タイプ「**ビジネス**」
3. アプリに **Instagram Graph API** 製品を追加

## ④ アクセストークンと Business ID を取得

一番かんたんなのは **グラフAPIエクスプローラ** を使う方法：

1. https://developers.facebook.com/tools/explorer/ を開く
2. 右上で作成したアプリを選択
3. **Permissions（権限）** に次を追加:
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_show_list`
   - `pages_read_engagement`
   - `business_management`
4. **Generate Access Token** を押して承認 → 出てきた文字列が仮トークン
5. 下のクエリで **Business ID（数字）** を確認:
   ```
   GET  me/accounts?fields=instagram_business_account{id,username}
   ```
   返ってきた `instagram_business_account.id` の数字が **IG_BUSINESS_ID**

### 長期トークンにする（60日有効・重要）

エクスプローラの短期トークンは1〜2時間で切れます。次のURLをブラウザで開いて長期トークンに変換:

```
https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token&client_id=【アプリID】&client_secret=【アプリのシークレット】&fb_exchange_token=【④の仮トークン】
```

- アプリID / シークレットは Meta開発者コンソールの「アプリの設定 → ベーシック」
- 返ってきた `access_token` が **IG_ACCESS_TOKEN**（60日有効）

---

## ⑤ `.env` に貼る

`nail_app/.env.example` を `.env` にコピーして、この2つ（＋Gemini）を貼る:

```
IG_ACCESS_TOKEN=（④の長期トークン）
IG_BUSINESS_ID=（④の数字）
GEMINI_API_KEY=（すでに手元にあるGeminiキー）
SALON_NAME=（サロン名・任意）
SALON_BOOKING_URL=（LINE予約リンク等・任意）
```

保存して `./run.sh` を再起動すれば、写真を選ぶだけで自動投稿されます。

---

## トークンの更新について（60日ごと）

長期トークンは60日で切れます。切れるとアプリが「要トークン更新」と表示します。
- 手動: ④の変換URLをもう一度開いて新しいトークンを `.env` に貼り直す
- 自動化したい場合は「たいたん」に相談（`threads/threads_token.py` と同じ自動更新の仕組みを付けられます）

## よくある詰まりどころ

- **`instagram_business_account` が null**: ①のプロ化 or ②のFBページ連携が未完了。両方やり直す。
- **投稿が拒否される（画像URL）**: アプリは catbox / 0x0 の2経路で自動リトライ済み。両方落ちている時のみ失敗。
- **写真がHEIC**: iPhoneのHEICもアプリが受け付けます（Geminiは解析可）。もし投稿だけ弾かれる場合はiPhoneの「設定→カメラ→フォーマット→互換性優先」でJPEG保存に。
