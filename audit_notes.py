#!/usr/bin/env python3
"""Audit all published notes for missing tags and missing local images."""
import json
import os
import re
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
ART_DIR = BASE / "blog/articles_note"
IMG_DIR = BASE / "blog/images"
URLNAME = "taitan_118"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


# Step 1: get all published notes
all_notes = []
seen_titles = set()
for page in range(1, 12):
    try:
        d = fetch(f"https://note.com/api/v2/creators/{URLNAME}/contents?kind=note&page={page}")
    except Exception as e:
        print(f"page {page} fail: {e}")
        break
    notes = d.get("data", {}).get("contents", [])
    if not notes:
        break
    all_notes.extend(notes)
    if d.get("data", {}).get("isLastPage"):
        break
    time.sleep(0.3)
print(f"total published: {len(all_notes)}")

# Step 2: dedupe by title (some have duplicate keys due to test posts)
unique = {}
for n in all_notes:
    title = n.get("name", "").strip()
    key = n.get("key")
    if title not in unique or unique[title]["created_at"] < n.get("created_at", ""):
        unique[title] = {"key": key, "title": title, "created_at": n.get("created_at", ""), "eyecatch": n.get("eyecatch", "")}
print(f"unique titles: {len(unique)}")

# Step 3: check hashtags for each via v3
no_tags = []
for title, info in unique.items():
    try:
        d = fetch(f"https://note.com/api/v3/notes/{info['key']}")
        tags = [h.get("hashtag", {}).get("name") for h in d.get("data", {}).get("hashtag_notes", [])]
        info["tags"] = tags
        if len(tags) == 0:
            no_tags.append(info)
    except Exception as e:
        print(f"  v3 fail {info['key']}: {e}")
    time.sleep(0.2)

print(f"\n=== TAG-LESS NOTES ({len(no_tags)}) ===")
for info in no_tags:
    print(f"  {info['key']} | {info['title'][:60]}")

# Step 4: match to local files
local_files = list(ART_DIR.glob("*.md"))
print(f"\n=== LOCAL FILES ({len(local_files)}) ===")

# Step 5: missing images
print("\n=== ARTICLES WITHOUT LOCAL IMAGE ===")
for fp in sorted(local_files):
    key = fp.stem  # e.g. "01_ライバー始め方"
    img = IMG_DIR / f"{key}.png"
    if not img.exists():
        # match to published title
        m = re.match(r"\d+_(.+)", key)
        slug = m.group(1) if m else key
        with open(fp, encoding="utf-8") as f:
            for line in f:
                if line.startswith("# "):
                    title = line.lstrip("# ").strip()
                    break
            else:
                title = ""
        # find matching published note
        published_key = None
        for ptitle, info in unique.items():
            if slug in ptitle or ptitle[:20] in title:
                published_key = info["key"]
                break
        marker = f"published={published_key}" if published_key else "NOT_PUBLISHED"
        print(f"  ❌ {key}  [{marker}]")

# Save results
out = BASE / "data/audit_result.json"
out.write_text(json.dumps({
    "no_tags": no_tags,
    "all_unique": list(unique.values()),
}, ensure_ascii=False, indent=2))
print(f"\n結果: {out}")
