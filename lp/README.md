# LP 運用メモ

公開URL: https://taitan-pro-lp.netlify.app/ （main に push すると Netlify が自動デプロイ）

## 画像・CSS・JS のキャッシュルール（重要）

netlify.toml で `/shared/*` と `/beginner/*.css|*.js` に `max-age=604800`（7日）を
付けている。表示速度のためキャッシュ自体は維持し、**更新は参照URL側で反映させる**。

**ファイルを差し替え・更新したら、必ずどちらかを行うこと:**

1. **ファイル名を変える**（推奨・画像向け）
   例: `hero-liver.jpg` → `hero-liver-photo.jpg`（2026-07-21 に実施した実例。旧ファイルは
   現在 `illust-sofa-phone.jpg`）。参照側（HTML の `src` / `og:image` /
   CSS の `url()`）も全て新ファイル名に更新する。
2. **参照側の `?v=` を更新する**（CSS/JS や、名前を変えたくない場合）
   例: `style.css?v=20260720` → `style.css?v=20260801`。日付ベースで付ける。

これを忘れると、再訪ユーザーには最長7日間古いファイルが表示され続ける
（2026-07-20 に beginner の hero 画像で実際に発生）。

### 参照箇所の一覧（?v= 付与済み: 2026-07-20 時点）

- `beginner/index.html` — `../shared/img/*.jpg`（本文16箇所 + og:image）、
  `../shared/logo.jpg` ×2、`../shared/taitan.jpg` ×1。
  CSS/JS は自前（`style.css?v=` / `script.js?v=`）。
- `agency/liver/sidejob` の各 `index.html` — `../shared/style.css?v=`、
  `../shared/script.js?v=`、`../shared/logo.jpg`。
- `shared/style.css` 内 — `url("taitan.jpg?v=...")`。

### 注意

- `shared/style.css` の中身を変えたら、それを参照する agency/liver/sidejob の
  `<link>` の `?v=` を3ファイルとも更新する（beginner は対象外）。
- `shared/liver_starter_guide.pdf`（LINE特典PDF）も同じ7日キャッシュ対象。
  差し替え時はファイル名を変えるのが安全。
- 新しい画像参照を追加するときも最初から `?v=YYYYMMDD` を付けておく。

## デプロイが動いているかの確認（重要）

main に push すると Netlify が `lp/` を自動デプロイする——**が、netlify.toml の `ignore`
コマンドが効きすぎて無言でスキップされることがある**。2026-08-24〜09-11 のビルド40件は
全部 `Canceled build due to no content change` でキャンセルされていて、`lp/` を実際に
変更したコミットまで公開されなかった（原因：`$CACHED_COMMIT_REF` が空だと
`git diff --quiet $COMMIT_REF -- .` に退化し、常に「差分なし」になる。2026-09-11 に
ref のガードを追加して修正）。

**LP を変更したら、公開URLで実物を見るまで完了にしない**。詰まっていないかの確認:

```sh
TOKEN=$(cat ~/.netlify_token)
SITE=3661f380-0fae-4e63-b1f8-1089c470b1d0   # taitan-pro-lp
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.netlify.com/api/v1/sites/$SITE/deploys?per_page=5" \
  | python3 -c "import json,sys;[print(d['state'],(d.get('commit_ref') or '')[:8],d['created_at'],(d.get('error_message') or '')[:60]) for d in json.load(sys.stdin)]"
```

スキップされていたら、キャッシュを消して強制ビルド:

```sh
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"clear_cache": true}' "https://api.netlify.com/api/v1/sites/$SITE/builds"
```

## もう1つの公開サイト: taitan-pro-lp-targets（手動デプロイ）

同じ `lp/` が**2つのサイト**に配られている。

| サイト | デプロイ | 何が見に来るか |
| --- | --- | --- |
| `taitan-pro-lp.netlify.app` | main への push で**自動** | 公式LINE・Note・SNS |
| `taitan-pro-lp-targets.netlify.app` | **手動 zip デプロイ** | 求人媒体（`job_posts/indeed/*.md` / `job_posts/engage/*.md`）・`ads/` の遷移先 |

**`lp/` を直したら -targets にも配ること。** 自動デプロイされるのは main 側だけなので、
忘れると**応募者が見る面だけが古いまま**になる。2026-08-24 の「面談」→「お話しするとき」
置換（4392b4f）は、2026-09-11 まで -targets に反映されておらず、`/beginner/` で7箇所・
`/agency/` で6箇所が古いままだった。

```sh
./scripts/lp_targets_deploy.sh
```

zip → アップロード → `state:"ready"` まで待機 → `lp_drift_guard.py` で突合、までやる。
（POST のレスポンスは `state:"uploaded"` で返る。ready を待たずに検証すると古い本文を読む）

### 番犬

`lp_drift_guard.py`（`.github/workflows/lp_drift_guard.yml` で毎日 JST 9:35）が
4ページを両サイトから取得して本文を突合し、ついでに -targets の実物へ確定ファクトの
禁止パターンを当てる。ドリフトがあれば Issue で鳴き、直すと自動クローズする。

```sh
python3 lp_drift_guard.py            # 手元で突合
python3 lp_drift_guard.py --verbose  # 差分を全部出す
```

監視対象のページは `lp/*/index.html` の実体から自動で拾う（`MIN_PAGES` の4ページを下限に
union する）ので、LPを増やしても番犬への追加忘れは起きない。

## shared/img 素材一覧（写真 / イラストの区別）

**命名ルール：`illust-` プレフィックス付き = イラスト。プレフィックスなし = 実写（写真風）。**

LP のビジュアル方針は「イラストでなく実写人物写真」なので、**LP・広告に新しく使うのは
プレフィックスなしの方だけ**。`illust-*` は 2026-07-21 の写真化より前の旧素材で、
現在どの LP からも参照していない（残してあるだけ）。

| 実写（LP で使用中） | イラスト（未参照・使わない） |
| --- | --- |
| `hero-liver-photo.jpg` / `mechanism.jpg` / `setup.jpg` / `safety.jpg` / `meeting.jpg` | `illust-phone-lookback.jpg`（後ろ姿で振り返る女性・**横顔あり**・スマホ） |
| `worry-start.jpg` / `worry-skill.jpg` / `worry-time.jpg` | `illust-desk-noperson.jpg`（机とタブレットのみ・**人物なし**） |
| `step-stream.jpg` / `step-talk.jpg` / `step-reward.jpg` | `illust-women-group.jpg`（女性4人・スマホ） |
| `agency-hero.jpg` / `agency-mechanism.jpg` / `agency-setup.jpg` | `illust-phone-hearts.jpg`（巨大スマホとハート） |
| `liver-muu.jpg` / `liver-hayato.jpg` / `liver-housewife.jpg` | `illust-notebook-writing.jpg`（ノートに書く女性） |
| | `illust-sofa-phone.jpg`（旧 hero・ソファでスマホ） |
| | `illust-kitchen-phone.jpg`（キッチンでスマホ） |
| | `illust-student-phone.jpg`（床座りの学生・スマホ） |

2026-09-11 に改名（旧名 → 新名）：`no-face.jpg` → `illust-phone-lookback.jpg` /
`desk.jpg` → `illust-desk-noperson.jpg` / `age.jpg` → `illust-women-group.jpg` /
`fans.jpg` → `illust-phone-hearts.jpg` / `prepare.jpg` → `illust-notebook-writing.jpg` /
`hero-liver.jpg` → `illust-sofa-phone.jpg` / `case-housewife.jpg` → `illust-kitchen-phone.jpg` /
`case-student.jpg` → `illust-student-phone.jpg`。
旧 `no-face.jpg` は「顔なし」という名前なのに人物の横顔が大きく写っていて、
Google 広告の「人物なしカット」素材探しで実際に誤選定した（`ads/google_ads_設計書.md` §0-42 ⑤）。
新しい素材を置くときも、イラストなら `illust-` を付けること。

## 洗い出しコマンド

?v= なしの画像参照が残っていないか確認:

```sh
grep -rn '\.jpg"' lp --include="*.html" | grep -v "?v="
grep -rn 'url(' lp --include="*.css" | grep -v 'data:\|fonts.googleapis\|?v='
```
