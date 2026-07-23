# Fly.io デプロイ — 1コマンド

```bash
cd liver_app
./deploy.sh
```

これだけ。スクリプトが自動で:

1. flyctl 未ログインなら `flyctl auth login` を実行（ブラウザ起動）
2. パスワードが無ければランダム生成して `.app_password` に保存
3. アプリ / ボリューム / シークレット作成（既存ならスキップ）
4. デプロイ
5. `data.sqlite` があれば初回のみボリュームへ転送
6. 最後に URL とパスワードを表示

完了後 iPhone Safari で表示された URL を開く → パスワード入力 → 共有 → ホーム画面に追加。

## 2回目以降

```bash
./deploy.sh
```

同じ。冪等。コード変更後の再デプロイにも使える（DB 転送はスキップされる）。

## アプリ名 / リージョン変更

```bash
FLY_APP=好きな名前 FLY_REGION=hkg ./deploy.sh
```

## パスワード再発行

```bash
rm .app_password
./deploy.sh   # 新しいPWで再デプロイ
```

## IG Cookie 設定（デプロイ後の初回作業）

クラウドでは Chrome Keychain は使えないので手動貼付:

1. Mac Chrome で instagram.com にログイン
2. F12 → Network タブ → 任意のリクエスト → Headers の `Cookie:` 値をコピー
3. PWA の設定タブ → 「IG Cookie」貼付 → 保存

寿命数週間。401 出たら再貼付。

## 監視 / SSH

```bash
flyctl logs -a taitan-pro-dm
flyctl status -a taitan-pro-dm
flyctl ssh console -a taitan-pro-dm
```

## 削除

```bash
flyctl apps destroy taitan-pro-dm
```
