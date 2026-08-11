import os

# LINE Messaging API
# LINE Developersコンソールから取得してください
# https://developers.line.biz/console/
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

# 管理者（自分）のLINEユーザーID。設定すると:
# - 面談希望が入ったとき通知が届く
# - 「一覧」「停止 <ID先頭8文字>」「再開 <ID先頭8文字>」コマンドが使える
# 自分のIDは data/message_log.json か Render のログで確認できる
ADMIN_USER_ID = os.environ.get("LINE_ADMIN_USER_ID", "")

# 代理店パートナー向けリッチメニューのID（rich_menu.py が作成時に表示する）
# intent が "agency" と分かった時点で、そのユーザーだけこのメニューに差し替える。
# 未設定なら差し替えをスキップし、全員デフォルト（ライバー向け）のままになる。
RICH_MENU_ID_AGENCY = os.environ.get("RICH_MENU_ID_AGENCY", "")

# 事務所情報・LPのURLはここに置かない。
# 実際にユーザーへ配信されるURLは messages.py / rich_menu.py が持っている
# （誘導先は git 自動デプロイ側の taitan-pro-lp.netlify.app＝計測タグあり）。
# ここに定数を置くと -targets 側（手動zipデプロイ・計測タグ未反映）と二重管理になり
# ドメインが食い違ったまま放置されるため、2026-08-11 に未参照定数ごと削除した。

# ステップ配信スケジュール（秒）
STEP_DELAYS = {
    "welcome": 0,               # 即時
    "followup_1day": 24 * 3600,  # 24時間後に1回だけ軽くフォロー（面談確定者には送らない）
}
