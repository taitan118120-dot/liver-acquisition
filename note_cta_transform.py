#!/usr/bin/env python3
"""note記事HTMLの外科的書き換え。
- CTA「15分のオンライン無料相談から(で)大丈夫です。」→「まずはLINEで気軽にご相談ください。」
- #85(n29e9feee936e)のみ FAQ Q1/Q3 を削除し Q2→Q. にリネーム
他は一切変更しない。
"""
import re

CTA_OLD_A = "<strong>15分のオンライン無料相談</strong>から大丈夫です。"
CTA_OLD_B = "<strong>15分のオンライン無料相談</strong>からで大丈夫です。"
CTA_NEW   = "<strong>まずはLINEで気軽に</strong>ご相談ください。"

KEY_85 = "n29e9feee936e"


def _delete_between(html, start_marker, end_marker):
    """start_marker の出現位置から end_marker の出現位置直前までを削除。"""
    i = html.find(start_marker)
    j = html.find(end_marker)
    if i == -1 or j == -1 or j < i:
        raise ValueError(f"marker not found / order wrong: {start_marker[:30]} .. {end_marker[:30]}")
    return html[:i] + html[j:]


def transform(key, html):
    out = html
    # --- CTA 置換（必ず1回） ---
    n = out.count(CTA_OLD_A) + out.count(CTA_OLD_B)
    if n != 1:
        raise ValueError(f"CTA出現数が想定外: {n} (key={key})")
    out = out.replace(CTA_OLD_A, CTA_NEW).replace(CTA_OLD_B, CTA_NEW)

    # --- #85 のみ FAQ 手術 ---
    if key == KEY_85:
        # Q1ブロック削除: Q1質問<p>開始 ～ Q2質問<p>開始直前
        out = _delete_between(out,
            '<p name="2bc5a56a-575f-4aba-ac7e-62a193ac67f5"',
            '<p name="f6358dd6-ab40-4e76-89e4-640b9e6fa7ae"')
        # Q2 → Q.
        out = out.replace(
            "<strong>Q2. フォロワーが増えても配信視聴者が増えない</strong>",
            "<strong>Q. フォロワーが増えても配信視聴者が増えない</strong>")
        if "<strong>Q2." in out:
            raise ValueError("Q2リネーム失敗")
        # Q3ブロック削除: Q2answer後のspacer<p>開始 ～ メッセージ前spacer<p>開始直前
        out = _delete_between(out,
            '<p name="44f6c95f-c5b9-4e77-a1df-6ffb51649ac4"',
            '<p name="d5004f27-f82c-490d-ba2c-9e4ced71ee6e"')
        # 検証
        for bad in ("Q1. フォロワー数とコアファン数", "フォロワー10：コアファン1",
                    "Q3. アイコンを変えると既存フォロワー"):
            if bad in out:
                raise ValueError(f"削除残り: {bad}")

    # --- 全体検証 ---
    if "オンライン無料相談" in out:
        raise ValueError("オンライン無料相談 が残存")
    return out
