# 💅 ネイル自動投稿アプリ（お母さん用）

石川県小松市のネイルサロン向け。**写真を選ぶだけ**でAIが文章とハッシュタグを付けて
Instagramに自動投稿するスマホアプリ（PWA）。

## しくみ

```
お母さんが写真を選ぶ
   ↓
Gemini が写真を解析（色・デザイン・雰囲気）→ 接客トーンのキャプション＋デザインタグ
   ↓
小松市・石川の地域ハッシュタグを自動で合成（合計〜28個）
   ↓
Instagram 公式API（コンテンツ公開API）で即投稿
```

- 非公式ツールは不使用＝**BAN対象外の正規ルート**
- お母さんの操作は「写真を選ぶ」だけ

## ファイル構成

| ファイル | 役割 |
|---|---|
| `app.py` | Flask本体（PWA・アップロード受付） |
| `vision.py` | Gemini で写真解析→キャプション＋タグ生成 |
| `hashtags.py` | 小松市・石川の固定タグ＋AIタグを合成 |
| `poster.py` | Instagram Graph API へ投稿（画像公開→コンテナ→公開） |
| `config.py` | 設定（`.env` から読む） |
| `templates/` | 画面（ログイン・投稿・履歴） |
| `instagram_setup.md` | **アカウント作成後の連携手順** |

## 使い始め方

### 1. いま出来ること（アカウント前でもOK）
```bash
cd nail_app
cp .env.example .env      # GEMINI_API_KEY だけ入れる
./run.sh
```
→ `http://localhost:5055` が開く。AI解析までは今すぐ試せる（投稿はアカウント連携後）。

### 2. アカウントを作ったら
`instagram_setup.md` の①〜⑤に沿って `IG_ACCESS_TOKEN` と `IG_BUSINESS_ID` を `.env` に入れる。
→ これだけで自動投稿が有効になる。

### 3. お母さんのスマホに置く（PWA）
- 同じWi-Fiで、お母さんのiPhoneのSafariで `http://（Macのローカルip）:5055` を開く
- 共有 → **ホーム画面に追加** → アイコンができる
- （外出先でも使うなら Fly.io 等へのデプロイを別途。`liver_app` と同じ手順で可能）

## あいことば
初期は `nail`（`.env` の `NAIL_APP_PASSWORD` で変更可）。
