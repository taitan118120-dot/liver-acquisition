# video_pipeline

SNS縦型ショート動画（1080×1920, TikTok/Shorts/Reels用）を**マルチエージェント編成**で自動生成するパイプライン。

## 起動手順

**常に仮想環境をアクティブにしてから実行する。システムPython(3.9)直実行は禁止:**

```bash
cd /Users/mitataisei/ライバー獲得/video_pipeline
source .venv/bin/activate
```

## 構成（v2: マルチエージェント版）

| ファイル | 役割 |
|---|---|
| `step1_transcribe.py` | faster-whisper で単語単位文字起こし → `temp/transcription.json` |
| `step2_director.py` | **新**: 7エージェントを並列実行して EditPlan v2 を生成（推奨） |
| `step2_logic_engine.py` | 旧: シングルプロンプト版（`--legacy-step2` で利用） |
| `step3_renderer.py` | EditPlan v1/v2 両対応の縦型レンダラー |
| `agents/` | エージェント本体（base/schemas/各種agent/director） |
| `templates/templates.json` | ジャンル別スタイル定義 |
| `run_all.py` | 単発の通し実行 |
| `batch_run.py` | 複数動画の一括処理 |

## エージェント分担

| Agent | 責務 |
|---|---|
| GenreClassifier | 動画ジャンル判定 (howto/qa/ranking/explanation/emotional/comedy/default) |
| HookStrategist | 冒頭3秒の全画面オーバーレイ設計 (banner/centered_huge/chat_bubble/scribble) |
| CutDirector | 無音カット判定 + 速度ランプ (0.85〜1.20×) |
| TelopWriter | Whisper原文を ≤10文字×2行 に書き直し + template判定 |
| HighlightSelector | マルチカラー強調 (yellow/red/green/cyan/pink) + サイズ強調 |
| SEComposer | pop/tada/whoosh のタイミング配置 |
| BRollPlanner | ken_burns/blur_bg/color_block/split_screen の差し込み区間 |
| RetentionCritic | 完成planを採点 → 弱ければHookを1回だけ再生成 |

Phase 1 (Genre) → Phase 2 (Hook+Cut+Telop 並列) → Phase 3 (Highlight+SE+Broll 並列) → Phase 4 (Plan組立) → Phase 5 (Critic loop)

## 呼び出しコマンド

### 単発（APIキー不要、ルールベースfallback）
```bash
python run_all.py inputs/動画.mp4 --no-llm --whisper-model small --language ja
```

### LLM本番（Anthropic prompt cache 利用、高品質）
`.env` に `ANTHROPIC_API_KEY=sk-ant-xxxx` を投入して:
```bash
python run_all.py inputs/動画.mp4 --bgm ../shorts/bgm/main.mp3
```

### 旧 step2（シングルプロンプト版）に戻す
```bash
python run_all.py inputs/動画.mp4 --legacy-step2
```

### 量産（フォルダ一括）
```bash
python batch_run.py --input-dir ../shorts/videos --bgm ../shorts/bgm/main.mp3
python batch_run.py --input-dir ../shorts/videos --no-llm --legacy-step2  # 動作確認
```

### 機能オフ（デバッグ用）
```bash
python step2_director.py --no-critic   # Criticループスキップ
python step2_director.py --no-se       # SE合成オフ
python step2_director.py --no-broll    # B-roll提案オフ
```

## 既知の罠（重要）

1. **Whisperモデル選択**: 日本語の word_timestamps では `small` が `large-v3` より実用的な場合あり。`medium` が無難な中間解。
2. **Pillow 11互換**: moviepy 1.0.3 が `Image.ANTIALIAS` 依存のため、step3 冒頭でシム適用済。
3. **フォント**: `assets/NotoSansJP-Bold.ttf` 推奨。`shorts/fonts/NotoSansJP-Bold.ttf` は破損 (HTML) なので使うな。無ければヒラギノ角ゴシック W8 に自動フォールバック。
4. **SE素材**: `shorts/se/{pop,tada,whoosh}.mp3` を使用。SECue.sfx は3種類のみ。
5. **BGM**: `--bgm` 引数で渡す。templates.json の `bgm_volume` で音量制御。
6. **EditPlan v1↔v2 互換**: step3 は version フィールドが無ければ v1 と判定し in-memory で v2 に昇格してレンダリング。
7. **prompt cache**: anthropic provider 時は `system` を ephemeral cache に。同一動画の複数エージェントで cache hit する。

## EditPlan v2 スキーマ (主要フィールド)

```jsonc
{
  "version": "2",
  "genre": "ranking",                    // 7ジャンルから選択
  "template": { ...TemplateConfig },
  "hook": {
    "text": "これがTOP3", "subtext": "...",
    "style": "banner",                  // banner/centered_huge/chat_bubble/scribble
    "bg_color": "#FF3C3C", "text_color": "#FFFFFF",
    "start": 0.0, "end": 3.0
  },
  "clips":     [{"start": 0.0, "end": 3.0, "scale": 1.15, "speed": 1.0}],
  "subtitles": [{
    "start": 0.0, "end": 0.96,
    "tokens": [{"text":"...", "highlight":true, "color":"#FF3C3C", "size_scale":1.4}],
    "template": "shock"                 // default/punchline/question/shock/whisper
  }],
  "se_cues":   [{"time": 4.5, "sfx": "pop", "volume": 0.55}],
  "broll_cues":[{"start": 8.0, "end": 12.0, "style": "blur_bg", "text_overlay": "..."}],
  "bgm":       {"path": "...", "volume": 0.12, "duck_during_speech": true},
  "critic":    {"score": 78.5, "retention_3s": 82.0, "weak_points": [...], "notes": [...]}
}
```

## 演出ルール（厳守・コード内）

| ルール | 場所 |
|---|---|
| 無音0.4s以上はカット候補、重要な間は残す | `agents/cut_director.py` |
| 先頭0〜3秒は scale=1.15 ズーム | `agents/director.py::_build_clips` |
| 重要語をマルチカラー強調 | `agents/highlight_selector.py` + `step3_renderer.py::render_subtitle_png_v2` |
| テロップは template 別の y_ratio + 黒ストローク + ドロップシャドウ | `step3_renderer.py::TEMPLATE_Y_RATIO` |
| pop/tada/whoosh の最大数は chunk数の30%以下 | `agents/se_composer.py` |
| B-roll は動画全体で3個以下 | `agents/broll_planner.py` |

## トラブル時の確認順序

1. `ls inputs/` で入力mp4があるか
2. `source .venv/bin/activate` 済みか（`which python` で確認）
3. `ffmpeg -version` が通るか
4. `ls assets/` または `ls ../shorts/fonts/` でフォントがあるか
5. `python step2_director.py --no-llm` で fallback が動くか
6. `logs/step*_YYYYMMDD.log` でスタックトレース確認
