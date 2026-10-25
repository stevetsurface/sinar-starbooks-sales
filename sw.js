// Minimal service worker: makes the dashboard installable as an app on Android (Chrome's install prompt
// needs one). It does not cache the page or data, so every open still fetches the latest CSVs.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
