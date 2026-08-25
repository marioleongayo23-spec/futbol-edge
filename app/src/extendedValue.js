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

export function actionableValueRows(rows, minEdge = 0.02) {
  return (rows || [])
    .filter((row) => Number(row?.edge) > minEdge && Number(row?.odds) > 1)
    .sort((a, b) => Number(b.edge) - Number(a.edge));
}
