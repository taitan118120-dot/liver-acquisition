// Pococha 運営ダッシュボードのライバー一覧ページで実行するスニペット。
// https://organizer-ope.pococha.com/publishers を開いた状態で、
// Claude in Chrome の javascript_tool から評価する（最後の式が戻り値）。
//
// PocoStudio リンクには organizer トークン付きURLが含まれ innerHTML を読むと
// Chrome MCP に弾かれるため、innerText(セル文字列)のみを取得する。
(() => {
  const t = document.querySelector('table');
  if (!t) return 'NO TABLE';
  const headers = [...t.querySelectorAll('thead th, thead td')].map(h => h.innerText.trim());
  const rows = [...t.querySelectorAll('tbody tr')].map(tr =>
    [...tr.querySelectorAll('td,th')].map(c => c.innerText.trim())
  );
  return JSON.stringify({ headers, rowCount: rows.length, rows });
})()
