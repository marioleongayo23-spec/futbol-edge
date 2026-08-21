// Carga del feed real (mismo que genera el cron cada 12h) y utilidades.

export const FEED_URL =
  import.meta.env.VITE_FEED_URL ||
  "https://raw.githubusercontent.com/marioleongayo23-spec/futbol-edge/main/football/data/dashboard.json";

// Copia empaquetada en /public como red de seguridad si el feed remoto falla
// (por ejemplo sin conexión, o antes de que el cron haya publicado en main).
// BASE_URL es "/" en Vercel y "/futbol-edge/" en GitHub Pages.
const FALLBACK_URL = (import.meta.env.BASE_URL || "/") + "dashboard.json";

async function fetchJson(url) {
  const r = await fetch(url + (url.includes("?") ? "&" : "?") + "t=" + Date.now());
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

export async function loadFeed() {
  // Feed embebido (preview autocontenida / offline duro): si existe, se usa.
  if (typeof window !== "undefined" && window.__FEED__) return window.__FEED__;
  try {
    return await fetchJson(FEED_URL);
  } catch (e) {
    // Si el remoto falla y no estamos ya usándolo, intenta la copia local.
    if (FEED_URL !== FALLBACK_URL) {
      try {
        const data = await fetchJson(FALLBACK_URL);
        data._fromFallback = true;
        return data;
      } catch {
        /* propaga el error original */
      }
    }
    throw e;
  }
}

// Devuelve la antigüedad del feed en horas (o null si no hay fecha).
export function feedAgeHours(data) {
  const iso = data?.generated_at;
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  return (Date.now() - t) / 36e5;
}

// El cron corre cada 12h; a partir de ~30h lo consideramos potencialmente viejo.
export function isStale(data) {
  const h = feedAgeHours(data);
  return h != null && h > 30;
}

export const CREST_FALLBACK =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='40' height='40'%3E%3Ccircle cx='20' cy='20' r='18' fill='%23182231' stroke='%23233048'/%3E%3C/svg%3E";

const COLORS = {
  white: "#e6edf3", red: "#ff5d6c", blue: "#5aa2ff", navy: "#3b74d6", sky: "#39d0ff",
  green: "#22c98a", yellow: "#ffb020", gold: "#e3b341", black: "#4a5468", maroon: "#c0473a",
  claret: "#a23b52", orange: "#ff9d4d", purple: "#a371f7", grey: "#7d8da3", gray: "#7d8da3",
};

export function accent(c) {
  if (!c) return "var(--line)";
  for (const t of c.toLowerCase().split(/[/,\s]+/))
    if (t !== "white" && COLORS[t]) return COLORS[t];
  return COLORS[c.toLowerCase().split(/[/,\s]+/)[0]] || "var(--line)";
}

export function fmtKick(iso) {
  try {
    return new Date(iso).toLocaleString("es-ES", {
      weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso || "";
  }
}

export const hasPrediction = (m) => !m.finished && Array.isArray(m.xg);
