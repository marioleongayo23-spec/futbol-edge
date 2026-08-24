export function marketMovementRows(odds) {
  const meta = odds?.meta;
  const opening = meta?.opening_1x2;
  const latest = meta?.latest_1x2 || meta?.closing_1x2;
  if (!opening || !latest) return [];
  return ["1", "X", "2"].flatMap((selection) => {
    const from = Number(opening[selection]);
    const to = Number(latest[selection]);
    if (!(from > 1) || !(to > 1)) return [];
    const movement = Number(meta?.movement_pct?.[selection]);
    const pct = Number.isFinite(movement) ? movement : 100 * (to - from) / from;
    return [{
      selection,
      opening: from,
      latest: to,
      movementPct: +pct.toFixed(1),
      direction: to < from ? "shortening" : to > from ? "drifting" : "flat",
    }];
  });
}

export function marketMovementSourceLabel(odds) {
  const source = odds?.meta?.movement_source;
  if (source === "market_average") return "media de mercado";
  if (source === "Bet365") return "Bet365 (fallback)";
  return "mercado";
}
