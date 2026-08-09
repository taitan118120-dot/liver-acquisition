#!/usr/bin/env python3
"""facts_patterns.py — 確定ファクト検品パターンの共有正本
==========================================================
[[project_taitan_pro_note_facts]] の「常設grepパターン」のうち、
**媒体をまたいで同じものを当てる必要があるもの** をここに集約する。

背景（2026-08-09）:
  X @taitan_LIVER の稼働中ポストに「9割の副業ライバーはフリーで十分」
  「成功する奴は10人に1人もいない」が出ていた。Note記事側では全数除去済み、
  Threads の _violations() でも弾ける設計だったのに、X の生成経路
  （cloud_evolve.py）と投稿経路（cloud_post.py）には機械検品が
  **1つも無かった** ため、そのまま素通りしていた。

  同じパターンを各スクリプトにコピペすると、必ずどれか1本が古くなる
  （2026-08-08 に social_profile_guard.py へ RATIO_SUBJECT を足したときも
  Threads・X には反映されなかった）。だから正本はこの1ファイルだけにして、
  各guardはここを import する。

このモジュールは **標準ライブラリのみ** に依存する。
requests 等を足すと、tweepy しか入っていない auto_post.yml から
import できなくなる（＝投稿ワークフローが落ちる）ので絶対に足さない。
"""

import re

# 公式LINE。増やしたらここと link_guard.py の LINE_ALLOWED を両方直す。
LINE_ALLOWED = "https://lin.ee/xchCfdn"

# ── 出典なしの割合統計 ────────────────────────────────────────
# 2系統で当てる（片方だけだと必ず取りこぼす）
#   ① 割合語 × 離脱/成功語の近接 …「9割が消える」「10人に1人も成功しない」型
#   ② 割合が主語を直接修飾する形 …「9割の副業ライバーはフリーで十分」型。
#      ②は離脱語を含まないので①では絶対に出ない（2026-08-08 実測で取りこぼした）
DROPOUT_RATIO = re.compile(r"[7-9]\s*割|[6-9]0\s*[%％]|10人に[1-3]人")
DROPOUT_WORD = re.compile(r"辞め|消え|脱落|挫折|離脱|成功|続か")
RATIO_SUBJECT = re.compile(
    r"(?:[1-9]\s*割|[0-9]{1,3}\s*[%％])の(?:ライバー|人|副業|女性|男性|初心者|配信者)")

# 近接判定の窓幅（前後の文字数）
RATIO_WINDOW = 40

# ── 収入レンジ ────────────────────────────────────────────────
MONEY_LOW = re.compile(r"月\s*([0-9]{1,2})\s*万")
# 確定レンジ（3ヶ月15〜20万 / 6ヶ月30〜40万 / B帯20〜30万）より下は書かない
# [[feedback_income_figures]]: 月1〜3万等の少額表記は今後全媒体で書かない
MONEY_FLOOR = 15


def ratio_violations(text):
    """出典なしの割合統計を検出して [(reason, hit), ...] を返す。"""
    out = []
    if not text:
        return out

    for m in DROPOUT_RATIO.finditer(text):
        window = text[max(0, m.start() - RATIO_WINDOW): m.end() + RATIO_WINDOW]
        if DROPOUT_WORD.search(window):
            out.append(("出典なしの割合統計（離脱/成功率）", window.strip()[:60]))
            break

    m = RATIO_SUBJECT.search(text)
    if m:
        out.append(("出典なしの割合統計（割合が主語を修飾）",
                    text[max(0, m.start() - 10): m.end() + 20].strip()[:60]))
    return out


def money_violations(text):
    """確定レンジ未満の少額表記を検出して [(reason, hit), ...] を返す。"""
    if not text:
        return []
    for m in MONEY_LOW.finditer(text):
        if int(m.group(1)) < MONEY_FLOOR:
            return [(f"確定レンジ未満の少額表記（月{MONEY_FLOOR}万が下限）", m.group(0))]
    return []


def line_link_violations(text):
    """許可リスト外の公式LINEリンクを検出して [(reason, hit), ...] を返す。"""
    out = []
    for m in re.finditer(r"https?://lin\.ee/\S+", text or ""):
        if m.group(0).rstrip("/。、）)") != LINE_ALLOWED:
            out.append(("許可リスト外のLINEリンク", m.group(0)))
    return out
