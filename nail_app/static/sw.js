// 最小のService Worker（PWA化＝ホーム画面に置くため）。
// キャッシュはあえて最小限（投稿は常に最新であるべきなのでネットワーク優先）。
const CACHE = 'nail-app-v1';

self.addEventListener('install', (e) => {
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (e) => {
  // ネットワーク優先。オフライン時のみ何もしない（アプリはオンライン前提）。
  return;
});
