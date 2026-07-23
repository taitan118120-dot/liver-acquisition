"""
step2_logic_engine.py
=====================
単語単位の文字起こし（step1 の transcription.json）を読み込み、
LLMを使って「演出指示書（EditPlan）」に変換する。

ルールA（テンポ）: 無音区間 >=0.4s はカット候補。ただし LLM が文脈上重要と判定した間は keep_pause=true で残す。
ルールB（視線誘導）: 動画開始直後の 0〜3 秒は scale=1.15 ズームを自動付与。
ルールC（強調）: LLM が抽出した重要キーワード（固有名詞・感情表現）に highlight=true を立て、レンダリング時に #FFFF00 で描画。

出力スキーマは Pydantic で厳格にバリデーション。不正な JSON は LLM にリトライさせる。

Usage:
  python step2_logic_engine.py
  python step2_logic_engine.py --input temp/transcription.json --output temp/edit_plan.json
  python step2_logic_engine.py --provider openai --model gpt-4o
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Literal

from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel, Field, ValidationError, model_validator
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}")
logger.add(LOG_DIR / "step2_{time:YYYYMMDD}.log", level="DEBUG", rotation="10 MB", retention="7 days")

# ----- ルール定数 -----
SILENCE_THRESHOLD_SEC = 0.4           # ルールA: 0.4秒以上の無音はカット候補
HOOK_DURATION_SEC = 3.0               # ルールB: 先頭フック区間
HOOK_SCALE = 1.15                     # ルールB: ズーム倍率
HIGHLIGHT_COLOR = "#FFFF00"           # ルールC: 強調色（黄）
SUBTITLE_CHUNK_MAX_WORDS = 8          # 1テロップに詰める最大単語数
SUBTITLE_CHUNK_MAX_SEC = 2.2          # 1テロップの最大長さ


# ======================================================================
#                         Pydantic スキーマ
# ======================================================================
class Token(BaseModel):
    text: str = Field(..., min_length=1)
    highlight: bool = False


class Subtitle(BaseModel):
    start: float = Field(..., ge=0.0)
    end: float = Field(..., gt=0.0)
    tokens: List[Token] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _check_times(self) -> "Subtitle":
        if self.end <= self.start:
            raise ValueError(f"subtitle.end({self.end}) は start({self.start}) より大きい必要があります")
        return self


class Clip(BaseModel):
    start: float = Field(..., ge=0.0)
    end: float = Field(..., gt=0.0)
    scale: float = Field(1.0, ge=0.5, le=3.0)
    keep_pause: bool = False

    @model_validator(mode="after")
    def _check(self) -> "Clip":
        if self.end <= self.start:
            raise ValueError(f"clip.end({self.end}) は start({self.start}) より大きい必要があります")
        return self


class EditPlan(BaseModel):
    source: str
    language: str = "ja"
    duration: float = Field(..., ge=0.0)
    clips: List[Clip] = Field(..., min_length=1)
    subtitles: List[Subtitle] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sort_and_check(self) -> "EditPlan":
        self.clips.sort(key=lambda c: c.start)
        self.subtitles.sort(key=lambda s: s.start)
        # クリップ重複チェック
        for a, b in zip(self.clips, self.clips[1:]):
            if b.start < a.end - 1e-6:
                raise ValueError(f"クリップ重複: {a} と {b}")
        return self


# ======================================================================
#                   機械的処理（LLM呼び出し前の下処理）
# ======================================================================
_MERGE_PUNCT = set("、。！？!?.,…・")


def merge_japanese_phrases(
    words: List[dict],
    max_gap: float = 0.18,
    max_chars: int = 8,
) -> List[dict]:
    """
    Whisperが日本語を1文字ずつに分割した場合、
    隣接するトークンを連結してフレーズ単位に統合する。

    連結条件（全て満たす場合に連結）:
      - 直前トークンとのギャップが max_gap 未満
      - 連結後の文字数が max_chars 以下
      - 直前トークンの末尾が句読点でない
      - 現トークンがASCII単語（既に語単位）ではない
    """
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

        # ASCII単語同士は連結しない（Whisperが単語分割済み）
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
            # 句読点始まりなら前に吸収
            if starts_punct and merged:
                prev = merged[-1]
                if len(prev["word"]) + len(text) <= max_chars:
                    prev["word"] += text
                    prev["end"] = w["end"]
                    cur = {"start": w["end"], "end": w["end"], "word": ""}
        # 末尾が句読点になったら強制flush
        if cur["word"] and cur["word"][-1] in _MERGE_PUNCT:
            merged.append(cur)
            cur = {"start": w["end"], "end": w["end"], "word": ""}

    if cur and cur["word"]:
        merged.append(cur)
    return merged


def detect_silences(words: List[dict]) -> List[tuple[float, float]]:
    """隣接する単語間のギャップ >= SILENCE_THRESHOLD_SEC を無音区間として返す。"""
    silences: List[tuple[float, float]] = []
    for a, b in zip(words, words[1:]):
        gap = b["start"] - a["end"]
        if gap >= SILENCE_THRESHOLD_SEC:
            silences.append((a["end"], b["start"]))
    return silences


def chunk_subtitles(words: List[dict]) -> List[dict]:
    """
    単語列をテロップ単位にまとめる。句読点・単語数・時間で区切る。
    出力: [{"start": float, "end": float, "words": [{"text":..., "start":..., "end":...}, ...]}, ...]
    """
    chunks: List[dict] = []
    current: List[dict] = []
    PUNCT_END = {"。", "！", "？", ".", "!", "?", "、", ","}

    def flush():
        nonlocal current
        if not current:
            return
        chunks.append({
            "start": current[0]["start"],
            "end": current[-1]["end"],
            "words": current,
        })
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


# ======================================================================
#                       LLM プロバイダ抽象化
# ======================================================================
SYSTEM_PROMPT = """あなたはTikTok・YouTube Shorts・Instagram Reelsで月間1億再生を叩き出す日本語ショート動画の編集ディレクターです。
離脱率の最大の敵は「テンポの悪さ」と「メリハリの欠如」であることを熟知しています。

入力として、動画の単語単位の文字起こし（タイムスタンプ付き）・検出された無音区間・テロップ候補チャンク が与えられます。
あなたの仕事は以下を JSON のみで返すことです（説明文・マークダウン・コードフェンスは一切禁止）。

## 判断ルール

### 1. 無音カット判断（ルールA: テンポ）
与えられた "silences" それぞれについて、「文脈上の重要な間」かどうかを判断します。
日本語ショートでは **冗長な沈黙は離脱の最大要因** なので、原則カット（keep_pause=false）が基本です。

**間を残す（keep_pause=true）のは次のいずれかに該当する場合のみ:**
- オチ・結論の直前のタメ（笑いや驚きを増幅する意図的な無音）
- 問いかけの直後、視聴者に考えさせる演出的な沈黙
- 強い感情表現の余韻（「まじで…」の後の溜息的沈黙など）
- 数値や衝撃的事実を提示した直後の"効かせる"無音（0.5〜1.0秒程度）

**必ずカット（keep_pause=false）するもの:**
- 言い淀み、「えーと」「あの」の後の思考時間
- 話題の切り替わり前後の無意味な沈黙
- カメラ/機材調整による休止
- 1.0秒を超える長い沈黙（演出意図が極めて明確でない限り）

### 2. ハイライト判断（ルールC: 強調）
テロップ候補 subtitles_raw の各チャンクで、黄色強調すべき単語にフラグを立てます。
**ショート動画で強調すべきは「視聴者の指を止める単語」** です。

**優先度高（必ず強調検討）:**
- 数値（「3つ」「97%」「10万円」「1秒」）
- 比較級・最上級（「最強」「唯一」「トップ」「一番」）
- 結論/オチを示す語（「答えは」「つまり」「実は」「結論」）
- 強い感情語（「やばい」「神」「衝撃」「まじ」「絶対」）
- 固有名詞（ブランド名、人名、ツール名、商品名）
- 呼びかけ/フック（「知ってた？」「え、これ？」）

**強調しないもの:**
- 助詞、接続詞、指示代名詞
- 一般動詞（「する」「ある」「いる」）
- 「とても」「すごく」程度の弱い副詞

**制約:**
- 1チャンクあたり最大2語まで（過剰ハイライトは視認性を損なう）
- チャンクによっては 0 個でも良い（強調すべき語がなければ立てない）
- 指定は chunk_index と word_index（chunk内の0始まり）で行う

## 出力JSONスキーマ（このフィールドのみ返す、他のフィールドは禁止）
{
  "cuts": [{"start": 1.23, "end": 1.80, "keep_pause": false}, ...],
  "highlights": [{"chunk_index": 0, "word_index": 2}, ...]
}

## 絶対厳守
- 入力にない silence 区間・word_index を出力しない。
- start/end は入力 silences の値をそのまま（小数3桁）使う。
- 必ず valid JSON オブジェクト1つのみを返す。前後テキスト・コードフェンス・配列単体・文字列単体は禁止。
- 迷ったら「カットする」「強調しない」を選ぶ（安全側）。
"""


def call_llm(provider: str, model: str, user_payload: dict) -> dict:
    """LLMを呼び出し、JSONパース済みdictを返す。"""
    prompt_user = json.dumps(user_payload, ensure_ascii=False)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        retry=retry_if_exception_type((RuntimeError, json.JSONDecodeError)),
    )
    def _inner() -> dict:
        if provider == "anthropic":
            return _call_anthropic(model, prompt_user)
        elif provider == "openai":
            return _call_openai(model, prompt_user)
        else:
            raise ValueError(f"未対応provider: {provider}")

    return _inner()


def _call_anthropic(model: str, user_text: str) -> dict:
    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise RuntimeError("anthropic が未インストールです: pip install anthropic") from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 未設定")

    client = Anthropic(api_key=api_key)
    logger.debug(f"Anthropic呼出 model={model} payload={len(user_text)}文字")
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_text}],
        )
    except Exception as e:
        raise RuntimeError(f"Anthropic API失敗: {e}") from e

    text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text").strip()
    return _extract_json(text)


def _call_openai(model: str, user_text: str) -> dict:
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai が未インストールです: pip install openai") from e

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 未設定")

    client = OpenAI(api_key=api_key)
    logger.debug(f"OpenAI呼出 model={model} payload={len(user_text)}文字")
    try:
        resp = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
        )
    except Exception as e:
        raise RuntimeError(f"OpenAI API失敗: {e}") from e

    text = resp.choices[0].message.content.strip()
    return _extract_json(text)


def _extract_json(text: str) -> dict:
    """LLM出力からJSON部分を抽出してパース。"""
    if not text:
        raise json.JSONDecodeError("LLM返答が空", text, 0)
    # コードフェンス除去
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    # 先頭/末尾の { } だけ残す
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1:
        raise json.JSONDecodeError("JSONオブジェクトが見つからない", text, 0)
    snippet = text[first : last + 1]
    return json.loads(snippet)


# ======================================================================
#                   EditPlan 組み立て
# ======================================================================
def build_clips(
    total_duration: float,
    silences: List[tuple[float, float]],
    cuts_decision: List[dict],
) -> List[Clip]:
    """
    LLMの cuts_decision（silences と対応するkeep_pause）を反映して、
    カット後のクリップ配列を構築。
    ルールB: 0〜3秒 はズーム1.15 を自動付与。
    """
    # silence -> keep_pause dict
    keep_map: dict[tuple[float, float], bool] = {}
    for d in cuts_decision:
        try:
            s = float(d["start"])
            e = float(d["end"])
            keep_map[(round(s, 3), round(e, 3))] = bool(d.get("keep_pause", False))
        except (KeyError, ValueError, TypeError):
            continue

    # 実際にカットする区間のみ収集
    cut_ranges: List[tuple[float, float]] = []
    for s, e in silences:
        keep = keep_map.get((round(s, 3), round(e, 3)), False)
        if not keep:
            cut_ranges.append((s, e))

    # カット範囲の補集合 = 残す区間
    cut_ranges.sort()
    kept: List[tuple[float, float]] = []
    cursor = 0.0
    for s, e in cut_ranges:
        if s > cursor:
            kept.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < total_duration:
        kept.append((cursor, total_duration))

    if not kept:
        # セーフティ: 全カットされるなら元動画全体を1クリップとして返す
        kept = [(0.0, total_duration)]

    # ルールB: 先頭3秒ズーム適用（kept区間を分割する必要がある）
    clips: List[Clip] = []
    hook_end = HOOK_DURATION_SEC
    for s, e in kept:
        if e <= hook_end:
            clips.append(Clip(start=s, end=e, scale=HOOK_SCALE))
        elif s >= hook_end:
            clips.append(Clip(start=s, end=e, scale=1.0))
        else:
            # 区間が hook境界をまたぐ → 分割
            clips.append(Clip(start=s, end=hook_end, scale=HOOK_SCALE))
            clips.append(Clip(start=hook_end, end=e, scale=1.0))
    return clips


def build_subtitles(
    raw_chunks: List[dict],
    highlights: List[dict],
) -> List[Subtitle]:
    """LLMが指定した highlight を反映して Subtitle 配列を構築。"""
    # highlight index set
    hl_set: set[tuple[int, int]] = set()
    for h in highlights:
        try:
            ci = int(h["chunk_index"])
            wi = int(h["word_index"])
            hl_set.add((ci, wi))
        except (KeyError, ValueError, TypeError):
            continue

    subtitles: List[Subtitle] = []
    for ci, chunk in enumerate(raw_chunks):
        tokens: List[Token] = []
        for wi, w in enumerate(chunk["words"]):
            tokens.append(Token(text=w["word"], highlight=(ci, wi) in hl_set))
        if tokens:
            subtitles.append(Subtitle(start=chunk["start"], end=chunk["end"], tokens=tokens))
    return subtitles


# ======================================================================
#                            メイン
# ======================================================================
RULE_BASED_HIGHLIGHT_TOKENS = {
    # 数値・比較・結論・感情語を素朴に検出するルールセット（--no-llm 用フォールバック）
    "数値": ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "百", "千", "万", "億"],
    "最上級": ["最強", "最高", "最大", "最新", "最悪", "唯一", "一番", "トップ", "神", "ベスト"],
    "結論語": ["つまり", "要するに", "実は", "結論", "答え", "ポイント", "重要", "秘密"],
    "感情語": ["やばい", "ヤバい", "まじ", "マジ", "衝撃", "驚き", "絶対", "絶対に", "本当", "ほんと"],
    "呼びかけ": ["知ってた", "え？", "ちょっと", "聞いて", "見て"],
}
_ALL_RULE_KEYWORDS = {kw for group in RULE_BASED_HIGHLIGHT_TOKENS.values() for kw in group}
# 半角/全角の0-9も数値として扱う
_DIGIT_CHARS = set("0123456789０１２３４５６７８９%％倍個円点位")


def rule_based_highlights(raw_chunks: List[dict]) -> List[dict]:
    """LLMを使わず、キーワード辞書と数値パターンだけで highlight を生成（--no-llm 用）。"""
    highlights: List[dict] = []
    for ci, chunk in enumerate(raw_chunks):
        picked = 0
        for wi, w in enumerate(chunk["words"]):
            if picked >= 2:
                break
            text = w["word"]
            is_number = any(ch in _DIGIT_CHARS for ch in text)
            is_keyword = any(kw in text for kw in _ALL_RULE_KEYWORDS)
            if is_number or is_keyword:
                highlights.append({"chunk_index": ci, "word_index": wi})
                picked += 1
    return highlights


def run(
    input_path: Path,
    output_path: Path,
    provider: str,
    model: str,
    no_llm: bool = False,
) -> Path:
    if not input_path.exists():
        raise FileNotFoundError(f"transcription JSON が見つかりません: {input_path}")

    with input_path.open("r", encoding="utf-8") as f:
        transcription = json.load(f)

    words: List[dict] = transcription.get("segments", [])
    if not words:
        raise RuntimeError("segments が空です。step1 の出力を確認してください。")

    source_video = transcription.get("source", "")
    language = transcription.get("language", "ja")
    total_duration = float(transcription.get("duration") or words[-1]["end"])

    # 日本語の1文字分割をフレーズに統合（Whisperの character-level 出力対策）
    if language.startswith("ja"):
        before = len(words)
        words = merge_japanese_phrases(words)
        logger.info(f"日本語フレーズ統合: {before} → {len(words)} トークン")

    # 機械的下処理
    silences = detect_silences(words)
    raw_chunks = chunk_subtitles(words)
    logger.info(f"無音区間 {len(silences)}件 / テロップチャンク {len(raw_chunks)}件")

    if no_llm:
        # --no-llm: APIキー不要のルールベース推論
        logger.warning("--no-llm モード: LLMをスキップし、全無音をカット+ルールベースでハイライト生成")
        cuts = [{"start": round(s, 3), "end": round(e, 3), "keep_pause": False} for s, e in silences]
        highlights = rule_based_highlights(raw_chunks)
        logger.info(f"ルールベース応答: cuts={len(cuts)} highlights={len(highlights)}")
    else:
        # LLM用ペイロード
        payload = {
            "language": language,
            "duration": total_duration,
            "silences": [{"start": round(s, 3), "end": round(e, 3)} for s, e in silences],
            "subtitles_raw": [
                {
                    "chunk_index": i,
                    "start": round(c["start"], 3),
                    "end": round(c["end"], 3),
                    "words": [{"word_index": j, "text": w["word"]} for j, w in enumerate(c["words"])],
                }
                for i, c in enumerate(raw_chunks)
            ],
        }

        logger.info(f"LLM呼出 provider={provider} model={model}")
        try:
            llm_out = call_llm(provider, model, payload)
        except Exception as e:
            logger.exception(f"LLM呼出失敗（3回リトライ済み）: {e}")
            raise

        cuts = llm_out.get("cuts", []) or []
        highlights = llm_out.get("highlights", []) or []
        logger.info(f"LLM応答: cuts={len(cuts)} highlights={len(highlights)}")

    # EditPlan構築
    clips = build_clips(total_duration, silences, cuts)
    subtitles = build_subtitles(raw_chunks, highlights)

    try:
        plan = EditPlan(
            source=source_video,
            language=language,
            duration=total_duration,
            clips=clips,
            subtitles=subtitles,
        )
    except ValidationError as e:
        logger.error(f"EditPlan バリデーション失敗: {e}")
        raise

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(plan.model_dump(), f, ensure_ascii=False, indent=2)
    logger.success(f"EditPlan 出力: {output_path}  (clips={len(plan.clips)}, subs={len(plan.subtitles)})")
    return output_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="step2: 文字起こしJSONを演出指示書に変換")
    p.add_argument("--input", type=Path, default=TEMP_DIR / "transcription.json")
    p.add_argument("--output", type=Path, default=TEMP_DIR / "edit_plan.json")
    p.add_argument("--provider", choices=["anthropic", "openai"], default=os.environ.get("LLM_PROVIDER", "anthropic"))
    p.add_argument("--model", default=os.environ.get("LLM_MODEL", "claude-opus-4-7"))
    p.add_argument("--no-llm", action="store_true",
                   help="APIキー不要モード。全無音カット+辞書ベースでハイライト生成（動作確認用）")
    return p.parse_args()


def main() -> int:
    load_dotenv(BASE_DIR / ".env")
    args = parse_args()
    # providerに応じたデフォルトmodel補正
    if args.provider == "openai" and args.model.startswith("claude"):
        args.model = "gpt-4o"
    try:
        run(args.input, args.output, args.provider, args.model, no_llm=args.no_llm)
        return 0
    except Exception as e:
        logger.exception(f"step2 失敗: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
