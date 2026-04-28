# Fly.io デプロイ — 1コマンド

```bash
cd x_app
./deploy.sh
```

これだけ。スクリプトが自動で:

1. flyctl 未ログインなら `flyctl auth login` を実行（ブラウザ起動）
2. パスワードが無ければランダム生成して `.app_password` に保存
3. アプリ (`taitan-pro-x-dm`) / ボリューム (`x_data`) / シークレット作成
4. デプロイ
5. 最後に URL とパスワードを表示

完了後 iPhone Safari で `https://taitan-pro-x-dm.fly.dev` を開く → パスワード入力 → 共有 → ホーム画面に追加。

## 2回目以降

```bash
./deploy.sh
```

同じ。冪等。

## アプリ名 / リージョン変更

```bash
FLY_APP=好きな名前 FLY_REGION=hkg ./deploy.sh
```

## X API Bearer Token 登録

クラウドでは環境変数で Fly secrets に登録するのが楽:

```bash
flyctl secrets set TWITTER_BEARER_TOKEN='AAAAAAAAAAAA...' -a taitan-pro-x-dm
```

または PWA 設定タブ → 「X API Bearer Token」貼付 → 保存（DB保存）。

## 監視 / SSH

```bash
flyctl logs -a taitan-pro-x-dm
flyctl status -a taitan-pro-x-dm
flyctl ssh console -a taitan-pro-x-dm
```

## 削除

```bash
flyctl apps destroy taitan-pro-x-dm
```
