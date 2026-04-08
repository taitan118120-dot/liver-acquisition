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
CTA = "詳しくはプロフのリンクから！LINEで無料相談できるよ"

# ペルソナ別の呼びかけ
PERSONA_CALL = {
    "大学生": "大学生のキミ",
    "主婦": "ママさん",
    "男性": "男性ライバー志望の人",
    "副業": "副業探してる人",
    "顔出しなし": "顔出しNGの人",
}

# CapCut スタイル
STYLES = {
    "hook":    {"font": 72, "color": "#FFFFFF", "bg": "#FF0050", "pos": "center",  "sec": 3.5},
    "point":   {"font": 52, "color": "#FFFFFF", "bg": "#1A1A2E", "pos": "center",  "sec": 4.0},
    "number":  {"font": 80, "color": "#FFE135", "bg": "#1A1A2E", "pos": "center",  "sec": 3.5},
    "compare": {"font": 48, "color": "#00F5FF", "bg": "#1A1A2E", "pos": "center",  "sec": 3.5},
    "cta":     {"font": 56, "color": "#FFFFFF", "bg": "#FF0050", "pos": "bottom",  "sec": 4.0},
}

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

    def hook(self, text, note=""):
        self.slides.append({"type": "hook", "text": truncate(text, 38), "note": note})
        return self

    def point(self, text, note=""):
        self.slides.append({"type": "point", "text": truncate(text, 42), "note": note})
        return self

    def number(self, text, note=""):
        self.slides.append({"type": "number", "text": truncate(text, 38), "note": note})
        return self

    def compare(self, text, note=""):
        self.slides.append({"type": "compare", "text": truncate(text, 42), "note": note})
        return self

    def cta(self):
        self.slides.append({"type": "cta", "text": CTA, "note": "プロフのリンクを指差し"})
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

def pat_question(art):
    """読者の疑問 → 一言で結論 → 数字で裏付け → CTA"""
    out = []
    for i, h in enumerate(art.hooks[:2]):
        s = Script(art.keyword, f"質問回答{i+1}", art.persona)
        s.hook(h, "カメラ目線で問いかけ")
        # 結論
        ans = art.get_bold_answer()
        if not ans:
            continue
        s.number(ans, "ドンと出す")
        # 裏付けファクト (結論テキストと被らないものを探す)
        used_v = s.used_values()
        used_ctx = {sl["text"] for sl in s.slides}
        f = art.get_fresh_fact(used_v, used_ctx)
        if f:
            s.point(f["ctx"], "うなずきながら")
            used_v = s.used_values()
            used_ctx.add(f["ctx"])
        # もう1つ補足
        f2 = art.get_fresh_fact(used_v, used_ctx)
        if f2 and s.seconds() < 28:
            s.point(f2["ctx"])
        s.cta()
        if s.ok():
            out.append(s.to_dict())
    return out


def pat_number(art):
    """衝撃数字フック → 文脈 → 追加数字 → CTA"""
    if len(art.facts) < 2:
        return []
    s = Script(art.keyword, "数字インパクト", art.persona)
    # フック: ペルソナ呼びかけ or 自然なテーマ文
    call = art.get_persona_call()
    # キーワードを自然な日本語にする
    kw_display = art.keyword
    # 「ライバー」接頭辞を除去して助詞でつなげる
    kw_display = re.sub(r"^ライバー", "", kw_display)
    kw_display = re.sub(r"^Pococha", "", kw_display)
    if not kw_display:
        kw_display = "ライバー"
    # 「収入現実」→「収入」のように末尾の冗長語を整理
    kw_display = re.sub(r"現実$|攻略$|完全ガイド$", "", kw_display) or kw_display
    if call:
        s.hook(f"{call}、この数字ヤバい", "驚いた顔")
    else:
        s.hook(f"{kw_display}の現実、知ってる？", "真剣な顔")
    # メイン数字
    f1 = art.facts[0]
    s.number(f1["v"], "大きく手を広げる")
    s.point(f1["ctx"], "説明")
    # サブ数字 (被らないやつ)
    used_v = s.used_values()
    used_ctx = {sl["text"] for sl in s.slides}
    f2 = art.get_fresh_fact(used_v, used_ctx)
    if f2:
        s.number(f2["ctx"], "指でカウント")
    s.cta()
    return [s.to_dict()] if s.ok() else []


def pat_steps(art):
    """N個のステップ/理由をテンポよく"""
    if len(art.steps) < 3:
        return []
    s = Script(art.keyword, "ポイント紹介", art.persona)
    n = min(len(art.steps), 4)
    # フック
    call = art.get_persona_call()
    if call:
        s.hook(f"{call}！{n}つだけ覚えて", "指でカウント")
    else:
        s.hook(f"{art.keyword}、{n}つだけ覚えて！", "指でカウント")
    # 各ステップ (短く刈り込む)
    for j, step in enumerate(art.steps[:n]):
        short = truncate(clean_text(step), 28)
        if j == 0:
            s.number(f"① {short}", "一番大事")
        else:
            marks = ["②", "③", "④"]
            s.point(f"{marks[j-1]} {short}")
    s.cta()
    return [s.to_dict()] if s.ok() else []


def pat_compare(art):
    """テーブルデータを比較形式で"""
    out = []
    for table in art.tables[:1]:
        if len(table) < 3:
            continue
        s = Script(art.keyword, "比較してみた", art.persona)
        # ヘッダから比較軸を作る
        header = table[0]
        if len(header) >= 3:
            s.hook(f"{header[1]} vs {header[2]}、どっちがいい？", "手を左右に")
        else:
            s.hook(f"{art.keyword}、比較すると全然違う", "手を横に振る")
        # データ行
        for row in table[1:4]:
            if len(row) >= 3:
                s.compare(f"{row[0]}：{row[1]} vs {row[2]}")
            elif len(row) >= 2:
                s.compare(f"{row[0]} → {row[1]}")
        s.cta()
        if s.ok():
            out.append(s.to_dict())
    return out


def pat_top3(art):
    """TOP3 カウントダウン"""
    items = art.bullets or art.steps
    if len(items) < 3:
        return []
    s = Script(art.keyword, "TOP3", art.persona)
    call = art.get_persona_call()
    if call:
        s.hook(f"{call}必見！{art.keyword}のコツTOP3", "テンション高め")
    else:
        s.hook(f"{art.keyword}のコツTOP3！", "テンション高め")
    top = items[:3]
    for k, item in enumerate(reversed(top)):
        short = truncate(clean_text(item), 28)
        rank = 3 - k
        if rank == 1:
            s.number(f"第1位：{short}", "一番大事！")
        else:
            s.point(f"第{rank}位：{short}")
    s.cta()
    return [s.to_dict()] if s.ok() else []


def pat_myth(art):
    """誤解を否定 → 真実"""
    myth = [h for h in art.hooks if any(w in h for w in ["無理", "ない", "できない", "ほんと", "本当", "不安", "つらい"])]
    if not myth:
        return []
    s = Script(art.keyword, "よくある誤解", art.persona)
    s.hook(myth[0], "共感の表情")
    s.point("って思ってない？実はそれ間違い！", "手でバツ→マル")
    # 正解
    truth_words = ["できる", "可能", "稼げ", "大丈夫", "OK", "十分", "不要"]
    truth = None
    for b in art.bold:
        if any(w in b for w in truth_words):
            truth = b
            break
    if truth:
        s.number(truth, "力強くうなずく")
    else:
        return []
    # 補足ファクト (正解テキストと被らないもの)
    used_ctx = {sl["text"] for sl in s.slides}
    f = art.get_fresh_fact(s.used_values(), used_ctx)
    if f:
        s.point(f["ctx"], "追い打ち")
    s.cta()
    return [s.to_dict()] if s.ok() else []


GENERATORS = [pat_question, pat_number, pat_steps, pat_compare, pat_top3, pat_myth]

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
    segs = []
    t = 0.0
    for sl in sc["slides"]:
        st = STYLES.get(sl["type"], STYLES["point"])
        segs.append({
            "text": sl["text"], "start": round(t, 2), "end": round(t + st["sec"], 2),
            "font_size": st["font"], "color": st["color"],
            "bg_color": st["bg"], "position": st["pos"], "type": sl["type"],
        })
        t += st["sec"]
    tags = f"#ライバー #{sc['keyword']} #Pococha #副業 #ライブ配信"
    return {"keyword": sc["keyword"], "pattern": sc["pattern"],
            "persona": sc.get("persona"), "duration": round(t, 2),
            "slides": len(segs), "segments": segs, "hashtags": tags}


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
