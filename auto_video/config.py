"""auto_video: 設定値"""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJECT = BASE.parent
CACHE_DIR = BASE / "cache"
OUTPUT_DIR = BASE / "outputs"


def _load_dotenv_files():
    """軽量 .env ローダ: KEY=VALUE 形式のみ. 既存 env を上書きしない."""
    candidates = [
        BASE / ".env",
        PROJECT / ".env",
        PROJECT / "video_pipeline" / ".env",
    ]
    for f in candidates:
        if not f.exists():
            continue
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and v and not os.environ.get(k):
                    os.environ[k] = v
        except Exception:
            pass


_load_dotenv_files()

# 既存アセット再利用
FONT_PATH = PROJECT / "video_pipeline" / "assets" / "NotoSansJP-Bold.ttf"
FONT_FALLBACK = Path("/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc")
BGM_PATH = PROJECT / "shorts" / "bgm" / "main.mp3"
SE_DIR = PROJECT / "shorts" / "se"

# 動画
WIDTH = 1080
HEIGHT = 1920
FPS = 30

# Claude
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2500

# 音声
# edge-tts の公開エンドポイントで使える日本語は Nanami/Keita のみ
# rate/pitch を変えて擬似的にキャラ分けする
VOICES = {
    "narrator_f":  "ja-JP-NanamiNeural",
    "narrator_m":  "ja-JP-KeitaNeural",
    "young_f":     "ja-JP-NanamiNeural",  # young女性: rate高め+pitch上
    "mature_f":    "ja-JP-NanamiNeural",  # 落ち着いた女性: rate低め+pitch下
}
VOICE_TUNING = {
    "narrator_f":  {"rate": "+18%", "pitch": "+0Hz"},
    "narrator_m":  {"rate": "+15%", "pitch": "+0Hz"},
    "young_f":     {"rate": "+28%", "pitch": "+60Hz"},
    "mature_f":    {"rate": "+8%",  "pitch": "-40Hz"},
}
DEFAULT_VOICE = "narrator_f"
TTS_RATE = "+18%"
TTS_PITCH = "+0Hz"

# ブランディング
AGENCY_NAME = "TAITAN PRO"
LP_URL = "https://taitan-pro-lp.netlify.app/#apply"
LINE_URL = "https://lin.ee/xchCfdn"
CTA_TEXT = "プロフのLINEで\n無料診断プレゼント中"

# 色パレット（マルチカラー強調）
PALETTE = {
    "bg_dark":   "#0B1020",
    "bg_accent": "#1A2347",
    "text":      "#FFFFFF",
    "emph_yellow": "#FFE24C",
    "emph_red":    "#FF4D6D",
    "emph_cyan":   "#4CE0FF",
    "emph_pink":   "#FF8FC9",
    "emph_green":  "#4CFF9A",
    "cta_pink":    "#FF2D87",
}

CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
