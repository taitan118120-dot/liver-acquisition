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
# 2026-08-27まで welcome と followup_1day の2通で打ち切りだった。本番stateを見たところ
# 友だち26人中9人が一度も返信しておらず、この層は2通で音信不通になっていたため3日後・7日後を追加。
# _send_step_if_active のガード（unfollowed / auto_paused / meeting_scheduled /
# meeting_offered / awaiting_slot / 直近12時間の会話）は全ステップに等しく効くので、
# 面談フローに入った人・会話が生きている人には届かない。増やしても追い打ちにはならない。
# ここから先は足さないこと（7日後の文面が「最後に一度だけ」と明言している）。
STEP_DELAYS = {
    "welcome": 0,                    # 即時
    "followup_1day": 24 * 3600,      # 24時間後：特典PDFの感想うかがい＋小さな質問の呼び水
    "followup_3day": 3 * 24 * 3600,  # 3日後：PDFの中身に触れて具体的な質問を促す
    "followup_7day": 7 * 24 * 3600,  # 7日後：「今は迷い中でも大丈夫」で軽く締める（最終）
}
