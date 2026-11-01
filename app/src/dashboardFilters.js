/** Pure competition filters for the matchday workspace. */
export const ALL_LEAGUES = "all";

export function competitionFilters(matches) {
  const counts = new Map();
  for (const match of Array.isArray(matches) ? matches : []) {
    if (!match || typeof match.league !== "string" || !match.league.trim()) continue;
    counts.set(match.league, (counts.get(match.league) || 0) + 1);
  }
  return [
    { key: ALL_LEAGUES, label: "Todos", count: Array.isArray(matches) ? matches.length : 0 },
    ...[...counts].sort(([a], [b]) => a.localeCompare(b, "es")).map(([key, count]) =>
      ({ key, label: key === "LaLiga Hypermotion" ? "Segunda" : key === "Champions League" ? "Champions" : key, count })),
  ];
}

export function visibleMatchday(matches, league) {
  const rows = Array.isArray(matches) ? matches : [];
  return !league || league === ALL_LEAGUES ? rows : rows.filter(m => m?.league === league);
}
