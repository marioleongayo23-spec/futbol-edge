export function marketMovementRows(odds) {
  const meta = odds?.meta;
  const opening = meta?.opening_1x2;
  const closing = meta?.closing_1x2;
  if (!opening || !closing) return [];
  return ["1", "X", "2"].flatMap((selection) => {
    const from = Number(opening[selection]);
    const to = Number(closing[selection]);
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
