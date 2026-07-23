# auto_video

Claude-powered バズる縦型ショート動画の自動生成パイプライン。

- **script.py**: Claude Sonnet 4.6 で 8ビート構成のスクリプトを JSON で生成
- **voice.py**: edge-tts (Nanami/Keita) で per-beat mp3 + duration 取得
- **visual.py**: PIL で 1080×1920 フレーム描画（zoom-in/pan/pulse、色強調、巨大数字、CTAバー、プログレスバー、ブランドバッジ）
- **compose.py**: moviepy で音声・BGM・SE を重ねて mp4 出力
- **make.py**: topic → mp4 の 1 コマンドオーケストレータ

## 使い方

### 1本だけ
```bash
cd /Users/mitataisei/ライバー獲得
python3 -m auto_video.make --topic "ライバー月収のリアル格差" --angle "下位50%と上位の落差を数字階段で"
```

### 量産 (topics.yaml から10本)
```bash
python3 -m auto_video.make --yaml auto_video/topics.yaml --count 10
```

### オプション
- `--voice narrator_m|narrator_f|young_f|mature_f` ナレーター切り替え（rate/pitch 変化）
- `--sec 26` 目標尺（秒）
- `--no-cache` スクリプト・TTS キャッシュ無効化
- `--model claude-sonnet-4-6` モデル指定

## 出力
- `outputs/<title>.mp4` — 1080×1920 h264 mp4
- `outputs/<title>.json` — メタ（caption/hashtags/thumbnail_text/usage）

## キャッシュ
- `cache/script_<hash>.json` — トピック別スクリプト
- `cache/tts_<hash>.mp3` — テキスト別音声

## 依存
- anthropic (Python SDK)
- edge-tts 7.x
- moviepy 2.x
- PIL, numpy, pyyaml

## 環境変数
`.env` (auto_video/ または video_pipeline/) に:
```
ANTHROPIC_API_KEY=sk-ant-...
```

## 旧 shorts_generator.py との違い
- ❌ 旧: テンプレ穴埋め → ずんだもん口調 → 弱いフック
- ✅ 新: Claude がビートごと "Pattern Interrupt" フック → 具体数字階段 → 逆張り → CTA
- ❌ 旧: 7パターン × 47トピック = 329本の機械的バリエーション
- ✅ 新: 1トピック 1本、Claude が最適切り口を選択
- ❌ 旧: gradient + flat text
- ✅ 新: ラジアルグラデ + grain + モーション + 巨大数字 + CTA ピンク帯 + ブランドバッジ
