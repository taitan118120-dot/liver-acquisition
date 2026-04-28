# TAITAN PRO X DM PWA

X(Twitter) DMスカウト運用のモバイルWebアプリ（PWA）。ホーム画面に追加してネイティブアプリのように使える。

**☁️ クラウド運用（推奨）**: Fly.io で固定URL公開。Macスリープでも動く。→ [DEPLOY.md](./DEPLOY.md)

## 初回起動

```bash
cd x_app
./run.sh
```

初回は自動で:
1. Python venv作成 + 依存インストール（tweepy含む）
2. SQLite初期化
3. `http://localhost:5051` で起動（liver_app=5050 と衝突回避）

## iPhoneから使う（同じWi-Fi）

1. Macの同一LAN内IP確認: `ipconfig getifaddr en0`
2. iPhone Safariで `http://<MacのLAN IP>:5051` を開く
3. 共有 → **ホーム画面に追加**

## X API 認証

X リサーチには Bearer Token が必要（GitHub Secrets と同じ `TWITTER_BEARER_TOKEN`）:

- 環境変数 `TWITTER_BEARER_TOKEN` を設定 → 自動使用
- もしくは設定タブの「X API Bearer Token」欄に貼付
- Free枠は 100 reads/月 と少ない。Basic($200/月) 以上推奨

**Free枠で運用したい場合**: Macの claude-in-chrome で x.com にログイン → 内部APIで検索/プロフィール取得 → `/api/ingest` にPOST する迂回ルート（IG版と同じ手法）。

## 機能

### キュータブ
精査通過・未送信リード一覧。各カード:
- 𝕏 アプリで開く → iOS Xアプリ直起動 (`twitter://user?screen_name=...`)
- 📋 DM本文コピー → スマホクリップボード
- ✓ 送信済 → 1タップで記録

### リサーチタブ
- 検索キーワード設定（種別ごと）
- 「リサーチ実行」 → X API v2 `tweets/search/recent` で投稿者抽出 → 自動精査
- `lang:ja -is:retweet -is:reply` は自動付与

### 設定タブ
- フォロワー上限/下限、比率、年齢レンジ、日次上限
- DMテンプレート（種別×複数バリエーション）
- X API Bearer Token 手動上書き

### 統計タブ
- 送信数、キュー数、総数 + 直近送信リスト

## ファイル構成

```
x_app/
  app.py         # Flask
  db.py          # SQLite（leads / settings / research_runs）
  x_api.py       # tweepy ラッパー（X API v2 Bearer）
  qualify.py     # 精査判定（IG版と共通ロジック）
  run.sh         # 起動スクリプト
  static/
    index.html   # PWA SPA
    login.html   # 認証画面
    manifest.webmanifest
    sw.js        # Service Worker
    icon-192.png
    icon-512.png
  data.sqlite    # DB（gitignore）
```

## ターゲット種別

- 🌱 **beginner**: 未経験ライバー候補（fl<10000）
- 🎤 **existing_liver**: 既存ライバー（Pococha以外、fl<5000）
- 🏢 **agency**: 副業/独立志向の代理店パートナー候補（fl<30000）

## よくあるつまずき

- **「TWITTER_BEARER_TOKEN が未設定」**: 環境変数 or 設定タブから貼付
- **rate limit エラー**: Free枠は月100ツイート読み込みで枯渇。Basic以上 or chrome MCP迂回
- **iPhone `twitter://` が効かない**: Xアプリ未インストール → 🌐 ボタンでブラウザを開く
