// Service worker for the /np Now Playing PWA.
//
// Its only job is to make /np installable: a fetch handler is the one hard
// requirement browsers place on an installable app. It deliberately does NOT
// cache — the page is the live Now Playing of the appliance, and /device/*
// carries real-time player and VU data that must never be served stale. So we
// pass every request straight to the network; offline simply fails, as it
// should for a page that only means anything while the player is reachable.

self.addEventListener('install', (e) => {
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (e) => {
  // Network pass-through. No respondWith-with-cache: keep it live.
  e.respondWith(fetch(e.request));
});
