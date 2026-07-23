/* Minimal service worker: cache static assets for install-to-home-screen.
   Full offline mode is NOT a goal — network is used for pages & price jobs. */
const CACHE = "steward-static-v1";
const ASSETS = [
  "/static/css/app.css",
  "/static/js/app.js",
  "/static/vendor/htmx.min.js",
  "/static/vendor/alpine.min.js",
  "/static/vendor/apexcharts.min.js",
  "/static/icons/icon.svg",
  "/static/manifest.webmanifest",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || !url.pathname.startsWith("/static/")) return;
  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(e.request, copy));
      return res;
    }).catch(() => hit))
  );
});
