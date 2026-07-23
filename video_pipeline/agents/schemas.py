"""EditPlan v2 スキーマ + 各エージェントのI/O契約。

v1 (step2_logic_engine.py) 互換性:
  - version フィールドが無ければ v1 とみなす
  - step3_renderer.py は v1/v2 両方を受け入れる（in-memory で v2 に昇格）

v2 の新要素:
  - genre / template (ジャンル判定による演出切替)
  - hook (冒頭3秒の全画面オーバーレイ)
  - Token.color / size_scale (マルチカラー強調・サイズ強調)
  - Subtitle.template (punchline/question/shock 等で位置やアニメを変える)
  - Clip.speed (速度ランプ 0.8-1.3×)
  - se_cues (pop/tada/whoosh を任意時刻に挿入)
  - broll_cues (B-roll風の演出区間: Ken Burns / blur_bg / color_block)
  - bgm (BGM音量・ダッキング設定)
  - critic_score / critic_notes (QAパス結果)
"""

from __future__ import annotations

from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator


Genre = Literal["howto", "qa", "ranking", "explanation", "emotional", "comedy", "default"]

HighlightColor = Literal["yellow", "red", "green", "cyan", "pink"]

HOOK_COLOR_MAP = {
    "yellow": "#FFFF00",
    "red": "#FF3C3C",
    "green": "#00FFAA",
    "cyan": "#00D9FF",
    "pink": "#FF5CB8",
    "white": "#FFFFFF",
}


# =====================================================================
#                          Genre / Template
# =====================================================================
class TemplateConfig(BaseModel):
    """ジャンル別のデフォルトスタイル。Director がロードして各エージェントに配布。"""

    genre: Genre = "default"
    subtitle_y_ratio: float = 0.72
    subtitle_max_width_ratio: float = 0.88
    base_highlight_color: str = "#FFFF00"
    accent_color: str = "#FF3C3C"
    hook_bg_color: str = "#FF3C3C"
    hook_text_color: str = "#FFFFFF"
    default_font_size: int = 72
    hook_font_size: int = 120
    bgm_volume: float = 0.12
    bgm_duck_during_speech: bool = True
    se_enabled: bool = True
    speed_ramp_enabled: bool = True


# =====================================================================
#                          Hook / Overlay
# =====================================================================
HookStyle = Literal["banner", "centered_huge", "chat_bubble", "scribble", "none"]
HookEntrance = Literal["none", "slide_left", "slide_right", "slide_up", "slide_down", "pop", "fade", "shake"]


class HookOverlay(BaseModel):
    """冒頭0-3秒に全画面で表示する導入テロップ。離脱対策の最重要要素。"""

    text: str = Field(..., min_length=1, max_length=30)
    subtext: Optional[str] = Field(None, max_length=30)
    style: HookStyle = "banner"
    text_color: str = "#FFFFFF"
    bg_color: str = "#FF3C3C"
    start: float = Field(0.0, ge=0.0)
    end: float = Field(3.0, gt=0.0)
    font_size: int = Field(120, ge=40, le=240)
    y_ratio: float = Field(0.38, ge=0.0, le=1.0)
    entrance: HookEntrance = "slide_left"
    entrance_dur: float = Field(0.35, ge=0.0, le=1.5)

    @model_validator(mode="after")
    def _check(self) -> "HookOverlay":
        if self.end <= self.start:
            raise ValueError(f"hook.end({self.end}) <= start({self.start})")
        return self


class OutroCard(BaseModel):
    """末尾1〜2秒に差し込むエンドカード。チャンネル登録CTAやフォロー促進。"""

    text: str = Field(..., min_length=1, max_length=20)
    subtext: Optional[str] = Field(None, max_length=20)
    duration: float = Field(1.5, ge=0.5, le=4.0)
    bg_color: str = "#0a0a14"
    text_color: str = "#FFFFFF"
    accent_color: str = "#FFFF00"
    icon: Optional[Literal["bell", "heart", "follow", "subscribe"]] = "subscribe"


# =====================================================================
#                           Token / Subtitle
# =====================================================================
SubtitleTemplate = Literal["default", "punchline", "question", "shock", "whisper"]


SubtitleEntrance = Literal["none", "punch", "slide_up", "slide_left", "fade", "scale_pop"]


class Token(BaseModel):
    text: str = Field(..., min_length=1)
    highlight: bool = False
    color: Optional[str] = None          # 明示色指定（無ければ template の base_highlight_color）
    size_scale: float = Field(1.0, ge=0.6, le=2.2)  # ベースfont_sizeに対する倍率
    # カラオケ用: subtitle.start からの相対秒。Noneなら subtitle 開始と同時に出す
    reveal_start: Optional[float] = Field(None, ge=0.0)


class Subtitle(BaseModel):
    start: float = Field(..., ge=0.0)
    end: float = Field(..., gt=0.0)
    tokens: List[Token] = Field(..., min_length=1)
    template: SubtitleTemplate = "default"
    y_ratio: Optional[float] = Field(None, ge=0.0, le=1.0)  # template既定値を上書き
    entrance: SubtitleEntrance = "punch"
    karaoke: bool = True  # token.reveal_start を使ってカラオケ風に進行ハイライト

    @model_validator(mode="after")
    def _check(self) -> "Subtitle":
        if self.end <= self.start:
            raise ValueError(f"subtitle.end({self.end}) <= start({self.start})")
        return self


# =====================================================================
#                              Clip
# =====================================================================
class Clip(BaseModel):
    """元動画上の残す区間。speed/scale はレンダリング時の効果。"""

    start: float = Field(..., ge=0.0)
    end: float = Field(..., gt=0.0)
    scale: float = Field(1.0, ge=0.5, le=3.0)
    speed: float = Field(1.0, ge=0.5, le=2.0)
    keep_pause: bool = False

    @model_validator(mode="after")
    def _check(self) -> "Clip":
        if self.end <= self.start:
            raise ValueError(f"clip.end({self.end}) <= start({self.start})")
        return self


# =====================================================================
#                             SE / BGM
# =====================================================================
SECategory = Literal["pop", "tada", "whoosh"]


class SECue(BaseModel):
    """編集後タイムライン上の時刻にSEを鳴らす。time はカット後秒数。"""

    time: float = Field(..., ge=0.0)
    sfx: SECategory
    volume: float = Field(0.55, ge=0.0, le=1.5)
    reason: Optional[str] = None  # LLMからの説明（デバッグ用）


class BGMConfig(BaseModel):
    path: Optional[str] = None
    volume: float = Field(0.12, ge=0.0, le=1.0)
    duck_during_speech: bool = True
    duck_volume: float = Field(0.05, ge=0.0, le=1.0)


# =====================================================================
#                             B-roll
# =====================================================================
BRollStyle = Literal["ken_burns", "color_block", "blur_bg", "split_screen"]


class BRollCue(BaseModel):
    """編集後タイムライン上の区間で、B-roll風の差し込みを表示。"""

    start: float = Field(..., ge=0.0)
    end: float = Field(..., gt=0.0)
    style: BRollStyle = "ken_burns"
    text_overlay: Optional[str] = Field(None, max_length=40)
    bg_color: str = "#111111"

    @model_validator(mode="after")
    def _check(self) -> "BRollCue":
        if self.end <= self.start:
            raise ValueError(f"broll.end({self.end}) <= start({self.start})")
        return self


# =====================================================================
#                           EditPlan v2
# =====================================================================
class CriticReport(BaseModel):
    score: float = Field(..., ge=0.0, le=100.0)
    retention_3s: float = Field(..., ge=0.0, le=100.0)  # 3秒離脱回避スコア
    notes: List[str] = Field(default_factory=list)
    weak_points: List[str] = Field(default_factory=list)


class EditPlan(BaseModel):
    version: Literal["2"] = "2"
    source: str
    language: str = "ja"
    duration: float = Field(..., ge=0.0)

    genre: Genre = "default"
    template: TemplateConfig = Field(default_factory=TemplateConfig)

    hook: Optional[HookOverlay] = None
    outro: Optional[OutroCard] = None
    clips: List[Clip] = Field(..., min_length=1)
    subtitles: List[Subtitle] = Field(default_factory=list)
    se_cues: List[SECue] = Field(default_factory=list)
    broll_cues: List[BRollCue] = Field(default_factory=list)
    bgm: Optional[BGMConfig] = None
    # 速度0.0〜1.0で発話中はBGM音量をduck_volumeまで下げる（ducking）
    bgm_duck_segments: List[List[float]] = Field(default_factory=list)  # [[start, end], ...]

    critic: Optional[CriticReport] = None

    @model_validator(mode="after")
    def _sort(self) -> "EditPlan":
        self.clips.sort(key=lambda c: c.start)
        self.subtitles.sort(key=lambda s: s.start)
        self.se_cues.sort(key=lambda s: s.time)
        self.broll_cues.sort(key=lambda b: b.start)
        for a, b in zip(self.clips, self.clips[1:]):
            if b.start < a.end - 1e-6:
                raise ValueError(f"clip重複: {a} と {b}")
        return self


# =====================================================================
#                   各エージェントのI/O契約（小さな構造体）
# =====================================================================
class GenreDecision(BaseModel):
    genre: Genre
    reason: str = ""


class HookDecision(BaseModel):
    hook: Optional[HookOverlay] = None
    reason: str = ""


class CutDecision(BaseModel):
    start: float
    end: float
    keep_pause: bool = False
    reason: Optional[str] = None


class CutDirectorOutput(BaseModel):
    cuts: List[CutDecision] = Field(default_factory=list)
    speed_ramps: List[dict] = Field(default_factory=list)  # [{"chunk_index": int, "speed": float}]


class TelopRewriteItem(BaseModel):
    chunk_index: int
    rewritten_lines: List[str] = Field(..., min_length=1, max_length=3)
    template: SubtitleTemplate = "default"


class TelopWriterOutput(BaseModel):
    rewrites: List[TelopRewriteItem] = Field(default_factory=list)


class HighlightItem(BaseModel):
    chunk_index: int
    line_index: int = 0
    word_index: int
    color: HighlightColor = "yellow"
    size_scale: float = 1.0


class HighlightSelectorOutput(BaseModel):
    highlights: List[HighlightItem] = Field(default_factory=list)


class SECueProposal(BaseModel):
    chunk_index: int
    sfx: SECategory
    volume: float = 0.55
    at: Literal["start", "end"] = "start"
    reason: Optional[str] = None


class SEComposerOutput(BaseModel):
    se_cues: List[SECueProposal] = Field(default_factory=list)


class BRollProposal(BaseModel):
    chunk_index_start: int
    chunk_index_end: int
    style: BRollStyle = "ken_burns"
    text_overlay: Optional[str] = None


class BRollPlannerOutput(BaseModel):
    broll_cues: List[BRollProposal] = Field(default_factory=list)


class RetentionCriticOutput(BaseModel):
    score: float = Field(..., ge=0.0, le=100.0)
    retention_3s: float = Field(..., ge=0.0, le=100.0)
    weak_points: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    suggested_hook_rewrite: Optional[str] = None
