# Threads 自動投稿 セットアップ手順

公式 Threads API を使った本垢の自動投稿。**投稿のみ**で、自動フォロー・自動DM・自動いいねは
一切やらない（規約準拠・BAN対象外。Pull戦略・コールドDM廃止の方針どおり）。

## 仕組み（全体像）

| ファイル | 役割 |
|---|---|
| `threads/threads_poster.py` | Threads Graph APIで投稿（コンテナ作成→公開の2段階） |
| `threads/threads_content.py` | Geminiで募集投稿を生成しキューに追加（liver/agency） |
| `threads/threads_token.py` | 長期トークンの交換・確認・自動更新 |
| `threads/threads_posts.json` | 投稿キュー（先頭の未投稿を1本ずつ消化） |
| `.github/workflows/threads_post.yml` | 毎日 JST 8:00 / 20:00 に1本ずつ投稿 |
| `.github/workflows/threads_token_refresh.yml` | 月2回トークン延長 |

投稿頻度は **1日2回まで**（IGのサイバー警告と同じ感覚で安全側に）。

---

## 初回セットアップ（1回だけ・手作業が必要）

トークン取得だけは Meta の管理画面でのOAuthが要るので手動です。

### 1. Meta開発者アプリに Threads API を追加
1. https://developers.facebook.com/apps/ で既存アプリ（META_APP_ID のもの）を開く
   ※ 既存のInstagram用アプリと別にしたい場合は新規作成でもOK
2. 「ユースケースを追加」→ **「Access the Threads API（Threads APIへのアクセス）」** を追加
3. 権限（permissions）に **`threads_basic`** と **`threads_content_publish`** を付ける
4. 「Threads testers」に自分のThreads本垢を追加 → Threadsアプリ側で招待を承認

### 2. アクセストークンを生成
1. アプリの Threads ユースケース設定画面に **「Generate access token（アクセストークンを生成）」** ボタンがある
2. 本垢でログイン状態で押す → トークンが出る（短期の場合あり）
3. このトークンを控える

### 3. 長期トークンに交換（短期だった場合）
```bash
cd ~/ライバー獲得
export THREADS_SHORT_TOKEN="手順2で出たトークン"
export THREADS_APP_SECRET="ThreadsアプリのClient Secret"   # 無ければ META_APP_SECRET でも可
python threads/threads_token.py --exchange
```
→ 出力された長期トークンを控える（60日有効・自動更新で延長されます）。

### 4. ユーザーIDを確認
```bash
export THREADS_ACCESS_TOKEN="長期トークン"
python threads/threads_poster.py --whoami
# 例: アカウント: @taitan_xxx  (id=1234567890)
```
この `id` が THREADS_USER_ID です。

### 5. GitHub Secrets に登録
```bash
gh secret set THREADS_ACCESS_TOKEN   # 長期トークンを貼る
gh secret set THREADS_USER_ID        # 手順4のid
# GEMINI_API_KEY / GH_PAT は既存のものが使われます（X/IGと共通）
```

---

## 動作確認

```bash
# トークンが有効か
THREADS_ACCESS_TOKEN=xxx python threads/threads_token.py --check

# キューの先頭を投稿せず確認（dry-run）
THREADS_ACCESS_TOKEN=xxx THREADS_USER_ID=xxx \
  python threads/threads_poster.py --next --dry-run

# 1本だけ本投稿
THREADS_ACCESS_TOKEN=xxx THREADS_USER_ID=xxx \
  python threads/threads_poster.py --next

# 任意テキストを即投稿
THREADS_ACCESS_TOKEN=xxx THREADS_USER_ID=xxx \
  python threads/threads_poster.py --text "テスト投稿です"
```

## コンテンツ補充
```bash
GEMINI_API_KEY=xxx python threads/threads_content.py --gen 8
# liverのみ / agencyのみ:
GEMINI_API_KEY=xxx python threads/threads_content.py --gen 6 --angle liver
```
ワークフローは未投稿が4本未満になると自動でGemini生成して補充します。

---

## 運用ルール（安全 & 規約）
- **投稿のみ**。フォロー/DM/いいねの自動化は絶対にやらない。
- 1日2回まで。リンクは全投稿に貼らない（約3本に1本）。
- 確定ファクト厳守（還元率100%+α／所属200名／Pococha歴4年／B帯月20-30万）。
  「絶対稼げる」等の断定・誇大はNG。
- 代理店募集は**報酬を釣り文句にしない**（Wantedly作法。マルチ表現NG）。
- 受け皿は公式LINE `lin.ee/xchCfdn` ／ LP `taitan-pro-lp.netlify.app`。
  Threadsのプロフィール(bio)にこのリンクを必ず入れておく。

## トークン更新について
- 長期トークンは60日有効。`threads_token_refresh.yml` が月2回 `--refresh` して延長＋Secret更新。
- もし期限切れさせてしまったら、初回セットアップの手順2〜5をもう一度。
