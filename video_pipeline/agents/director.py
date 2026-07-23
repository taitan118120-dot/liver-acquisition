"""Director: 全エージェントを orchestrate して EditPlan v2 を組み立てる。

実行フロー:
  step1出力(transcription) を受け取る
   → Phase 0: 機械的下処理 (フレーズ統合, 無音検出, テロップchunk化)
   → Phase 1 (並列): GenreClassifier
   → Phase 2 (並列): HookStrategist + CutDirector + TelopWriter
   → Phase 3 (並列): HighlightSelector + SEComposer + BRollPlanner
   → Phase 4: EditPlan v2 をビルド
   → Phase 5: RetentionCritic で採点
   → 採点 < threshold なら Hook を1回だけ再生成して再採点（最大1ループ）

各Phaseの中はasyncio.gatherで並列、Phase間は依存があるので逐次。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from loguru import logger

from .base import LLMConfig, get_global_usage, run_in_parallel
from .broll_planner import BRollPlanner
from .cut_director import CutDirector
from .genre_classifier import GenreClassifier
from .highlight_selector import HighlightSelector
from .hook_strategist import HookStrategist
from .retention_critic import RetentionCritic
from .schemas import (
    BRollCue,
    BRollPlannerOutput,
    Clip,
    CriticReport,
    CutDirectorOutput,
    EditPlan,
    GenreDecision,
    HighlightSelectorOutput,
    HOOK_COLOR_MAP,
    HookDecision,
    HookOverlay,
    OutroCard,
    RetentionCriticOutput,
    SEComposerOutput,
    SECue,
    Subtitle,
    TelopWriterOutput,
    TemplateConfig,
    Token,
)
from .se_composer import SEComposer
from .telop_writer import TelopWriter

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_PATH = BASE_DIR / "templates" / "templates.json"


# =====================================================================
#                  下処理（旧step2から移植・改良）
# =====================================================================
SILENCE_THRESHOLD_SEC = 0.4
HOOK_DURATION_SEC = 3.0
HOOK_SCALE = 1.15
SUBTITLE_CHUNK_MAX_WORDS = 8
SUBTITLE_CHUNK_MAX_SEC = 2.2

_MERGE_PUNCT = set("、。！？!?.,…・")


def _merge_japanese_phrases(words: List[dict], max_gap: float = 0.18, max_chars: int = 8) -> List[dict]:
    if not words:
        return []
    merged: List[dict] = []
    cur = {"start": words[0]["start"], "end": words[0]["end"], "word": words[0]["word"]}

    def is_ascii_word(s: str) -> bool:
        return bool(s) and all(ord(c) < 128 and not c.isspace() for c in s)

    for w in words[1:]:
        text = w["word"]
        gap = w["start"] - cur["end"]
        ends_punct = any(p in cur["word"][-1:] for p in _MERGE_PUNCT)
        starts_punct = text[:1] in _MERGE_PUNCT
        would_exceed = len(cur["word"]) + len(text) > max_chars
        cur_is_ascii = is_ascii_word(cur["word"])
        new_is_ascii = is_ascii_word(text)
        if (
            cur["word"]
            and gap < max_gap
            and not ends_punct
            and not would_exceed
            and not (cur_is_ascii and new_is_ascii)
        ):
            cur["word"] = cur["word"] + text
            cur["end"] = w["end"]
        else:
            if cur["word"]:
                merged.append(cur)
            cur = {"start": w["start"], "end": w["end"], "word": text}
            if starts_punct and merged:
                prev = merged[-1]
                if len(prev["word"]) + len(text) <= max_chars:
                    prev["word"] += text
                    prev["end"] = w["end"]
                    cur = {"start": w["end"], "end": w["end"], "word": ""}
        if cur["word"] and cur["word"][-1] in _MERGE_PUNCT:
            merged.append(cur)
            cur = {"start": w["end"], "end": w["end"], "word": ""}
    if cur and cur["word"]:
        merged.append(cur)
    return merged


def _detect_silences(words: List[dict]) -> List[Tuple[float, float]]:
    silences = []
    for a, b in zip(words, words[1:]):
        gap = b["start"] - a["end"]
        if gap >= SILENCE_THRESHOLD_SEC:
            silences.append((a["end"], b["start"]))
    return silences


def _chunk_subtitles(words: List[dict]) -> List[dict]:
    chunks: List[dict] = []
    current: List[dict] = []
    PUNCT_END = {"。", "！", "？", ".", "!", "?", "、", ","}

    def flush():
        nonlocal current
        if not current:
            return
        chunks.append(
            {"start": current[0]["start"], "end": current[-1]["end"], "words": current}
        )
        current = []

    for w in words:
        current.append(w)
        span = current[-1]["end"] - current[0]["start"]
        last_text = w["word"]
        if (
            len(current) >= SUBTITLE_CHUNK_MAX_WORDS
            or span >= SUBTITLE_CHUNK_MAX_SEC
            or any(p in last_text for p in PUNCT_END)
        ):
            flush()
    flush()
    return chunks


# =====================================================================
#                       テンプレート読み込み
# =====================================================================
def load_template(genre: str) -> TemplateConfig:
    if not TEMPLATES_PATH.exists():
        logger.warning(f"templates.json が見つかりません: {TEMPLATES_PATH} → default")
        return TemplateConfig(genre="default")  # type: ignore[arg-type]
    with TEMPLATES_PATH.open("r", encoding="utf-8") as f:
        all_t = json.load(f)
    t = all_t.get(genre) or all_t.get("default") or {}
    t["genre"] = genre  # type: ignore[index]
    return TemplateConfig(**t)


# =====================================================================
#                       Clip ビルド (旧step2から)
# =====================================================================
def _build_clips(
    total_duration: float,
    silences: List[Tuple[float, float]],
    cuts: CutDirectorOutput,
    chunks: List[dict],
) -> List[Clip]:
    keep_map = {(round(c.start, 3), round(c.end, 3)): c.keep_pause for c in cuts.cuts}
    cut_ranges = [(s, e) for s, e in silences if not keep_map.get((round(s, 3), round(e, 3)), False)]

    cut_ranges.sort()
    kept: List[Tuple[float, float]] = []
    cursor = 0.0
    for s, e in cut_ranges:
        if s > cursor:
            kept.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < total_duration:
        kept.append((cursor, total_duration))
    if not kept:
        kept = [(0.0, total_duration)]

    # speed_ramps: chunk_index → speed
    speed_map = {}
    for r in cuts.speed_ramps:
        try:
            speed_map[int(r["chunk_index"])] = float(r["speed"])
        except (KeyError, ValueError, TypeError):
            continue

    # chunk時刻範囲 → speed のマップを kept 区間に投影
    def clip_speed_for(start: float, end: float) -> float:
        # 区間の中央時刻が含まれるchunkのspeedを採用（無ければ1.0）
        mid = (start + end) / 2
        for ci, ch in enumerate(chunks):
            if ch["start"] <= mid <= ch["end"]:
                return speed_map.get(ci, 1.0)
        return 1.0

    clips: List[Clip] = []
    for s, e in kept:
        if e <= HOOK_DURATION_SEC:
            clips.append(Clip(start=s, end=e, scale=HOOK_SCALE, speed=clip_speed_for(s, e)))
        elif s >= HOOK_DURATION_SEC:
            clips.append(Clip(start=s, end=e, scale=1.0, speed=clip_speed_for(s, e)))
        else:
            clips.append(Clip(start=s, end=HOOK_DURATION_SEC, scale=HOOK_SCALE, speed=clip_speed_for(s, HOOK_DURATION_SEC)))
            clips.append(Clip(start=HOOK_DURATION_SEC, end=e, scale=1.0, speed=clip_speed_for(HOOK_DURATION_SEC, e)))
    return clips


# =====================================================================
#                       Subtitle ビルド (v2)
# =====================================================================
def _build_subtitles(
    raw_chunks: List[dict],
    telop_out: TelopWriterOutput,
    highlight_out: HighlightSelectorOutput,
    template: TemplateConfig,
) -> List[Subtitle]:
    """Telop Writerの書き直し + Highlight Selectorの色付け を統合してSubtitle列を作る。

    各 line を1個のtoken にし、Highlightで指定された (line_index, word_index) を、
    line内の char position に投影して **part分割** で個別tokenとして発行する。
    例: line="Wi-Fi環境" で word_index=0 を強調指定 → tokens = [{"text":"Wi-Fi環境", color}]
        line="第2位はWi-Fi環境" で word_index=4 (= "W" の位置) を yellow 指定
          → tokens = [{"text":"第2位は", normal}, {"text":"Wi-Fi環境", color="yellow"}]
    （簡易投影: word_index は line文字列の char index と同視する）

    karaoke 用の reveal_start: subtitle 全体を chars 数で按分した相対秒を各 token に付与。
    """
    rewrite_map = {r.chunk_index: r for r in telop_out.rewrites}
    # highlight: (chunk_index, line_index) → list of (char_index, color, size)
    hl_map: dict[Tuple[int, int], List[Tuple[int, str, float]]] = {}
    for h in highlight_out.highlights:
        key = (h.chunk_index, h.line_index)
        color_hex = HOOK_COLOR_MAP.get(h.color, template.base_highlight_color)
        hl_map.setdefault(key, []).append((h.word_index, color_hex, h.size_scale))

    subtitles: List[Subtitle] = []
    for ci, chunk in enumerate(raw_chunks):
        rewrite = rewrite_map.get(ci)
        sub_start = float(chunk["start"])
        sub_end = float(chunk["end"])
        sub_dur = max(0.001, sub_end - sub_start)

        if rewrite is None:
            text = "".join(w["word"] for w in chunk["words"])
            tokens = [Token(text=text[:20] or "（無音）")]
            subtitles.append(Subtitle(start=sub_start, end=sub_end, tokens=tokens, template="default"))
            continue

        # 各行を char 単位で分割。highlight指定された char index をハイライト境界とする
        all_tokens: List[Token] = []
        # まず全体の文字数を数えて per-char duration を算出
        total_chars = sum(len(line) for line in rewrite.rewritten_lines)
        if total_chars == 0:
            total_chars = 1
        per_char = sub_dur / total_chars
        char_cursor = 0  # subtitle全体での文字位置

        for li, line in enumerate(rewrite.rewritten_lines):
            line_hls = sorted(hl_map.get((ci, li), []), key=lambda x: x[0])
            # ハイライト境界点で分割（重複/逆順を弾く）
            cuts: List[Tuple[int, int, Optional[str], float]] = []  # (start, end, color, size)
            cur = 0
            for word_idx, color, size in line_hls:
                start = max(0, min(len(line), word_idx))
                end = min(len(line), start + 4)
                if start < cur:
                    # 前のハイライトと重複 → このハイライトは捨てる
                    continue
                if start > cur:
                    cuts.append((cur, start, None, 1.0))
                if end <= start:
                    continue
                cuts.append((start, end, color, size))
                cur = end
            if cur < len(line):
                cuts.append((cur, len(line), None, 1.0))
            if not cuts:
                cuts.append((0, len(line), None, 1.0))

            for ci_part, (s, e, color, size) in enumerate(cuts):
                seg = line[s:e]
                if not seg:
                    continue
                reveal_rel = char_cursor * per_char
                tok = Token(
                    text=seg,
                    highlight=color is not None,
                    color=color,
                    size_scale=size,
                    reveal_start=round(reveal_rel, 3),
                )
                all_tokens.append(tok)
                char_cursor += len(seg)
            # 行末改行
            if li < len(rewrite.rewritten_lines) - 1:
                all_tokens.append(
                    Token(text="\n", reveal_start=round(char_cursor * per_char, 3))
                )

        if all_tokens:
            subtitles.append(
                Subtitle(
                    start=sub_start,
                    end=sub_end,
                    tokens=all_tokens,
                    template=rewrite.template,
                    entrance="punch",
                    karaoke=True,
                )
            )
    return subtitles


# =====================================================================
#               Outro CTA カード（ジャンル別）
# =====================================================================
def _build_outro(genre: str, template: TemplateConfig) -> OutroCard:
    presets = {
        "ranking": ("チャンネル登録で続報", "次のTOPを見逃すな", "subscribe"),
        "howto": ("保存しておこう", "見返せる", "bell"),
        "qa": ("コメント待ってる", "次の質問は？", "follow"),
        "explanation": ("チャンネル登録してね", "もっと深掘り", "subscribe"),
        "emotional": ("いいねで応援", "感想コメントへ", "heart"),
        "comedy": ("また見にきてね", "保存推奨", "follow"),
        "default": ("チャンネル登録してね", "また見にきて", "subscribe"),
    }
    text, subtext, icon = presets.get(genre, presets["default"])
    return OutroCard(
        text=text,
        subtext=subtext,
        duration=1.5,
        bg_color=template.hook_bg_color if template.hook_bg_color != "#FF3C3C" else "#0a0a14",
        text_color="#FFFFFF",
        accent_color=template.base_highlight_color,
        icon=icon,
    )


# =====================================================================
#               BGM ducking セグメント計算
# =====================================================================
def _compute_duck_segments(subtitles: List[Subtitle]) -> List[List[float]]:
    """Subtitle が出ている区間を発話中とみなし、BGMをduckするセグメント [[start,end],...]。
    隣接区間（gap < 0.4s）は1区間にマージ。
    """
    if not subtitles:
        return []
    # subtitle.start/end は元動画時刻だが、編集後タイムラインに変換する必要あり…ではなく、
    # ここでは renderer 側で edit時刻に変換するため、edit時刻に合わせるのは renderer の責務とする。
    # → renderer で計算するのが正しいが、ここでは元時刻ベースで近似（カットが少ない場合は十分機能する）
    raw = sorted([(s.start, s.end) for s in subtitles])
    merged: List[List[float]] = []
    for s, e in raw:
        if merged and s - merged[-1][1] < 0.4:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


# =====================================================================
#               カット後タイムライン上での時刻マッピング
# =====================================================================
def _build_time_mapping(clips: List[Clip]) -> List[Tuple[float, float, float, float]]:
    """各clipの (orig_start, orig_end, edit_offset, speed) を返す。"""
    mapping = []
    cum = 0.0
    for c in clips:
        dur = (c.end - c.start) / c.speed
        mapping.append((c.start, c.end, cum, c.speed))
        cum += dur
    return mapping


def _map_orig_to_edit(t: float, mapping: List[Tuple[float, float, float, float]]) -> Optional[float]:
    for s, e, offset, sp in mapping:
        if s <= t <= e:
            return offset + (t - s) / sp
    return None


def _chunk_to_edit_time(chunk: dict, mapping) -> Optional[float]:
    return _map_orig_to_edit(chunk["start"], mapping)


# =====================================================================
#                        Director エントリ
# =====================================================================
@dataclass
class DirectorConfig:
    llm: LLMConfig
    no_llm: bool = False
    enable_critic_loop: bool = True
    critic_threshold: float = 70.0  # retention_3s がこれ未満なら hook 再生成
    enable_se: bool = True
    enable_broll: bool = True


async def build_edit_plan(
    transcription: dict,
    cfg: DirectorConfig,
    bgm_path: Optional[str] = None,
) -> EditPlan:
    words: List[dict] = transcription.get("segments", [])
    if not words:
        raise RuntimeError("segments が空")
    source_video = transcription.get("source", "")
    language = transcription.get("language", "ja")
    total_duration = float(transcription.get("duration") or words[-1]["end"])

    # ---------- Phase 0: 下処理 ----------
    if language.startswith("ja"):
        before = len(words)
        words = _merge_japanese_phrases(words)
        logger.info(f"フレーズ統合: {before} → {len(words)}")

    silences = _detect_silences(words)
    raw_chunks = _chunk_subtitles(words)
    logger.info(f"無音 {len(silences)}件 / chunk {len(raw_chunks)}件")

    transcript_full = "".join(w["word"] for w in words)[:1500]
    intro_text = "".join(w["word"] for w in words if w["start"] < 5.0)[:200]

    # ---------- Phase 1: GenreClassifier ----------
    genre_agent = GenreClassifier(cfg.llm)
    genre_dec: GenreDecision = await genre_agent.run(
        {"transcript": transcript_full}, no_llm=cfg.no_llm
    )
    genre = genre_dec.genre
    template = load_template(genre)
    logger.info(f"[genre] {genre} ({genre_dec.reason})")

    # ---------- Phase 2: Hook + Cut + Telop (並列) ----------
    hook_agent = HookStrategist(cfg.llm)
    cut_agent = CutDirector(cfg.llm)
    telop_agent = TelopWriter(cfg.llm)

    hook_payload = {"genre": genre, "intro_text": intro_text}
    cut_payload = {
        "duration": total_duration,
        "silences": [{"start": round(s, 3), "end": round(e, 3)} for s, e in silences],
        "subtitles_raw": [
            {
                "chunk_index": i,
                "start": round(c["start"], 3),
                "end": round(c["end"], 3),
                "text": "".join(w["word"] for w in c["words"]),
            }
            for i, c in enumerate(raw_chunks)
        ],
    }
    telop_payload = {
        "subtitles_raw": [
            {
                "chunk_index": i,
                "text": "".join(w["word"] for w in c["words"]),
                # フレーズ統合済みの単位（fallback でフレーズ境界改行に使う）
                "phrases": [w["word"] for w in c["words"]],
            }
            for i, c in enumerate(raw_chunks)
        ]
    }

    logger.info("Phase 2: Hook + Cut + Telop 並列実行")
    hook_dec, cut_out, telop_out = await run_in_parallel(
        hook_agent.run(hook_payload, no_llm=cfg.no_llm),
        cut_agent.run(cut_payload, no_llm=cfg.no_llm),
        telop_agent.run(telop_payload, no_llm=cfg.no_llm),
    )
    logger.info(f"[hook] {hook_dec.hook.text if hook_dec.hook else 'なし'}")
    logger.info(f"[cut] cuts={len(cut_out.cuts)} ramps={len(cut_out.speed_ramps)}")
    logger.info(f"[telop] rewrites={len(telop_out.rewrites)}")

    # ---------- Phase 3: Highlight + SE + Broll (並列) ----------
    # Highlight 用ペイロード: telopの書き直し結果を line/word 単位に展開
    hl_payload_subs = []
    for r in telop_out.rewrites:
        lines = []
        for li, line_text in enumerate(r.rewritten_lines):
            words_list = [{"word_index": wi, "text": ch} for wi, ch in enumerate(line_text)]
            lines.append({"line_index": li, "words": words_list})
        hl_payload_subs.append(
            {"chunk_index": r.chunk_index, "template": r.template, "lines": lines}
        )
    hl_payload = {"subtitles": hl_payload_subs}

    se_payload_subs = [
        {
            "chunk_index": r.chunk_index,
            "template": r.template,
            "text": "".join(r.rewritten_lines),
        }
        for r in telop_out.rewrites
    ]
    se_payload = {"genre": genre, "subtitles": se_payload_subs}

    broll_payload = {"genre": genre, "subtitles": se_payload_subs}

    hl_agent = HighlightSelector(cfg.llm)
    se_agent = SEComposer(cfg.llm) if (cfg.enable_se and template.se_enabled) else None
    broll_agent = BRollPlanner(cfg.llm) if cfg.enable_broll else None

    coros = [hl_agent.run(hl_payload, no_llm=cfg.no_llm)]
    if se_agent:
        coros.append(se_agent.run(se_payload, no_llm=cfg.no_llm))
    if broll_agent:
        coros.append(broll_agent.run(broll_payload, no_llm=cfg.no_llm))

    logger.info("Phase 3: Highlight + SE + Broll 並列実行")
    results = await run_in_parallel(*coros)
    hl_out: HighlightSelectorOutput = results[0]
    se_out: SEComposerOutput = results[1] if se_agent else SEComposerOutput()
    broll_out: BRollPlannerOutput = results[-1] if broll_agent else BRollPlannerOutput()
    logger.info(
        f"[highlight] {len(hl_out.highlights)}件 / [se] {len(se_out.se_cues)}件 / [broll] {len(broll_out.broll_cues)}件"
    )

    # ---------- Phase 4: EditPlan v2 ビルド ----------
    clips = _build_clips(total_duration, silences, cut_out, raw_chunks)
    subtitles = _build_subtitles(raw_chunks, telop_out, hl_out, template)

    # SE/Broll を chunk_index → 編集後タイムライン に変換
    mapping = _build_time_mapping(clips)
    se_cues: List[SECue] = []
    for cue in se_out.se_cues:
        if cue.chunk_index >= len(raw_chunks):
            continue
        ch = raw_chunks[cue.chunk_index]
        anchor = ch["start"] if cue.at == "start" else ch["end"]
        edit_t = _map_orig_to_edit(anchor, mapping)
        if edit_t is None:
            continue
        se_cues.append(SECue(time=edit_t, sfx=cue.sfx, volume=cue.volume, reason=cue.reason))

    broll_cues: List[BRollCue] = []
    for cue in broll_out.broll_cues:
        if cue.chunk_index_start >= len(raw_chunks) or cue.chunk_index_end >= len(raw_chunks):
            continue
        s_anchor = raw_chunks[cue.chunk_index_start]["start"]
        e_anchor = raw_chunks[cue.chunk_index_end]["end"]
        es = _map_orig_to_edit(s_anchor, mapping)
        ee = _map_orig_to_edit(e_anchor, mapping)
        if es is None or ee is None or ee - es < 0.5:
            continue
        broll_cues.append(
            BRollCue(start=es, end=ee, style=cue.style, text_overlay=cue.text_overlay)
        )

    bgm = None
    if bgm_path:
        from .schemas import BGMConfig
        bgm = BGMConfig(
            path=bgm_path,
            volume=template.bgm_volume,
            duck_during_speech=template.bgm_duck_during_speech,
        )

    outro = _build_outro(genre, template)
    duck_segments = _compute_duck_segments(subtitles)

    plan = EditPlan(
        version="2",
        source=source_video,
        language=language,
        duration=total_duration,
        genre=genre,
        template=template,
        hook=hook_dec.hook,
        outro=outro,
        clips=clips,
        subtitles=subtitles,
        se_cues=se_cues,
        broll_cues=broll_cues,
        bgm=bgm,
        bgm_duck_segments=duck_segments,
    )

    # ---------- Phase 5: Critic ----------
    if cfg.enable_critic_loop:
        critic = RetentionCritic(cfg.llm)
        critic_payload = {
            "hook": plan.hook.model_dump() if plan.hook else None,
            "subtitles": [
                {"start": s.start, "end": s.end, "template": s.template}
                for s in plan.subtitles
            ],
            "se_cues": [{"time": s.time, "sfx": s.sfx} for s in plan.se_cues],
            "broll_cues": [{"start": b.start, "end": b.end} for b in plan.broll_cues],
        }
        critic_out: RetentionCriticOutput = await critic.run(critic_payload, no_llm=cfg.no_llm)
        logger.info(
            f"[critic] score={critic_out.score:.1f} retention_3s={critic_out.retention_3s:.1f}"
        )
        if critic_out.weak_points:
            logger.info("  weak: " + " / ".join(critic_out.weak_points))

        # 1回だけリトライ: hook が弱いと判断されたら hook を再生成
        if critic_out.retention_3s < cfg.critic_threshold and critic_out.suggested_hook_rewrite:
            logger.info(f"  → Hook再生成（提案: {critic_out.suggested_hook_rewrite}）")
            new_hook = HookOverlay(
                text=critic_out.suggested_hook_rewrite[:15],
                subtext=plan.hook.subtext if plan.hook else None,
                style=plan.hook.style if plan.hook else "banner",
                text_color=template.hook_text_color,
                bg_color=template.hook_bg_color,
                start=0.0,
                end=plan.hook.end if plan.hook else 2.5,
                font_size=template.hook_font_size,
                y_ratio=plan.hook.y_ratio if plan.hook else 0.38,
            )
            plan.hook = new_hook
            # 再採点
            critic_payload["hook"] = new_hook.model_dump()
            critic_out = await critic.run(critic_payload, no_llm=cfg.no_llm)
            logger.info(
                f"[critic-retry] score={critic_out.score:.1f} retention_3s={critic_out.retention_3s:.1f}"
            )

        plan.critic = CriticReport(
            score=critic_out.score,
            retention_3s=critic_out.retention_3s,
            notes=critic_out.notes,
            weak_points=critic_out.weak_points,
        )

    usage = get_global_usage().to_dict()
    logger.info(f"LLM使用量: {usage}")
    return plan
