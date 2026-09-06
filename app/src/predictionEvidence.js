import { coverageRows } from "./coverage.js";
import { validProbabilities } from "./probabilityContract.js";
export { validProbabilities, displayPercentages } from "./probabilityContract.js";

export function publishedMatrix(match) {
  const rows = match?.score_matrix?.matrix;
  if (!Array.isArray(rows) || rows.length < 2 || rows.length > 31
      || !rows.every(r => Array.isArray(r) && r.length === rows.length
        && r.every(v => typeof v === "number" && Number.isFinite(v) && v >= 0))) return null;
  const sum = rows.flat().reduce((a, b) => a + b, 0);
  if (Math.abs(sum - 1) > 0.00001) return null;
  return rows.map(r => r.map(v => v / sum));
}

export function wilsonInterval(hits, n) {
  if (!n || hits < 0 || hits > n) return null;
  const z = 1.959963984540054, p = hits / n, denom = 1 + z * z / n;
  const centre = (p + z * z / (2 * n)) / denom;
  const half = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom;
  return [Math.max(0, centre - half), Math.min(1, centre + half)];
}

const LABELS = { fixture: "Calendario", weather: "Clima", absences: "Bajas", lineup_probable: "Once probable", lineup_official: "Once oficial", odds: "Cuotas" };
const STATES = { ok: "Disponible", estimated: "Estimación", partial: "Parcial", scheduled: "Pendiente de ventana", waiting: "Esperando publicación", missing: "Sin datos", unavailable: "No disponible", stale: "Desactualizada" };
const EFFECT = { fixture: "Identifica el partido y su horario", weather: "Contexto y escenario; no recalibra el 1X2", absences: "Disponibilidad y solidez de la evidencia", lineup_probable: "Escenario provisional y minutos de jugadores", lineup_official: "Confirma titulares y habilita la revisión final", odds: "Referencia de mercado; mezcla solo si se indica" };

export function evidenceRows(match, now = Date.now()) {
  const audited = new Map(coverageRows(match, now).rows.map(row => [row.key, row]));
  return Object.entries(LABELS).map(([key, label]) => {
    const item = audited.get(key);
    return { key, label, state: STATES[item?.state] || "Sin auditoría", source: item?.source || "Fuente no identificada",
      checkedAt: item?.checkedAt || null, detail: item?.detail || "No hay evidencia de esta fuente en la revisión del partido.", effect: EFFECT[key] };
  });
}

export function picksForDay(picks, matches, day, now = Date.now()) {
  const byId = new Map(matches.map(m => [m.id, m]));
  return (picks || []).filter(p => {
    const m = byId.get(p.match_id);
    return m && m.date === day && !m.finished && new Date(m.kickoff).getTime() > now
      && m.recommendation?.decision !== "no_pick" && validProbabilities(m.probs);
  }).slice(0, 5);
}
