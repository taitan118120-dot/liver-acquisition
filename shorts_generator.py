#!/usr/bin/env python3
"""
Note記事 → TikTok / YouTube Shorts スクリプト自動変換ツール v3

使い方:
  python3 shorts_generator.py                    # 全記事から生成
  python3 shorts_generator.py --article 01       # 特定記事のみ
  python3 shorts_generator.py --format capcut    # CapCut JSON のみ
  python3 shorts_generator.py --list             # 生成済み一覧表示
"""

import os, re, json, glob, argparse, csv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTICLES_DIR = os.path.join(BASE_DIR, "blog", "articles_note")
OUTPUT_DIR = os.path.join(BASE_DIR, "shorts")
SCRIPTS_DIR = os.path.join(OUTPUT_DIR, "scripts")
CAPCUT_DIR = os.path.join(OUTPUT_DIR, "capcut")

CHARS_PER_SEC = 4
MAX_SEC = 50
# バズ動画パターン: 具体性 + 緊急性 + 行動コスト低
CTA = "プロフのLINE追加で無料診断プレゼント中！今だけ"

# バズ動画のフック語録（実データ分析済み）
VIRAL_HOOKS = {
    "secret":    ["9割が知らない{kw}の裏側", "{kw}で損する人の共通点", "誰も教えてくれない{kw}の真実"],
    "question":  ["{kw}って本当に稼げるの？", "え、{kw}でこんなに稼げるの？", "知らないと後悔する{kw}の話"],
    "number":    ["{kw}でまさかの月{n}", "{kw}でこの数字はヤバい", "{kw}の現実、数字で見せる"],
    "warning":   ["これ知らないと{kw}失敗する", "{kw}でやりがちなミス3つ", "{kw}始める前に絶対見て"],
    "countdown": ["失敗しない{kw}のコツTOP3", "{kw}勝ち組だけがやってるTOP3", "知ってるだけで得する{kw}TOP3"],
}

# ペルソナ別の呼びかけ
PERSONA_CALL = {
    "大学生": "大学生のキミ",
    "主婦": "ママさん",
    "男性": "男性ライバー志望の人",
    "副業": "副業探してる人",
    "顔出しなし": "顔出しNGの人",
}

# CapCut スタイル (tzunda-v1: 掛け合い型統一)
# font/sec は新スキーマでも使う。color/bg は bg_preset に置換済み。
STYLES = {
    "hook":     {"font": 86, "sec": 3.2, "bg_preset": "gradient_pink"},
    "point":    {"font": 78, "sec": 3.2, "bg_preset": "navy"},
    "number":   {"font": 96, "sec": 3.0, "bg_preset": "navy"},
    "compare":  {"font": 78, "sec": 3.0, "bg_preset": "gradient_cool"},
    "cta":      {"font": 72, "sec": 3.5, "bg_preset": "cta_pink"},
    "dialogue": {"font": 82, "sec": 2.8, "bg_preset": "navy"},
}

# 話者規格 (canonical keys: zunda / metan)
SPEAKER_SIDE = {"zunda": "left", "metan": "right"}

# 数字/順位を自動で emphasis に吸い出す正規表現
import re as _emph_re
EMPH_RE = _emph_re.compile(r"(第\d+位|\d+[\d,]*(?:万円|円|%|人|時間|ヶ月|倍)|①|②|③|④|⑤)")

def _auto_emphasis(text):
    out, seen = [], set()
    for m in EMPH_RE.findall(text or ""):
        if m not in seen:
            seen.add(m); out.append(m)
    return out

# ============================================================
# ユーティリティ
# ============================================================

def clean_text(s):
    """Markdown記法を除去してプレーンテキストに"""
    s = re.sub(r"\*\*", "", s)
    s = re.sub(r"\|", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def truncate(s, n=40):
    s = s.strip()
    if len(s) <= n:
        return s
    # 句読点・助詞で自然に切る
    for i in range(n, max(n-10, 0), -1):
        if s[i] in "。、！？でにをはがもの":
            return s[:i+1]
    return s[:n]

# ============================================================
# 記事パーサー
# ============================================================

class Article:
    def __init__(self, filepath):
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.num = re.match(r"(\d+)", self.filename).group(1)
        with open(filepath, "r", encoding="utf-8") as f:
            self.raw = f.read()
        self._parse()

    def _parse(self):
        # タイトル
        m = re.search(r"^#\s+(.+)", self.raw, re.MULTILINE)
        self.title = m.group(1).strip() if m else ""

        # キーワード
        m = re.match(r"\d+_(.+)\.md", self.filename)
        self.keyword = m.group(1) if m else ""

        # フック（「」内テキスト、冒頭1000文字以内）
        self.hooks = re.findall(r"\u300c([^\u300d]+)\u300d", self.raw[:1200])

        # 見出し
        self.headings = re.findall(r"^##\s+(.+)", self.raw, re.MULTILINE)

        # --- 太字フレーズ (記事内の**...**) ---
        self.bold = list(dict.fromkeys(re.findall(r"\*\*([^*]{3,})\*\*", self.raw)))

        # --- 数字ファクト ---
        self.facts = self._extract_facts()

        # --- テーブル ---
        self.tables = self._extract_tables()

        # --- ステップ/理由系 ###見出し ---
        self.steps = re.findall(
            r"###\s+(?:ステップ|STEP|理由|方法|原因|コツ)\s*\d+[:.：\s]+(.+)",
            self.raw, re.IGNORECASE
        )

        # --- 箇条書き太字 ---
        self.bullets = re.findall(r"^[-・]\s+\*\*([^*]+)\*\*", self.raw, re.MULTILINE)

        # --- ペルソナ ---
        self.persona = None
        for key in PERSONA_CALL:
            if key in self.keyword or key in self.title:
                self.persona = key
                break

    def _extract_facts(self):
        """数字+文脈をセットで抽出。ノイズ除去つき"""
        noise_re = re.compile(r"残業|ブラック|パワハラ|プログラミング|YouTube|ブログ")
        num_re = re.compile(r"((?:月|年|時給|約|月収)?[\d,]+(?:万円|円|%|人|時間|ヶ月|倍))")
        facts = []
        for line in self.raw.split("\n"):
            if line.startswith("#") or noise_re.search(line):
                continue
            stripped = line.strip()
            if stripped.startswith("\u300c") and stripped.endswith("\u300d"):
                continue
            for m in num_re.finditer(clean_text(line)):
                val = m.group(1)
                if len(val) < 3:
                    continue
                ctx = self._extract_context(clean_text(line), m.start(), m.end())
                if ctx:
                    facts.append({"v": val, "ctx": ctx})
        # 重複除去
        seen = set()
        unique = []
        for f in facts:
            if f["v"] not in seen:
                seen.add(f["v"])
                unique.append(f)
        return unique[:20]

    def _extract_context(self, line, start, end):
        """数字を含む自然な短文を切り出す"""
        # 前方: 句読点で区切る
        pre_zone = line[max(0, start-25):start]
        for sep in ["\u3002", "\u3001", ":", "\uff1a"]:
            if sep in pre_zone:
                pre_zone = pre_zone[pre_zone.rfind(sep)+1:]
        # 後方: 句読点で区切る
        post_zone = line[end:min(len(line), end+25)]
        for sep in ["\u3002", "\u3001", "\uff08", "("]:
            if sep in post_zone:
                post_zone = post_zone[:post_zone.find(sep)]
        ctx = (pre_zone + line[start:end] + post_zone).strip()
        # 先頭の助詞で始まるゴミを除去
        ctx = re.sub(r"^[をにはがでもと、]\s*", "", ctx)
        if len(ctx) < 5:
            return None
        return truncate(ctx, 42)

    def _extract_tables(self):
        tables = []
        for block in re.findall(r"(\|.+\|(?:\n\|.+\|)+)", self.raw):
            rows = []
            for row in block.strip().split("\n"):
                if re.match(r"\|[\s\-:]+\|", row):
                    continue
                cells = [c.strip() for c in row.split("|") if c.strip()]
                if cells:
                    rows.append(cells)
            if len(rows) > 1:
                tables.append(rows)
        return tables

    def get_persona_call(self):
        return PERSONA_CALL.get(self.persona, "")

    def get_bold_answer(self, exclude_texts=None):
        """太字から「結論」っぽいフレーズを返す"""
        exclude_texts = exclude_texts or set()
        answer_words = ["月", "万", "稼", "可能", "できる", "不要", "OK", "おすすめ", "十分", "時給"]
        for b in self.bold:
            if any(w in b for w in answer_words) and b not in exclude_texts:
                return truncate(b, 38)
        for b in self.bold:
            if b not in exclude_texts:
                return truncate(b, 38)
        return None

    def get_fresh_fact(self, exclude_values=None, exclude_ctx=None):
        """使用済みの数字・文脈を避けてファクトを返す"""
        exclude_values = exclude_values or set()
        exclude_ctx = exclude_ctx or set()
        for f in self.facts:
            if f["v"] in exclude_values:
                continue
            # 文脈テキストが既存スライドと似すぎていたらスキップ
            too_similar = False
            for existing in exclude_ctx:
                # 短い方の80%以上が含まれていたら重複扱い
                shorter = min(len(f["ctx"]), len(existing))
                if shorter < 5:
                    continue
                overlap = f["ctx"][:shorter]
                if overlap in existing or existing[:shorter] in f["ctx"]:
                    too_similar = True
                    break
            if not too_similar:
                return f
        return None


# ============================================================
# スクリプトビルダー
# ============================================================

class Script:
    def __init__(self, keyword, pattern, persona=None):
        self.keyword = keyword
        self.pattern = pattern
        self.persona = persona
        self.slides = []

    def _add(self, slide_type, text, note="", speaker=None, emphasis=None, is_end_card=False, max_len=42):
        speaker = speaker or "zunda"
        slide = {
            "type": slide_type,
            "text": truncate(text, max_len),
            "note": note,
            "speaker": speaker,
            "emphasis": emphasis if emphasis is not None else _auto_emphasis(text),
            "is_end_card": is_end_card,
        }
        self.slides.append(slide)

    def hook(self, text, note="", speaker="zunda", emphasis=None):
        self._add("hook", text, note, speaker, emphasis, False, 38)
        return self

    def point(self, text, note="", speaker="metan", emphasis=None):
        self._add("point", text, note, speaker, emphasis, False, 42)
        return self

    def number(self, text, note="", speaker="metan", emphasis=None):
        self._add("number", text, note, speaker, emphasis, False, 38)
        return self

    def compare(self, text, note="", speaker="metan", emphasis=None):
        self._add("compare", text, note, speaker, emphasis, False, 42)
        return self

    def cta(self, speaker="metan"):
        """最終CTA: エンドカード扱い"""
        self._add("cta", "チャンネル登録してね！", "プロフのリンクを指差し",
                  speaker, emphasis=[], is_end_card=True, max_len=42)
        return self

    # 対話セリフ (zunda=左・聞き手、metan=右・解説役)
    def zunda(self, text, note="", emphasis=None):
        self._add("dialogue", text, note, speaker="zunda", emphasis=emphasis, max_len=42)
        return self

    def metan(self, text, note="", emphasis=None):
        self._add("dialogue", text, note, speaker="metan", emphasis=emphasis, max_len=42)
        return self

    def seconds(self):
        return sum(len(s["text"]) for s in self.slides) / CHARS_PER_SEC

    def ok(self):
        return len(self.slides) >= 4 and 12 <= self.seconds() <= MAX_SEC

    def used_values(self):
        """スライドに含まれる数字文字列のセット"""
        all_text = " ".join(s["text"] for s in self.slides)
        return set(re.findall(r"[\d,]+(?:万円|円|%|人|時間|ヶ月|倍)", all_text))

    def to_dict(self):
        return {"keyword": self.keyword, "pattern": self.pattern,
                "persona": self.persona, "slides": self.slides}


# ============================================================
# 6つの生成パターン
# ============================================================

def _kw_short(art):
    kw = re.sub(r"^ライバー", "", art.keyword) or "ライバー"
    kw = re.sub(r"^Pococha", "", kw) or kw
    kw = re.sub(r"現実$|攻略$|完全ガイド$", "", kw) or kw
    return kw[:10] if len(kw) > 10 else kw


def pat_question(art):
    """ずんだの質問 → めたん結論 → ずんだ驚き → めたん補足 → CTA"""
    out = []
    for i, h in enumerate(art.hooks[:2]):
        s = Script(art.keyword, f"質問回答{i+1}", art.persona)
        ans = art.get_bold_answer()
        if not ans:
            continue
        kw = _kw_short(art)
        s.zunda(f"めたん、{truncate(h, 22)}なのだ？", "カメラ目線で問いかけ")
        s.metan(f"それがね、答えは「{ans}」よ", "ドンと出す", emphasis=[ans])
        s.zunda(f"えっ、マジなのだ！？", "驚き顔")
        used_v = s.used_values()
        used_ctx = {sl["text"] for sl in s.slides}
        f = art.get_fresh_fact(used_v, used_ctx)
        if f:
            s.metan(f"本当よ。{f['ctx']}", "うなずきながら")
            used_ctx.add(f["ctx"])
        f2 = art.get_fresh_fact(s.used_values(), used_ctx)
        if f2 and s.seconds() < 26:
            s.zunda("他には何があるのだ？")
            s.metan(f2["ctx"])
        s.cta()
        if s.ok():
            out.append(s.to_dict())
    return out


def pat_number(art):
    """ずんだが数字を疑問 → めたん衝撃数字提示 → ずんだ反応 → めたん補強 → CTA"""
    if len(art.facts) < 2:
        return []
    s = Script(art.keyword, "数字インパクト", art.persona)
    kw = _kw_short(art)
    f1 = art.facts[0]
    s.zunda(f"めたん、{kw}って本当に稼げるのだ？", "驚いた顔")
    s.metan(f"{f1['v']} 稼げる世界よ", "ドンと出す", emphasis=[f1["v"]])
    s.zunda(f"{f1['v']}！？ ウソなのだ…", "目を見開く")
    s.metan(f"本当よ。{f1['ctx']}", "説明")
    used_v = s.used_values()
    used_ctx = {sl["text"] for sl in s.slides}
    f2 = art.get_fresh_fact(used_v, used_ctx)
    if f2:
        s.zunda("他にも凄い数字あるのだ？")
        s.metan(f2["ctx"], "指でカウント", emphasis=[f2["v"]])
    s.zunda("夢があるのだ…！")
    s.cta()
    return [s.to_dict()] if s.ok() else []


def pat_steps(art):
    """ずんだが順に質問 → めたんがステップ解説。掛け合いで進む"""
    if len(art.steps) < 3:
        return []
    s = Script(art.keyword, "ポイント紹介", art.persona)
    n = min(len(art.steps), 4)
    kw = _kw_short(art)
    marks = ["①", "②", "③", "④"]
    s.zunda(f"めたん、{kw}で大事なことって何なのだ？", "指でカウント")
    for j, step in enumerate(art.steps[:n]):
        short = truncate(clean_text(step), 26)
        mark = marks[j]
        # ずんだ→めたん の掛け合い（初回以外は「次は？」「他には？」でテンポ）
        if j == 0:
            s.metan(f"{mark} {short}", "一番大事", emphasis=[mark, short])
        else:
            prompts = ["次は何なのだ？", "他には？", "あと何があるのだ？"]
            s.zunda(prompts[(j-1) % len(prompts)])
            s.metan(f"{mark} {short}", emphasis=[mark, short])
    s.zunda(f"{n}つ覚えたのだ！", "納得顔")
    s.cta()
    return [s.to_dict()] if s.ok() else []


def pat_compare(art):
    """比較を掛け合い化: ずんだが「どっち？」→めたんが行ごとに比較 → 結論"""
    out = []
    for table in art.tables[:1]:
        if len(table) < 3:
            continue
        s = Script(art.keyword, "比較してみた", art.persona)
        header = table[0]
        if len(header) >= 3:
            s.zunda(f"{header[1]} と {header[2]}、どっちがいいのだ？", "手を左右に")
        else:
            s.zunda(f"{art.keyword}って比較するとどうなのだ？", "手を横に振る")
        rows = [r for r in table[1:5] if len(r) >= 2]
        for k, row in enumerate(rows[:3]):
            if len(row) >= 3:
                if k == 0:
                    s.metan(f"{row[0]}なら {row[1]} vs {row[2]} よ", emphasis=[row[0]])
                else:
                    s.zunda("他には？")
                    s.metan(f"{row[0]}なら {row[1]} vs {row[2]}", emphasis=[row[0]])
            else:
                s.metan(f"{row[0]} → {row[1]}", emphasis=[row[0]])
        s.zunda("どっちを選べばいいのだ？")
        if len(rows) > 0 and len(rows[0]) >= 3:
            verdict = rows[0][2]
            s.metan(f"結論は「{verdict}」よ", "強調", emphasis=["結論", verdict])
        s.cta()
        if s.ok():
            out.append(s.to_dict())
    return out


def pat_top3(art):
    """TOP3 を掛け合いカウントダウン: ずんだが順位を聞く → めたんが答える"""
    items = art.bullets or art.steps
    if len(items) < 3:
        return []
    s = Script(art.keyword, "TOP3", art.persona)
    kw = _kw_short(art)
    s.zunda(f"めたん、{kw}の勝ちパターンTOP3が知りたいのだ！", "指を立てて強調")
    top = items[:3]
    for k, item in enumerate(reversed(top)):
        short = truncate(clean_text(item), 22)
        rank = 3 - k
        rank_label = f"第{rank}位"
        if rank == 3:
            s.zunda("まず第3位は何なのだ？")
        elif rank == 2:
            s.zunda("じゃあ第2位は？")
        else:
            s.zunda("…そして第1位は？", "溜めて")
        s.metan(f"{rank_label}は「{short}」よ",
                "ドンと発表" if rank == 1 else "",
                emphasis=[rank_label, short])
    s.zunda("全部メモしたのだ！", "納得")
    s.cta()
    return [s.to_dict()] if s.ok() else []


def pat_myth(art):
    """誤解を掛け合いで否定: ずんだが信じてる → めたんが真実"""
    myth = [h for h in art.hooks if any(w in h for w in ["無理", "ない", "できない", "ほんと", "本当", "不安", "つらい"])]
    if not myth:
        return []
    s = Script(art.keyword, "よくある誤解", art.persona)
    myth_short = truncate(myth[0], 18)
    s.zunda(f"めたん、「{myth_short}」って聞いたのだ…", "呆れ顔")
    s.metan("それ、もう古いわよ", "手でバツ")
    truth_words = ["できる", "可能", "稼げ", "大丈夫", "OK", "十分", "不要"]
    truth = None
    for b in art.bold:
        if any(w in b for w in truth_words):
            truth = b
            break
    if not truth:
        return []
    s.metan(f"本当は「{truth}」のよ", "力強く", emphasis=[truth])
    s.zunda(f"マジなのだ！？ 信じられないのだ", "驚き")
    used_ctx = {sl["text"] for sl in s.slides}
    f = art.get_fresh_fact(s.used_values(), used_ctx)
    if f:
        s.metan(f["ctx"], "追い打ち")
    s.cta()
    return [s.to_dict()] if s.ok() else []


def _clean_fact_ctx(ctx, max_len=28):
    """ファクトの文脈テキストを一人称トーンに整える (文中打ち切り対策)"""
    ctx = clean_text(ctx).strip()
    # 途中で切れている助詞を除去
    ctx = re.sub(r"[をにはがでもと、]\s*$", "", ctx)
    # 句読点で自然に切る
    if len(ctx) > max_len:
        for i in range(max_len, max(max_len - 8, 0), -1):
            if i < len(ctx) and ctx[i] in "。、！？":
                return ctx[:i]
        ctx = ctx[:max_len]
    return ctx


def pat_dialogue(art):
    """ずんだもん×四国めたん 対話形式解説動画 (転職ずんだ風フォーマット)

    構成 (全7-9セリフ、25-35秒):
    1. ずんだもん: 疑問フック
    2. めたん: ショッキング結論
    3. ずんだもん: 驚きリアクション
    4. めたん: 数字で裏付け
    5. ずんだもん: 追加質問
    6. めたん: 2つ目のポイント
    7. ずんだもん: 納得リアクション
    8. めたん: CTA
    """
    if len(art.facts) < 1:
        return []
    s = Script(art.keyword, "対話解説", art.persona)

    topic = _kw_short(art)
    f1 = art.facts[0]
    ctx1 = _clean_fact_ctx(f1["ctx"])

    s.zunda(f"めたん、{topic}って実際どうなのだ？")
    s.metan(f"それがね、{f1['v']}稼げる世界なのよ", emphasis=[f1["v"]])
    s.zunda(f"{f1['v']}…！？ マジなのだ？", emphasis=[f1["v"]])
    s.metan(f"本当よ。{ctx1}")

    f2 = art.get_fresh_fact({f1["v"]}, {f1["ctx"]})
    if f2:
        ctx2 = _clean_fact_ctx(f2["ctx"])
        s.zunda("他にもコツあるのだ？")
        s.metan(f"あるわよ。{ctx2}", emphasis=[f2["v"]] if f2.get("v") else None)
    elif art.bullets:
        bullet = _clean_fact_ctx(art.bullets[0])
        s.zunda("始めるのに必要なの？")
        s.metan(f"{bullet}さえあれば十分よ")

    s.zunda("思ったよりいけそうなのだ！")
    s.cta()

    return [s.to_dict()] if len(s.slides) >= 7 and s.seconds() <= MAX_SEC else []


GENERATORS = [pat_question, pat_number, pat_steps, pat_compare, pat_top3, pat_myth, pat_dialogue]

# ============================================================
# 出力
# ============================================================

EMOJI = {"hook": "🔥", "point": "💬", "number": "💰", "compare": "⚡", "cta": "👉"}
LABEL = {"hook": "HOOK", "point": "BODY", "number": "数字", "compare": "比較", "cta": "CTA"}

def to_markdown(sc, title):
    lines = []
    kw, pat = sc["keyword"], sc["pattern"]
    tag = f" [{sc['persona']}向け]" if sc.get("persona") else ""
    total = sum(len(s["text"]) for s in sc["slides"])
    sec = total / CHARS_PER_SEC

    lines.append(f"# {kw}｜{pat}{tag}")
    lines.append(f"元記事: {title}")
    lines.append(f"尺: 約{sec:.0f}秒 / {len(sc['slides'])}スライド")
    lines.append("")

    for i, sl in enumerate(sc["slides"], 1):
        e = EMOJI.get(sl["type"], "📌")
        lab = LABEL.get(sl["type"], "??")
        lines.append(f"{e} {i}. [{lab}] {sl['text']}")
        if sl.get("note"):
            lines.append(f"   → {sl['note']}")

    lines.append("")
    lines.append("--- コピペ用テロップ ---")
    for sl in sc["slides"]:
        lines.append(sl["text"])

    lines.append("")
    tags = ["ライバー", "ライブ配信", "Pococha", "副業", "在宅ワーク", kw]
    if sc.get("persona"):
        tags.insert(0, sc["persona"])
    lines.append(" ".join(f"#{t}" for t in dict.fromkeys(tags)))
    return "\n".join(lines)


def to_capcut(sc):
    """tzunda-v1 スキーマで出力"""
    segs = []
    t = 0.0
    for sl in sc["slides"]:
        st = STYLES.get(sl["type"], STYLES["point"])
        speaker = sl.get("speaker", "zunda")
        side = SPEAKER_SIDE.get(speaker, "left")
        is_end = bool(sl.get("is_end_card", False))
        bg_preset = "cta_pink" if is_end else st["bg_preset"]
        seg = {
            "text": sl["text"],
            "start": round(t, 2),
            "end": round(t + st["sec"], 2),
            "font_size": st["font"],
            "position": "center",
            "type": sl["type"],
            "speaker": speaker,
            "side": side,
            "emphasis": sl.get("emphasis") or [],
            "bg_preset": bg_preset,
            "is_end_card": is_end,
        }
        segs.append(seg)
        t += st["sec"]
    tags = f"#ライバー #{sc['keyword']} #Pococha #副業 #ライブ配信 #ずんだもん #四国めたん"
    return {
        "style_version": "tzunda-v1",
        "keyword": sc["keyword"],
        "pattern": sc["pattern"],
        "persona": sc.get("persona"),
        "duration": round(t, 2),
        "slides": len(segs),
        "segments": segs,
        "hashtags": tags,
    }


# ============================================================
# メイン
# ============================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--article", type=str)
    ap.add_argument("--format", choices=["markdown", "capcut", "both"], default="both")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        p = os.path.join(OUTPUT_DIR, "scripts_index.csv")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f: print(f.read())
        else:
            print("未生成")
        return

    os.makedirs(SCRIPTS_DIR, exist_ok=True)
    os.makedirs(CAPCUT_DIR, exist_ok=True)

    files = sorted(glob.glob(os.path.join(ARTICLES_DIR, "*.md")))
    if args.article:
        files = [f for f in files if os.path.basename(f).startswith(args.article)]
    if not files:
        print("対象記事なし"); return

    print(f"\n{'='*55}")
    print(f"  TikTok / Shorts スクリプト生成 v3")
    print(f"{'='*55}")
    print(f"  対象: {len(files)} 記事\n")

    rows = []
    for fp in files:
        art = Article(fp)
        scripts = []
        for g in GENERATORS:
            scripts.extend(g(art))
        if not scripts:
            print(f"  -- {art.filename} → スキップ"); continue

        print(f"  ✅ {art.filename} → {len(scripts)}本")
        for sc in scripts:
            safe = sc["pattern"].replace("/", "_")
            base = f"{art.num}_{sc['keyword']}_{safe}"
            if args.format in ("markdown", "both"):
                with open(os.path.join(SCRIPTS_DIR, f"{base}.md"), "w", encoding="utf-8") as f:
                    f.write(to_markdown(sc, art.title))
            if args.format in ("capcut", "both"):
                with open(os.path.join(CAPCUT_DIR, f"{base}.json"), "w", encoding="utf-8") as f:
                    json.dump(to_capcut(sc), f, ensure_ascii=False, indent=2)
            total = sum(len(s["text"]) for s in sc["slides"])
            rows.append({"num": art.num, "keyword": sc["keyword"], "pattern": sc["pattern"],
                         "persona": sc.get("persona") or "", "sec": f"{total/CHARS_PER_SEC:.0f}",
                         "slides": str(len(sc["slides"])), "file": f"{base}.md"})

    # CSV
    with open(os.path.join(OUTPUT_DIR, "scripts_index.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["num","keyword","pattern","persona","sec","slides","file"])
        w.writeheader(); w.writerows(rows)

    # サマリー
    print(f"\n{'='*55}")
    print(f"  完了: {len(rows)} 本")
    print(f"{'='*55}")
    print(f"  shorts/scripts/  撮影スクリプト")
    print(f"  shorts/capcut/   テロップJSON")
    print(f"  shorts/scripts_index.csv  管理台帳\n")

    # 集計
    pc, rc = {}, {}
    for r in rows:
        p = re.sub(r"\d+$", "", r["pattern"])
        pc[p] = pc.get(p, 0) + 1
        q = r["persona"] or "汎用"
        rc[q] = rc.get(q, 0) + 1
    print("  パターン別:")
    for k, v in sorted(pc.items(), key=lambda x: -x[1]): print(f"    {k}: {v}本")
    print("\n  ペルソナ別:")
    for k, v in sorted(rc.items(), key=lambda x: -x[1]): print(f"    {k}: {v}本")
    print()


if __name__ == "__main__":
    main()
