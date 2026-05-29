// ==UserScript==
// @name         Pococha 過去コメント収集
// @namespace    taitan-pro
// @version      1.0
// @description  organizer-ope の配信詳細からコメント(ユーザー/本文/時刻)を巡回収集し、ローカルサーバーに保存する
// @match        https://organizer-ope.pococha.com/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-idle
// ==/UserScript==
(function () {
  'use strict';

  const CONFIG = {
    server: 'http://127.0.0.1:5057/api/comments',
    delayMs: 400,       // 各fetchの間隔（Pococha側への配慮。短くしすぎない）
    maxPagesPerStream: 60,
    batchSize: 100,
  };

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let stopFlag = false;

  // ---------- 収集ロジック ----------
  async function getLivers() {
    const r = await fetch('/publishers?max_display=1000', { credentials: 'same-origin' });
    const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
    const trs = [...doc.querySelectorAll('table tbody tr')];
    return trs.map(tr => {
      const c = [...tr.querySelectorAll('td,th')].map(x => x.innerText.trim());
      return { id: c[0], name: c[1] };
    }).filter(x => /^\d+$/.test(x.id));
  }

  async function getStreamIds(uid) {
    const ids = new Set();
    for (let page = 1; page <= 30; page++) {
      if (stopFlag) break;
      const r = await fetch(`/publishers/${uid}?page=${page}`, { credentials: 'same-origin' });
      const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
      const links = [...doc.querySelectorAll('a[href^="/lives/"]')]
        .map(a => (a.getAttribute('href').match(/\/lives\/(\d+)/) || [])[1])
        .filter(Boolean);
      if (links.length === 0) break;
      const before = ids.size;
      links.forEach(id => ids.add(id));
      if (ids.size === before) break; // 増えなければ終端
      await sleep(CONFIG.delayMs);
    }
    return [...ids];
  }

  async function getStreamComments(sid, liverName) {
    const out = [];
    for (let page = 1; page <= CONFIG.maxPagesPerStream; page++) {
      if (stopFlag) break;
      const r = await fetch(`/lives/${sid}/comments?page=${page}`, { credentials: 'same-origin' });
      if (!r.ok) break;
      const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
      const trs = [...doc.querySelectorAll('table tbody tr')];
      if (trs.length === 0) break;
      for (const tr of trs) {
        const c = [...tr.querySelectorAll('td,th')].map(x => x.innerText.trim());
        if (!c[0] || c[0].includes('*****')) continue; // マスク行は除外
        out.push({
          liver: liverName, stream_id: sid,
          commenter: c[0], text: c[1], timing: c[2] || '', posted_at: c[3] || '',
          source: 'history',
        });
      }
      await sleep(CONFIG.delayMs);
      if (trs.length < 50) break; // 最終ページ
    }
    return out;
  }

  function post(items) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method: 'POST', url: CONFIG.server,
        headers: { 'Content-Type': 'application/json' },
        data: JSON.stringify(items),
        onload: res => resolve(JSON.parse(res.responseText || '{}')),
        onerror: () => reject(new Error('POST失敗（サーバー起動中か確認）')),
        ontimeout: () => reject(new Error('POSTタイムアウト')),
      });
    });
  }

  async function flush(buffer) {
    if (!buffer.length) return 0;
    let saved = 0;
    for (let i = 0; i < buffer.length; i += CONFIG.batchSize) {
      const res = await post(buffer.slice(i, i + CONFIG.batchSize));
      saved += (res.saved || 0);
    }
    return saved;
  }

  // ---------- UI ----------
  const $ = (sel, root = document) => root.querySelector(sel);
  function log(msg) {
    const el = $('#pc-log');
    if (el) { el.textContent = msg + '\n' + el.textContent; }
  }

  async function run(scope) {
    stopFlag = false;
    let livers;
    try {
      if (scope === 'current') {
        const m = location.pathname.match(/\/publishers\/(\d+)/);
        if (!m) { alert('ライバー詳細ページ(/publishers/ID)で実行するか「全ライバー」を選んでください'); return; }
        const all = await getLivers();
        const found = all.find(x => x.id === m[1]);
        livers = [{ id: m[1], name: found ? found.name : m[1] }];
      } else {
        livers = await getLivers();
      }
    } catch (e) { log('ライバー取得エラー: ' + e.message); return; }

    log(`対象ライバー ${livers.length}名`);
    let grandSaved = 0, grandSeen = 0;
    for (const lv of livers) {
      if (stopFlag) { log('停止しました'); break; }
      log(`▶ ${lv.name} (${lv.id}) 配信ID収集中…`);
      let streamIds;
      try { streamIds = await getStreamIds(lv.id); }
      catch (e) { log(`  配信ID取得エラー: ${e.message}`); continue; }
      log(`  配信 ${streamIds.length}件`);
      let buffer = [];
      for (let i = 0; i < streamIds.length; i++) {
        if (stopFlag) break;
        const sid = streamIds[i];
        try {
          const cmts = await getStreamComments(sid, lv.name);
          grandSeen += cmts.length;
          buffer.push(...cmts);
          log(`  [${i + 1}/${streamIds.length}] 配信${sid}: 非マスク${cmts.length}件`);
          if (buffer.length >= CONFIG.batchSize) {
            grandSaved += await flush(buffer); buffer = [];
          }
        } catch (e) { log(`  配信${sid}エラー: ${e.message}`); }
      }
      try { grandSaved += await flush(buffer); } catch (e) { log('保存エラー: ' + e.message); }
    }
    log(`✅ 完了: 取得${grandSeen}件 / 新規保存${grandSaved}件`);
  }

  function buildPanel() {
    if ($('#pc-panel')) return;
    const p = document.createElement('div');
    p.id = 'pc-panel';
    p.style.cssText = 'position:fixed;right:14px;bottom:14px;z-index:99999;width:300px;'
      + 'background:#fff;border:1px solid #ff5b8a;border-radius:10px;padding:10px;'
      + 'box-shadow:0 4px 16px rgba(0,0,0,.15);font:12px/1.5 system-ui,sans-serif';
    p.innerHTML = `
      <div style="font-weight:700;color:#ff5b8a;margin-bottom:6px">Pococha コメント収集</div>
      <button id="pc-cur" style="margin:2px;padding:5px 8px;border:0;border-radius:6px;background:#ff5b8a;color:#fff;cursor:pointer">このライバー</button>
      <button id="pc-all" style="margin:2px;padding:5px 8px;border:0;border-radius:6px;background:#444;color:#fff;cursor:pointer">全ライバー</button>
      <button id="pc-stop" style="margin:2px;padding:5px 8px;border:0;border-radius:6px;background:#aaa;color:#fff;cursor:pointer">停止</button>
      <pre id="pc-log" style="margin-top:8px;max-height:180px;overflow:auto;background:#fafafa;border:1px solid #eee;border-radius:6px;padding:6px;white-space:pre-wrap"></pre>
      <div style="color:#999;margin-top:4px">先に comment_server.py を起動してください</div>`;
    document.body.appendChild(p);
    $('#pc-cur').onclick = () => run('current');
    $('#pc-all').onclick = () => run('all');
    $('#pc-stop').onclick = () => { stopFlag = true; log('停止要求…'); };
  }

  buildPanel();
})();
