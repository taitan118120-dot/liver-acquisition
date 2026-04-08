#!/usr/bin/env python3
"""
Note記事 一括公開アシスタント
================================
blog/articles_note/ のMarkdown記事を1本ずつ:
  1. Note.com向けに整形（テーブル→リスト変換等）
  2. タイトル・本文・ハッシュタグを分離
  3. 本文をクリップボードにコピー (pbcopy)
  4. ブラウザで note.com/new を自動オープン
  5. ユーザーがペースト&公開 → Enter で次の記事へ

使い方: python3 note_publisher.py [--start N] [--list] [--dry-run]
"""

import os
import re
import sys
import glob
import subprocess
import webbrowser
import argparse
import csv
from datetime import datetime

# ─── 設定 ───────────────────────────────────────────
ARTICLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blog", "articles_note")
NOTE_NEW_URL = "https://note.com/new"
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "note_publish_log.csv")

# 記事ファイル名 → ハッシュタグのマッピング
HASHTAG_MAP = {
    "01_ライバー始め方":       ["ライバー", "ライブ配信", "始め方", "副業", "Pococha"],
    "02_Pococha稼げる":       ["Pococha", "ポコチャ", "ライバー", "稼ぎ方", "ライブ配信"],
    "03_事務所選び方":         ["ライバー事務所", "事務所選び", "ライブ配信", "ライバー"],
    "04_配信初心者コツ":       ["配信初心者", "ライブ配信コツ", "ライバー", "トーク術"],
    "05_ライバー収入現実":     ["ライバー収入", "ライバー現実", "副業収入", "ライブ配信"],
    "06_在宅副業おすすめ":     ["在宅副業", "副業おすすめ", "スマホ副業", "ライバー"],
    "07_Pococha時間ダイヤ完全ガイド": ["Pococha", "時間ダイヤ", "ポコチャ", "ライバー収入"],
    "08_ライバー事務所フリー比較":   ["ライバー事務所", "フリーライバー", "事務所比較", "ライバー"],
    "09_顔出しなしライバー":   ["顔出しなし", "Vtuber", "ラジオ配信", "ライバー"],
    "10_大学生ライバー":       ["大学生副業", "大学生ライバー", "学生副業", "ライバー"],
    "11_主婦ライバー":         ["主婦副業", "主婦ライバー", "在宅ワーク", "ライバー"],
    "12_ライバー確定申告":     ["確定申告", "ライバー税金", "副業税金", "フリーランス"],
    "13_ライバーイベント攻略":  ["ライバーイベント", "Pococha", "イベント攻略", "ライバー"],
    "14_ライバー辞めたい":     ["ライバー辞めたい", "事務所退所", "ライバー悩み"],
    "15_ライバー男性":         ["男性ライバー", "メンズライバー", "ライブ配信", "ライバー"],
    "16_ライバー還元率":       ["還元率", "ライバー収入", "投げ銭", "ライバー事務所"],
    "17_ライバー面接対策":     ["ライバー面接", "事務所面接", "ライバー事務所", "面接対策"],
    "18_Pocochaランク上げ方":  ["Pococha", "ランク上げ", "ポコチャ攻略", "ライバー"],
    "19_ライバー機材おすすめ":  ["配信機材", "リングライト", "マイク", "ライバー"],
    "20_ライバー配信ネタ":     ["配信ネタ", "トーク術", "ライブ配信", "ライバー"],
    "21_ライバー伸びない原因":  ["伸びない原因", "配信コツ", "ライバー", "ライブ配信"],
    "22_30代ライバー":         ["30代ライバー", "30代副業", "ライバー", "ライブ配信", "大人の副業"],
    "23_ライブ配信市場将来性":   ["ライブ配信市場", "将来性", "ライバー", "副業", "成長産業"],
    "24_ライバー事務所代理店":   ["ライバー事務所", "代理店", "パートナー", "副業ビジネス", "ライバー"],
    "25_ライバーマネージャー":   ["ライバーマネージャー", "マネージャー", "ライバー事務所", "転職"],
    "26_ライバー副業バレない":   ["副業バレない", "副業バレ対策", "ライバー副業", "確定申告"],
    "27_ライバー事務所おすすめランキング": ["ライバー事務所", "おすすめ", "ランキング", "ライバー", "事務所比較"],
    "28_ライバー1日スケジュール":         ["ライバー", "1日スケジュール", "ライブ配信", "副業", "日常"],
    "29_ライバー事務所怪しい見分け方":     ["ライバー事務所", "怪しい", "詐欺", "見分け方", "注意"],
    "30_ライバーファン増やし方":           ["ファン増やし方", "リスナー", "ライバー", "配信コツ", "ライブ配信"],
    "31_ライバーメンタルケア":             ["ライバー", "メンタルケア", "病む", "配信つらい", "ライブ配信"],
    "32_ライバー事務所移籍":               ["事務所移籍", "退所", "ライバー事務所", "事務所変更", "ライバー"],
    "33_ライブ配信アプリ比較":             ["ライブ配信アプリ", "アプリ比較", "Pococha", "17LIVE", "ライバー"],
    "34_ライバー容姿関係ない":             ["ライバー", "容姿", "見た目", "ライブ配信", "自信"],
    "35_ライバー事務所契約書注意点":       ["契約書", "ライバー事務所", "注意点", "違約金", "ライバー"],
    "36_ライバーコラボ配信":               ["コラボ配信", "コラボ", "ライバー", "ファン増やす", "ライブ配信"],
}

# デフォルトハッシュタグ（マッピングにない場合）
DEFAULT_HASHTAGS = ["ライバー", "ライブ配信", "副業", "Pococha"]


def get_article_files():
    """記事ファイルを番号順にソートして返す"""
    pattern = os.path.join(ARTICLES_DIR, "*.md")
    files = sorted(glob.glob(pattern))
    return files


def parse_article(filepath):
    """Markdownファイルを解析してタイトル・本文・ハッシュタグを返す"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")

    # タイトル抽出（最初の # 行）
    title = ""
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title = line.lstrip("# ").strip()
            body_start = i + 1
            break

    body = "\n".join(lines[body_start:]).strip()

    # ファイル名からハッシュタグを取得
    basename = os.path.splitext(os.path.basename(filepath))[0]
    hashtags = HASHTAG_MAP.get(basename, DEFAULT_HASHTAGS)

    return title, body, hashtags


def convert_table_to_list(text):
    """Markdownテーブルをリスト形式に変換（Note.comはテーブル非対応）"""
    lines = text.split("\n")
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # テーブルヘッダー行を検出（| で始まり | で終わる）
        if re.match(r"^\|.+\|$", line.strip()):
            # テーブル全体を収集
            table_lines = []
            while i < len(lines) and re.match(r"^\|.+\|$", lines[i].strip()):
                table_lines.append(lines[i].strip())
                i += 1

            # セパレータ行を除去（|---|---|形式）
            table_lines = [l for l in table_lines if not re.match(r"^\|[\s\-:|]+$", l)]

            if len(table_lines) >= 2:
                # ヘッダー行のカラム名を取得
                headers = [c.strip() for c in table_lines[0].split("|")[1:-1]]

                # データ行を変換
                for row in table_lines[1:]:
                    cells = [c.strip() for c in row.split("|")[1:-1]]
                    parts = []
                    for h, c in zip(headers, cells):
                        if h and c:
                            parts.append(f"{h}: {c}")
                    if parts:
                        result.append("・" + " ／ ".join(parts))

                result.append("")  # 空行
            else:
                # テーブルが1行だけならそのまま
                result.extend(table_lines)
            continue

        result.append(line)
        i += 1

    return "\n".join(result)


def format_for_note(body):
    """Note.com向けにMarkdownを整形"""
    text = body

    # テーブルをリスト形式に変換
    text = convert_table_to_list(text)

    # 水平線を空行に
    text = re.sub(r"^---+$", "", text, flags=re.MULTILINE)

    # H2: ## → そのまま（Note.comはペースト時にH2を認識する）
    # H3: ### → ■ プレフィックスに変換（Note.comの見出し3は目立たないため）
    text = re.sub(r"^### (.+)$", r"■ \1", text, flags=re.MULTILINE)

    # 連続空行を2行まで圧縮
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    return text.strip()


def copy_to_clipboard(text):
    """macOS: テキストをクリップボードにコピー"""
    process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
    process.communicate(text.encode("utf-8"))


def open_note_editor():
    """ブラウザでNote.comの新規記事エディタを開く"""
    webbrowser.open(NOTE_NEW_URL)


def log_publish(index, filename, title, status="published"):
    """公開ログをCSVに記録"""
    file_exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["index", "filename", "title", "status", "published_at"])
        writer.writerow([index, filename, title, status, datetime.now().isoformat()])


def print_header():
    """ヘッダー表示"""
    print("=" * 60)
    print("  Note記事 一括公開アシスタント")
    print("  記事数: {}本".format(len(get_article_files())))
    print("=" * 60)
    print()
    print("【操作方法】")
    print("  Enter  → 本文をコピー＆エディタを開く")
    print("  s      → この記事をスキップ")
    print("  q      → 終了")
    print()


def list_articles():
    """記事一覧を表示"""
    files = get_article_files()
    print(f"\n全{len(files)}本の記事:\n")
    for i, f in enumerate(files, 1):
        title, _, _ = parse_article(f)
        basename = os.path.basename(f)
        print(f"  {i:2d}. [{basename}]")
        print(f"      {title}")
    print()


def run_publish(start_index=1, dry_run=False):
    """メインの公開ループ"""
    files = get_article_files()
    total = len(files)

    print_header()

    for i, filepath in enumerate(files, 1):
        if i < start_index:
            continue

        basename = os.path.basename(filepath)
        title, body, hashtags = parse_article(filepath)
        formatted_body = format_for_note(body)

        # 記事情報を表示
        print(f"── 記事 {i}/{total} ──────────────────────────")
        print(f"ファイル: {basename}")
        print(f"タイトル: {title}")
        print(f"文字数:   {len(formatted_body)}文字")
        print(f"ハッシュタグ: {' '.join('#' + t for t in hashtags)}")
        print()

        if dry_run:
            print("  [dry-run] スキップ")
            print()
            continue

        # ユーザー操作を待つ
        action = input("  → Enter で公開作業開始 / s でスキップ / q で終了: ").strip().lower()

        if action == "q":
            print("\n終了します。")
            break
        elif action == "s":
            print("  → スキップしました")
            log_publish(i, basename, title, status="skipped")
            print()
            continue

        # 1. タイトルをクリップボードにコピー
        copy_to_clipboard(title)
        print("  ✅ タイトルをクリップボードにコピーしました")

        # 2. エディタを開く
        open_note_editor()
        print("  ✅ Note.com エディタを開きました")
        print()
        print("  【手順】")
        print("  1. エディタのタイトル欄にペースト（⌘V）")

        input("  2. タイトル貼り付けたら Enter →（本文をコピーします）")

        # 3. 本文をクリップボードにコピー
        copy_to_clipboard(formatted_body)
        print("  ✅ 本文をクリップボードにコピーしました")
        print()
        print("  3. エディタの本文欄にペースト（⌘V）")

        # ハッシュタグ文字列を準備
        hashtag_str = " ".join("#" + t for t in hashtags)
        input(f"  4. 公開設定でハッシュタグを追加 → Enter（タグをコピーします）")

        copy_to_clipboard(hashtag_str)
        print(f"  ✅ ハッシュタグをコピーしました: {hashtag_str}")
        print()

        input("  5. 記事を公開したら Enter で次の記事へ →")

        log_publish(i, basename, title, status="published")
        print(f"  ✅ 公開ログに記録しました ({i}/{total})")
        print()

    # 完了メッセージ
    print("=" * 60)
    print("  完了！公開ログ: {}".format(LOG_FILE))
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Note記事 一括公開アシスタント")
    parser.add_argument("--start", type=int, default=1, help="開始する記事番号（デフォルト: 1）")
    parser.add_argument("--list", action="store_true", help="記事一覧を表示")
    parser.add_argument("--dry-run", action="store_true", help="実際にコピー・ブラウザを開かずに動作確認")

    args = parser.parse_args()

    if args.list:
        list_articles()
        return

    run_publish(start_index=args.start, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
