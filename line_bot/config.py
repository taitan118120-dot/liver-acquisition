import os

# LINE Messaging API
# LINE Developersコンソールから取得してください
# https://developers.line.biz/console/
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

# 事務所情報
OFFICE_NAME = "TAITAN PRO"
OFFICE_URL = "https://taitan-pro-lp-targets.netlify.app/#apply"
LP_BEGINNER = "https://taitan-pro-lp-targets.netlify.app/beginner/"
LP_LIVER = "https://taitan-pro-lp-targets.netlify.app/liver/"
LP_SIDEJOB = "https://taitan-pro-lp-targets.netlify.app/sidejob/"
CONTACT_LINE = "https://lin.ee/xchCfdn"

# ステップ配信スケジュール（秒）
STEP_DELAYS = {
    "welcome": 0,           # 即時
    "day1": 86400,          # 1日後
    "day3": 259200,         # 3日後
    "day7": 604800,         # 7日後
}
