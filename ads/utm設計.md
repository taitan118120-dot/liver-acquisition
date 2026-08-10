# 流入元計測（utm）設計書

作成日：2026-08-10 / 対象：taitan-pro-lp.netlify.app 配下の全LP（beginner / agency / liver / sidejob）

> **なぜ作ったか**：2026-08-08 に開設以来初のコンバージョン1件（キャンペーンA経由・CPA ￥3,562）が出て、
> 広告クリック → LP → LINE の導線が端から端まで通ったことが実データで確認できた。
> ここから先の改善には「どこから来て、どのボタンを押したか」の分離が要る。
> 詳細は `ads/google_ads_設計書.md` §0-9。

---

## 1. 前提（先に読む）

| 事実 | 現在の状態 |
|---|---|
| GA4 測定ID | ⛔ **未発行**。`lp/shared/tracking.js` の `GA4_ID` は空。ここに `G-…` を入れて push すれば全LPで即有効になる |
| Google広告 CVタグ | ✅ 稼働中（`AW-429748464` / `-KwzCJvzmNQcEPDh9cwB`）。**utmとは無関係に動く**ので、utmを付けてもCVは壊れない（§4） |
| 自動タグ設定（gclid） | ✅ ON。Google広告のクリックには gclid が自動で付く |
| 計測実装の置き場所 | `lp/shared/tracking.js` **1ファイルのみ**。4つのLPが全部これを読む |

### 1-1. lin.ee には絶対に utm を付けない

**理由は2つある。両方とも実害が出る。**

1. **LINEはクエリパラメータを受け取らない。** `https://lin.ee/xchCfdn?utm_source=note` を付けても LINE 側で捨てられ、
   計測にも友だち追加経路にも一切反映されない。付ける意味がゼロ。
2. **`link_guard.py` が落ちる。** 許可リストは `LINE_ALLOWED = {"https://lin.ee/xchCfdn"}` の**完全一致**で、
   1文字でも違う lin.ee URL がリポジトリ内・公開Note内に現れると DEAD 判定になり GitHub Actions が赤くなる
   （`link_guard.py:45,191`）。

**したがって「LINEに直リンクする導線は、原理的に媒体別分離ができない」。**
媒体別に見たいものは **LPを経由させる**（LPのCTAクリックとして計測される）。§3 の方針はこの制約から来ている。

---

## 2. utm の値の決め方（全媒体共通ルール）

| パラメータ | 使い方 | 値の書式 |
|---|---|---|
| `utm_source` | **媒体**。どのサービスから来たか | 半角小文字。`google` `note` `threads` `instagram` `x` `indeed` `wantedly` `engage` `gbp` |
| `utm_medium` | **導線の種類**。同じ媒体の中のどこか | `cpc`（広告）／`article`（記事本文）／`profile`（プロフィール欄）／`post`（投稿）／`story`／`bio_link`／`organic` |
| `utm_campaign` | **施策のまとまり**。集計の主キー | 半角小文字＋アンダースコア。広告は `ads_a_kensou` 等、それ以外は §3 の表 |
| `utm_content` | **個体の識別**。どの記事・どの広告グループか | Note記事は記事番号（`097`）、広告は広告グループID |
| `utm_term` | 検索語・キーワード | Google広告のみ（`{keyword}` で自動挿入） |

**大文字・全角・日本語は使わない。** GA4 は `Note` と `note` を別ソースとして数える。

---

## 3. 媒体別の付与ルール

### 3-1. Google広告（7広告 ＋ サイトリンク）

**方式：「最終ページURLのサフィックス」をキャンペーン単位で設定する。広告ごとの最終ページURLは触らない。**

なぜトラッキングテンプレート（`{lpurl}?utm_…`）ではなくサフィックスなのか：

- テンプレートは `{lpurl}` の後ろにクエリを足すので、**サイトリンクのようにアンカー付きのURL**
  （`…/beginner/#cases`）だと `…/beginner/#cases?utm_source=…` になり、**アンカージャンプもutm解釈も両方壊れる**
- サフィックスは Google 側が最終ページURLに正しくマージする方式で、書式を間違えても
  ランディング自体は壊れない（テンプレートは書式ミスで全広告のリンク先が死ぬ）

設定場所：**キャンペーン → 設定 → その他の設定 → キャンペーンURLのオプション → 最終ページURLのサフィックス**

| キャンペーン | 設定する文字列（そのまま貼る） |
|---|---|
| A｜TAITANPRO_顕在層_事務所探し | `utm_source=google&utm_medium=cpc&utm_campaign=ads_a_kensou&utm_content={adgroupid}&utm_term={keyword}` |
| C｜TAITANPRO_競合名_テスト | `utm_source=google&utm_medium=cpc&utm_campaign=ads_c_kyogo&utm_content={adgroupid}&utm_term={keyword}` |
| D｜TAITANPRO_代理店パートナー | `utm_source=google&utm_medium=cpc&utm_campaign=ads_d_dairiten&utm_content={adgroupid}&utm_term={keyword}` |

`{adgroupid}` は数値IDで入る。読み替え表は初回設定時に管理画面から拾って下表に埋めること
（広告グループ一覧に「広告グループID」列を表示させれば取れる）。

| 広告グループ | ID | 対応 |
|---|---|---|
| A1_アプリ別事務所 | （未取得） | |
| A2_事務所比較 | （未取得） | |
| A3_募集 | （未取得） | |
| A4_地域 | （未取得） | |
| A5_検討層 | （未取得） | |
| C1_321 | （未取得） | |
| C2_ベガプロモーション | （未取得） | |
| D1〜 | （未取得） | |

**⚠️ 管理画面の変更はユーザー承認が必要。本書は設計を記録するだけで、稼働側は未変更（2026-08-10 時点）。**

適用したら必ず確認すること（3点）：

1. 広告プレビューではなく**実クリック**で着地し、アドレスバーに `utm_source=google` と `gclid=` の**両方**が乗っているか
2. **キャンペーンCのサイトリンク4本**（`#cases` `#reward` `#reasons` `#faq`）が、
   utm付与後も**該当セクションまでちゃんとジャンプするか**。アンカーが壊れていないかを目視する
3. 翌日、管理画面でCVが引き続き記録されているか（§4）

> 保険として、万一 `#cases?utm_source=…` の形で来た場合でも utm を読めるように
> `lp/shared/tracking.js` にハッシュ側パーサを入れてある（アンカージャンプ自体は直らないので、
> 上記2で壊れていたらサフィックスをサイトリンク個別に設定し直すこと）。

### 3-2. Note（公開108本）

Note記事のCTAは **LINE直リンク**と**LPリンク**の2本立てになっている。
LINE直リンクは §1-1 のとおり計測できないので、**LPリンク側にだけ utm を付ける**。

| 導線 | URL |
|---|---|
| 記事末CTAの「サイトを見る →」 | `https://taitan-pro-lp.netlify.app/beginner/?utm_source=note&utm_medium=article&utm_campaign=note_cta&utm_content={記事番号3桁}` |
| 記事冒頭CTA | 同上（`utm_medium=article_top`） |
| Noteプロフィール欄のリンク | `https://taitan-pro-lp.netlify.app/beginner/?utm_source=note&utm_medium=profile&utm_campaign=note_profile` |

- **新規記事**：`note_article_generator.py` のテンプレートに反映済み（2026-08-10）
- **公開済み108本**：本セッションでは書き換えていない。全記事の本文を書き換えるには
  `note_publish_core.py` 経由の再公開が要り、タグ・カバーの巻き添え事故リスクがある（記憶 `project_note_tag_guard`）。
  やるなら独立したタスクとして、少数記事で検証してから一括に進めること

### 3-3. Threads / Instagram / X

| 導線 | URL |
|---|---|
| Threads プロフィールリンク | `…/beginner/?utm_source=threads&utm_medium=profile&utm_campaign=threads_profile` |
| Threads 投稿内リンク | `…/beginner/?utm_source=threads&utm_medium=post&utm_campaign=threads_post` |
| Instagram プロフィールリンク | `…/beginner/?utm_source=instagram&utm_medium=profile&utm_campaign=ig_profile` |
| Instagram ストーリーズのリンク | `…/beginner/?utm_source=instagram&utm_medium=story&utm_campaign=ig_story` |
| X プロフィールリンク | `…/beginner/?utm_source=x&utm_medium=profile&utm_campaign=x_profile` |

⚠️ Instagram の**投稿本文にはURLを書かない**運用（`ig_content_generator.py:233`）なので、IGは
プロフィールリンク・ストーリーズだけが対象。

### 3-4. 求人媒体（Indeed / Wantedly / engage）

`job_generator.py` の `LP_URLS` に反映済み（2026-08-10）。

`…/{target}/?utm_source={indeed|wantedly|engage}&utm_medium=job&utm_campaign=job_{target}`

> ⚠️ 求人媒体の誘導先は **`taitan-pro-lp-targets.netlify.app`**（メインとは別のNetlifyサイト・**手動zipデプロイ**）。
> 今回追加した `shared/tracking.js` は、このサイトを**手動で再デプロイするまで反映されない**。
> utmだけ付いていても計測タグが無ければ何も取れないので、再デプロイまでは求人媒体の数字は出ないと理解しておくこと。

### 3-5. Googleビジネスプロフィール

`https://taitan-pro-lp.netlify.app/beginner/?utm_source=gbp&utm_medium=organic&utm_campaign=gbp_profile`

---

## 4. Google広告のCV計測を壊さないことの根拠

**結論：utm を付けても Google広告のコンバージョンは壊れない。** 理由を分解すると：

| 論点 | 事実 |
|---|---|
| CVの発火条件 | LINEボタンのクリック時に `gtag('event','conversion',{send_to:'AW-…/…'})` を送るだけ。**URLパラメータを一切参照していない**（`lp/shared/tracking.js`） |
| gclid の扱い | 自動タグ設定が付ける `gclid` は utm とは独立した別パラメータ。サフィックスで utm を足しても gclid は消えない |
| クリックとCVの紐付け | gtag（コンバージョンリンカー）が着地時に gclid を `_gcl_aw` Cookie に保存し、CV送信時にそれを使う。utm は関与しない |
| LP側の破壊リスク | `tracking.js` も `script.js` も URL を書き換えない。utm が付いたまま LINE へ遷移する |

### ローカル実測（2026-08-10）

`http://localhost:8899/beginner/?utm_source=google&utm_medium=cpc&utm_campaign=A_beginner&utm_content=A1&gclid=TEST_GCLID_12345`
に着地してヘッダーCTAをクリックし、gtag をスタブに差し替えて発火内容だけを捕捉した（実データは1件も送っていない）。

```
event line_cta_click {cta_position:"header", cta_label:"まずはLINEで相談してみる",
                      lp_page:"beginner", page_path:"/beginner/",
                      traffic_source:"google", traffic_medium:"cpc",
                      traffic_campaign:"A_beginner", traffic_content:"A1", has_gclid:"yes"}
event conversion     {send_to:"AW-429748464/-KwzCJvzmNQcEPDh9cwB", event_callback:FUNCTION}
```

`send_to` は Google広告発行の公式スニペットと完全一致（設計書 §0-9 の照合結果と同値）。
`event_callback` 経由の遷移も動作し、CTAの遷移先へ実際に移動することを確認済み。
17個のCTAすべてで `line_cta_click` 17件・`conversion` 17件＝**二重送信なし**も確認した。

### ⛔ まだ確認できていないこと（実データ待ち）

**「管理画面上でCVが引き続き記録される」ことは未確認。** サフィックスの適用自体がユーザー承認待ちで、
まだ稼働側に何も入れていないため。適用後の翌日〜翌々日に、
**期間セレクタを「過去30日間」等に直してから**（設計書 §0-2 の鉄則）CV列を確認すること。

---

## 5. LP側で取れるようになるもの

`GA4_ID` を入れた時点で、GA4 に `line_cta_click` イベントが以下のパラメータ付きで届く。

| パラメータ | 中身 | 何が分かるか |
|---|---|---|
| `cta_position` | `header` `hero` `campaign` … `dock` | **16箇所のどのボタンが押されたか**（設計書 §0-9 の残タスク5） |
| `cta_label` | ボタンの文言 | 文言別の効き |
| `lp_page` | `beginner` `agency` `liver` `sidejob` | どのLPか |
| `traffic_source` / `traffic_medium` / `traffic_campaign` / `traffic_content` | §2 の値 | **媒体別の寄与** |
| `has_gclid` | `yes` / `no` | 広告経由かどうか |

- `source` `medium` `campaign` は GA4 の予約語と衝突するので **`traffic_` 接頭辞**を付けている
- utm が無い流入もリファラのホスト名から推定する（note.com → `note` 等）。
  ただし推定は保険であって、**正確な媒体別集計はあくまで utm 付きURLで行う**
- 流入元は **sessionStorage にセッション初回接触を保存**する。LP内を回遊しても `direct` に上書きされない

### GA4 側でやる設定（測定ID発行後）

1. 管理 > データストリーム でウェブストリームを作り、測定ID（`G-…`）を取得
2. `lp/shared/tracking.js` の `GA4_ID` に貼って push（Netlifyが自動デプロイ）
3. 管理 > **カスタム定義** で `cta_position` `cta_label` `lp_page` `traffic_source` `traffic_medium`
   `traffic_campaign` `traffic_content` `has_gclid` を**カスタムディメンション（イベントスコープ）に登録**
   ← これをやらないとレポートで内訳が見えない
4. 管理 > **キーイベント** で `line_cta_click` をキーイベントに設定
5. 管理 > **サービス間のリンク > Google広告とのリンク** で CID 927-150-4466 を連携

---

## 6. 変更履歴

| 日付 | 内容 |
|---|---|
| 2026-08-10 | 新規作成。`lp/shared/tracking.js` に計測を一元化し、全4LPへ適用。utm設計を確定。Google広告側は未変更（ユーザー承認待ち） |
