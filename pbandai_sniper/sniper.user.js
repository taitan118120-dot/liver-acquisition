// ==UserScript==
// @name         P-Bandai Sniper (cart auto-click)
// @namespace    local.pbandai.sniper
// @version      0.1
// @description  カートボタンが押せるようになった瞬間に自動クリック→カート画面で「購入手続きへ」も自動で進める。注文確定の手前で必ず止まる。人間がブラウザ前にいる前提。BANリスクは自己責任。
// @match        https://p-bandai.jp/item/*
// @match        https://p-bandai.jp/cart*
// @run-at       document-start
// @grant        none
// ==/UserScript==

// セットアップ:
//   1) Chrome に Tampermonkey 拡張をインストール
//   2) Tampermonkey ダッシュボード → 新規スクリプト → このファイル全文を貼り付け → 保存
//   3) 商品ページを開いて発売開始を待つ。発売の瞬間に自動でカート投入→カート画面遷移→購入手続きへ進む
//   4) 「注文確定」ボタンは押さない（手動で確認してから自分で押す）

(function() {
  'use strict';

  // ⚠️ テスト時は true、本番(明日12時)は false にする
  // true: クリック対象を赤く光らせるだけで実クリックしない（ログイン中でもカートに入らない）
  // false: 本番クリック発火
  const DRY_RUN = true;

  const isItemPage = location.pathname.startsWith('/item/');
  const isCartPage = location.pathname.startsWith('/cart');

  // ------- UI helpers -------
  function banner(msg, color) {
    console.log('[SNIPER]', msg);
    const div = document.createElement('div');
    div.textContent = msg;
    div.style.cssText = `position:fixed;top:10px;right:10px;background:${color || '#ff3b30'};color:#fff;padding:12px 16px;font-size:14px;font-weight:bold;z-index:99999;border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,.3);font-family:-apple-system,sans-serif`;
    if (document.body) document.body.appendChild(div);
    setTimeout(() => div.remove(), 4000);
  }

  function beep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain); gain.connect(ctx.destination);
      osc.frequency.value = 880;
      gain.gain.value = 0.4;
      osc.start();
      osc.stop(ctx.currentTime + 0.4);
    } catch (e) {}
  }

  // ------- Button finders -------
  function findButtonByText(regex) {
    const candidates = document.querySelectorAll('button, a, input[type="submit"], input[type="button"], [role="button"]');
    for (const b of candidates) {
      const text = (b.innerText || b.textContent || b.value || '').trim();
      if (regex.test(text)) return b;
    }
    return null;
  }

  function isClickable(btn) {
    if (!btn) return false;
    if (btn.disabled === true) return false;
    if (btn.getAttribute('aria-disabled') === 'true') return false;
    if (btn.classList && (btn.classList.contains('disabled') || btn.classList.contains('is-disabled'))) return false;
    const cs = window.getComputedStyle(btn);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) < 0.3) return false;
    if (cs.pointerEvents === 'none') return false;
    return true;
  }

  // ------- Item page logic -------
  let cartClicked = false;

  function tryCart() {
    if (cartClicked) return;
    // 「カートに入れる」「カートにいれる」「種類を選んでカートにいれる」「ご予約はこちら」を全部対象
    const candidates = document.querySelectorAll('button, a, input[type="submit"], input[type="button"], [role="button"]');
    let target = null;
    for (const b of candidates) {
      const text = (b.innerText || b.textContent || b.value || '').trim();
      if (/カート(に|へ)?(入|い)れる|ご予約はこちら/.test(text)) {
        if (!isClickable(b)) continue;
        // 予約開始前は「予約受付開始前です」というメッセージが近くにあるはずなのでスキップ
        const ctx = (b.closest('section,div,form') || document.body).innerText || '';
        if (/予約受付開始前|予約開始予定|より予約開始|受付開始前/.test(ctx) && !/予約開始しました/.test(ctx)) {
          // まだ予約前なのでクリックしない
          continue;
        }
        target = b;
        break;
      }
    }
    if (!target) return;
    cartClicked = true;
    if (DRY_RUN) {
      target.style.outline = '4px solid #ff3b30';
      target.style.boxShadow = '0 0 20px rgba(255,59,48,.8)';
      banner('🧪 [DRY_RUN] ここをクリックします（実クリックなし）', '#ff9500');
      beep();
      return;
    }
    banner('🎯 カート投入クリック！', '#34c759');
    beep();
    target.click();
  }

  // ------- Cart page logic -------
  let checkoutClicked = false;
  function tryCheckout() {
    if (checkoutClicked) return;
    const btn = findButtonByText(/購入手続き|注文手続き|レジへ進む|お支払いへ/);
    if (!btn) return;
    if (!isClickable(btn)) return;
    checkoutClicked = true;
    if (DRY_RUN) {
      btn.style.outline = '4px solid #ff3b30';
      btn.style.boxShadow = '0 0 20px rgba(255,59,48,.8)';
      banner('🧪 [DRY_RUN] 購入手続きボタンをクリックします（実クリックなし）', '#ff9500');
      beep();
      return;
    }
    banner('➡️ 購入手続きへ進行（注文確定は手動）', '#0a84ff');
    beep();
    btn.click();
  }

  // ------- Boot -------
  function start() {
    if (isItemPage) {
      banner('👀 監視開始: 発売の瞬間に自動カート投入', '#0a84ff');
      tryCart();
      const obs = new MutationObserver(tryCart);
      obs.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['disabled', 'aria-disabled', 'class', 'style']
      });
      // 200msポーリング併用（Mutation取りこぼし対策）
      setInterval(tryCart, 200);
    }
    if (isCartPage) {
      banner('🛒 カート到達。購入手続きへ自動進行（注文確定は手動）', '#0a84ff');
      // カートページのDOMが固まるまで少し待つ
      setTimeout(tryCheckout, 500);
      const obs = new MutationObserver(tryCheckout);
      obs.observe(document.body, { childList: true, subtree: true });
      setInterval(tryCheckout, 300);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
