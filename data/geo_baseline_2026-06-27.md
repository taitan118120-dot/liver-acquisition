# GEO ベースライン測定（2026-06-27）

目的：AI/検索でTAITAN PROがどれだけ「おすすめ事務所」として出るかの**出発点**を記録。施策後の改善を測る基準。
月1で同じクエリを再測定して比較する（[project_ai_geo_channel]）。

---

## 測定結果（2026-06-27・Web検索で実測）

### ① ブランド/具体ワード検索 → ◎ 出る
- クエリ：「TAITAN PRO ライバー事務所 還元率100% 金沢」
- 結果：**1〜2位が自社Note記事**（note.com/taitan_118）。AIが内容を読んで推薦できる状態。
- → AIに「TAITAN PROってどう？」と聞けば肯定的に答える。**ここは既に強い**。

### ② 一般質問ワード → ✗ 出ない（伸びしろ）
- クエリ：「ライバー事務所 おすすめ 還元率100% 未経験 Pococha」／「ポコチャ ライバー事務所 おすすめ 未経験」
- 結果：**TAITAN PROは1件も出ない**。上位は第三者ランキング（avex探検隊・LIVE配信研究所・sublive・streamer-blog・EXiST・ピクノア・buzz-navi・neobright・amicolive・ccarveout）。
- 競合として頻出：321inc / YOUPACE / LIVESTAR / ONE CARAT / MUUL / Neo Bright / アルファ / KIRINZ。
- → **名前を知らない新規には、AIはまだTAITAN PROを勧めていない**。ここを取るのが本丸。

---

## 今回打った施策（2026-06-27）
1. LP(beginner)に構造化データ（Organization + FAQPage schema）＋事務所概要セクション追加。還元率100%をLP本文に明記。
2. robots.txt（AIクローラー歓迎）＋ sitemap.xml 追加。
3. GEO比較記事 `blog/articles_note/97_...md`（一般質問ワード狙い・AI抽出最適構造）作成 → Note公開待ち。
4. 第三者メディア掲載キット `data/geo_media_listing_kit.md` 作成 → 掲載依頼は本人実施待ち。

## 次回測定（目安：2026-07-27）でチェックすること
- ② の一般質問で TAITAN PRO が出るようになったか（Perplexity/ChatGPT検索/Geminiで実際に質問）。
- Note記事#97 が検索・AI回答に拾われ始めたか。
- 掲載依頼した媒体に載ったか。
- 公式LINE問い合わせ件数の推移（出発点：3ヶ月で2件＋AI経由1件）。

## 測定のやり方（再現手順）
- ChatGPT(検索ON)/Perplexity/Geminiに「ポコチャ おすすめ ライバー事務所 未経験」「還元率100% ライバー事務所」と素で聞く。
- 回答にTAITAN PROが含まれるか／何番目か／どのソースを引用しているかを記録。
- 引用ソースが第三者ランキングなら、そのサイトへの掲載が次の一手。
