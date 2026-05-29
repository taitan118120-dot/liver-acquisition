// Pococha 運営の配信詳細ページ /lives/{live_id} で実行するスニペット。
// joined_live_archiving の playlist.m3u8 URL を抜き出して返す。
// Claude in Chrome の javascript_tool から評価する（再生プレイヤーが描画された後に実行）。
(() => {
  const live_id = (location.pathname.match(/lives\/(\d+)/) || [])[1] || null;
  const html = document.documentElement.innerHTML;
  const urls = [...html.matchAll(/https?:\/\/[^'"\s]+\.m3u8[^'"\s]*/g)].map(x => x[0]);
  // joined_live_archiving を優先
  const arch = urls.find(u => u.includes('joined_live_archiving')) || urls[0] || null;
  return JSON.stringify({ live_id, m3u8: arch, all: [...new Set(urls)].slice(0, 5) });
})()
