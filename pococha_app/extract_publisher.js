// Pococha 運営ダッシュボードのライバー詳細ページ用エクストラクタ。
// https://organizer-ope.pococha.com/publishers/{user_id} を開いた状態で、
// Claude in Chrome の javascript_tool から評価する。
//
// ページ内の全テーブルを「直前の見出しテキスト」で識別し、
// {user_id, captured_at, sections:{<見出し>:{headers,rows}}} を組み立て、
// publisher_{uid}_{date}.json として Blob ダウンロードする（戻り値はサイズ等の確認のみ）。
// PocoStudio等のトークン付きURLを含むため innerText のみ取得。
(() => {
  const uid = (location.pathname.match(/publishers\/(\d+)/) || [])[1] || null;
  const labelOf = (t) => {
    let el = t;
    for (let hops = 0; hops < 6 && el; hops++) {
      let p = el.previousElementSibling;
      while (p) {
        const tx = (p.innerText || '').trim();
        if (tx && tx.length < 40) return tx;
        p = p.previousElementSibling;
      }
      el = el.parentElement;
    }
    return '';
  };
  const grid = (t) => ({
    headers: [...t.querySelectorAll('thead th, thead td')].map(h => h.innerText.trim()),
    rows: [...t.querySelectorAll('tbody tr')].map(tr =>
      [...tr.querySelectorAll('td,th')].map(c => c.innerText.trim())
    ),
  });
  const sections = {};
  [...document.querySelectorAll('table')].forEach((t, i) => {
    sections[labelOf(t) || ('table_' + i)] = grid(t);
  });
  const date = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
  const payload = { user_id: uid, captured_on: date, captured_at: new Date().toISOString(), sections };
  const json = JSON.stringify(payload);
  const blob = new Blob([json], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `publisher_${uid}_${date}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  return JSON.stringify({ uid, date, bytes: json.length, sections: Object.keys(sections) });
})()
