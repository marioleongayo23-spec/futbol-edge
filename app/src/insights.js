// Utilidades analíticas para la UI: aciertos del modelo, confianza, forma,
// mejores value bets y favoritos. Todo se calcula en cliente desde el feed.

const SIGN = (hg, ag) => (hg > ag ? "1" : hg < ag ? "2" : "X");

// Acierto 1X2 del modelo sobre partidos jugados que llevaban predicción.
export function modelAccuracy(matches) {
  let hits = 0, total = 0;
  for (const m of matches) {
    const probs = m.prediction_snapshot?.probs;
    if (!m.finished || !Array.isArray(m.result) || !Array.isArray(probs)) continue;
    const fav = ["1", "X", "2"][probs.indexOf(Math.max(...probs))];
    const real = SIGN(m.result[0], m.result[1]);
    total++; if (fav === real) hits++;
  }
  return { hits, total, pct: total ? Math.round((hits / total) * 100) : null };
}

// Confianza de una predicción por la probabilidad del favorito.
export function confidence(m) {
  if (!Array.isArray(m.probs)) return null;
  const mx = Math.max(...m.probs);
  const published = m.prediction_confidence;
  if (published?.score != null) {
    const label = published.level ? published.level[0].toUpperCase() + published.level.slice(1) : "Media";
    return {
      stars: published.score >= 72 ? 3 : published.score >= 55 ? 2 : 1,
      label, mx,
      disagreement: (published.model_disagreement_pp || 0) / 100,
      score: published.score,
    };
  }
  const components = m.model_meta?.components;
  const dc = components?.dixon_coles, elo = components?.elo;
  const disagreement = dc && elo
    ? Math.max(...["1", "X", "2"].map((key) => Math.abs((dc[key] || 0) - (elo[key] || 0))))
    : 0;
  if (mx >= 55 && disagreement <= 0.08) return { stars: 3, label: "Alta", mx, disagreement };
  if (mx >= 45 && disagreement <= 0.15) return { stars: 2, label: "Media", mx, disagreement };
  return { stars: 1, label: "Baja", mx, disagreement };
}

// Mejor value bet del partido (edge máximo) si supera el umbral.
export function bestValue(m, min = 0.03) {
  if (!Array.isArray(m.value) || !m.value.length) return null;
  const b = m.value[0]; // ya viene ordenado por edge desc
  return b.edge > min ? b : null;
}

// ¿El favorito del modelo NO es el favorito del mercado? (pick sorpresa)
export function isSurprise(m) {
  const mo = m.odds?.["1x2"]?.odds;
  if (!mo || !Array.isArray(m.probs)) return false;
  const modelFav = ["1", "X", "2"][m.probs.indexOf(Math.max(...m.probs))];
  const mktFav = ["1", "X", "2"].reduce((a, b) => (mo[a] <= mo[b] ? a : b));
  return modelFav !== mktFav;
}

// Top value bets del feed (próximos), ordenados por edge.
export function topValueBets(matches, n = 3, min = 0.03) {
  const out = [];
  for (const m of matches) {
    if (m.finished) continue;
    const b = bestValue(m, min);
    if (b) out.push({ m, ...b });
  }
  out.sort((a, b) => b.edge - a.edge);
  return out.slice(0, n);
}

// Forma reciente (últimos N) de un equipo: array de "W"/"D"/"L" cronológico.
export function recentForm(matches, team, n = 5) {
  const played = matches
    .filter((m) => (m.home === team || m.away === team) && m.finished && Array.isArray(m.result))
    .sort((a, b) => (a.kickoff || "").localeCompare(b.kickoff || ""));
  return played.slice(-n).map((m) => {
    const home = m.home === team;
    const gf = home ? m.result[0] : m.result[1];
    const ga = home ? m.result[1] : m.result[0];
    return gf > ga ? "W" : gf < ga ? "L" : "D";
  });
}

// Cuenta atrás legible hasta el saque ("en 2h 15m", "en 3 días", "en juego").
export function countdown(kickoff) {
  if (!kickoff) return "";
  const ms = new Date(kickoff).getTime() - Date.now();
  if (ms < -3 * 3600e3) return "";
  if (ms < 0) return "en juego";
  const min = Math.round(ms / 60000);
  if (min < 60) return `en ${min}m`;
  const h = Math.floor(min / 60);
  if (h < 24) return `en ${h}h ${min % 60}m`;
  return `en ${Math.round(h / 24)} días`;
}

// Favoritos (localStorage).
const FAV_KEY = "fe_favs";
export function getFavs() {
  try { return new Set(JSON.parse(localStorage.getItem(FAV_KEY) || "[]")); } catch { return new Set(); }
}
export function toggleFav(team) {
  const s = getFavs();
  if (s.has(team)) s.delete(team); else s.add(team);
  try { localStorage.setItem(FAV_KEY, JSON.stringify([...s])); } catch { /* ignore */ }
  return s;
}
