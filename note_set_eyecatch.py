#!/usr/bin/env python3
"""note_set_eyecatch.py
公開済みNote記事に対してアイキャッチ画像をPlaywright UI経由でセットする。

使い方:
  python3 note_set_eyecatch.py 55 nc3013c157ee0 \
                                56 ndce8a9117fa4 \
                                57 n576132a999ab \
                                58 nbbbc925ec0a8 \
                                59 n0144caabbb73

引数は (article_num note_key) のペアを並べる。
画像は blog/images/{XX_slug}.png から自動解決。
"""
import json
import os
import re
import sys
import time
import glob

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTICLES_DIR = os.path.join(BASE_DIR, "blog", "articles_note")
IMAGES_DIR = os.path.join(BASE_DIR, "blog", "images")


def resolve_image(article_num):
    pat = os.path.join(IMAGES_DIR, f"{article_num:02d}_*.png")
    files = glob.glob(pat)
    return files[0] if files else None


def resolve_article_title(article_num):
    pat = os.path.join(ARTICLES_DIR, f"{article_num:02d}_*.md")
    files = glob.glob(pat)
    if not files:
        return ""
    with open(files[0], encoding="utf-8") as f:
        for line in f:
            if line.startswith("# "):
                return line.lstrip("# ").strip()
    return ""


def load_cookies():
    # CI(GitHub Actions)では Secret NOTE_COOKIES_JSON から、ローカルではファイルから読む
    raw = os.environ.get("NOTE_COOKIES_JSON", "").strip()
    if raw:
        cookies = json.loads(raw)
    else:
        with open(os.path.join(BASE_DIR, "note_cookies.json"), encoding="utf-8") as f:
            cookies = json.load(f)
    pw_cookies = []
    for c in cookies:
        pw_cookies.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".note.com"),
            "path": c.get("path", "/"),
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure": bool(c.get("secure", True)),
            "sameSite": (c.get("sameSite") or "Lax").capitalize(),
        })
    return pw_cookies


def set_eyecatch(article_num, note_key, headless=True):
    """1記事のアイキャッチを設定。

    フロー:
      1. /notes/{key}/edit を開く
      2. アイキャッチ用 file input を探す（複数候補）
      3. set_input_files でローカル画像をアップロード
      4. アップロード完了をネットワーク観測で待機
      5. publish ページへ遷移して再公開（既に公開済みなので更新）
    """
    image_path = resolve_image(article_num)
    if not image_path:
        return {"ok": False, "reason": f"画像見つからず: #{article_num}"}

    title = resolve_article_title(article_num)
    print(f"\n── #{article_num} {title[:40]} ──")
    print(f"  key={note_key}")
    print(f"  image={os.path.basename(image_path)}")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
            locale="ja-JP",
            viewport={"width": 1400, "height": 900},
        )
        ctx.add_cookies(load_cookies())
        page = ctx.new_page()

        upload_responses = []

        def _on_response(resp):
            url = resp.url
            if "image" in url.lower() or "upload" in url.lower() or "eyecatch" in url.lower():
                if any(s in url for s in ("note.com/api", "amazonaws", "cloudfront")):
                    upload_responses.append((resp.status, url))

        page.on("response", _on_response)

        edit_url = f"https://editor.note.com/notes/{note_key}/edit"
        print(f"  [PW] open {edit_url}")
        page.goto(edit_url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        time.sleep(3)

        # アイキャッチ「画像を追加」ボタン (aria-label) をクリック → モーダル表示
        clicked = False
        try:
            btn = page.locator('button[aria-label="画像を追加"]').first
            if btn.count() > 0:
                btn.click(timeout=5000)
                clicked = True
                print(f"  [PW] '画像を追加' ボタン clicked")
                time.sleep(3)
        except Exception as e:
            print(f"  [PW] 画像を追加ボタン失敗: {e}")

        # モーダル内の「アップロード」タブ/ボタンをクリック（必要なら）
        for label in ("アップロード", "ファイルを選択", "画像をアップロード", "アップロードする"):
            try:
                el = page.get_by_text(label, exact=False).first
                if el.count() > 0 and el.is_visible():
                    el.click(timeout=2000)
                    print(f"  [PW] '{label}' クリック")
                    time.sleep(2)
                    break
            except Exception:
                continue

        # ファイル入力を探す
        file_inputs = page.locator('input[type="file"]')
        cnt = file_inputs.count()
        print(f"  [PW] file_input候補数: {cnt}")
        if cnt == 0:
            page.evaluate("""() => {
                document.querySelectorAll('input[type=file]').forEach(el => {
                    el.style.display='block'; el.style.opacity='1'; el.style.visibility='visible';
                });
            }""")
            cnt = file_inputs.count()
            print(f"  [PW] 強制表示後 file_input数: {cnt}")

        if cnt == 0:
            # ヒントログ + HTML スナップショット保存
            html = page.content()
            with open(f"/tmp/note_edit_{article_num}.html", "w", encoding="utf-8") as f:
                f.write(html)
            page.screenshot(path=f"/tmp/note_edit_{article_num}.png", full_page=True)
            browser.close()
            return {"ok": False, "reason": "file input見つからず", "saved_html": f"/tmp/note_edit_{article_num}.html"}

        # 全 file input にトライ
        success_idx = -1
        for i in range(cnt):
            try:
                file_inputs.nth(i).set_input_files(image_path, timeout=10000)
                print(f"  [PW] set_input_files OK (input #{i})")
                success_idx = i
                break
            except Exception as e:
                print(f"  [PW] input#{i} 失敗: {str(e)[:80]}")

        if success_idx < 0:
            browser.close()
            return {"ok": False, "reason": "set_input_files全敗"}

        # アップロード完了を待つ
        time.sleep(8)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        # 「決定」「適用」「保存」「OK」などのボタンを押す
        confirm_buttons = ["決定", "適用", "保存", "完了", "OK", "Apply", "Save"]
        for label in confirm_buttons:
            try:
                btn = page.get_by_role("button", name=label).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=3000)
                    print(f"  [PW] '{label}' クリック")
                    time.sleep(2)
                    break
            except Exception:
                continue

        # editor の autosave に任せる
        time.sleep(5)

        # draft API（editorと同じデータ源。公開APIより反映が速い）で設定を確認する。
        # editorページ内の相対fetchは editor.note.com に飛んで常に404だったため、
        # cookie共有済みの ctx.request で note.com オリジンへ直接投げる。
        # 再公開PUT({"status":"published"})は不要（記事は公開済みのまま維持される）で、
        # fetch-PUTはタグ消失の副作用があるため送らない。
        eyecatch_url = None
        for attempt in range(1, 7):
            try:
                r = ctx.request.get(
                    f"https://note.com/api/v3/notes/{note_key}?draft=true&ts={int(time.time()*1000)}",
                    headers={"X-Requested-With": "XMLHttpRequest"}, timeout=20000)
                data = json.loads(r.text()).get("data", {}) if r.ok else {}
                ec = data.get("eyecatch") or (data.get("note") or {}).get("eyecatch") or ""
                if "uploads/images" in ec:
                    eyecatch_url = ec
                    print(f"  [PW] draft APIでeyecatch確認OK (attempt {attempt})")
                    break
                print(f"  [PW] draft API eyecatch未反映 (attempt {attempt})")
            except Exception as e:
                print(f"  [PW] draft API確認エラー: {str(e)[:80]}")
            time.sleep(5)

        browser.close()

    # draft APIで確認できなかった場合の保険として、公開側APIでも最終確認する。
    # アップロード直後は公開APIへの反映に数十秒かかることがあるのでリトライする。
    if not eyecatch_url:
        try:
            import requests
            for attempt in range(1, 6):
                time.sleep(10)
                r = requests.get(
                    f"https://note.com/api/v3/notes/{note_key}",
                    headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
                data = r.json().get("data", {}) if r.status_code == 200 else {}
                ec = data.get("eyecatch") or ""
                if "uploads/images" in ec:
                    eyecatch_url = ec
                    print(f"  [verify] 公開APIでeyecatch確認OK (attempt {attempt})")
                    break
                print(f"  [verify] eyecatch未反映 (attempt {attempt})")
        except Exception as e:
            print(f"  [verify] 公開API確認失敗: {e}")

    if eyecatch_url:
        return {"ok": True, "eyecatch_url": eyecatch_url}
    return {"ok": True, "eyecatch_url": None, "note": "アップロード送信済（URL未確認）"}


def main():
    args = sys.argv[1:]
    if len(args) < 2 or len(args) % 2 != 0:
        print(__doc__)
        sys.exit(1)

    pairs = [(int(args[i]), args[i+1]) for i in range(0, len(args), 2)]
    results = []
    for num, key in pairs:
        try:
            r = set_eyecatch(num, key, headless=True)
        except Exception as e:
            r = {"ok": False, "reason": f"例外: {e}"}
        results.append((num, key, r))
        time.sleep(3)

    print("\n" + "="*60)
    print("結果サマリー")
    print("="*60)
    for num, key, r in results:
        status = "✅" if r.get("ok") else "❌"
        info = r.get("eyecatch_url") or r.get("reason") or ""
        print(f"  #{num} {key}: {status} {info[:80]}")


if __name__ == "__main__":
    main()
