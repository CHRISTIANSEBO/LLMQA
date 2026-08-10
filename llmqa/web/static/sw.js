/* LLMQA service worker — enhanced PWA version.
 *
 * Features:
 * - Versioned cache for easy updates
 * - Offline shell + last-known-good data for /api/history and /api/config
 * - Network-first for navigations and critical API data
 * - Cache-first for static assets with background refresh
 * - Explicit bypass for live /api/run and other mutating endpoints
 * - Update notification support via postMessage
 */

const VERSION = "llmqa-pwa-v2";
const SHELL_CACHE = `${VERSION}-shell`;
const DATA_CACHE = `${VERSION}-data`;

const SHELL_ASSETS = [
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

// Endpoints we want to cache for offline use (last known good)
const CACHEABLE_DATA_PATHS = ["/api/config", "/api/history"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => !key.startsWith(VERSION))
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

// Helper: notify all clients of an available update
function notifyClientsOfUpdate() {
  self.clients.matchAll({ type: "window" }).then((clients) => {
    clients.forEach((client) => {
      client.postMessage({ type: "SW_UPDATE_AVAILABLE" });
    });
  });
}

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Never cache live evaluation runs or mutating calls
  if (url.pathname.startsWith("/api/run")) return;

  // === Data endpoints: network-first with offline fallback ===
  if (CACHEABLE_DATA_PATHS.some((p) => url.pathname.startsWith(p))) {
    event.respondWith(
      fetch(req)
        .then((resp) => {
          if (resp && resp.status === 200) {
            const copy = resp.clone();
            caches.open(DATA_CACHE).then((c) => c.put(req, copy)).catch(() => {});
          }
          return resp;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

  // === API calls (non-cached): always network ===
  if (url.pathname.startsWith("/api/")) return;

  // === Navigations: network-first, fallback to cached shell ===
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(SHELL_CACHE).then((c) => c.put(req, copy)).catch(() => {});
          return resp;
        })
        .catch(() =>
          caches.match(req).then((r) => r || caches.match("/dashboard"))
        )
    );
    return;
  }

  // === Static assets: cache-first with background refresh ===
  event.respondWith(
    caches.match(req).then((cached) => {
      const networkFetch = fetch(req)
        .then((resp) => {
          if (resp && resp.status === 200) {
            const copy = resp.clone();
            caches.open(SHELL_CACHE).then((c) => c.put(req, copy)).catch(() => {});
          }
          return resp;
        })
        .catch(() => cached);

      return cached || networkFetch;
    })
  );
});

// Optional: notify on new SW ready (can be triggered from activate if desired)
self.addEventListener("controllerchange", () => {
  // Could notify here, but we use message-based flow instead
});