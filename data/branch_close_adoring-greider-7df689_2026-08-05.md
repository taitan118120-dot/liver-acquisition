# ブランチ claude/adoring-greider-7df689 のクローズ記録（2026-08-05）

未マージだった2コミットを精査し、main に必要なものだけを個別コピーで取り込んだうえでブランチを閉じた。

対象コミット:
- `450faff` 全98記事の内容監査＋NGワード12件修正＋新着3記事のeyecatch/タグ/json登録
- `56905f8` 同一タイトル重複7記事を下書きに戻す（note_unpublish_articles.py新設＋復元用バックアップ）

note 側への実反映（NGワード除去・7記事の下書き化）はどちらも実行済みで、note.com 上の状態は正しい。
このブランチはその作業ログにあたる。

## 取り込んだもの

| ファイル | 判断 |
| --- | --- |
| `note_fix_ngwords.py` | **取り込み。** 公開済みnote記事の本文を一括で外科的に置換する道具。NGワード方針（手数料表現・オンライン無料相談・カーブアウトパートナー等）は今後も増えるので再利用価値がある。`note_leadmagnet_publish.publish_one(key, transform_fn)` に依存し、現行 main の同関数と署名互換であることを確認済み。 |

`note_fix_ngwords.py` を別のNGワードに流用するときの注意: `publish_one` の `expect_marker`
を省略しているため、反映確認がリードマグネットCTA文字列基準になる。CTAを含まない記事に
使うと verify が WARNING を出す（例外にはならず処理は完走する）。気になる場合は
`publish_one(k, fn, expect_marker=None)` か、置換後の文字列を marker に渡すこと。

## 取り込まなかったもの

| ファイル | 判断理由 |
| --- | --- |
| `data/published_note_keys.json` | **絶対に戻さない。** ブランチ側は98件で、main の108件に対し「main のみ13件が欠落・ブランチのみ3件が余分」の状態。余分な3件（`n13b97c639422` / `nbbbc925ec0a8` / `nc3013c157ee0`）は 2026-08-05 の `9fcda5f` で死にキーとして除去済みのもの。マージすると台帳が巻き戻る。台帳は `note_keys_registry.py` が正本管理する。 |
| `blog/images/101〜103` のカバー画像3点 | **不要。** main に同一blobで既に存在（blob hash 一致を確認）。 |
| `note_unpublish_articles.py`（ブランチ版・93行） | **不要。** main 側に別系統の後継版（151行, `2c815c6`→`9fcda5f`）があり、退避先が `blog/articles_note_unpublished/` に変わったうえ、成功時に `note_keys_registry.remove()` で台帳を自動縮小する。ブランチ版を入れると台帳連動のない旧仕様に戻る。 |
| `data/unpublished_backup/*.json`（7件） | **不要。** 下書きに戻した7記事は「同一タイトルの重複公開分」で、内容は二重に復元可能。①元原稿が `blog/articles_note/44,45,46,47,105_*.md` に残っている ②各タイトルの生き残り側が今も公開中で台帳にある（`ndb58de31b4de` / `n29aafb234cec` / `n673be1bcfcb8` / `n72ac7218ef26` / `n421fb46eb9a0`）。加えて `data/unpublished_backup/` はどのスクリプトも読み書きしない死んだディレクトリ規約（現行の退避先は `blog/articles_note_unpublished/`）で、入れるとバックアップ置き場が2箇所に分裂する。 |

7記事の内訳（キー → タイトル / 生き残り側キー）:

- `n5d23f4cfe7b3` → 「月5万円の在宅副業」で5個失敗した私が… / `ndb58de31b4de`（原稿 47）
- `n9bf3240d2dbd` → 1年続くライバーの9割が持っている「たった1つの性格」… / `n29aafb234cec`（原稿 46）
- `n9d59cd20f7cf` → 【2026年最新】大学生におすすめのライバー事務所の選び方… / `n673be1bcfcb8`（原稿 105）
- `na128c4f02806`, `ne623b717963b` → ライバーの時給、本当に「時給3,000円」は実在するのか… / `n72ac7218ef26`（原稿 45）
- `nd8f0e53ef071`, `nec84b0c1dc2e` → 正直に言います。初配信で緊張しないライバーはいません… / `n421fb46eb9a0`（原稿 44）

## ブランチの扱い

コミット自体は消さずに、削除前にタグ `archive/adoring-greider-7df689` を打って到達可能なまま残した。
退避JSONが後で必要になったら次で取り出せる。

```bash
git show archive/adoring-greider-7df689:data/unpublished_backup/n5d23f4cfe7b3.json
```
