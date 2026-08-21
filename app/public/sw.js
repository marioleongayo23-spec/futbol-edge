// Service worker mínimo para instalar la app y que funcione offline.
// - App shell (HTML/JS/CSS/iconos): cache-first.
// - Feed dashboard.json: network-first con caché de respaldo.
const CACHE = "futbol-edge-v1";
const SHELL = ["/", "/index.html", "/favicon.svg", "/manifest.webmanifest", "/dashboard.json"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  const isFeed = url.pathname.endsWith("dashboard.json");

  if (isFeed) {
    // Network-first: datos frescos si hay red, si no la última copia cacheada.
    e.respondWith(
      fetch(request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(request, copy));
        return res;
      }).catch(() => caches.match(request).then((r) => r || caches.match("/dashboard.json")))
    );
    return;
  }

  // Resto: cache-first con relleno de red.
  e.respondWith(
    caches.match(request).then((cached) =>
      cached || fetch(request).then((res) => {
        if (res.ok && url.origin === self.location.origin) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(request, copy));
        }
        return res;
      }).catch(() => cached)
    )
  );
});
