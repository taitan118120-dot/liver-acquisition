# LP 運用メモ

公開URL: https://taitan-pro-lp.netlify.app/ （main に push すると Netlify が自動デプロイ）

## 画像・CSS・JS のキャッシュルール（重要）

netlify.toml で `/shared/*` と `/beginner/*.css|*.js` に `max-age=604800`（7日）を
付けている。表示速度のためキャッシュ自体は維持し、**更新は参照URL側で反映させる**。

**ファイルを差し替え・更新したら、必ずどちらかを行うこと:**

1. **ファイル名を変える**（推奨・画像向け）
   例: `hero-liver.jpg` → `hero-liver-photo.jpg`。参照側（HTML の `src` / `og:image` /
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

## 洗い出しコマンド

?v= なしの画像参照が残っていないか確認:

```sh
grep -rn '\.jpg"' lp --include="*.html" | grep -v "?v="
grep -rn 'url(' lp --include="*.css" | grep -v 'data:\|fonts.googleapis\|?v='
```
