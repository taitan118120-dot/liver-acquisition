# IG Scraping 凍結中（2026-05-17 〜 最低 2026-06-14）

## 経緯
- 2026-05-11: `@taitan_pro7` にIGから「サイバーセキュリティ規定違反 / 機密情報の収集」警告。
  「審査リクエスト不可」級。次回検出で永久BAN相当。
- 原因（推定）:
  1. `local_research.py` (launchd `com.taitan.dm-research`, 毎日03:00) が **本垢Cookie** で
     137タグ/日のhashtag scraping
  2. `agency_smart_v4.py` (launchd `com.taisei.agency-smart`, 毎日07:00) が **本垢Cookie** で
     200プロフィール/日のscraping
  3. 投稿側 (`instagram_post.yml`) が1日2回連投で inauthentic behaviour 検知

## 停止済み（2026-05-17）
- `launchctl unload com.taitan.dm-research`
- `launchctl unload com.taisei.agency-smart`
- 投稿頻度を週3回（月水金20:00）に削減（commit 670d60e）
- `ig_api._cookie_header` を改修:
  - `IG_SCRAPING_DISABLED=1` で内部API系の kill switch
  - `IG_DISPOSABLE_COOKIE` env で捨て垢Cookie優先
  - Chrome本垢Cookie吸出は `IG_ALLOW_CHROME_COOKIE=1` 明示時のみ
  - 優先順位: manual_cookie > IG_DISPOSABLE_COOKIE > (明示時のみChrome)

## 凍結対象（停止/再開判断が必要）
| script | 経路 | 状態 |
|---|---|---|
| `local_research.py` | hashtag/profile API | unload済 |
| `agency_smart_v4.py` | profile API | unload済 |
| `agency_following_research.py` | following list API | 手動実行のみ・凍結中 |
| `auto_enrich_ingest.py` | profile API | 手動実行のみ・凍結中 |
| `overnight_enrich.py` | 第一手 fetch_profile_html (Cookie不要) | **安全・継続可** |

## 再開条件
1. 最低 **2026-06-14** までは scraping 系を一切再開しない（4週間）
2. 再開時は **捨て垢必須**:
   - 物理分離（中古iPhone + 別SIM）が理想
   - 最低でも別Chromeプロファイル + VPN
   - 同一Mac/同一IP/同一fingerprint だと連鎖検知リスク
3. 再開フロー:
   - 捨て垢のCookieを `~/Library/LaunchAgents/*.plist` の `EnvironmentVariables` の
     `IG_DISPOSABLE_COOKIE` に設定
   - `IG_ALLOW_CHROME_COOKIE` は絶対セットしない
   - DELAY_TAG>=4s, DELAY_PROFILE>=2.5s は厳守
4. 投稿側は警告解除確認後も最低4週間は週3回維持
