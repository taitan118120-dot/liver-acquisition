"""
P-Bandai 商品ページ監視 → 状態変化を検知してmacOS通知＋アラーム＋Chrome自動起動

使い方:
  python3 monitor.py
  python3 monitor.py "https://p-bandai.jp/item/item-1000249423/"

依存:
  pip3 install requests beautifulsoup4

仕組み:
  - 5秒間隔(±2秒jitter)で商品ページをGET
  - 「カートに入れる」ボタンが活性かどうか判定
  - 状態が AVAILABLE に変わったら:
      1) macOS通知 (osascript)
      2) Glass.aiff を連続8回鳴らす（爆音アラーム）
      3) Chromeで商品ページを自動オープン → Tampermonkey の sniper.user.js が即クリック
  - 単独で実行してもOK。sniper.user.js と併用すると強力。
"""

import hashlib
import random
import subprocess
import sys
import time

import requests
from bs4 import BeautifulSoup

DEFAULT_URL = "https://p-bandai.jp/item/item-1000249423/"
INTERVAL = 5  # 平均ポーリング間隔(秒)
JITTER = 2    # ±jitter(秒)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Safari/605.1.15"
)

CART_TEXTS = (
    "カートに入れる",
    "カートにいれる",
    "カートへ入れる",
    "種類を選んでカートにいれる",
    "ご予約はこちら",
)
PRE_TEXTS = (
    "予約受付開始前", "受付開始前", "予約開始日", "予約開始予定",
    "発売前", "近日発売", "より予約開始",
)
SOLDOUT_TEXTS = ("売り切れ", "完売", "受付終了", "販売終了")


def fetch(url: str) -> str:
    headers = {
        "User-Agent": UA,
        "Accept-Language": "ja,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.text


def classify(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.get_text()

    # 1) 予約開始予定の文言があれば PRE 確定（このページはそのパターン）
    if any(k in body for k in PRE_TEXTS):
        return "PRE"

    # 2) 売り切れ系
    if any(k in body for k in SOLDOUT_TEXTS):
        return "SOLDOUT"

    # 3) 「カートにいれる」系ボタンが活性なら AVAILABLE
    for tag in soup.find_all(["button", "a", "input"]):
        text = (tag.get_text() or tag.get("value", "") or "").strip()
        if not text:
            continue
        if any(k in text for k in CART_TEXTS):
            disabled = (
                tag.has_attr("disabled")
                or tag.get("aria-disabled") == "true"
                or "disabled" in (tag.get("class") or [])
                or "is-disabled" in (tag.get("class") or [])
            )
            if not disabled:
                return "AVAILABLE"
    return "UNKNOWN"


def notify_macos(title: str, message: str) -> None:
    safe_t = title.replace('"', "'")
    safe_m = message.replace('"', "'")
    script = f'display notification "{safe_m}" with title "{safe_t}" sound name "Glass"'
    subprocess.run(["osascript", "-e", script], check=False)


def alarm_loud() -> None:
    # 爆音で気付く用：Glass.aiff を 8 回連射
    for _ in range(8):
        subprocess.Popen(
            ["afplay", "-v", "2", "/System/Library/Sounds/Glass.aiff"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.4)


def open_chrome(url: str) -> None:
    subprocess.run(["open", "-a", "Google Chrome", url], check=False)


def speak(text: str) -> None:
    subprocess.Popen(["say", "-v", "Kyoko", text])


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    print(f"[monitor] target: {url}")
    print(f"[monitor] interval: {INTERVAL}±{JITTER}s")
    print("[monitor] Ctrl+C で停止\n")

    last_state: str | None = None
    last_hash: str | None = None
    fail_count = 0

    while True:
        ts = time.strftime("%H:%M:%S")
        try:
            html = fetch(url)
            fail_count = 0
            html_hash = hashlib.md5(html.encode("utf-8", errors="ignore")).hexdigest()[:8]
            state = classify(html)

            if state != last_state:
                print(f"[{ts}] STATE CHANGE: {last_state} -> {state} (hash={html_hash})")
                if state == "AVAILABLE":
                    notify_macos("🎯 P-Bandai 予約開始！", "Chrome が自動で開きます")
                    open_chrome(url)
                    speak("予約開始。今すぐ買え")
                    alarm_loud()
                else:
                    notify_macos("P-Bandai 状態変化", f"{last_state} -> {state}")
                last_state = state
            elif html_hash != last_hash:
                print(f"[{ts}] html changed (hash={html_hash}, state={state})")
            else:
                print(f"[{ts}] state={state} hash={html_hash}")
            last_hash = html_hash

        except Exception as e:
            fail_count += 1
            print(f"[{ts}] ERROR ({fail_count}): {e}")
            if fail_count >= 5:
                # 連続エラーは少し待つ（IPブロック疑い）
                time.sleep(30)

        time.sleep(max(1.0, INTERVAL + random.uniform(-JITTER, JITTER)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[monitor] stopped")
