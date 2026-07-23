"""小松市空き家バンクを巡回して、ガイド§0の式に収まる物件が出たら通知する。

    python3 run.py            # 巡回して新着・値下げだけ通知
    python3 run.py --report   # 今の全売買物件を判定して一覧表示（通知しない）
    python3 run.py --test     # LINEへテスト送信
"""
from __future__ import annotations

import sys
import traceback
import unicodedata

import config
import notify
import store
from scoring import build_rent_model, judge, man
from sources import fetch_all


def pad(text: str, width: int) -> str:
    """全角を2桁として左詰めする（--report の表がずれないように）"""
    w = sum(2 if unicodedata.east_asian_width(c) in "WFA" else 1 for c in text)
    return text + " " * max(0, width - w)


def _notify_worthy(b, v) -> bool:
    """通知に値するか。

    ・300万以下の戸建てはガイドの狩場そのものなので、判定PASSでも必ず知らせる
      （家賃を上げる手・修繕をDIYで半減させる手が残っているため）
    ・それ以上の価格帯は、指値すれば式に収まるもの＝BUY/NEGOだけ
    """
    if b.kind != "売買":
        return False
    if b.price and b.price <= config.MAX_PRICE:
        return True
    return v.status in ("BUY", "NEGO", "INFO")


def cmd_report() -> int:
    bukkens, label = fetch_all()
    model = build_rent_model(bukkens)
    overrides = config.load_overrides()
    sales = [b for b in bukkens if b.kind == "売買"]
    print(f"台帳: {label}")
    print(f"全{len(bukkens)}件（売買{len(sales)}件 / 賃貸{len(bukkens) - len(sales)}件）")
    print(f"家賃モデル: 全体中央値 {model['overall']:.0f}円/㎡（n={model['n']}）"
          if model["overall"] else "家賃モデル: サンプルなし")
    print()
    rank = {"BUY": 0, "NEGO": 1, "INFO": 2, "PASS": 3}
    scored = [(b, judge(b, model, overrides.get(b.no))) for b in sales]
    scored.sort(key=lambda p: (rank[p[1].status], p[0].price or 10**9))

    print(f"{'No':>4}  {pad('町名', 12)}{'価格':>8}{'延床':>7}  {'判定':<5}{'指値上限':>9}  想定家賃")
    print("-" * 66)
    for b, v in scored:
        area = f"{int(b.floor_area)}㎡" if b.floor_area else "—"
        offer = man(v.max_offer) if v.max_offer > 0 else "—"
        print(f"{b.no:>4}  {pad(b.town, 12)}{man(b.price):>8}{area:>7}  "
              f"{v.status:<5}{offer:>9}  {v.rent / 10000:.1f}万")
    return 0


def cmd_watch() -> int:
    conn = store.connect()
    try:
        bukkens, label = fetch_all()
    except Exception as exc:
        store.log_run(conn, 0, 0, 0, f"取得失敗: {exc}")
        print("取得に失敗:", exc)
        traceback.print_exc()
        return 1

    model = build_rent_model(bukkens)
    overrides = config.load_overrides()
    new_items, price_drops = store.diff_and_save(conn, bukkens)

    messages: list[str] = []
    for b in new_items:
        v = judge(b, model, overrides.get(b.no))
        if _notify_worthy(b, v):
            messages.append(notify.format_bukken(b, v, "🏠 新着"))

    if config.NOTIFY_PRICE_DROP:
        for b, old in price_drops:
            v = judge(b, model, overrides.get(b.no))
            if _notify_worthy(b, v):
                head = f"📉 値下げ {man(old)}→{man(b.price)}"
                messages.append(notify.format_bukken(b, v, head))

    store.log_run(conn, len(bukkens), len(new_items), len(price_drops), label)
    print(f"{label} / 全{len(bukkens)}件 / 新着{len(new_items)}件 / 値下げ{len(price_drops)}件 "
          f"/ 通知{len(messages)}件")
    if messages:
        notify.deliver(messages)
    return 0


def cmd_test() -> int:
    ok = notify.send_line("🏠 小松の物件ウォッチャー、通知テストです。これが届けば設定完了。")
    print("LINE送信:", "成功" if ok else "失敗（.env のトークン/ユーザーIDを確認）")
    return 0 if ok else 1


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit({"--report": cmd_report, "--test": cmd_test}.get(arg, cmd_watch)())
