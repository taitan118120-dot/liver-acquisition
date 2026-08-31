# 流入元計測（utm）設計書

作成日：2026-08-10 / 対象：taitan-pro-lp.netlify.app 配下の全LP（beginner / agency / liver / sidejob）

> **なぜ作ったか**：2026-08-08 に開設以来初のコンバージョン1件（キャンペーンA経由・CPA ￥3,562）が出て、
> 広告クリック → LP → LINE の導線が端から端まで通ったことが実データで確認できた。
> ここから先の改善には「どこから来て、どのボタンを押したか」の分離が要る。
> 詳細は `ads/google_ads_設計書.md` §0-9。

---

## 0. ⚠️ 最重要：**いま utm もCTAクリックも「受け取り手」がいない**

2026-08-10 にユーザーが **「GA4は使わない」** と決定した。この決定の帰結を先に書く。

| 送っているもの | 受け取り手 | 結果 |
|---|---|---|
| `conversion`（Google広告CV） | **Google広告** | ✅ **従来どおり動く。** 唯一いま数字になっているもの |
| `line_cta_click`（どのボタン・どの媒体） | **なし** | ⛔ 送信はされるが**どこにも溜まらない** |
| URLの utm パラメータ | **なし** | ⛔ URLには乗るが**読む主体がいない**（2026-09-01 に Google広告3キャンペーンへサフィックスを適用済み＝**乗るようにはなった**が、受け取り手はいまも無い。§3-1） |

**utm は「それを読む解析ツール」があって初めて数字になる。** Google広告の管理画面は自社サイトに付いた
utm を読まない（読むのは gclid とアカウント内の実績だけ）。したがって現状のままでは、
**媒体別の流入分離も「16箇所のどのボタンか」も分からないまま**である。

### GA4を使わずに前へ進む選択肢（どちらもユーザー判断が必要）

| 案 | 何が分かるか | 分からないままのもの | コスト |
|---|---|---|---|
| **A. Google広告に「セカンダリ」コンバージョンを増やす**（例：`LINE_CTA_上部` / `_中盤` / `_下部` の3本）。`tracking.js` から位置別に `send_to` を出し分ける | **広告経由のクリックについて、LPのどのゾーンのボタンが押されたか**。Google広告の管理画面だけで完結し、GA4不要 | **広告以外（Note / Threads / IG / 自然検索）の流入は一切見えない**（gclidが無いのでCVとして記録されない） | 管理画面でCVアクションを3本作る＋`tracking.js` を少し変更。**「コンバージョン列に含めない＝セカンダリ」にすれば入札に影響しない** |
| **B. GTMコンテナだけ入れる**（GA4プロパティは作らない） | 現状の `dataLayer` にはもう `line_cta_click` が流れているので、GTM経由で任意の送信先に繋げられる | 送信先を別途決めない限り、GTMを入れただけでは何も溜まらない | 中 |
| **C. 何もしない** | Google広告のCV数・CPAのみ | 媒体別・ボタン別のすべて | 0 |

> **推奨は A。** GA4を作らないという決定と両立し、いま最も金がかかっている導線（Google広告）について
> 「LPのどこで刺さっているか」だけは取れるようになる。

**以下 §1〜§5 の設計は、将来受け取り手を用意したときにそのまま使えるように残してある。**
utm自体は付けておいても無害で、後からGA4やGTMを入れた瞬間に意味を持つ。

---

## 1. 前提（先に読む）

| 事実 | 現在の状態 |
|---|---|
| GA4 測定ID | ⛔ **使わない方針（2026-08-10 ユーザー決定）**。未発行のまま、`lp/shared/tracking.js` の `GA4_ID` は空で運用する。**この決定の帰結は §0 を必ず読むこと** |
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

`{adgroupid}` は数値IDで入る。読み替え表は**2026-09-01 に管理画面から実取得**した
（広告グループ一覧 → 表示項目 → 属性 → 「広告グループ ID」列を追加すれば取れる。
なお**この列設定は「表示項目の設定を保存する」にチェックを入れないと再読込で消える**）。

| 広告グループ | ID | 所属キャンペーン |
|---|---|---|
| A1_アプリ別事務所 | `202157762321` | A |
| A2_事務所比較 | `198776585499` | A |
| A3_募集 | `200067277913` | A |
| A4_地域 | `200067503953` | A |
| A5_検討層 | `204230192768` | A |
| C1_321 | `200073945513` | C |
| C2_ベガプロモーション | `202437750710` | C |
| D1_ポコチャ代理店 | `198258850745` | D |

> 広告グループは**この8個で全部**（`3 件中 1〜3 件` のキャンペーン × 一覧8行で照合済み）。
> `D2_代理店副業` は 2026-08-25 に空箱ごと削除済みなので表にない（設計書 §0-25 手前の記録）。

### ✅ 2026-09-01 適用完了（完全再読込後に実値照合済み）

**2026-08-10 のユーザー承認に加えて、適用直前に改めてユーザーへ文字列を提示して承認を取り直したうえで実施した。**
（2026-08-10 に適用できなかった理由＝Chrome拡張が応答不能で管理画面に到達できなかったこと。本セッションでは拡張は正常だった。）

| キャンペーン | 適用前 | 適用後（完全再読込して input の value を実値照合） |
|---|---|---|
| A｜TAITANPRO_顕在層_事務所探し（`24048528471`） | 空 | ✅ 101文字・§3-1 の文字列と**完全一致** |
| C｜TAITANPRO_競合名_テスト（`24060709354`） | 空 | ✅ 100文字・**完全一致** |
| D｜TAITANPRO_代理店パートナー（`24100129616`） | 空 | ✅ 103文字・**完全一致** |

- **トラッキング テンプレートは3本とも空のまま**（適用前後で変化なし）＝設計どおり、サフィックス方式のみ。
- **本人確認ダイアログは3本とも出なかった**（設計書 §0-A A-2 の「増額系・新規作成で出る」に整合。設定値の編集は素通り）。
- 操作の罠：**この設定画面は初回描画のあと一度勝手に再読込が走る。** 1回目に「キャンペーン URL のオプション」を開こうとすると
  そのタイミングでリロードされて空振りするので、**2回目のクリックで開くのが既定**と思っておく。

### 適用後の確認（§3-1 の3点）

| # | 確認項目 | 結果 |
|---|---|---|
| 1 | 着地URLに `utm_source=google` と `gclid=` の両方が乗るか | ✅ 実質確認済み（下記の代替手段。**実クリックはしていない**） |
| 2 | キャンペーンCのサイトリンク4本のアンカージャンプが壊れていないか | ✅ **4本とも正常**（下表） |
| 3 | 翌日、管理画面でCVが引き続き記録されているか | ⏳ **2026-09-02 以降に確認**（未実施） |

**#1 について：「実クリック」はやっていない。** 自社広告を自分でクリックするのは
Google のポリシー上の無効クリックにあたるうえ、平均CPC ￥257〜292 の実費が発生するため。代わりに次の2つで裏を取った。

- **Google 自身の「トラッキング設定のテスト」**（キャンペーンURLのオプション内の `テスト` ボタン）で、
  Google が組み立てた**クリックURL**を確認した。3キャンペーンとも `✅ ランディング ページが見つかりました`。
  - C：`https://taitan-pro-lp.netlify.app/beginner/?utm_source=google&utm_medium=cpc&utm_campaign=ads_c_kyogo&utm_content=200073945513&utm_term=`（C1_321）
    ／ `utm_content=202437750710`（C2_ベガプロモーション）＝**`{adgroupid}` が上の読み替え表どおりに解決されている**
  - D：`…/agency/?…&utm_campaign=ads_d_dairiten&utm_content=198258850745`（D1_ポコチャ代理店）
  - `{keyword}` はテスト時は検索語のコンテキストが無いので**空**になる（実配信では入る）
- **LP側**：`?utm_…&gclid=…` 付きURLを実際に読み込み、`sessionStorage` の `taitan_traffic_src` に
  `{"source":"google","medium":"cpc","campaign":"ads_c_kyogo","content":"200073945513","gclid":"…"}` が
  保存されることを確認した＝**utm と gclid が同時に読めている**。
- 残る未確認は「Google が実配信のクリックで自動タグの `gclid` を足すこと」だけだが、これは
  自動タグ設定ON（§1）の既定動作で、サフィックスとは独立（§4）。

**#2 の実測（2026-09-01・1280×900・`?utm_…&gclid=…#アンカー` の形で読み込み）**

| サイトリンク | アンカー | 着地時の scrollY | セクション上端の位置 | 判定 |
|---|---|---|---|---|
| 所属ライバーの実績 | `#cases` | 9,496 | ビューポート上端 +72px | ✅ |
| 報酬・還元率について | `#reward` | 3,520 | 同 +72px | ✅ |
| 選ばれている理由 | `#reasons` | 6,041 | 同 +72px | ✅ |
| よくある質問 | `#faq` | 14,987 | 同 +72px | ✅ |

`+72px` は固定ヘッダー分のオフセットで、**utm なしの `#cases` 単体（scrollY 9,496）と1pxも変わらない**＝utm付与の影響ゼロ。
`#faq` は `elementFromPoint` でも画面上端に FAQ セクションが来ていることを確認した。

> ⚠️ **検証時にハマった点（次回のため）**：Browser pane は**開いた直後のビューポートが 0×0** で、
> その状態だと `scrollY` が常に 0 になり「アンカーが飛んでいない」と誤読する。**必ず `resize_window` で
> サイズを与えてから測る。** また**同じURLへ再ナビゲートしても hash ジャンプは再発火しない**ので、
> 別ページを挟んでから目的URLへ入ること。この2つで一度「アンカーが壊れた」と誤判定しかけた。

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

> ✅ **`shared/tracking.js` は再デプロイ済みで反映されている（2026-08-11 実測）。**
> 求人媒体の誘導先は **`taitan-pro-lp-targets.netlify.app`**（メインとは別のNetlifyサイト・**手動zipデプロイ**）だが、
> 本日 curl で確認したところ **`/beginner/` `/agency/` `/liver/` `/sidejob/` の4ページすべてに
> `<script src="../shared/tracking.js?v=20260810a">` が入っており**、`/shared/tracking.js` 自体も HTTP 200 で配信されている。
> 中身はメイン側 `taitan-pro-lp.netlify.app` およびリポジトリの `lp/shared/tracking.js` と**バイト単位で同一**。
>
> ⚠️ **注意は残る。このサイトは手動zipデプロイのままである。**
> メイン側は git push で自動反映されるが、こちらは反映されない。
> **今後 `lp/shared/` や `lp/{target}/` を触ったら、その都度 zip を作って手動で再デプロイすること**
> （手順は記憶 `project_netlify_lp_deploy`）。片方だけ直して満足すると、また今回のようにズレる。
>
> ⛔ **ただし「タグが載った＝数字が読める」ではない。** §0 のとおり utm も `line_cta_click` も
> **いま受け取り手がいない**ので、タグが入っただけでは求人媒体の数字は依然として出ない。
> 数字になるのは受け取り手（A案のセカンダリCV、またはGTM）を用意してから。

### 3-5. Googleビジネスプロフィール

`https://taitan-pro-lp.netlify.app/beginner/?utm_source=gbp&utm_medium=organic&utm_campaign=gbp_profile`

### 3-6. DM・公式LINE（2026-08-10 追加）

> ⚠️ **§0 のとおり、いま utm を読む主体はいない。** ここで付けた値がレポートになるのは
> 受け取り手（A案のセカンダリCV、またはGTM/GA4）を用意してから。付けておくこと自体は無害で、
> 用意した瞬間に遡らず・そこから意味を持つ、という前提で読むこと。

| 導線 | 実装ファイル | URL |
|---|---|---|
| DMテンプレ（`dm_sender.py` 系・媒体横断） | `config.py` `OFFICE_URL` / `templates/dm_*.txt` | `…/beginner/?utm_source=dm&utm_medium=dm&utm_campaign=dm_direct` |
| liver_app のDMテンプレ（Instagram） | `liver_app/db.py` `_DEFAULT_*_TEMPLATE` | `…/beginner/?utm_source=instagram&utm_medium=dm&utm_campaign=ig_dm` |
| x_app のDMテンプレ（X） | `x_app/db.py` `_DEFAULT_*_TEMPLATE` | `…/beginner/?utm_source=x&utm_medium=dm&utm_campaign=x_dm` |
| 公式LINE リッチメニュー（ライバー向け＝デフォルト） | `line_bot/rich_menu.py` | `…/beginner/?utm_source=line&utm_medium=richmenu&utm_campaign=line_richmenu` |
| 公式LINE リッチメニュー（代理店向け＝intent=agencyの人だけ差し替え） | `line_bot/rich_menu.py` | `…/agency/?utm_source=line&utm_medium=richmenu&utm_campaign=line_richmenu_agency` |

> 🗑️ **`line_bot/config.py` の `OFFICE_URL` / `LP_BEGINNER` / `LP_LIVER` / `LP_SIDEJOB` /
> `CONTACT_LINE` / `OFFICE_NAME` は 2026-08-11 に削除した。** どこからも参照されていない上に、
> 誘導先が `-targets.netlify.app`（手動zipデプロイ）を指していて、
> 実際に配信している `line_bot/rich_menu.py` の `taitan-pro-lp.netlify.app` と食い違っていたため。
> （削除を判断した時点では `tracking.js` 未反映も理由に挙げていたが、**その点は同日中に解消済み**＝§3-4。
> 削除の主因である「配信実体との食い違い」は変わらないので、削除はそのままでよい。）
> 公式LINEからLPへ送る導線は**リッチメニューの2本だけ**で、`messages.py` にLPのURLは無い
> （持っているのは特典PDFのjsDelivr URLのみ）。今後 bot 本文からLPへ送るなら
> `taitan-pro-lp.netlify.app` 側を使うこと。

> `liver_app` / `x_app` はテンプレ本体を **Fly.io の本番DB** に持つ。`db.py` の `_DEFAULT_*` を
> 書き換えても既存DBは `INSERT OR IGNORE` で無視されるので、**URL置換マイグレーションを
> `init_db()` に足してデプロイするまで本番の文面は変わらない**（記憶 `project_liver_app_template_migration`）。

### 3-7. `#apply` は使わない（2026-08-10 決定）

長らく `https://taitan-pro-lp.netlify.app/#apply` を「応募ページ」として各所に配っていたが、
**LP側に `id="apply"` は一度も存在しなかった**。`netlify.toml` の `/` → `/beginner/index.html`
200リライトで beginner LP のトップに着地するだけで、アンカージャンプは無言で不発だった。
`link_guard.py` はURLをGETするだけだったので HTTP 200 で素通りしていた（＝1年近く誰も気づけなかった）。

対応は2本立て：

1. **LP に受け皿の `id="apply"` を追加**（`lp/beginner/index.html` の希少性セクション＝最後のCTA）。
   送信済みDM・投稿済みThreads・旧Xプロフィールなど**もう書き換えられない分**のための救済。
   コメントアウト運用の対象になっている `#campaign` ではなく、常設のセクションに置いてある。
2. **新規に作るリンクは `#apply` を使わない。** 上表のとおり `/beginner/?utm_…` に統一する。
   フラグメントとクエリを併用すると §3-1 のとおり壊れやすいので、**アンカーは付けない**のが既定。

再発防止として `link_guard.py` に**フラグメント実在チェック**を入れた（自サイトのLPに限り、
着地先HTMLに `id`/`name` があるかまで見る。無ければ DEAD 扱いで Actions が赤くなる）。

> ⚠️ **2026-08-11 追記：このチェックだけでは広告のアンカーは守れなかった**
>
> フラグメント実在チェックは「`link_guard.py` が拾えたURL」にしか働かない。ところが
> **Google広告のサイトリンクURLは管理画面の中にしか存在せず**、`CONTENT_GLOBS` に
> `ads/*.md` は入っていないため、**広告のアンカーは1本も検査されていなかった**。
> しかも稼働中のアカウント単位サイトリンク「初配信までのサポート」の向き先は、
> **`#campaign`＝コメントアウト運用の対象になっている期間限定セクション**そのものだった
> （まさに上の 1. で「避けた」場所を、広告側が指していた）。
>
> 対応：`link_guard.py` に **`AD_SITELINK_URLS`** を新設して広告サイトリンクを明示的に
> 監視対象へ。LP側は `#campaign` を「枠ごと消さない」運用に変更し、恒久的な受け皿として
> `id="flow"`（常設のFLOWセクション）を追加した。広告側のURL変更はユーザー承認待ち。
> 詳細は `ads/google_ads_設計書.md` §5-5「⛔ `#campaign` は期間限定セクション」。
>
> **教訓**：「アンカーが実在するか」だけでなく「**そのアンカーが消えない約束になっているか**」まで
> 見ないと同じ事故が起きる。広告・DM・印刷物など**後から書き換えられない導線**が指すセクションは、
> LP側に常設である旨を明記する。

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

### ⏳ まだ確認できていないこと（実データ待ち）

**「管理画面上でCVが引き続き記録される」ことは未確認。** サフィックスを適用したのが **2026-09-01** なので、
判定できるのは **2026-09-02 以降**。**期間セレクタを「過去30日間」等に直してから**（設計書 §0-A A-1 の鉄則）
CV列を確認すること。適用前の基準値は、過去30日で CV は月1〜2件のオーダー（設計書 §0-21・§0-25）。

> 壊れていた場合の切り戻しは簡単で、**3キャンペーンのサフィックス欄を空にして保存するだけ**。
> 広告の最終ページURLもトラッキングテンプレートも触っていないので、他に戻すものはない。

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

### GA4 側でやる設定（**将来 GA4 を使う方針に変えた場合のみ**。2026-08-10 時点では実施しない）

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
| 2026-08-10 | 新規作成。`lp/shared/tracking.js` に計測を一元化し、全4LPへ適用。utm設計を確定 |
| 2026-08-10 | ユーザー決定：**GA4は使わない**（§0）／Google広告のサフィックス適用は**承認済み**。ただしChrome拡張が応答不能で本セッションでは適用できず、管理画面は未変更のまま |
| 2026-08-10 | 死にアンカー `#apply` を撤去（§3-7）。DM・公式LINE導線に utm を付与（§3-6）。`link_guard.py` にフラグメント実在チェックを追加 |
| 2026-09-01 | **§3-1 のサフィックスを A・C・D の3キャンペーンに適用＝完了**（適用直前にユーザー再承認・完全再読込後に実値照合）。広告グループID読み替え表8件を実取得して §3-1 に記入。確認3点のうち #1（utm＋gclid）と #2（キャンペーンCのサイトリンク4本のアンカー）を実測でクリア、#3（CV継続）は 2026-09-02 以降 |
| 2026-08-11 | 稼働中の広告サイトリンクが期間限定セクション `#campaign` を指していた問題（§3-7 の追記）。`link_guard.py` に `AD_SITELINK_URLS` を新設し広告サイトリンク10本を監視対象へ。beginner LP に恒久アンカー `id="flow"` を追加し、`#campaign` を「枠ごと消さない」運用に変更。**広告管理画面のURL変更はユーザー承認待ちで未実施** |
