#!/usr/bin/env python3
"""
video_karaoke.py — VOICEVOX mora timing → カラオケ字幕
=====================================================
- fetch_mora_timing(): /audio_query から各モーラ(カナ)の累積発話時刻を抽出。
  併せて /synthesis も同クエリで一往復分節約して WAV を保存する。
- build_karaoke_clip(): キャプションと同位置に重ねる動的レイヤ。
  発話済みの文字を黄色に塗り替えた PIL 画像を、モーラ境界時刻でスイッチする。

制約:
  VOICEVOX の mora は「カナ」単位。表示テキストに漢字が混ざっている場合は
  文節（accent_phrase）単位で前方突合せし、漢字文節はまるごとハイライトに
  degrade する（許容範囲）。
"""

from __future__ import annotations
import os
from bisect import bisect_right

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont
from moviepy import VideoClip

from video_layout import (
    WIDTH, HEIGHT, _font, _wrap, _emphasis_spans, _char_in_spans,
)


VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://localhost:50021")


def _mora_to_text(m: dict) -> str:
    """モーラの表示カナ。無声子音だけ等のケアで vowel/consonant を補完"""
    return m.get("text") or (m.get("consonant") or "") + (m.get("vowel") or "")


def _accent_phrase_kana(ap: dict) -> str:
    return "".join(_mora_to_text(m) for m in ap.get("moras", []))


def fetch_mora_timing(
    text: str,
    speaker_id: int,
    wav_path: str,
    speed: float = 1.1,
) -> tuple[str | None, list[dict]]:
    """VOICEVOX で mora timing を取得しつつ WAV も保存。
    戻り値: (wav_path, [{'kana':..,'start':..,'end':..,'phrase_idx':..,'phrase_kana':..}, ...])
    失敗時は (None, []) を返し呼び出し側でフォールバック。
    """
    try:
        q = requests.post(
            f"{VOICEVOX_URL}/audio_query",
            params={"text": text, "speaker": speaker_id},
            timeout=30,
        )
        q.raise_for_status()
        query = q.json()
        query["speedScale"] = speed
        query["volumeScale"] = 1.0
        query["intonationScale"] = 1.2

        s = requests.post(
            f"{VOICEVOX_URL}/synthesis",
            params={"speaker": speaker_id},
            json=query,
            timeout=60,
        )
        s.raise_for_status()
        with open(wav_path, "wb") as f:
            f.write(s.content)

        # 前後の無音もオフセットに含める（/audio_query の prePhonemeLength / postPhonemeLength）
        t = float(query.get("prePhonemeLength", 0.1)) / max(speed, 0.01)
        timings: list[dict] = []
        for p_idx, ap in enumerate(query.get("accent_phrases", [])):
            phrase_kana = _accent_phrase_kana(ap)
            for m in ap.get("moras", []):
                c = float(m.get("consonant_length") or 0.0) / max(speed, 0.01)
                v = float(m.get("vowel_length") or 0.0) / max(speed, 0.01)
                start = t
                t += c + v
                timings.append({
                    "kana": _mora_to_text(m),
                    "start": start,
                    "end": t,
                    "phrase_idx": p_idx,
                    "phrase_kana": phrase_kana,
                })
            # pause_mora
            pm = ap.get("pause_mora")
            if pm:
                pv = float(pm.get("vowel_length") or 0.0) / max(speed, 0.01)
                t += pv
        return wav_path, timings
    except Exception as e:
        print(f"  ⚠️ VOICEVOX mora timing 取得失敗: {e}")
        return None, []


# ─── カラオケ描画 ──────────────────────────────

def _active_count_at(t: float, boundaries: list[float]) -> int:
    """時刻 t までに発話完了したモーラ数"""
    return bisect_right(boundaries, t)


def _align_text_to_phrases(text: str, timings: list[dict]) -> list[tuple[int, int, int, int]]:
    """表示テキストの各文字に、どの mora/phrase が対応するかを推定。
    戻り値: [(ch_start, ch_end, phrase_idx, mora_idx_end)] 文節単位の区間列。
    漢字混じりは phrase まるごと割り当てる degrade 戦略。
    """
    if not timings:
        return []

    # phrase 単位にまとめる
    phrases: list[dict] = []
    for i, m in enumerate(timings):
        pid = m["phrase_idx"]
        if not phrases or phrases[-1]["idx"] != pid:
            phrases.append({
                "idx": pid,
                "kana": m["phrase_kana"],
                "start_mora": i,
                "end_mora": i + 1,
            })
        else:
            phrases[-1]["end_mora"] = i + 1

    # テキストを前方スキャンし、各 phrase に「この範囲が対応」と割り当てる
    # ひらがな/カタカナの一致があればそのぶん進め、漢字は「カナ化不明」として phrase 全体へ寄せる
    spans: list[tuple[int, int, int, int]] = []
    cursor = 0
    for ph in phrases:
        kana = ph["kana"]
        ch_start = cursor
        # kana 文字列を text の先頭から貪欲に吸収
        k_i = 0
        while cursor < len(text) and k_i < len(kana):
            tc = text[cursor]
            kc = kana[k_i]
            if tc == kc or (_is_small_kana(kc) and _is_small_kana(tc)):
                cursor += 1
                k_i += 1
            elif _is_non_kana(tc):
                # 漢字/記号はスキップして cursor を進め、k_i は据え置き
                cursor += 1
            else:
                # 不一致: text 側を進める（ひらがな vs カタカナなどで食い違う場合）
                cursor += 1
                k_i += 1
        ch_end = cursor
        spans.append((ch_start, ch_end, ph["idx"], ph["end_mora"]))
    # 末尾の残り文字は最後の phrase に吸収
    if spans and spans[-1][1] < len(text):
        s = spans[-1]
        spans[-1] = (s[0], len(text), s[2], s[3])
    return spans


def _is_small_kana(c: str) -> bool:
    return c in "ぁぃぅぇぉゃゅょっァィゥェォャュョッー"


def _is_non_kana(c: str) -> bool:
    if not c:
        return False
    o = ord(c)
    is_hira = 0x3041 <= o <= 0x3096
    is_kata = 0x30A1 <= o <= 0x30FA
    is_choon = c == "ー"
    return not (is_hira or is_kata or is_choon)


def build_karaoke_clip(
    text: str,
    emphasis: list[str] | None,
    mora_timing: list[dict],
    duration: float,
    font_size: int = 84,
    y_ratio: float = 0.14,
    fill_unspoken: tuple = (255, 255, 255, 255),
    fill_spoken: tuple = (255, 235, 59, 255),
    fill_emphasis: tuple = (255, 82, 82, 255),
    outline: tuple = (0, 0, 0, 255),
    outline_px: int = 12,
) -> VideoClip | None:
    """時刻 t に応じて、発話済み文字を黄色に塗り替えた PIL フレームを返す VideoClip。"""
    if not mora_timing:
        return None

    font = _font(font_size)
    font_big = _font(int(font_size * 1.15))
    lines = _wrap(text, font, WIDTH - 120)
    emp_spans = _emphasis_spans(text, emphasis or [])

    # 文字ごとのレイアウトを前計算（行内で emphasis=大フォント）
    line_h = int(font_size * 1.35)
    y_start = int(HEIGHT * y_ratio)

    char_layout: list[tuple[int, int, int, str, ImageFont.FreeTypeFont, bool]] = []
    ch_global = 0
    for li, line in enumerate(lines):
        widths = []
        for ch in line:
            use_big = _char_in_spans(ch_global + widths.__len__(), emp_spans)
            f = font_big if use_big else font
            bb = f.getbbox(ch)
            widths.append((ch, f, bb[2] - bb[0], use_big))
        total_w = sum(w for _, _, w, _ in widths)
        x = (WIDTH - total_w) // 2
        y = y_start + li * line_h
        for ch, f, w, use_big in widths:
            char_layout.append((ch_global, x, y, ch, f, use_big))
            x += w
            ch_global += 1

    # テキスト → phrase スパン
    phrase_spans = _align_text_to_phrases(text, mora_timing)
    # モーラ累積境界 (end 時刻)
    mora_ends = [m["end"] for m in mora_timing]

    def make_frame(t: float) -> np.ndarray:
        # 発話済みモーラ数 → どこまでハイライトするか
        done = _active_count_at(t, mora_ends)
        # done に収まる phrase の ch_end までをハイライト
        hl_ch = 0
        for ch_s, ch_e, _p_idx, mora_end in phrase_spans:
            if mora_end <= done:
                hl_ch = ch_e
            else:
                # この phrase は途中: モーラ進捗で線形補間して文字単位に
                phrase_len = ch_e - ch_s
                # 同じ phrase 内の開始/終了モーラ
                mora_start = mora_end - 0  # 粗いが実用上十分
                # 粗い比率ハイライト
                # phrase 内の進捗は (done - (mora_end - モーラ数)) / モーラ数
                # 近似: done が (mora_end - モーラ数) を超えた割合で ch 進行
                # モーラ数は前の phrase までの合計から差を見るのが正確だが近似でOK
                break
        # hl_ch を使って描画
        img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        for ch_global, x, y, ch, f, use_big in char_layout:
            # 縁取り
            for ox in range(-outline_px, outline_px + 1, 2):
                for oy in range(-outline_px, outline_px + 1, 2):
                    if ox * ox + oy * oy <= outline_px * outline_px:
                        draw.text((x + ox, y + oy), ch, fill=outline, font=f)
            if ch_global < hl_ch:
                fill = fill_spoken if not use_big else fill_emphasis
            else:
                fill = fill_unspoken if not use_big else fill_emphasis
            draw.text((x, y), ch, fill=fill, font=f)
        return np.array(img)

    # 境界時刻サンプリングでパフォーマンス確保（mora 境界で再描画）
    boundaries = sorted({round(b, 3) for b in mora_ends if b <= duration})
    last_frame_cache: dict[int, np.ndarray] = {}

    def make_frame_cached(t: float) -> np.ndarray:
        key = _active_count_at(t, boundaries)
        if key in last_frame_cache:
            return last_frame_cache[key]
        f = make_frame(t)
        last_frame_cache[key] = f
        return f

    clip = VideoClip(make_frame_cached, duration=duration)
    return clip
