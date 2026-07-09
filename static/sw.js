const CACHE_NAME = "ayodele-ai-v1";

// Add static routes/assets you want available offline.
// Don't cache dynamic pages that need fresh data (dashboard, course content)
// unless you're okay with stale content shown when offline.
const PRECACHE_URLS = [
  "/",
  "/static/manifest.json",
  "/static/images/icon-192.png",
  "/static/images/icon-512.png",
  "/login",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

// Network-first: try the network, fall back to cache if offline.
// Keeps course content fresh while still working offline for cached pages.
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const responseClone = response.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(event.request, responseClone);
        });
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});