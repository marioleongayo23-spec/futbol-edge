const MARKET_LABELS = {
  "1x2": "1X2",
  ou25: "Goles O/U 2,5",
  btts: "Ambos marcan",
  alternate_totals_corners: "Córners",
  alternate_totals_cards: "Tarjetas",
  spreads: "Hándicap asiático",
  alternate_spreads: "Hándicap asiático",
  player_shots: "Remates jugador",
  player_shots_on_target: "A puerta jugador",
  player_to_receive_card: "Tarjeta jugador",
};

export function marketLabel(key) {
  return MARKET_LABELS[key] || String(key || "Mercado");
}

export function selectionLabel(row) {
  const parts = [];
  if (row?.player) parts.push(row.player);
  if (row?.selection) parts.push(row.selection);
  if (row?.line != null) parts.push(String(row.line));
  return parts.join(" · ") || "—";
}

export function quoteEvidence(row, now = Date.now()) {
  const sourceMs = Date.parse(row?.source_updated_at || "");
  if (!Number.isFinite(sourceMs)) return "unverified";
  const ageMinutes = (now - sourceMs) / 60000;
  if (ageMinutes < -5 || ageMinutes > 180) return "stale";
  return "verified_recent";
}

export function actionableValueRows(rows, minEdge = 0.02, now = Date.now()) {
  // The ranking must not silently trust old saved rows from the bundled feed.
  return (Array.isArray(rows) ? rows : [])
    .filter((row) => {
      const edge = row?.edge, odds = row?.odds;
      const kickoff = Date.parse(row?.kickoff || "");
      return Number.isFinite(edge) && edge > minEdge &&
        Number.isFinite(odds) && odds > 1 &&
        Number.isFinite(kickoff) && kickoff > now &&
        quoteEvidence(row, now) === "verified_recent" &&
        (row?.modelProb == null ||
          (Number.isFinite(row.modelProb) && row.modelProb >= 0 && row.modelProb <= 1));
    })
    .sort((a, b) => b.edge - a.edge);
}

export function excludedQuoteCounts(rows, now = Date.now()) {
  const counts = { unverified: 0, stale: 0 };
  for (const row of Array.isArray(rows) ? rows : []) {
    const status = quoteEvidence(row, now);
    if (status in counts) counts[status] += 1;
  }
  return counts;
}
