# TAITAN PRO DM PWA

IG DMスカウト運用のモバイルWebアプリ（PWA）。ホーム画面に追加してネイティブアプリのように使える。

**☁️ クラウド運用（推奨）**: Fly.io で固定URL公開。Macスリープでも動く。→ [DEPLOY.md](./DEPLOY.md)

## 初回起動

```bash
cd liver_app
./run.sh
```

初回は自動で:
1. Python venv作成 + 依存インストール
2. SQLite初期化
3. 既存 `data/leads.csv` + `data/ig_qualified.json` を移行
4. `http://localhost:5050` で起動

## Macローカルで動作確認

ブラウザで `http://localhost:5050` を開く。

## iPhoneから使う（同じWi-Fi）

1. Macの同一LAN内IP確認: `ipconfig getifaddr en0`
2. iPhone Safariで `http://<MacのLAN IP>:5050` を開く
3. 共有ボタン → **ホーム画面に追加**
4. ホーム画面のアイコンから起動（全画面で動く）

## 外出先からも使う（推奨）

### Tailscale（一番簡単）

1. Mac側: `brew install --cask tailscale` → 起動してログイン
2. iPhone: App Store から Tailscale インストール → 同じアカウントでログイン
3. MacのTailscale名を確認（例: `mac-mini`）
4. iPhoneで `http://mac-mini:5050` を開く
5. 共有 → ホーム画面に追加

MagicDNSで固定URL、どこからでも繋がる。

### Cloudflare Tunnel（Macを閉じてても継続したい場合）

※ Macが動いてないとAPI叩けないので基本Tailscaleで十分

## IG認証について

- Mac Chromeで `instagram.com` にログイン済であれば、`browser-cookie3` が自動でCookieを取得して認証に使う
- もしCookie取得に失敗したら、設定画面の「IG Cookie（手動フォールバック）」に
  - Chrome DevTools（F12）→ Network タブ → `instagram.com` リクエスト → Headers の `Cookie:` 値を丸ごと貼付
  - `sessionid=...; ds_user_id=...;` のような形式

## 機能

### キュータブ
精査通過・未送信リード一覧。各カード:
- 📱 IGで開く → IGアプリ直起動
- 📋 DM本文コピー → スマホクリップボード
- ✓ 送信済 → 1タップで記録

### リサーチタブ
- ハッシュタグ設定（`#不要`）
- 「リサーチ実行」 → 裏で `/api/v1/tags/web_info` + `/api/v1/users/web_profile_info` を叩いて自動精査
- 進捗表示 + 履歴

### 設定タブ
- フォロワー上限/下限、比率、年齢レンジ、日次上限
- DMテンプレート編集
- IG Cookie手動フォールバック

### 統計タブ
- 送信数、キュー数、総数
- 直近送信リスト

## ファイル構成

```
liver_app/
  app.py         # Flask
  db.py          # SQLite（leads / settings / research_runs）
  ig_api.py      # IG内部API + browser-cookie3
  qualify.py     # 精査判定
  migrate.py     # CSV→SQLite
  run.sh         # 起動スクリプト
  static/
    index.html   # PWA SPA
    manifest.webmanifest
    sw.js        # Service Worker
    icon-192.png
    icon-512.png
  data.sqlite    # DB（gitignore）
```

## よくあるつまずき

- **「IG Cookieが取得できません」**: Chrome閉じてる or IG未ログイン。Chrome開いてinstagram.comにログインするか、手動Cookie貼付。
- **iPhone `instagram://` が効かない**: IGアプリ未インストール or バージョン古い → ブラウザリンクタップ
- **Service Workerがキャッシュ効きすぎ**: Safari → サイト設定 → データ削除
