# video_pipeline

SNS縦型ショート動画（1080×1920 / TikTok・YouTube Shorts）を完全自動生成する**マルチエージェント編成**パイプライン。

```
inputs/source.mp4
  └─ step1_transcribe.py  (Whisper: 単語単位文字起こし)
       └─ temp/transcription.json
            └─ step2_director.py  (7エージェント並列実行 → EditPlan v2)
                 │   ├─ GenreClassifier
                 │   ├─ HookStrategist        ─┐
                 │   ├─ CutDirector            ├─ Phase 2 並列
                 │   ├─ TelopWriter           ─┘
                 │   ├─ HighlightSelector     ─┐
                 │   ├─ SEComposer             ├─ Phase 3 並列
                 │   ├─ BRollPlanner          ─┘
                 │   └─ RetentionCritic        (採点+1回リライト)
                 └─ temp/edit_plan.json (v2)
                      └─ step3_renderer.py  (テンプレ駆動 / SE / 速度ランプ / Hook / B-roll)
                           └─ outputs/final.mp4
```

旧シングルプロンプト版 (`step2_logic_engine.py`) は `--legacy-step2` で利用可能。

## セットアップ

```bash
cd video_pipeline

# 1) Python仮想環境
python -m venv .venv && source .venv/bin/activate

# 2) 依存インストール
pip install -r requirements.txt

# 3) FFmpegが無ければ
brew install ffmpeg

# 4) APIキー設定
cp .env.example .env
# → .env を編集して ANTHROPIC_API_KEY を入れる

# 5) 日本語フォントを配置（推奨: Noto Sans JP Bold）
# https://fonts.google.com/noto/specimen/Noto+Sans+JP から
# NotoSansJP-Bold.ttf を assets/ に置く
```

## 使い方

### 一括実行
```bash
python run_all.py inputs/source.mp4
```

### 個別実行
```bash
# step1: 文字起こし
python step1_transcribe.py inputs/source.mp4 --backend local --model large-v3

# step2: マルチエージェント版（推奨）
python step2_director.py --provider anthropic --model claude-opus-4-7 --bgm ../shorts/bgm/main.mp3

# step2 旧版（シングルプロンプト）
python step2_logic_engine.py --provider anthropic --model claude-opus-4-7

# step3: レンダリング
python step3_renderer.py --font assets/NotoSansJP-Bold.ttf
```

### マルチエージェント機能のオン/オフ
```bash
python step2_director.py --no-critic     # Critic loopをスキップ
python step2_director.py --no-se         # SE合成を無効化
python step2_director.py --no-broll      # B-roll提案を無効化
```

### APIキー無しで動作確認（ルールベース）
`--no-llm` でLLM呼出を全スキップし、無音カット＋辞書ハイライトだけで処理:
```bash
python run_all.py inputs/test.mp4 --no-llm --whisper-model small
```

### 量産モード（複数動画の一括処理）
`batch_run.py` で指定ディレクトリ内の全mp4/mov/m4v/mkvを順次または並列処理。
動画ごとに `outputs/<動画名>/final.mp4` を生成し、`outputs/batch_summary_*.json` にサマリ出力:
```bash
# ディレクトリ指定（逐次）
python batch_run.py --input-dir ../shorts/videos

# 2並列 + LLM無しテスト
python batch_run.py --input-dir ../shorts/videos --parallel 2 --no-llm --whisper-model small

# 個別ファイル指定 + 本番Claude
python batch_run.py --files inputs/a.mp4 inputs/b.mp4 --provider anthropic --model claude-opus-4-7

# エラーで即中断
python batch_run.py --input-dir ../shorts/videos --stop-on-error
```

### APIキー本番運用（LLM有効化）
Claude または GPT-4o の API キーを取得し、`.env` に設定:

```bash
# Anthropic（推奨）: https://console.anthropic.com/settings/keys
echo 'ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxx' >> .env
echo 'LLM_PROVIDER=anthropic' >> .env
echo 'LLM_MODEL=claude-opus-4-7' >> .env

# または OpenAI: https://platform.openai.com/api-keys
echo 'OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxx' >> .env
echo 'LLM_PROVIDER=openai' >> .env
echo 'LLM_MODEL=gpt-4o' >> .env
```

有効化後は `--no-llm` 無しで実行:
```bash
python run_all.py inputs/source.mp4
```

**LLM利用時の差分**: 無音を「文脈上重要な間」として残す判断、キーワード強調の精度、が辞書ベースより大幅に向上。

## 厳守している演出ルール

| ルール | 実装箇所 |
|---|---|
| A: 無音 ≥0.4s はカット、重要な間は残す | `agents/cut_director.py` |
| B: 先頭0〜3sはscale=1.15でズーム | `agents/director.py::_build_clips` |
| C: 重要語をマルチカラーで強調 (yellow/red/green/cyan/pink) | `agents/highlight_selector.py` |
| D: 冒頭3秒に全画面Hookを差す | `agents/hook_strategist.py` + `step3_renderer.py::render_hook_png` |
| E: Whisper原文は ≤10文字×2行 に圧縮 | `agents/telop_writer.py` |
| F: SE (pop/tada/whoosh) は chunk数の30%以下 | `agents/se_composer.py` |
| G: B-roll (ken_burns/blur_bg/color_block) は最大3個 | `agents/broll_planner.py` |
| H: Critic 採点 < 70 なら Hook を1回だけ再生成 | `agents/director.py::Phase 5` |

## 出力仕様

| 項目 | 値 |
|---|---|
| 解像度 | 1080×1920 |
| FPS | 30 |
| 映像コーデック | H.264 (libx264) |
| 音声コーデック | AAC 192kbps |
| ピクセル形式 | yuv420p |
| moov atom | +faststart（ストリーミング対応） |

## テロップ仕様
- 位置: y ≒ 縦中央から下寄り（SUBTITLE_Y_RATIO=0.72）
- 黒ストローク幅: 8px
- ドロップシャドウ: (4,6)px 半透明黒
- ハイライト色: `#FFFF00`
- 最大幅88%、折返し対応

## エラーハンドリング
各step は `try/except` で `loguru` にスタックトレースを出力し、非0終了します。
中間JSON (`temp/*.json`) が不正なら後続stepが起動時に検知して停止します。
ログは `logs/stepN_YYYYMMDD.log` に10MBローテーションで保存されます。
