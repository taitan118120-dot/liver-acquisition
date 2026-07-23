"""通知。既存の公式LINE Botのチャネルを流用して自分あてにpushする。"""
from __future__ import annotations

import subprocess

import requests

import config
from scoring import Verdict, man
from sources import Bukken

STATUS_LABEL = {
    "BUY":  "🔥 売出価格のまま式に収まる",
    "NEGO": "💬 指値なら勝負になる",
    "PASS": "🙅 この家賃想定では利回り20%に届かない",
    "INFO": "❓ 価格未掲載（要相談）",
}


def format_bukken(b: Bukken, v: Verdict, header: str) -> str:
    lines = [f"{header} No.{b.no}　{b.town}（{b.school}校下）"]

    spec = [
        man(b.price) if b.price else "価格応談",
        f"{b.floor_area:.0f}㎡" if b.floor_area else "延床不明",
        f"{b.build_year}年築" if b.build_year else "築年不明",
        b.structure or "",
        f"駐車{b.parking}台" if b.parking is not None else "駐車場不明",
    ]
    lines.append(" / ".join(x for x in spec if x))
    lines.append("")
    lines.append(STATUS_LABEL[v.status])
    lines.append(f"想定家賃 {v.rent / 10000:.1f}万（{v.rent_basis}）")
    lines.append(f"年間手残り {man(v.annual_net)} → 総投資上限 {man(v.max_total)}")

    if b.price:
        lines.append(
            f"売出のまま買うと総投資 {man(v.total_invest)}（実質{v.real_yield:.1f}%）"
        )
        lines.append(f"　内訳: 物件{man(b.price)}＋諸費用{man(v.other_costs)}＋修繕{man(v.renovation)}")
        if v.max_offer > 0:
            lines.append(f"👉 指値上限 {man(v.max_offer)}　これ以下で買えば20%")
        else:
            lines.append("👉 タダでも修繕費で式が壊れる。家賃を上げる手（ペット可/駐車2台/法人契約）が要る")

    if b.flags:
        lines.append("")
        lines.append("⚠️ " + "／".join(b.flags))

    if b.note:
        lines.append(f"備考: {b.note[:120]}")
    if b.detail_url:
        lines.append(b.detail_url)
    return "\n".join(lines)


def send_line(text: str) -> bool:
    if not (config.LINE_CHANNEL_ACCESS_TOKEN and config.LINE_ADMIN_USER_ID):
        return False
    res = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}",
        },
        json={
            "to": config.LINE_ADMIN_USER_ID,
            "messages": [{"type": "text", "text": text[:4900]}],
        },
        timeout=20,
    )
    if res.status_code != 200:
        print(f"[LINE] 送信失敗 {res.status_code}: {res.text[:200]}")
        return False
    return True


def send_mac(title: str, text: str) -> None:
    """LINE未設定でも取りこぼさないようMacの通知センターにも出す"""
    body = text.replace('"', "'")[:250]
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{body}" with title "{title}"'],
            check=False, capture_output=True, timeout=10,
        )
    except Exception:
        pass


def deliver(messages: list[str], title: str = "小松の物件") -> None:
    for msg in messages:
        print("\n" + "=" * 60)
        print(msg)
        sent = send_line(msg)
        if not sent:
            send_mac(title, msg.split("\n")[0])
    if messages and not (config.LINE_CHANNEL_ACCESS_TOKEN and config.LINE_ADMIN_USER_ID):
        print("\n[!] LINE未設定のため画面表示のみ。fudosan_app/.env を作れば通知が飛びます")
