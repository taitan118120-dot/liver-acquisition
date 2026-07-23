"""
sniper.user.js → ブックマークレット用 install.html を生成

実行: python3 build_bookmarklet.py
出力: install.html (Chromeで開いて、ボタンを bookmarks bar にドラッグ)
"""
import re
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "sniper.user.js"
OUT = HERE / "install.html"

js = SRC.read_text(encoding="utf-8")

# UserScript ヘッダコメント (==UserScript== ブロック) を除去
js = re.sub(r"//\s*==UserScript==[\s\S]*?//\s*==/UserScript==", "", js)
# 行コメント除去 (URLにある // は壊さないが、ここでは安全側でURL以外のみ)
# ブックマークレットは1行JSで動く必要があるので IIFE 構造はそのまま使える
# 改行をスペースに置換（文字列内の改行は基本ないので大丈夫）
# 念のため複数空白を1つに
js_min = re.sub(r"\s+", " ", js).strip()

bookmarklet = "javascript:" + urllib.parse.quote(js_min, safe="(){}[],;:=<>!&|+-*/?'\"`%@#$.")

html = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>P-Bandai Sniper インストール</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 720px; margin: 40px auto; padding: 0 20px; line-height: 1.7; }}
  h1 {{ font-size: 22px; }}
  .btn {{
    display: inline-block;
    background: linear-gradient(180deg, #ff3b30 0%, #c70016 100%);
    color: white !important;
    padding: 16px 28px;
    font-size: 18px;
    font-weight: bold;
    border-radius: 10px;
    text-decoration: none !important;
    box-shadow: 0 4px 16px rgba(255,59,48,.4);
    cursor: grab;
  }}
  .btn:hover {{ transform: translateY(-2px); }}
  .step {{ background: #f5f5f7; border-left: 4px solid #0a84ff; padding: 14px 18px; margin: 14px 0; border-radius: 6px; }}
  .warn {{ background: #fff5e0; border-left: 4px solid #ff9500; padding: 14px 18px; margin: 14px 0; border-radius: 6px; }}
  code {{ background: #eee; padding: 2px 6px; border-radius: 4px; font-size: 14px; }}
  kbd {{ background: #fff; border: 1px solid #ccc; border-bottom-width: 2px; padding: 2px 8px; border-radius: 4px; font-size: 13px; }}
</style>
</head>
<body>
<h1>🎯 P-Bandai Sniper — インストール</h1>

<p><b>下の赤いボタンを Chrome のブックマークバーにドラッグ＆ドロップ</b>するだけです。</p>

<p style="text-align:center; margin: 30px 0;">
  <a class="btn" href="{bookmarklet}">🎯 P-Bandai Sniper</a>
</p>

<div class="step">
  <b>ステップ1: ブックマークバーを表示</b><br>
  Chromeで <kbd>⌘ + Shift + B</kbd> を押す（バーが出てなければ）
</div>

<div class="step">
  <b>ステップ2: 上の赤ボタンをドラッグ</b><br>
  ボタンを掴んだまま、ブックマークバー (画面上部の細い帯) に持っていって離す
</div>

<div class="step">
  <b>ステップ3: テスト</b><br>
  ① 商品ページを開く: <a href="https://p-bandai.jp/item/item-1000232939/" target="_blank">テスト用商品（アンパンマンスタイ）</a><br>
  ② ブックマークバーの「🎯 P-Bandai Sniper」をクリック<br>
  ③ 右上に青いバナー → オレンジ「🧪 [DRY_RUN]」 → カートボタンが赤く光る = 成功
</div>

<div class="warn">
  <b>⚠️ 本番（明日 4/27 12:00）の使い方</b><br>
  1. 11:55 に商品ページ <a href="https://p-bandai.jp/item/item-1000249423/" target="_blank">予約商品ページ</a> を開く<br>
  2. ブックマーク「🎯 P-Bandai Sniper」をクリック → 「監視開始」バナーが出ればOK<br>
  3. あとは何もしないで12:00を待つ。発売の瞬間にカート自動投入＋購入手続きへ自動遷移<br>
  4. 注文確定の手前で必ず止まる → 自分で確認して確定ボタンを押す<br>
  <br>
  <b>★ DRY_RUN モード</b>: 現在は安全のため <code>DRY_RUN=true</code>。本番前に sniper.user.js の冒頭を <code>const DRY_RUN = false;</code> に書き換えて、再度この install.html を <code>python3 build_bookmarklet.py</code> で再生成 → ブックマークを上書きしてください。<br>
  <br>
  <b>もしくは: 当日11:55に「本番版ブックマーク」を別途用意しておく</b>のが安全。
</div>

<p style="color:#888; font-size: 13px;">
  生成元: sniper.user.js / 利用規約違反のリスクは自己責任。プレミアムバンダイのToSは自動化アクセスを禁止しています。
</p>
</body>
</html>
"""

OUT.write_text(html, encoding="utf-8")
print(f"wrote {OUT}")
print(f"open with: open {OUT}")
