const CLUB_WORDS = new Set(["fc", "cf", "cd", "ud", "club", "deportivo", "de"]);

export const OFFICIAL_STAT_METRICS = [
  ["shots", "Remates"],
  ["sot", "Tiros a puerta"],
  ["corners", "Córners"],
  ["fouls", "Faltas"],
  ["yellows", "Amarillas"],
  ["reds", "Rojas"],
  ["offsides", "Fueras de juego"],
  ["possession", "Posesión", "%"],
  ["passes", "Pases"],
  ["passes_accurate", "Pases precisos"],
  ["pass_accuracy", "Precisión de pase", "%"],
  ["saves", "Paradas"],
];

export function normalizeClubName(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter((token) => token && !CLUB_WORDS.has(token))
    .join(" ");
}

function teamScore(expected, actual) {
  const a = normalizeClubName(expected);
  const b = normalizeClubName(actual);
  if (!a || !b) return 0;
  if (a === b) return 1;
  if (a.includes(b) || b.includes(a)) return 0.9;
  const left = new Set(a.split(" "));
  const right = new Set(b.split(" "));
  let common = 0;
  for (const token of left) common += right.has(token) ? 1 : 0;
  return common / Math.max(left.size, right.size, 1);
}

function pickEntry(entries, team, excluded = new Set()) {
  let best = null;
  for (let index = 0; index < entries.length; index += 1) {
    if (excluded.has(index)) continue;
    const [name, stats] = entries[index];
    const score = teamScore(team, name);
    if (!best || score > best.score) best = { index, name, stats, score };
  }
  return best && best.score >= 0.5 ? best : null;
}

export function officialTeamStats(context, home, away) {
  const raw = context?.live_or_post_stats;
  if (!raw || typeof raw !== "object") return null;
  const entries = Object.entries(raw).filter(([, stats]) => stats && typeof stats === "object");
  if (entries.length < 2) return null;

  const homeEntry = pickEntry(entries, home);
  const excluded = new Set(homeEntry ? [homeEntry.index] : []);
  const awayEntry = pickEntry(entries, away, excluded);

  // API-Football mantiene el orden local/visitante. Solo usamos ese fallback si
  // los nombres no pudieron resolverse con suficiente confianza.
  const resolvedHome = homeEntry || { index: 0, name: entries[0][0], stats: entries[0][1] };
  const fallbackAwayIndex = resolvedHome.index === 0 ? 1 : 0;
  const resolvedAway = awayEntry || {
    index: fallbackAwayIndex,
    name: entries[fallbackAwayIndex]?.[0],
    stats: entries[fallbackAwayIndex]?.[1],
  };
  if (!resolvedHome.stats || !resolvedAway.stats) return null;
  return { home: resolvedHome.stats, away: resolvedAway.stats };
}

export function officialStatsRows(context, home, away) {
  const teams = officialTeamStats(context, home, away);
  if (!teams) return [];
  return OFFICIAL_STAT_METRICS.flatMap(([key, label, suffix = ""]) => {
    const homeValue = teams.home?.[key];
    const awayValue = teams.away?.[key];
    if (homeValue == null && awayValue == null) return [];
    return [{ key, label, suffix, home: homeValue ?? "—", away: awayValue ?? "—" }];
  });
}

export function formatOfficialStat(value, suffix = "") {
  if (value === "—" || value == null) return "—";
  const number = Number(value);
  const display = Number.isFinite(number)
    ? (Number.isInteger(number) ? String(number) : number.toFixed(1))
    : String(value);
  return `${display}${suffix}`;
}
