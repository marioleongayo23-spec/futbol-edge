// Service worker para instalar la app y que funcione offline.
// IMPORTANTE: la navegación (HTML) es NETWORK-FIRST. Si fuera cache-first, tras
// un redeploy el index.html cacheado apuntaría a bundles con hash antiguo que ya
// no existen -> 404 del JS -> pantalla en negro. Network-first evita eso; los
// assets con hash (inmutables) sí van cache-first.
const CACHE = "futbol-edge-v4";
// BASE = "/" (Vercel) o "/futbol-edge/" (GitHub Pages), derivado de la ruta del SW.
const BASE = self.location.pathname.replace(/sw\.js$/, "");
const SHELL = [BASE, BASE + "index.html", BASE + "manifest.webmanifest", BASE + "dashboard.json"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => Promise.allSettled(SHELL.map((u) => c.add(u))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (e) => {
  if (e.data === "skipWaiting") self.skipWaiting();
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  if (request.method !== "GET") return;
  const url = new URL(request.url);

  // El propio SW nunca se cachea (para que las actualizaciones lleguen siempre).
  if (url.pathname.endsWith("/sw.js")) return;

  const isNavigation = request.mode === "navigate" ||
    (request.destination === "document") ||
    url.pathname === BASE || url.pathname.endsWith("/index.html");
  const isFeed = url.pathname.endsWith("dashboard.json");

  // Navegación y feed: NETWORK-FIRST (siempre el HTML/datos frescos del deploy).
  if (isNavigation || isFeed) {
    // no-store evita que una index.html cacheada por HTTP apunte a bundles viejos.
    const fresh = isNavigation ? new Request(request, { cache: "no-store" }) : request;
    e.respondWith(
      fetch(fresh).then((res) => {
        if (res && res.ok && url.origin === self.location.origin) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(request, copy));
        }
        return res;
      }).catch(() =>
        caches.match(request).then((r) => r || caches.match(BASE + "index.html") || caches.match(BASE))
      )
    );
    return;
  }

  // Assets con hash y estáticos: cache-first con relleno de red.
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
