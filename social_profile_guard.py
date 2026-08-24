#!/usr/bin/env python3
"""social_profile_guard.py — プロフィール／固定ポストの確定ファクト番犬
=====================================================================
背景（2026-08-08）:
  X @taitan_LIVER の固定ポスト（2026-03-28 の初投稿）に
  「累計150名」「傘下11代理店を統括」「DMでご相談を」「私は現役プレイヤー」が
  4ヶ月以上そのまま公開され続けていた。プロフィール本体は 2026-07-31〜08-01 に
  是正済みだったのに、固定ポストだけ取り残されていた。

  真因は走査対象の設計:
    - 一括ファクト更新は **記事本文** を対象にしていて、プロフィール文は対象外だった
      （2026-07-31 に是正済み）
    - さらに **固定ポストは、そのプロフィール是正のときも対象外** だった
    - link_guard.py は「リンクが生きているか」しか見ず、文面の中身は見ない
  → 「一度書いたら二度と読み返さない場所」＝プロフィール・固定ポストを
     毎日読み直す番犬がどこにも居なかった。

このスクリプトが見る4軸:
  1. 禁止パターン走査 — 確定ファクト（[[project_taitan_pro_note_facts]]）の
     常設grepパターンを、実物のプロフィール文・固定ポスト・IG投稿キャプションに当てる
  2. 正本との突合 — marketing/social_profiles.md（表示名・bio・リンクの正本）を
     パースして、実物と1文字単位で一致するか見る。乖離＝どちらかが古い
  3. 正本そのものの検査（2026-08-09 追加）— パース結果に (a) 期待する媒体・項目が
     全部読めているかの取りこぼし検知と (b) 禁止パターン走査を当てる。
     従来は NG_PATTERNS を実物にしか当てていなかったので、正本自体が違反を含んでいても
     それを実物へ反映するまで誰も気づかなかった。
  4. 反映スクリプトの検査（2026-08-09 追加）— 実物へ書き込む側
     （x_profile_update.py / social_pinned_publish.py）が、文面を正本から読んでいるか。
     以前は正本と同じ文字列をスクリプトにも手書きでコピーしていて、
     docstring の「必ず両方を直すこと」だけが担保だった＝片方だけ直しても誰も気づかない。
     → 埋め込みを撤去して正本読み込みに一本化し、**戻したら赤くなる**ようにした（audit_consumers）。

判定ポリシー:
  - NG   = プロフィール／固定ポストの禁止パターン検出、正本との乖離、正本自体の問題、
           反映スクリプトが正本から読んでいない、
           トークンが別アカウントを指している → exit 1（Actionsが赤くなる）
  - WARN = 過去投稿のキャプションの違反 → 報告のみ。**Graph API でキャプションは編集できない**ので
           赤にすると番犬が永久に鳴きやまなくなる（[[feedback_watchdog_autoclose]]）
  - SKIP = 取得に必要なトークンが無い／固定ポスト本文が取れなかった媒体
           （ローカル実行時など）→ 既定では報告のみで exit 0。
           ただし SKIP が1件でもある回は、その実行が言えるのは
           **「取得できた媒体には違反が無かった」だけ**で、未取得の媒体については
           何も検査していない。だから SKIP があるとき最後のサマリに
           「違反なし ✅」とは書かない（2026-08-24: トークンの無いローカルで
           3媒体すべて SKIP なのに緑＋「違反なし ✅」で終わり、
           IG @taitan_pro7 の bio が確定ファクト違反を含んだままなのを
           「ローカルで緑になったから直った」と誤読した）。
           --require-live（または環境変数 PROFILE_GUARD_REQUIRE_LIVE=1）を付けると
           1媒体でも取得できなかった時点で exit 1 にする。
           **CI は Secrets が揃っている前提なので必ず付ける**
           ＝ Secrets 切れ・トークン失効で番犬が「緑のまま何も見ていない」状態に
           なるのを防ぐ。ローカルはトークンが無いのが普通なので既定は SKIP のまま。
  - 手動 = IG @taitanblog は個人アカウントで Graph API が使えない。
           自動取得できないので毎回チェック項目として出力するだけ（赤にはしない）

使い方:
  python3 social_profile_guard.py          # 全媒体（取得できない媒体は SKIP）
  python3 social_profile_guard.py --require-live  # 1媒体でも取得できなければ exit 1（CI用）
  python3 social_profile_guard.py --local  # 正本＋反映スクリプトの自己テストのみ（ネット不要／問題があれば exit 1）
  python3 social_profile_guard.py --local --json  # 上に加えてパース結果を生JSONで出す

正本の書き方（重要）:
  値は ```canonical:<媒体>.<項目> と印を付けたフェンスにだけ書く。
  例:  ```canonical:x.pinned … ```    媒体= threads / x / ig_taitan_pro7 / ig_taitanblog
                                      項目= name / bio / link / pinned
  印の無い ``` ブロックは**すべて単なる例示**として無視されるので、
  手順例・旧文面・エラーログを正本のどこに置いても値には影響しない。

必要な環境変数（GitHub Secrets から注入）:
  TWITTER_BEARER_TOKEN                        X
  THREADS_ACCESS_TOKEN                        Threads
  INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ID   Instagram @taitan_pro7

レポートは data/social_profile_guard_report.json に保存される。
"""

import ast
import importlib
import json
import os
import re
import sys

import requests

# 割合統計・収入レンジのパターンは媒体共通なので facts_patterns.py が正本。
# ここに再定義すると、X/Threads 側と片方だけ更新されて必ずズレる
# （2026-08-08 に RATIO_SUBJECT を足したとき、まさにX側が取り残された）。
from facts_patterns import (
    AUDIT_WARN_LABELS,
    COMMON_NG_PATTERNS,
    LINE_ALLOWED,
    line_link_violations,
    money_violations,
    ratio_violations,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_FILE = os.path.join(BASE_DIR, "data", "social_profile_guard_report.json")
CANON_FILE = os.path.join(BASE_DIR, "marketing", "social_profiles.md")

X_USERNAME = "taitan_LIVER"
IG_GRAPH = "https://graph.facebook.com/v21.0"
THREADS_GRAPH = "https://graph.threads.net/v1.0"

# ── 事務所IGハンドルの正本 ────────────────────────────────────
# config.OFFICE_INSTAGRAM が唯一の正本。番犬側にも期待username を手書きしていたので
# 一本化した（片方だけ直せる状態そのものが、この番犬が潰すべき欠陥）。
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
import config  # noqa: E402

OFFICE_IG_HANDLE = ("@" + config.OFFICE_INSTAGRAM.lstrip("@"))
OFFICE_IG_USERNAME = OFFICE_IG_HANDLE[1:]
# 末尾の数字だけが違う紛らわしいハンドル（@taitan_pro / @taitan_pro77）まで拾う。
# 「@taitan_pro が無い」ではなく「正本と一致しない事務所ハンドル」を検知したいので、
# 旧値を直書きせずに正本から機械的に組む（[[feedback_verify_before_asserting]]）。
OFFICE_HANDLE_LOOKALIKE = re.compile(
    r"@" + re.escape(OFFICE_IG_USERNAME.rstrip("0123456789")) + r"\d*(?![\w.])")

# ── 禁止パターン ──────────────────────────────────────────────
# 【2026-08-12】以前はここに確定ファクトの禁止パターンを**丸ごと自前で持って**いた。
# facts_patterns.py（媒体共通の正本）と9割が同じ内容の第2のリストで、
# まさに facts_patterns.py の docstring が「必ずどれか1本が古くなる」と
# 警告していた形そのものだった。そして実際に古くなっていた:
#   - ここにしか無かった … `京都コレクション`（実在しないイベント）
#     → 共通側に無いので LP・特典PDF・記事の検品には一切効かず、
#       2026-08-01 に確定した禁止が LP2本と**配布中の代理店特典PDF**で生き残った
#   - 共通側にしか無かった … 契約期間・不労所得・実績誇張・断定/保証・市場規模・
#     オフの日の主語・他社を下げる書き方・ロイヤリティ・少額表記 ほか多数
#     → プロフィールと固定ポストはこれらを一度も検査されていなかった
# → 共通正本を読み込み、**この媒体でしか意味がないものだけ**を足す形に統一した。
#   新しい確定ファクトは facts_patterns.COMMON_NG_PATTERNS に足せば全媒体に効く。
PROFILE_EXTRA_PATTERNS = [
    # プロフィール／固定ポスト特有の言い回し。所属数そのものは共通側が見ている
    (r"[0-9]{1,4}\s*[名人][^。\n]{0,6}(?:集客|育成|抱え)", "所属数を集客/育成実績として表記"),
]
NG_PATTERNS = list(COMMON_NG_PATTERNS) + PROFILE_EXTRA_PATTERNS

def scan(text, where):
    """1本のテキストに全パターンを当てて violation のリストを返す。

    各要素の "warn" は「検知はするが赤にはしない」印
    （facts_patterns.AUDIT_WARN_LABELS。主語や文脈で可否が変わるルール）。
    """
    if not text:
        return []
    flat = re.sub(r"\s+", "", text)
    out = []
    for pat, label in NG_PATTERNS:
        m = re.search(pat, text) or re.search(pat, flat)
        if m:
            out.append({"where": where, "reason": label, "hit": m.group(0)[:40],
                        "warn": label in AUDIT_WARN_LABELS})

    # 割合統計・収入レンジ・LINEリンクは facts_patterns.py（媒体共通の正本）に委譲
    for reason, hit in (ratio_violations(text) + money_violations(text)
                        + line_link_violations(text)):
        out.append({"where": where, "reason": reason, "hit": hit,
                    "warn": reason in AUDIT_WARN_LABELS})
    return out


def split_warn(items):
    """[(赤にするもの), (報告だけするもの)] に分ける。"""
    return ([i for i in items if not i.get("warn")],
            [i for i in items if i.get("warn")])


# ── 正本（marketing/social_profiles.md）のパース ───────────────────
# 【重要】正本の値は **``` canonical:<媒体>.<項目> と印を付けたフェンスからしか読まない**。
#
# 旧実装は「項目見出しの直後に現れた最初のフェンス」を本文として採っていた。
# つまり正本の“見た目の並び”に依存していて、説明用・手順例のコードブロックを
# 設計版フェンスより上に書くと、それが正本の値として読まれてしまった
# （2026-08-09: X「### 固定ツイート」節に固定手順の ``` を足したら
#   canon['x']['pinned'] が手順テキストに化けた）。
# しかも pinned は compare() の突合対象に入っていないため **番犬は何も鳴かなかった**。
# 同じことを bio / name でやれば、正本乖離の誤検知か、実物の違反の隠蔽になる。
#
# → フェンス自身に媒体と項目を書かせることで、見出しの文言・節の並び・
#   説明ブロックの位置から完全に切り離した。印の無いフェンスは全て「ただの例示」。
CANON_FENCE = re.compile(
    r"^`{3,}\s*canonical:\s*([A-Za-z0-9_]+)\s*\.\s*([A-Za-z0-9_]+)\s*$")
FENCE_END = re.compile(r"^`{3,}\s*$")

# 媒体ごとに「正本へ必ず書かれているべき項目」。ここに無い媒体／項目を
# canonical: で書くとタイポとして弾く（黙って無視されるのを防ぐ）。
EXPECTED_FIELDS = {
    "threads": ("name", "bio", "link", "pinned"),
    "x": ("name", "bio", "link", "pinned"),
    # IG は固定投稿という概念を運用していないので pinned は設計対象外
    "ig_taitan_pro7": ("name", "bio", "link"),
    "ig_taitanblog": ("name", "bio", "link"),
}
KNOWN_FIELDS = {f for fs in EXPECTED_FIELDS.values() for f in fs}
# 複数行になっていたら「別のブロックを掴んでいる」ことがほぼ確定する項目
SINGLE_LINE_FIELDS = ("name", "link")


def parse_canonical(path=CANON_FILE, problems=None):
    """正本を読んで {媒体: {項目: 本文}} を返す。

    problems にリストを渡すと、正本そのものの構造的な壊れ（未知キー・重複・
    閉じ忘れ・空・改行混入）を {where, reason, hit} 形式で追記する。
    """
    def bad(where, reason, hit=""):
        if problems is not None:
            problems.append({"where": where, "reason": reason, "hit": hit})

    lines = open(path, encoding="utf-8").read().split("\n")
    canon, i = {}, 0
    while i < len(lines):
        m = CANON_FENCE.match(lines[i])
        if not m:
            i += 1
            continue
        media, field = m.group(1), m.group(2)
        where = f"正本 {media}.{field}"
        buf, closed, i = [], False, i + 1
        while i < len(lines):
            if FENCE_END.match(lines[i]):
                closed, i = True, i + 1
                break
            buf.append(lines[i])
            i += 1
        value = "\n".join(buf).strip()

        if not closed:
            bad(where, "```canonical フェンスが閉じられていない（以降を全部飲み込んだ）")
        if media not in EXPECTED_FIELDS:
            bad(where, "未知の媒体キー（EXPECTED_FIELDS に無い）", media)
            continue
        if field not in KNOWN_FIELDS:
            bad(where, "未知の項目名（name/bio/link/pinned のいずれかにする）", field)
            continue
        if field not in EXPECTED_FIELDS[media]:
            bad(where, f"{media} では設計対象外の項目", field)
            continue
        if field in canon.get(media, {}):
            bad(where, "同じキーの canonical フェンスが2つ以上ある（どちらが正本か決まらない）",
                value[:40])
            continue
        if not value:
            bad(where, "中身が空")
            continue
        if field in SINGLE_LINE_FIELDS and "\n" in value:
            bad(where, "1行のはずが複数行（別のブロックを掴んでいる可能性）", value[:40])
        if field == "link" and not re.match(r"^https?://\S+$", value):
            bad(where, "リンクがURLの形をしていない", value[:60])
        canon.setdefault(media, {})[field] = value
    return canon


def audit_canonical(canon):
    """正本そのものを検査する。

    (1) 取りこぼし検知 — 期待している媒体・項目が実際に読めているか。
        「読めてはいるが中身が別物」は canonical: タグ側で防ぐ設計なので、
        ここは純粋に欠落（節ごと消えた／フェンスの印を付け忘れた）を見る。
    (2) 自己スキャン — NG_PATTERNS を **正本にも** 当てる。
        従来は実物にしか当てていなかったので、正本自体が確定ファクト違反を
        含んでいても、それを実物へ反映するまで誰も気づかなかった。
    """
    out = []
    for media, fields in EXPECTED_FIELDS.items():
        got = canon.get(media)
        if not got:
            out.append({"where": f"正本 {media}",
                        "reason": "媒体の節ごと読めていない（見出し変更 or canonical タグ消失）",
                        "hit": ""})
            continue
        for f in fields:
            if not got.get(f):
                out.append({"where": f"正本 {media}.{f}",
                            "reason": "正本から読み取れていない（```canonical: の印が無い？）",
                            "hit": ""})
    for media in sorted(canon):
        for f in sorted(canon[media]):
            out += scan(canon[media][f], f"正本 {media}.{f}")
    return out


# ── 反映スクリプト（正本の値を実物へ書き込む側）の検査 ─────────────
# 2026-08-09 以前、x_profile_update.py と social_pinned_publish.py は
# 正本と同じ文字列を **スクリプト内にも手書きでコピー** していた。
# 担保は docstring の「変更時は必ず両方を直すこと」だけで、機械的な照合が無く、
# 片方だけ直しても CI は緑のままだった（＝一括ファクト更新が固定ポストを
# 取りこぼした 2026-08-08 の事故と同じ構造の死角）。
#
# → 埋め込みを撤去して parse_canonical() 読み込みに一本化した（ig_profile_update.py と同じ形）。
#   ここでは「またコピーに戻していないか」を3重に見る:
#     (a) ast — 対象の定数に文字列リテラルを代入していないか（今日たまたま一致していても
#         リテラルなら明日必ずズレる。値比較だけでは捕まらないのでこちらが本命）
#     (b) ast — ファイルのどこかに正本の値と同一の文字列リテラルが無いか
#         （定数名を変えて別の場所へ逃がしたコピーを拾う。名前に依存しないので
#           ig_profile_update.py のように定数を持たないスクリプトも守れる）
#     (c) import — 実際に読める値が正本と **1文字単位で** 一致するか
#         norm() は使わない。空白の差も「片方だけ直した」の兆候なので潰さない
CONSUMERS = [
    ("x_profile_update.py", "x_profile_update",
     [("NAME", "x", "name"), ("DESCRIPTION", "x", "bio"), ("URL", "x", "link")]),
    ("social_pinned_publish.py", "social_pinned_publish",
     [("X_PINNED_TEXT", "x", "pinned"), ("THREADS_PINNED_TEXT", "threads", "pinned")]),
    # 元から正本読み込み型。定数は持たないので (b) だけが効く
    ("ig_profile_update.py", "ig_profile_update", []),
]


def _parse_module(path):
    try:
        return ast.parse(open(path, encoding="utf-8").read(), filename=path)
    except (OSError, SyntaxError):
        return None


def _literal_assigned_names(tree):
    """モジュール直下で「文字列リテラルを代入されている」名前の集合を返す。"""
    out = set()
    for node in tree.body:
        targets = ([node.target] if isinstance(node, ast.AnnAssign)
                   else node.targets if isinstance(node, ast.Assign) else [])
        if not isinstance(getattr(node, "value", None), (ast.Constant, ast.JoinedStr)):
            continue
        if isinstance(node.value, ast.Constant) and not isinstance(node.value.value, str):
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                out.add(t.id)
    return out


def _string_literals(tree):
    """ファイル中の全ての文字列リテラル（docstring含む）を返す。"""
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def audit_consumers(canon):
    out = []
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)

    for fname, modname, mapping in CONSUMERS:
        path = os.path.join(BASE_DIR, fname)
        where_file = f"反映スクリプト {fname}"
        if not os.path.exists(path):
            out.append({"where": where_file, "reason": "ファイルが見つからない（リネーム／削除された？）",
                        "hit": ""})
            continue

        tree = _parse_module(path)
        if tree is None:
            out.append({"where": where_file, "reason": "Pythonとして解析できない（構文エラー？）", "hit": ""})
        else:
            names = _literal_assigned_names(tree)
            for const, media, field in mapping:
                if const in names:
                    out.append({
                        "where": f"{where_file} / {const}",
                        "reason": f"正本ではなく文字列リテラルを埋め込んでいる"
                                  f"（正本 {media}.{field} から読むこと）",
                        "hit": const})

            # 定数名を変えて逃がしたコピーも拾う。**正本の値と完全一致する
            # 文字列リテラル**はコピー以外にあり得ないので誤検知しない
            # 同じ値が複数の媒体に出る（リンクなど）ので、キーは全部並べる
            canon_values = {}
            for m, fs in canon.items():
                for f, v in fs.items():
                    canon_values.setdefault(v, []).append(f"{m}.{f}")
            for lit in _string_literals(tree):
                if lit in canon_values:
                    out.append({
                        "where": where_file,
                        "reason": f"正本 {' / '.join(canon_values[lit])} と同じ文字列がリテラルで書かれている"
                                  f"（コピーを持たず parse_canonical() で読むこと）",
                        "hit": lit[:60]})

        try:
            mod = importlib.import_module(modname)
        except Exception as e:
            # 読み込めない＝正本と一致しているか確認できない。黙って素通りさせない
            out.append({"where": where_file, "reason": "import できず正本との突合ができなかった",
                        "hit": f"{type(e).__name__}: {e}"[:120]})
            continue

        for const, media, field in mapping:
            want = canon.get(media, {}).get(field)
            if want is None:
                continue  # 正本側の欠落は audit_canonical() が既に報告している
            got = getattr(mod, const, None)
            if got is None:
                out.append({"where": f"{where_file} / {const}",
                            "reason": f"定数が無い（リネーム？ 正本 {media}.{field} の反映先）",
                            "hit": ""})
            elif got != want:  # ← norm() を通さない。空白1つの差も検知する
                out.append({"where": f"{where_file} / {const}",
                            "reason": f"正本 {media}.{field} と1文字単位で一致しない",
                            "hit": f"正本 {want[:60]!r} / スクリプト {str(got)[:60]!r}"})
    return out


# ── 5軸目: 生成側のハンドル検査（2026-08-10 追加）──────────────────
# 背景: 事務所公式が @taitan_pro7 に確定（2026-08-08）した後も、
#   instagram/ig_content_generator.py と ig_viral_generator.py は @taitan_pro を
#   直書きしたままで、キャプションのCTAと画像ウォーターマークが
#   **未運用の別アカウント** へフォロワーを誘導し続けていた。
#   未投稿キュー10件（ig_auto_065〜074）は既にその文面で待機していた。
#   この番犬は「プロフィールと固定ポスト」しか見ていなかったので、
#   これから公開される投稿が汚染されていても一切鳴かなかった。
# → 公開テキストを **作る側** も毎日読む。投稿前に直せる場所なので NG（exit 1）扱い。
GENERATORS = [
    "instagram/ig_content_generator.py",
    "instagram/ig_viral_generator.py",
    "threads/threads_content.py",
]
POST_QUEUE = "instagram/ig_posts.json"


def _handle_mismatches(text):
    """テキスト中の「正本と一致しない事務所ハンドル」を返す。"""
    return [m.group(0) for m in OFFICE_HANDLE_LOOKALIKE.finditer(text or "")
            if m.group(0) != OFFICE_IG_HANDLE]


def audit_generators():
    out = []

    # (1) 正本ファイルが config と同じアカウントを設計対象にしているか。
    #     ここがズレると、以降の突合が「別アカウントの正本」との比較になる
    key = f"ig_{OFFICE_IG_USERNAME}"
    if key not in EXPECTED_FIELDS:
        out.append({
            "where": "config.OFFICE_INSTAGRAM",
            "reason": f"正本の媒体キー {key} が EXPECTED_FIELDS に無い"
                      f"（config だけ変えて marketing/social_profiles.md と番犬が取り残されている）",
            "hit": f"既知の媒体キー: {', '.join(sorted(EXPECTED_FIELDS))}"})

    # (2) 生成スクリプトの直書き。**文字列リテラルだけ** を見るので、
    #     経緯を説明する `#` コメントや docstring の外の記述は誤検知しない
    for rel in GENERATORS:
        path = os.path.join(BASE_DIR, rel)
        where = f"生成スクリプト {rel}"
        if not os.path.exists(path):
            out.append({"where": where, "reason": "ファイルが見つからない（リネーム／削除された？）",
                        "hit": ""})
            continue
        tree = _parse_module(path)
        if tree is None:
            out.append({"where": where, "reason": "Pythonとして解析できない（構文エラー？）", "hit": ""})
            continue
        for lit in _string_literals(tree):
            for hit in _handle_mismatches(lit):
                out.append({
                    "where": where,
                    "reason": f"正本でないIGハンドルを直書きしている"
                              f"（config.OFFICE_INSTAGRAM = {OFFICE_IG_HANDLE} を参照すること）",
                    "hit": f"{hit} … {lit.strip()[:60]}"})

    # (3) 未投稿キュー。既に投稿済みのキャプションは Graph API で編集できないので
    #     対象外（main() が過去投稿を warn として別途拾う）。未投稿分は今なら直せる
    qpath = os.path.join(BASE_DIR, POST_QUEUE)
    if not os.path.exists(qpath):
        out.append({"where": f"投稿キュー {POST_QUEUE}", "reason": "ファイルが見つからない", "hit": ""})
        return out
    try:
        queue = json.load(open(qpath, encoding="utf-8"))
    except (OSError, ValueError) as e:
        out.append({"where": f"投稿キュー {POST_QUEUE}", "reason": "JSONとして読めない",
                    "hit": f"{type(e).__name__}: {e}"[:120]})
        return out
    for item in queue:
        if item.get("posted"):
            continue
        for hit in _handle_mismatches(item.get("caption", "")):
            out.append({
                "where": f"投稿キュー {POST_QUEUE} / {item.get('id', '?')}",
                "reason": f"未投稿キャプションが正本でないIGハンドルを含む"
                          f"（このまま投稿されると {hit} へ誘導される）",
                "hit": f"{hit} … {item.get('title', '')[:40]}"})
    return out


def norm(s):
    return re.sub(r"\s+", "", s or "")


# ── 実物の取得 ────────────────────────────────────────────────
def fetch_x():
    token = os.environ.get("TWITTER_BEARER_TOKEN", "").strip()
    if not token:
        return None, "TWITTER_BEARER_TOKEN 未設定"
    r = requests.get(
        f"https://api.x.com/2/users/by/username/{X_USERNAME}",
        params={
            "user.fields": "username,name,description,url,entities,pinned_tweet_id",
            "expansions": "pinned_tweet_id",
            "tweet.fields": "text,created_at",
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if r.status_code != 200:
        return None, f"X API {r.status_code}: {r.text[:200]}"
    d = r.json()
    u = d.get("data") or {}
    pinned = (d.get("includes", {}).get("tweets") or [{}])[0]
    # ⚠️ pinned_tweet_id が data に入っていても includes が空で返ることがある（実測）。
    #    expansions を当てにせず、id で単体取得にフォールバックする。
    pinned_id = u.get("pinned_tweet_id") or ""
    if not pinned.get("text") and pinned_id:
        t = requests.get(f"https://api.x.com/2/tweets/{pinned_id}",
                         params={"tweet.fields": "text,created_at"},
                         headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if t.status_code == 200:
            pinned = t.json().get("data") or {}
    if not pinned.get("text"):
        # 固定ポストはこの番犬の主目的。取れないなら黙って素通りさせず必ず可視化する
        print(f"  ⚠️ X: 固定ポストが取得できませんでした "
              f"（pinned_tweet_id={pinned_id!r} / includes={sorted(d.get('includes', {}))}）")
    # url は t.co なので entities から実URLを取る
    link = u.get("url", "")
    for e in (u.get("entities", {}).get("url", {}).get("urls") or []):
        if e.get("expanded_url"):
            link = e["expanded_url"]
    return {
        "username": u.get("username", ""),
        "name": u.get("name", ""),
        "bio": u.get("description", ""),
        "link": link,
        "pinned": pinned.get("text", ""),
        "pinned_id": u.get("pinned_tweet_id", ""),
    }, None


def fetch_threads():
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        return None, "THREADS_ACCESS_TOKEN 未設定"
    r = requests.get(
        f"{THREADS_GRAPH}/me",
        params={"fields": "id,username,name,threads_biography", "access_token": token},
        timeout=30,
    )
    if r.status_code != 200:
        return None, f"Threads API {r.status_code}: {r.text[:200]}"
    d = r.json()
    # Threads API はプロフィールリンク・固定投稿を返さない（読み取り不可）
    return {"username": d.get("username", ""), "name": d.get("name", ""),
            "bio": d.get("threads_biography", "")}, None


def fetch_ig():
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    biz = os.environ.get("INSTAGRAM_BUSINESS_ID", "").strip()
    if not (token and biz):
        return None, "INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ID 未設定"
    r = requests.get(f"{IG_GRAPH}/{biz}",
                     params={"fields": "username,name,biography,website",
                             "access_token": token}, timeout=30)
    if r.status_code != 200:
        return None, f"IG API {r.status_code}: {r.text[:200]}"
    d = r.json()
    out = {"username": d.get("username", ""), "name": d.get("name", ""),
           "bio": d.get("biography", ""), "link": d.get("website", ""), "captions": []}
    m = requests.get(f"{IG_GRAPH}/{biz}/media",
                     params={"fields": "caption,permalink,timestamp", "limit": 25,
                             "access_token": token}, timeout=30)
    if m.status_code == 200:
        out["captions"] = [
            {"caption": x.get("caption", ""), "permalink": x.get("permalink", "")}
            for x in m.json().get("data", [])
        ]
    return out, None


# ── 突合 ─────────────────────────────────────────────────────
def compare(media_label, live, canon, fields):
    diffs = []
    for f in fields:
        want, got = canon.get(f), live.get(f)
        if want is None or got is None:
            continue
        if norm(want) != norm(got):
            diffs.append({"where": f"{media_label} / {f}", "canonical": want, "live": got})
    return diffs


def load_canon():
    """正本を読み、同時に正本自体・反映スクリプト側の問題も集める。

    戻り値は (canon, 赤にする問題, 報告だけする警告)。
    警告は AUDIT_WARN_LABELS のルール（主語や文脈で可否が変わるもの）だけ。
    """
    problems = []
    canon = parse_canonical(problems=problems)
    problems += audit_canonical(canon)
    problems += audit_consumers(canon)
    problems += audit_generators()
    return (canon, *split_warn(problems))


def print_canon(canon, problems, warns=()):
    for media, fields in EXPECTED_FIELDS.items():
        print(f"\n== {media} ==")
        for f in ("name", "bio", "link", "pinned"):
            v = canon.get(media, {}).get(f)
            if v is None:
                mark = "—（この媒体では設計対象外）" if f not in EXPECTED_FIELDS[media] \
                    else "❌ 正本から読めていない"
                print(f"  [{f}] {mark}")
                continue
            body = v.replace("\n", "\n        ")
            print(f"  [{f}] {len(v)}字\n        {body}")
    print(f"\n[正本＋反映スクリプト＋生成側の検査] 問題 {len(problems)} 件"
          f" / 警告 {len(warns)} 件（事務所IG正本 = {OFFICE_IG_HANDLE}）")
    for p in problems:
        print(f"  ❌ {p['where']}: {p['reason']}" + (f"\n     → {p['hit']}" if p["hit"] else ""))
    for w in warns:
        print(f"  ⚠️ (判断保留) {w['where']}: {w['reason']}"
              + (f"\n     → {w['hit']}" if w["hit"] else ""))


def require_live_enabled(argv=None):
    """--require-live / PROFILE_GUARD_REQUIRE_LIVE が有効か。

    有効なら「1媒体でも取得できなかった＝検査していない媒体がある」時点で赤にする。
    CI は Secrets が揃っている前提なので必ず有効にする（Secrets切れ・トークン失効で
    番犬が緑のまま何も見ていない状態になるのを防ぐ）。
    """
    if "--require-live" in (sys.argv if argv is None else argv):
        return True
    return os.environ.get("PROFILE_GUARD_REQUIRE_LIVE", "").strip().lower() \
        not in ("", "0", "false", "no")


def main():
    if "--local" in sys.argv:
        canon, problems, canon_warns = load_canon()
        print_canon(canon, problems, canon_warns)
        if "--json" in sys.argv:
            print(json.dumps(canon, ensure_ascii=False, indent=1))
        return 1 if problems else 0

    require_live = require_live_enabled()
    canon, canon_problems, canon_warns = load_canon()
    violations, warns, diffs, skipped = [], list(canon_warns), [], []

    # (表示名, 正本キー, 取得関数, 期待username, 突合フィールド, 走査フィールド)
    sources = [
        ("X @taitan_LIVER", "x", fetch_x, "taitan_LIVER",
         ["name", "bio", "link"], ["bio", "pinned"]),
        ("Threads @taitanblog", "threads", fetch_threads, "taitanblog",
         ["name", "bio"], ["bio"]),
        # 事務所公式は @taitan_pro7（2026-08-08 ユーザー確定）。
        # @taitan_pro は投稿が一度も流れていない別アカウントで、運用しない。
        # 期待username は config.OFFICE_INSTAGRAM から引く（ここに手書きすると
        # 「configだけ直して番犬が旧アカを見続ける」が起きる）
        (f"IG {OFFICE_IG_HANDLE}", f"ig_{OFFICE_IG_USERNAME}", fetch_ig, OFFICE_IG_USERNAME,
         ["name", "bio", "link"], ["bio"]),
    ]

    for label, key, fetch, want_user, cmp_fields, scan_fields in sources:
        live, err = fetch()
        if err:
            skipped.append({"media": label, "reason": err})
            print(f"  {'❌' if require_live else '⏭ '} {label}: {err}"
                  + ("（--require-live なので赤にします）" if require_live else ""))
            continue

        # トークンが別アカウントを指していたら、以降の検査は全部無意味になる
        got_user = (live.get("username") or "").lstrip("@")
        if got_user and got_user.lower() != want_user.lower():
            violations.append({
                "where": f"{label} / username",
                "reason": f"トークンが別アカウント（@{got_user}）を指している",
                "hit": f"期待 @{want_user} / 実際 @{got_user}"})

        for f in scan_fields:
            if f == "pinned" and not live.get("pinned"):
                # 取得できていないだけなのを「違反なし」と誤読しないための死角検知
                skipped.append({"media": label,
                                "reason": "固定ポスト本文を取得できなかった（番犬の主目的なので要調査）"})
                continue
            ng, warn = split_warn(scan(live.get(f, ""), f"{label} / {f}"))
            violations += ng
            warns += warn
        # 過去投稿のキャプションはAPIで編集できない（＝直せない）。
        # 赤にすると番犬が永久に鳴きやまなくなるので warn 扱いにする。
        for c in live.get("captions", []):
            warns += scan(c["caption"], f"{label} / 投稿 {c['permalink']}")
        diffs += compare(label, live, canon.get(key, {}), cmp_fields)

        print(f"  ✅ {label}: 取得OK（@{got_user or '?'}）"
              + (f" 固定ポスト {len(live.get('pinned', ''))}字" if live.get("pinned") else ""))
        for f in dict.fromkeys(cmp_fields + scan_fields):
            if live.get(f):
                print(f"     [{f}] {live[f][:70].replace(chr(10), ' / ')}")

    # 自動取得できない媒体は毎回チェックリストとして出すだけ（赤にはしない）
    manual = [
        "IG @taitanblog（個人アカウント／Graph API 対象外）: 表示名・bio・リンク・ハイライト名",
        "X / Threads の「固定」状態そのもの（固定APIが存在しないため自動判定不可）",
    ]

    # 同じ媒体が「トークン無し」と「固定ポストが取れない」で二重に入りうるので、
    # 「未取得 N媒体」は媒体単位で数える
    skipped_media = sorted({s["media"] for s in skipped})

    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump({"violations": violations, "warn": warns, "diffs": diffs,
                   "canon": canon_problems, "skipped": skipped,
                   "skipped_media": skipped_media, "require_live": require_live,
                   "manual": manual},
                  f, ensure_ascii=False, indent=1)

    print(f"\n[結果] 禁止パターン={len(violations)} 正本との乖離={len(diffs)} "
          f"正本・反映スクリプトの問題={len(canon_problems)} "
          f"警告(過去投稿)={len(warns)} 取得スキップ={len(skipped)} → {REPORT_FILE}")
    for p in canon_problems:
        print(f"  ❌ {p['where']}: {p['reason']}" + (f"\n     → {p['hit']}" if p["hit"] else ""))
    for v in violations:
        print(f"  ❌ {v['where']}: {v['reason']}\n     → {v['hit']}")
    for w in warns:
        print(f"  ⚠️ (過去投稿・API編集不可) {w['where']}: {w['reason']}\n     → {w['hit']}")
    for d in diffs:
        print(f"  ⚠️ {d['where']} が正本と不一致")
        print(f"     正本: {d['canonical'][:80]!r}")
        print(f"     実物: {d['live'][:80]!r}")
    if skipped:
        print(f"\n[取得できなかった媒体 {len(skipped_media)}件]"
              "（この回はここを一切検査していない）")
        for s in skipped:
            print(f"  {'❌' if require_live else '⏭ '} {s['media']}: {s['reason']}")
    print("\n[手動確認]")
    for m in manual:
        print(f"  - {m}")

    # --require-live のときは「未取得＝検査していない」を赤にする。
    # Secrets 切れ・トークン失効で番犬が緑のまま何も見ていない状態を防ぐのが目的。
    live_missing = require_live and bool(skipped)
    if live_missing:
        print(f"\n❌ --require-live: {len(skipped_media)}媒体を取得できませんでした"
              f"（{', '.join(skipped_media)}）"
              "\n   トークン／Secrets を確認してください。取得できていない媒体は"
              "「違反が無い」ではなく「見ていない」です。")

    if violations or diffs or canon_problems or live_missing:
        sys.exit(1)

    if skipped:
        # 「ローカルで緑になったから直った」の誤読を生まないための文言。
        # 全媒体を取得できた回だけが「違反なし ✅」と言える（2026-08-24）
        print(f"\n取得できた媒体には違反なし（未取得 {len(skipped_media)}媒体: "
              f"{', '.join(skipped_media)}）⚠️")
        print("   → 未取得の媒体は検査していません。全媒体を検査するには"
              " トークンを設定して --require-live を付けて実行してください。")
        return 0
    print("\nプロフィール・固定ポストに違反なし ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
