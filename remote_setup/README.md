# スマホから Claude Code をリモート操作するセットアップガイド

Mac (macOS) 上の Claude Code CLI を iPhone からリモートで操作する方法を3つ紹介する。
簡単な順に並べているので、方法1から試すことを推奨する。

---

## 方法1: Claude Code のスケジュールタスク機能（最も簡単）

Claude Code には `scheduled-tasks` MCP ツールが組み込まれている。
スマホから直接操作するのではなく、タスクを事前にスケジュールしておく方式。

### 使い方

Claude Code の対話セッション内で以下のように指示する:

```
スケジュールタスクを作成して。毎朝9時にブログ記事の更新状況をチェックして報告するタスク。
```

Claude が `mcp__scheduled-tasks__create_scheduled_task` を使って自動でタスクを登録する。

### メリット
- 追加設定不要
- セキュリティリスクなし
- スマホ操作すら不要（自動実行）

### デメリット
- リアルタイムの対話的操作はできない
- 事前にタスク内容を決めておく必要がある

---

## 方法2: SSH 接続（推奨 - リアルタイム操作）

iPhone の SSH アプリから Mac に接続し、Claude Code CLI を直接操作する。

### Step 1: Mac で SSH（リモートログイン）を有効化

```bash
# システム設定 > 一般 > 共有 > リモートログイン を有効にする
# または、ターミナルで:
sudo systemsetup -setremotelogin on
```

### Step 2: Mac のローカル IP を確認

```bash
ipconfig getifaddr en0
```

例: `192.168.1.10` のような値が表示される。メモしておく。

### Step 3: iPhone に SSH アプリをインストール

以下のいずれかを App Store からインストール:

| アプリ名 | 価格 | 特徴 |
|---------|------|------|
| **Termius** | 無料 | 使いやすいUI、おすすめ |
| **Blink Shell** | 有料 | 高機能、プロ向け |
| **a-Shell** | 無料 | 軽量 |

### Step 4: iPhone から接続

アプリで以下の情報を入力:

```
ホスト: 192.168.1.10  (Step 2 で確認した IP)
ユーザー: mitataisei
ポート: 22
認証: パスワード または SSH鍵
```

### Step 5: Claude Code を起動

SSH 接続後、ターミナルで:

```bash
cd ~/ライバー獲得
claude
```

これで iPhone から Claude Code を対話的に操作できる。

### 外出先からも使いたい場合（Tailscale推奨）

同じ Wi-Fi にいないとき（外出先など）は、VPN が必要。
**Tailscale** が最も簡単:

1. Mac に Tailscale をインストール: https://tailscale.com/download
2. iPhone にも Tailscale をインストール（App Store）
3. 同じアカウントでログイン
4. Tailscale が割り当てた IP（100.x.x.x）で SSH 接続

```bash
# Mac 側で Tailscale をインストール
brew install tailscale
```

これでカフェや電車の中からでも SSH 接続できる。

### メリット
- 完全な対話的操作が可能
- Claude Code の全機能が使える
- Tailscale を使えば外出先からもアクセス可能

### デメリット
- SSH の初期設定が必要
- iPhone 用 SSH アプリが必要

---

## 方法3: Web ベースターミナル（ttyd）

ブラウザからアクセスできる Web ターミナルを立ち上げる方式。
iPhone の Safari から Mac のターミナルを操作できる。

### Step 1: ttyd をインストール

```bash
brew install ttyd
```

### Step 2: 起動スクリプトを使う

このディレクトリに `start_web_terminal.sh` を用意してある。

```bash
cd ~/ライバー獲得/remote_setup
chmod +x start_web_terminal.sh
./start_web_terminal.sh
```

### Step 3: iPhone の Safari からアクセス

```
http://192.168.1.10:7681
```

（IP は Mac のローカル IP に置き換える）

### セキュリティに関する注意

- ttyd はデフォルトでは認証なしでターミナルを公開する
- 起動スクリプトにはベーシック認証を設定済み（ユーザー名/パスワードを変更すること）
- **絶対にインターネットに直接公開しないこと**
- ローカルネットワーク内、または Tailscale 経由でのみ使用すること

### メリット
- アプリのインストール不要（Safari だけで使える）
- 設定が比較的簡単

### デメリット
- セキュリティリスクがやや高い
- ttyd のインストールが必要

---

## どの方法を選ぶべきか

| 用途 | 推奨方法 |
|------|---------|
| 定期的な自動タスク実行 | 方法1（スケジュールタスク） |
| iPhone からリアルタイム操作（自宅） | 方法2（SSH） |
| iPhone からリアルタイム操作（外出先） | 方法2（SSH + Tailscale） |
| アプリを入れたくない | 方法3（Web ターミナル） |

**初めての方へ**: まず方法2（SSH）を試すことを強く推奨する。
Termius アプリは無料で使いやすく、設定も10分程度で完了する。

---

## トラブルシューティング

### SSH 接続できない
```bash
# Mac 側でリモートログインが有効か確認
sudo systemsetup -getremotelogin

# ファイアウォールで SSH が許可されているか確認
# システム設定 > ネットワーク > ファイアウォール > オプション
# 「外部からの接続をすべてブロック」がオフになっていることを確認
```

### Claude Code が見つからない
```bash
# Claude Code のインストール確認
which claude

# パスが通っていない場合
export PATH="$HOME/.claude/bin:$PATH"

# まだインストールしていない場合
npm install -g @anthropic-ai/claude-code
```

### ttyd が見つからない
```bash
# Homebrew がインストールされていない場合
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# ttyd をインストール
brew install ttyd
```
