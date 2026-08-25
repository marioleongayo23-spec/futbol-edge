import { teamProfile, teamSquad } from "./teams.js";

const norm = (value) => String(value || "")
  .normalize("NFD")
  .replace(/[\u0300-\u036f]/g, "")
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, " ")
  .trim();

const same = (a, b) => Boolean(norm(a) && norm(a) === norm(b));
const ts = (value) => {
  const n = new Date(value || 0).getTime();
  return Number.isFinite(n) ? n : 0;
};

export const TEAM_STYLE_DIMENSIONS = [
  ["attack_volume", "Volumen ofensivo", false],
  ["territorial_pressure", "Presión territorial", false],
  ["defensive_exposure", "Exposición defensiva", true],
  ["finishing_efficiency", "Eficacia de remate", false],
  ["contact_intensity", "Intensidad de contacto", false],
];

function sideStyle(match, team) {
  const matchup = match?.tactical_matchup;
  if (!matchup) return null;
  if (same(match.home, team)) return { ...matchup.home, venue: "home", matchup };
  if (same(match.away, team)) return { ...matchup.away, venue: "away", matchup };
  return null;
}

export function teamStyleSnapshots(matches, team) {
  const rows = (matches || [])
    .map((match) => ({ match, side: sideStyle(match, team) }))
    .filter((row) => row.side?.style_vector)
    .sort((a, b) => ts(b.match.kickoff) - ts(a.match.kickoff));
  const home = rows.find((row) => row.side.venue === "home") || null;
  const away = rows.find((row) => row.side.venue === "away") || null;
  const latest = rows[0] || null;
  return { home, away, latest };
}

export function teamStyleTraits(snapshot) {
  const vector = snapshot?.side?.style_vector || {};
  return TEAM_STYLE_DIMENSIONS.map(([key, label, adverse]) => {
    const row = vector[key] || {};
    const score = Number.isFinite(Number(row.score)) ? Number(row.score) : null;
    return { key, label: row.label || label, score, observed: row.observed ?? null, unit: row.unit || "", adverse };
  }).filter((row) => row.score != null);
}

export function teamFixtureContext(matches, team, now = Date.now()) {
  const fixtures = (matches || []).filter((m) => same(m.home, team) || same(m.away, team));
  const next = fixtures
    .filter((m) => !m.finished && ts(m.kickoff) >= now - 60 * 60 * 1000)
    .sort((a, b) => ts(a.kickoff) - ts(b.kickoff))[0] || null;
  const recent = fixtures
    .filter((m) => m.finished && Array.isArray(m.result))
    .sort((a, b) => ts(b.kickoff) - ts(a.kickoff));
  return { next, recent };
}

function matchXi(match, team) {
  const lineup = match?.alineacion || {};
  if (same(match?.home, team)) return lineup.local || [];
  if (same(match?.away, team)) return lineup.visitante || [];
  return [];
}

export function xiContinuity(matches, team) {
  const lineups = (matches || [])
    .filter((m) => same(m.home, team) || same(m.away, team))
    .map((match) => ({ kickoff: match.kickoff, xi: matchXi(match, team) }))
    .filter((row) => Array.isArray(row.xi) && row.xi.length >= 8)
    .sort((a, b) => ts(b.kickoff) - ts(a.kickoff));
  if (lineups.length < 2) return { pct: null, shared: null, sample: lineups.length };
  const a = new Set(lineups[0].xi.map(norm));
  const b = new Set(lineups[1].xi.map(norm));
  const shared = [...a].filter((name) => b.has(name)).length;
  const denom = Math.max(a.size, b.size, 11);
  return { pct: Math.round((shared / denom) * 100), shared, sample: 2 };
}

function absenceRows(match, team) {
  if (!match) return [];
  const lineup = match.alineacion || {};
  const home = same(match.home, team);
  const candidates = home
    ? [lineup.bajas_local, lineup.ausencias_local, lineup.availability_home, match.absences_home]
    : [lineup.bajas_visitante, lineup.ausencias_visitante, lineup.availability_away, match.absences_away];
  const rows = candidates.find(Array.isArray) || [];
  return rows.map((row) => typeof row === "string" ? { jugador: row } : row).filter(Boolean);
}

export function teamIntelligence(matches, players, team, now = Date.now()) {
  const base = teamProfile(matches || [], team);
  const style = teamStyleSnapshots(matches, team);
  const context = teamFixtureContext(matches, team, now);
  const continuity = xiContinuity(matches, team);
  const squad = teamSquad(players, team);
  const keyPlayers = squad.slice(0, 4);
  const next = context.next;
  const isHome = next ? same(next.home, team) : null;
  const opponent = next ? (isHome ? next.away : next.home) : null;
  const nextStyle = next ? sideStyle(next, team) : null;
  const matchup = next?.tactical_matchup || null;
  const opponentStyle = next
    ? (isHome ? matchup?.away : matchup?.home)
    : null;
  return {
    base,
    style,
    context,
    continuity,
    keyPlayers,
    absences: absenceRows(next, team),
    next: next ? {
      match: next,
      isHome,
      opponent,
      ownStyle: nextStyle,
      opponentStyle,
      clashes: matchup?.style_clashes || [],
    } : null,
  };
}
