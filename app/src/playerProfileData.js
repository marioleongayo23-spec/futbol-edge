const strip = (value) => String(value || "")
  .normalize("NFD")
  .replace(/[\u0300-\u036f]/g, "")
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, " ")
  .trim();

export function samePlayer(a, b) {
  if (!a || !b) return false;
  const nameA = strip(a.player || a.jugador || a.name);
  const nameB = strip(b.player || b.jugador || b.name);
  const teamA = strip(a.team || a.equipo);
  const teamB = strip(b.team || b.equipo);
  return Boolean(nameA && nameA === nameB && (!teamA || !teamB || teamA === teamB));
}

export function flattenPlayers(players) {
  if (!players) return [];
  return Object.values(players).flatMap((league) => Array.isArray(league?.players) ? league.players : []);
}

export function resolvePlayer(players, candidate) {
  const rows = flattenPlayers(players);
  return rows.find((row) => samePlayer(row, candidate)) || candidate || null;
}

export function positionGroup(position) {
  const p = strip(position);
  if (/goal|keeper|portero|gk/.test(p)) return "goalkeeper";
  if (/def|back|centre back|center back|lateral|cb|lb|rb/.test(p)) return "defender";
  if (/mid|medio|volante|dm|cm|am/.test(p)) return "midfielder";
  if (/att|forward|striker|wing|delantero|extremo|fw|st/.test(p)) return "attacker";
  return "other";
}

const number = (value) => {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

export function percentile(value, sample, higherIsBetter = true) {
  const v = number(value);
  const clean = sample.map(number).filter((x) => x != null);
  if (v == null || clean.length < 5) return null;
  const below = clean.filter((x) => x < v).length;
  const equal = clean.filter((x) => x === v).length;
  const raw = (below + 0.5 * equal) / clean.length;
  const p = higherIsBetter ? raw : 1 - raw;
  return Math.max(1, Math.min(99, Math.round(p * 100)));
}

export const PROFILE_METRICS = [
  { key: "g", label: "Goles /90", short: "Gol", path: ["season", "per90", "g"] },
  { key: "a", label: "Asistencias /90", short: "Asis", path: ["season", "per90", "a"] },
  { key: "shots", label: "Remates /90", short: "Rem", path: ["season", "per90", "r"] },
  { key: "sot", label: "A puerta /90", short: "AP", path: ["season", "per90", "rp"] },
  { key: "key_passes", label: "Pases clave /90", short: "PC", path: ["season", "per90_extended", "key_passes"] },
  { key: "duels_won", label: "Duelos ganados /90", short: "Duel", path: ["season", "per90_extended", "duels_won"] },
  { key: "tackles", label: "Entradas /90", short: "Ent", path: ["season", "per90_extended", "tackles"] },
  { key: "interceptions", label: "Intercepciones /90", short: "Int", path: ["season", "per90_extended", "interceptions"] },
  { key: "dribbles", label: "Regates buenos /90", short: "Reg", path: ["season", "per90_extended", "dribbles_success"] },
  { key: "fouls_drawn", label: "Faltas recibidas /90", short: "FR", path: ["season", "per90", "fr"] },
  { key: "fouls", label: "Faltas cometidas /90", short: "FC", path: ["season", "per90", "fc"], higherIsBetter: false },
];

export function getPath(row, path) {
  let cur = row;
  for (const key of path) cur = cur?.[key];
  return number(cur);
}

export function playerMetricRows(players, player) {
  const resolved = resolvePlayer(players, player);
  if (!resolved) return [];
  const group = positionGroup(resolved.position || resolved.api_position);
  const peers = flattenPlayers(players).filter((row) => {
    if (positionGroup(row.position || row.api_position) !== group) return false;
    return number(row?.season?.minutes ?? row.sample_minutes ?? row.min) >= 270;
  });
  return PROFILE_METRICS.map((metric) => {
    const value = getPath(resolved, metric.path);
    const sample = peers.map((row) => getPath(row, metric.path)).filter((x) => x != null);
    return {
      ...metric,
      value,
      sample: sample.length,
      percentile: percentile(value, sample, metric.higherIsBetter !== false),
    };
  }).filter((metric) => metric.value != null);
}

export function nextFixture(matches, player) {
  const team = player?.team;
  if (!team) return null;
  const now = Date.now();
  return (matches || [])
    .filter((m) => !m.finished && (m.home === team || m.away === team))
    .filter((m) => {
      const t = new Date(m.kickoff || 0).getTime();
      return Number.isFinite(t) && t >= now - 60 * 60 * 1000;
    })
    .sort((a, b) => new Date(a.kickoff) - new Date(b.kickoff))[0] || null;
}

export function profileCompleteness(player) {
  if (!player) return 0;
  const checks = [
    player.profile?.photo,
    player.profile?.age,
    player.profile?.nationality,
    player.position || player.api_position,
    player.rating,
    player.season?.minutes ?? player.sample_minutes ?? player.min,
    player.season?.per90,
    player.season?.per90_extended,
  ];
  return Math.round(100 * checks.filter(Boolean).length / checks.length);
}
