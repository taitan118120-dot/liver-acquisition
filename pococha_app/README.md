# pococha_app

Pococha 運営ダッシュボード（organizer-ope.pococha.com）から所属ライバーの成績を
取得し SQLite に蓄積する土台。

## 取得方法（ログイン中Chrome）

運営サイトはログインが必要なため、Claude in Chrome 拡張でログイン済みブラウザから取得する。

1. `https://organizer-ope.pococha.com/publishers` を開く
2. `extract_list.js` の中身を javascript_tool で評価 → `{headers, rows}` のJSONが返る
3. JSONを `data/list_YYYY-MM-DD.json` に保存
4. `python3 ingest.py data/list_YYYY-MM-DD.json` で取り込み（日付未指定なら今日のJST日付）

## 詳細ページ取得（/publishers/{id}）

各ライバー詳細ページには、ランク変動履歴・イベント入賞/エントリー履歴・配信一覧・
ダイヤ残高・プロフィール（レベル/性別/地域/フォロワー数/事務所登録日 等）がある。

1. `https://organizer-ope.pococha.com/publishers/{user_id}` を開く
2. `extract_publisher.js` の中身を javascript_tool で評価
   → 8テーブルを構造化し `publisher_{uid}_{date}.json` を Blob ダウンロード（戻り値はサイズ確認のみ）
3. ダウンロードした JSON を `data/publishers/` に置く
4. `python3 ingest_publisher.py`（引数なしで `data/publishers/*.json` を全取り込み）

注意: 詳細ページの「名前」はイベント幕付きで揮発的なため `display_name` に格納し、
コメント紐付けに使う `name` は上書きしない（新規ライバー登録時のみ設定）。
そのため詳細ページ初取得後は `ingest.py`（一覧）も流して `name` を確定させる。

## 成績コーチング（coach.py）

蓄積データから各ライバーの「現状・要サポート・伸び/推移・次の目標」を自動要約。

    python3 coach.py            # 全ライバー
    python3 coach.py むう        # 名前部分一致
    python3 coach.py 11874524   # user_id
    python3 coach.py --json     # 機械可読JSON

要サポート判定: 最終配信からの空き日数 / 直近7日の配信日数 / 5分未満NG配信数 /
ランクメーターのマイナス・降格 / 未同意。捏造防止のため昇格閾値などは推測しない。

## DB スキーマ（data/pococha.sqlite）

- `livers` — ライバーマスタ（user_id, name, display_name, X名, グループ名, 初回/最終取得日, level/gender/region/follows/followers/member_since/agency_since/close_time/ext_url）
- `snapshots` — 日次スナップショット（ランク・メーター・週/月ダイヤ・週/月ダイヤ発生時間(分)・配信時間/上限・同意・オフ日数）。`(user_id, captured_on)` で1日1件
- `off_days` — オフの日（user_id, 日付）
- `rank_history` — ランク変動履歴（change_id PK / 配信日 / Before / After / 変動理由 / メーター増減）
- `event_history` — イベント履歴（kind=entry/result / イベント名 / ステージ / ブロック / ステータス / 順位 / エントリー日時 / 期間）
- `streams` — 配信一覧（stream_id PK / タイトル / 配信時間(分) / 開始時間 / 状態 / 配信形態 / 配信種別 / 支払対象）
- `dia_balance` — ダイヤ残高（user_id, captured_on, diamonds, updated_at）

## 取得できる項目（一覧ページ）

ID / 名前 / X名 / オフの日 / ダイヤ発生時間(週・月) / ダイヤ数(週・月) /
ランク / 同意済み / 現在の配信時間・上限 / グループ名

## 過去配信のコメント収集

運営ダッシュボードの配信詳細 `/lives/{配信ID}` と `/lives/{配信ID}/comments` に、
**過去配信のコメント（ユーザー名 / 本文 / 配信内経過 / 投稿日時）が残っている**。
ただし約7割のリスナーは `*****` でマスクされ、見えるのは同意済み/常連層のみ。

### 仕組み

`pococha.com` / `studio.biz.pococha.com` は Claude in Chrome がブロックするため、
収集は **Tampermonkey ユーザースクリプト**で行う（同一オリジンfetchでクロール →
GM_xmlhttpRequest でローカルサーバーにPOST。https→http://localhost の mixed-content を回避）。

### 使い方

1. `python3 comment_server.py` を起動（http://127.0.0.1:5057）
2. Tampermonkey に `pococha_comments.user.js` を追加
3. `https://organizer-ope.pococha.com/` を開くと右下にパネルが出る
   - **このライバー** … 開いている `/publishers/{id}` のライバーのみ
   - **全ライバー** … 所属全員
4. クロール完了後、`http://127.0.0.1:5057/` で一覧確認・CSVダウンロード

各fetchは400ms間隔（Pococha側への配慮）。重複はサーバー側で自動排除。

## comment_server.py（コメント閲覧）

- `/`           … コメント一覧（ライバー絞り込み）
- `/export.csv` … CSVダウンロード
- `POST /api/comments` … ユーザースクリプトからの保存先（過去/ライブ共用）

## 注意

- コメントの約7割はマスク（`*****`）。非マスク＝同意済み/常連リスナーのみ取得可
- PocoStudio リンクは organizer トークン付きURLを含むため innerText のみ取得する
- pococha.com / studio.biz.pococha.com は Claude in Chrome では直接操作不可
