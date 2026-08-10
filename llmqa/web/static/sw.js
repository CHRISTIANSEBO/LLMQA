/* LLMQA service worker.
 *
 * Minimal by design: its main job is to make the site installable as a PWA
 * (Chrome/Edge require a service worker with a fetch handler) and to serve the
 * app shell offline. It uses a small precache for the static shell and a
 * network-first strategy for navigations, always bypassing /api/* so live
 * evaluation calls are never cached/stale.
 */
const CACHE = "llmqa-shell-v1";
const SHELL = [
  "/dashboard",
  "/assets/app.css",
  "/assets/app.js",
  "/assets/theme.js",
  "/assets/pwa.js",
  "/assets/logo-light.svg",
  "/assets/logo-dark.svg",
  "/assets/favicon.svg",
  "/assets/icon-192.png",
  "/assets/icon-512.png",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // Never intercept API calls — always hit the network for live data.
  if (url.pathname.startsWith("/api/")) return;

  // Same-origin only.
  if (url.origin !== self.location.origin) return;

  // Navigations: network-first, fall back to cached shell when offline.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          return resp;
        })
        .catch(() => caches.match(req).then((r) => r || caches.match("/dashboard")))
    );
    return;
  }

  // Static assets: cache-first with background refresh.
  event.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req)
        .then((resp) => {
          if (resp && resp.status === 200) {
            const copy = resp.clone();
            caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          }
          return resp;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
