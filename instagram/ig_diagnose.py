#!/usr/bin/env python3
"""Instagram Graph API の疎通を切り分ける診断ツール。

なぜ要るか（2026-09-15）:
  `Unsupported get/post request. Object with ID '***' does not exist, cannot be
  loaded due to missing permissions, or does not support this operation`
  (code=100 / subcode=33) は、次のどれでも**まったく同じ文面**で返ってくる。

    (a) INSTAGRAM_BUSINESS_ID が別アカウントのIDになっている
    (b) トークンが別のFacebookユーザー／別アプリのもの
    (c) Facebookページ ↔ IGビジネスアカウントの連携が切れている
    (d) トークン生成時にそのページを許可しなかった（granular_scopes に入っていない）
    (e) Instagramログイン（graph.instagram.com）のトークンを
        graph.facebook.com に投げている

  エラー文からは区別できないので「とりあえずトークン再発行」に流れがちだが、
  (a)(c)(d) は再発行しても直らない（実際 2026-09-11 に再発行して即日再発している）。
  このスクリプトは上の5つを**1回の実行で機械的に切り分ける**ためにある。

出力はCIログに残る前提で、アクセストークンは絶対に出さない。
INSTAGRAM_BUSINESS_ID も全文は出さず、指紋（sha1先頭10桁）と長さ、
および「APIから見つかったIDと一致するか」の真偽だけを出す。
APIから発見したIDのほうは、Secretsに貼り直す必要があるのでそのまま出す
（Secretと同じ値ならGitHub側が自動で伏せ字にする）。

使い方:
    python instagram/ig_diagnose.py
環境変数: INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ID
"""

import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

FB = "https://graph.facebook.com/v21.0"
IG = "https://graph.instagram.com/v21.0"
TIMEOUT = 30


def fingerprint(value):
    """秘匿値を、比較だけできる形にして出す。"""
    if not value:
        return "（未設定）"
    return f"len={len(value)} sha1={hashlib.sha1(value.encode()).hexdigest()[:10]}"


def call(base, path, token, **params):
    """Graph APIを叩いて (dict, エラー文字列) を返す。例外は投げない。"""
    params["access_token"] = token
    url = f"{base}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            err = json.loads(body).get("error", {})
            return None, (f"HTTP {e.code} code={err.get('code')} "
                          f"subcode={err.get('error_subcode')} "
                          f"{err.get('message', '')[:200]}")
        except Exception:
            return None, f"HTTP {e.code} {body[:200]}"
    except Exception as e:  # ネットワーク断など
        return None, f"{type(e).__name__}: {e}"


def section(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main():
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    biz = os.environ.get("INSTAGRAM_BUSINESS_ID", "").strip()

    if not token:
        print("[FATAL] INSTAGRAM_ACCESS_TOKEN が空です")
        return 1

    print(f"INSTAGRAM_BUSINESS_ID の指紋: {fingerprint(biz)}")
    print(f"INSTAGRAM_ACCESS_TOKEN の指紋: {fingerprint(token)}")

    # 見つかったIGアカウントを貯めて、最後に BUSINESS_ID と突き合わせる
    found = []          # [(どこで見つけたか, id, username)]
    token_kind = "?"

    # ── 1. トークンの正体 ────────────────────────────────────
    section("1. debug_token — このトークンは誰の・どのアプリのものか")
    data, err = call(FB, "debug_token", token, input_token=token)
    info = (data or {}).get("data") or {}
    if err or not info:
        print(f"[NG] 取得できません: {err or 'data が空'}")
        print("     → トークン文字列そのものが壊れている可能性。手順1からやり直す。")
    else:
        token_kind = info.get("type", "?")
        print(f"  type         : {token_kind}   (USER=ユーザートークン / PAGE=ページトークン)")
        print(f"  app_id       : {info.get('app_id')}  ({info.get('application')})")
        print(f"  user_id      : {info.get('user_id') or info.get('profile_id') or '(なし)'}")
        print(f"  is_valid     : {info.get('is_valid')}")
        exp = info.get("expires_at")
        print(f"  expires_at   : {exp if exp else 0}"
              f"{'  ← 0 = 無期限（理想）' if not exp else ''}")
        print(f"  data_access  : {info.get('data_access_expires_at')}")
        print(f"  scopes       : {', '.join(info.get('scopes') or []) or '（なし）'}")

        # granular_scopes が本命。どのスコープが「どのページ/IGに対して」
        # 有効かがここに出る。target_ids が空 = 対象を1つも許可していない。
        gs = info.get("granular_scopes") or []
        print("  granular_scopes（スコープごとの適用対象）:")
        if not gs:
            print("    （返ってきていない）")
        for g in gs:
            targets = g.get("target_ids")
            if targets is None:
                mark = "全対象"
            elif not targets:
                mark = "❌ 対象0件"
            else:
                mark = f"{len(targets)}件: {', '.join(map(str, targets))}"
            print(f"    - {g.get('scope')}: {mark}")
            for t in targets or []:
                found.append((f"granular_scopes[{g.get('scope')}]", str(t), ""))

    # ── 2. /me ───────────────────────────────────────────────
    section("2. /me — トークンの持ち主")
    data, err = call(FB, "me", token, fields="id,name")
    print(f"  {err}" if err else f"  id={data.get('id')} name={data.get('name')}")

    # ── 3. Facebookページと、その先のIG ──────────────────────
    section("3. /me/accounts — 管理しているFacebookページと連携IG")
    print("  ※ ここが空だと graph.facebook.com 経由でIGビジネスアカウントに")
    print("     一切到達できない（=今回のエラーの典型的な真因）")
    data, err = call(FB, "me/accounts", token,
                     fields="id,name,instagram_business_account{id,username,name}",
                     limit=50)
    if err:
        print(f"  [NG] {err}")
    else:
        pages = data.get("data") or []
        if not pages:
            print("  ❌ data が空 — このトークンはFacebookページを1つも管理していない")
            print("     考えられる原因:")
            print("       - トークン生成時に対象ページを選択しなかった")
            print("       - pages_show_list の granular target_ids が0件（上の1.を見る）")
            print("       - 別のFacebookユーザーでログインしてトークンを作った")
        for p in pages:
            iga = p.get("instagram_business_account") or {}
            print(f"  - ページ: {p.get('name')} (id={p.get('id')})")
            if iga:
                print(f"      └ 連携IG: @{iga.get('username')} id={iga.get('id')}")
                found.append(("me/accounts", str(iga.get("id")), iga.get("username", "")))
            else:
                print("      └ ❌ IGビジネスアカウント未連携")

    # ページトークンの場合、/me 自体がページなのでそこからも辿る
    if token_kind == "PAGE":
        section("3b. /me（ページトークン）から見た連携IG")
        data, err = call(FB, "me", token, fields="id,name,instagram_business_account{id,username}")
        if err:
            print(f"  [NG] {err}")
        else:
            iga = (data or {}).get("instagram_business_account") or {}
            print(f"  ページ: {data.get('name')} (id={data.get('id')})")
            if iga:
                print(f"    └ 連携IG: @{iga.get('username')} id={iga.get('id')}")
                found.append(("me(page)", str(iga.get("id")), iga.get("username", "")))
            else:
                print("    └ ❌ IGビジネスアカウント未連携")

    # ── 4. 付与済み権限 ──────────────────────────────────────
    section("4. /me/permissions — 実際に granted な権限")
    data, err = call(FB, "me/permissions", token)
    if err:
        print(f"  [NG] {err}")
    else:
        for p in data.get("data") or []:
            mark = "✅" if p.get("status") == "granted" else "❌"
            print(f"  {mark} {p.get('permission')} ({p.get('status')})")

    # ── 5. 本命: 設定中のIDを直接叩く ────────────────────────
    section("5. GET /{INSTAGRAM_BUSINESS_ID} — 実際に落ちている呼び出し")
    if not biz:
        print("  [SKIP] INSTAGRAM_BUSINESS_ID が未設定")
    else:
        data, err = call(FB, biz, token, fields="id,username,name,followers_count")
        if err:
            print(f"  ❌ {err}")
        else:
            print(f"  ✅ 取得OK: @{data.get('username')} / {data.get('name')} "
                  f"/ フォロワー {data.get('followers_count')}")

        # Instagramログイン系トークンを誤って入れていないかの判定
        data2, err2 = call(IG, biz, token, fields="id,username")
        print(f"  graph.instagram.com 側: "
              f"{'✅ ' + str(data2.get('username')) if not err2 else '❌ ' + err2}")

    # ── 6. Instagramログイン（graph.instagram.com）のトークンか ──
    section("6. graph.instagram.com/me — IGログイン方式のトークンかどうか")
    data, err = call(IG, "me", token, fields="id,username,user_id")
    if err:
        print(f"  ❌ {err}")
        print("     → これが失敗するなら Facebookログイン方式のトークン（本来こちらが正しい）")
    else:
        print(f"  ⚠️ 成功: @{data.get('username')} id={data.get('id')} user_id={data.get('user_id')}")
        print("     → Instagramログイン方式のトークンを使っている。")
        print("        graph.facebook.com の /{ig-business-id} 系は使えないので、")
        print("        Facebookログイン方式（Graph APIエクスプローラー）で取り直す必要がある。")
        for key in ("user_id", "id"):
            if data.get(key):
                found.append((f"graph.instagram.com/me.{key}", str(data[key]),
                              data.get("username", "")))

    # ── 7. 判定 ──────────────────────────────────────────────
    section("7. 判定")
    uniq = {}
    for where, fid, uname in found:
        uniq.setdefault(fid, [uname, []])[1].append(where)
        if uname and not uniq[fid][0]:
            uniq[fid][0] = uname

    if not uniq:
        print("  このトークンからは、到達できるIGアカウントが1つも見つかりませんでした。")
        print("  → ID側ではなくトークン側の問題。Facebookページの許可からやり直す。")
    else:
        print("  このトークンから到達できるID:")
        for fid, (uname, wheres) in uniq.items():
            same = "✅ INSTAGRAM_BUSINESS_ID と一致" if fid == biz else "⚠️ Secretsの値と不一致"
            print(f"    - {fid} (@{uname or '?'}) [{', '.join(sorted(set(wheres)))}] {same}")

    if biz and biz not in uniq:
        print("\n  ❗ 設定中の INSTAGRAM_BUSINESS_ID は、このトークンからは到達できません。")
        print("     上に候補IDが出ていれば Secrets を差し替える。")
        print("     候補が0件なら、Facebookページ側の連携／許可を直してからトークンを取り直す。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
