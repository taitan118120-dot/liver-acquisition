# 退役したDMテンプレート

ここにあるテンプレートは**送信しない**。参照用に残しているだけ。

`dm_sender.load_template()` は `_RETIRED_TEMPLATES` で明示的にエラーにする
（未指定時の beginner フォールバックに黙って吸われるのを防ぐため）。
`ig_dm_assist.py --template <名前>` も `templates/dm_<名前>.txt` を直接見るので、
このディレクトリに移した時点で「テンプレ不明」で止まる。

## dm_model_scout.txt（2026-08-01 退役）

「京都コレクション出演オファー」の着物ランウェイオーディション募集DM。

- **京都コレクションはユーザー確認の結果、実在しないことが判明**（2026-08-01）
- 告知先 `https://collection.c.ccarveout.jp/` は **404**
- ドメイン名の `ccarveout` は使用禁止ブランド「カーブアウト」（TAITAN PRO で統一するルール）

同じ「京都コレクション参加可能」の1行が `templates/dm_hourly_5k.txt` にもあり、同日に除去済み。
