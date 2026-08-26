// Carga del feed real. Los datos rápidos y el pipeline pesado pueden tener cadencias distintas.

export const FEED_URL =
  import.meta.env?.VITE_FEED_URL ||
  "https://raw.githubusercontent.com/marioleongayo23-spec/futbol-edge/main/football/data/dashboard.json";

// Copia empaquetada en /public como red de seguridad si el feed remoto falla
// (por ejemplo sin conexión, o antes de que el cron haya publicado en main).
// BASE_URL es "/" en Vercel y "/futbol-edge/" en GitHub Pages.
const FALLBACK_URL = (import.meta.env?.BASE_URL || "/") + "dashboard.json";

function normalizeAvailability(rows) {
  if (!Array.isArray(rows)) return rows;
  return rows.map((raw) => {
    if (!raw || typeof raw !== "object") return raw;
    const player = raw.jugador || raw.player || raw.name || "";
    const detail = raw.detalle || raw.reason || raw.descripcion || "";
    if (!player) return raw;
    const stateParts = [raw.estado, detail && detail !== player ? detail : null]
      .filter(Boolean)
      .filter((value, index, values) => values.indexOf(value) === index);
    return {
      ...raw,
      // MatchDetail prioriza `detalle`: para UI debe ser la identidad del jugador,
      // no un texto suelto como "Hamstring Injury".
      detalle: player,
      estado: stateParts.join(" · ") || raw.estado,
      raw_detalle: detail || undefined,
    };
  });
}

export function normalizeFeedForDisplay(data) {
  if (!data || !Array.isArray(data.matches)) return data;
  return {
    ...data,
    matches: data.matches.map((match) => {
      const lineup = match?.alineacion;
      if (!lineup || typeof lineup !== "object") return match;
      const normalized = {
        ...lineup,
        disponibilidad_local: normalizeAvailability(lineup.disponibilidad_local),
        disponibilidad_visitante: normalizeAvailability(lineup.disponibilidad_visitante),
      };

      // squad-only-v3 no es un once probable: son 11 nombres escogidos por grupo
      // posicional dentro de la plantilla. Se conserva el bloque en el backend
      // para trazabilidad, pero la UI no debe dibujarlo como una predicción real.
      if (normalized.model === "squad-only-v3" && normalized.status !== "confirmado") {
        normalized.local = [];
        normalized.visitante = [];
        normalized.posiciones_local = [];
        normalized.posiciones_visitante = [];
        normalized.formacion_local = null;
        normalized.formacion_visitante = null;
        normalized.status = "sin confirmar";
        normalized.provider = "Plantilla real · sin fuente fiable de once probable";
        normalized.display_withheld = true;
        normalized.display_warning = "La plantilla está disponible, pero aún no hay un once probable fiable.";
      }
      return { ...match, alineacion: normalized };
    }),
  };
}

async function fetchJson(url) {
  const r = await fetch(url + (url.includes("?") ? "&" : "?") + "t=" + Date.now());
  if (!r.ok) throw new Error("HTTP " + r.status);
  const data = await r.json();
  if (!isUsableFeed(data)) throw new Error("Feed incompleto o regresivo");
  return normalizeFeedForDisplay(data);
}

// Segunda barrera: aunque GitHub responda 200, nunca renderizamos un JSON vacío,
// con campos críticos en blanco o rechazado por el guard del backend.
export function isUsableFeed(data) {
  if (!data || !Array.isArray(data.matches) || data.matches.length < 20) return false;
  if (data.feed_quality && data.feed_quality.valid === false) return false;
  if (data.counts?.total != null && data.counts.total !== data.matches.length) return false;
  return data.matches.every((m) => m && m.id && m.home && m.away && m.league && m.kickoff);
}

export async function loadFeed() {
  // Feed embebido (preview autocontenida / offline duro): si existe, se normaliza
  // igual que el remoto para no mostrar formatos antiguos de bajas/onces.
  if (typeof window !== "undefined" && window.__FEED__) return normalizeFeedForDisplay(window.__FEED__);
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
// ``now`` es inyectable para que consumidores y tests usen la misma referencia temporal.
export function feedAgeHours(data, now = Date.now()) {
  const iso = data?.generated_at;
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  return (now - t) / 36e5;
}

// "Desactualizado" con contexto: el cron solo commitea si el feed CAMBIA, así que
// de madrugada (sin partidos) el generated_at envejece sin que pase nada malo. Solo
// avisamos si el feed es viejo Y hay fútbol ahora mismo (en juego o en las próximas
// 3 h), o si lleva claramente atascado (>18 h). Evita el falso aviso nocturno.
export function isStale(data, now = Date.now()) {
  const h = feedAgeHours(data, now);
  if (h == null) return false;
  if (h > 18) return true;          // claramente atascado
  if (h <= 2) return false;         // recién actualizado
  const win = 3 * 36e5;             // ±3 h: partido en juego o inminente
  const matches = Array.isArray(data?.matches) ? data.matches : [];
  return matches.some((m) => {
    const t = new Date(m?.kickoff).getTime();
    return !Number.isNaN(t) && t >= now - win && t <= now + win;
  });
}

export const CREST_FALLBACK =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='40' height='40'%3E%3Ccircle cx='20' cy='20' r='18' fill='%23182231' stroke='%23233048'/%3E%3C/svg%3E";

// Iniciales de un equipo (p. ej. "Real Oviedo" -> "OV", "Sporting de Gijón" -> "SG").
const CREST_STOP = new Set(["cf", "fc", "cd", "ud", "sd", "rc", "cp", "de", "la", "el", "los", "real", "club", "b"]);
function crestInitials(name) {
  const words = (name || "").normalize("NFD").replace(/[̀-ͯ]/g, "")
    .split(/[\s.]+/).filter((w) => w && !CREST_STOP.has(w.toLowerCase()));
  const src = words.length ? words : [(name || "?")];
  let ini = src.slice(0, 2).map((w) => w[0]).join("");
  if (ini.length < 2 && (name || "").length >= 2) ini = name.slice(0, 2);
  return ini.toUpperCase().slice(0, 3);
}
const CREST_PALETTE = ["#3b74d6", "#22c98a", "#ff5d6c", "#a371f7", "#ff9d4d", "#e3b341", "#39d0ff", "#c0473a", "#5aa2ff", "#a23b52"];
function crestHashColor(name) {
  let h = 0; for (const c of (name || "")) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return CREST_PALETTE[h % CREST_PALETTE.length];
}

// Escudo real si lo hay; si no, un monograma (iniciales sobre color del club),
// así ningún equipo se ve "sin escudo" (Segunda no trae escudos gratis).
export function crestFor(name, colors, crest) {
  if (crest) return crest;
  const col = accent(colors);
  const bg = col && col !== "var(--line)" ? col : crestHashColor(name);
  const ini = crestInitials(name);
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40'>`
    + `<circle cx='20' cy='20' r='18' fill='${bg}' stroke='rgba(255,255,255,.18)'/>`
    + `<text x='20' y='25.5' font-family='system-ui,-apple-system,sans-serif' font-size='13' `
    + `font-weight='700' fill='#fff' text-anchor='middle'>${ini}</text></svg>`;
  return "data:image/svg+xml," + encodeURIComponent(svg);
}

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