# Instagram自動投稿 セットアップガイド

## やること（3ステップ、約10分）

---

### ステップ1: Gemini APIキー取得（1分）

1. https://aistudio.google.com/apikey を開く
2. Googleアカウントでログイン
3. 「APIキーを作成」をクリック
4. 表示されたキーをコピー → メモ帳に貼り付け

---

### ステップ2: imgBB APIキー取得（1分）

1. https://api.imgbb.com/ を開く
2. 「Get API key」→ アカウント作成（Googleログイン可）
3. 表示されたAPIキーをコピー → メモ帳に貼り付け

---

### ステップ3: GitHub Secretsに設定（3分）

1. https://github.com/taitan118120-dot/liver-acquisition/settings/secrets/actions を開く
2. 「New repository secret」をクリックして、以下を1つずつ追加:

| Name | Value |
|------|-------|
| `GEMINI_API_KEY` | ステップ1のキー |
| `IMGBB_API_KEY` | ステップ2のキー |

---

### ステップ4: Meta（Instagram）設定（5分）※後でもOK

1. https://developers.facebook.com/ でアプリ作成
2. Instagramビジネスアカウントを接続
3. Graph APIエクスプローラーでトークン取得
4. GitHub Secretsに追加:

| Name | Value |
|------|-------|
| `INSTAGRAM_ACCESS_TOKEN` | Graph APIのトークン |
| `INSTAGRAM_BUSINESS_ID` | InstagramビジネスアカウントID |
| `META_APP_ID` | MetaアプリのApp ID |
| `META_APP_SECRET` | MetaアプリのApp Secret |

---

## テスト方法

```bash
# コンテンツ生成テスト（Gemini APIキーが必要）
GEMINI_API_KEY=あなたのキー python instagram/ig_content_generator.py --dry-run

# 投稿テスト（全APIキーが必要）
python instagram/ig_scheduler.py --test
```

## 自動投稿スケジュール

GitHub Actionsで毎日12:00と20:00（JST）に自動投稿されます。
手動実行: GitHub → Actions → Instagram自動投稿 → Run workflow
