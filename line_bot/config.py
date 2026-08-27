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

# 代理店パートナー向けリッチメニューのID。**通常は設定しなくてよい**。
# 未設定なら app.py が LINE のメニュー一覧から名前で自動的に見つける
# （rich_menu.py の RICH_MENU_IMAGES["agency"]["name"] と突き合わせる）。
# 特定のIDに固定したいときだけ、ここを環境変数で上書きする。
RICH_MENU_ID_AGENCY = os.environ.get("RICH_MENU_ID_AGENCY", "")

# 事務所情報・LPのURLはここに置かない。
# 実際にユーザーへ配信されるURLは messages.py / rich_menu.py が持っている
# （誘導先は git 自動デプロイ側の taitan-pro-lp.netlify.app＝計測タグあり）。
# ここに定数を置くと -targets 側（手動zipデプロイ・計測タグ未反映）と二重管理になり
# ドメインが食い違ったまま放置されるため、2026-08-11 に未参照定数ごと削除した。

# ステップ配信スケジュール（秒）
# ※ slot_reminder だけは友だち追加時ではなく「面談を打診した時点」から数える。
#    app.py の schedule_slot_reminder() が個別にスケジュールする。
STEP_DELAYS = {
    "welcome": 0,               # 即時
    "followup_1day": 24 * 3600,  # 24時間後に1回だけ軽くフォロー（面談確定者には送らない）
    "slot_reminder": 2 * 24 * 3600,  # 面談打診の2日後に1回だけ日程を聞き直す
}

# 友だち追加時にはスケジュールしないステップ（起点が follow ではないもの）
STEP_NOT_ON_FOLLOW = ("slot_reminder",)
