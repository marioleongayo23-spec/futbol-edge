function key(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

export function findBetMatch(bet, matches) {
  if (!bet || !Array.isArray(matches)) return null;
  if (bet.matchId) {
    const exact = matches.find((match) => String(match.id) === String(bet.matchId));
    if (exact) return exact;
  }
  const wanted = key(bet.match);
  if (!wanted) return null;
  return matches.find((match) => key(`${match.home} - ${match.away}`) === wanted) || null;
}

export function closingSourceLabel(closing) {
  const source = closing?.market_source;
  if (source === "market_average") return "media de mercado";
  if (source === "Bet365") return "Bet365 (fallback)";
  if (source === "The Odds API consensus") return "consenso The Odds API · T−2h";
  if (source === "football-data.co.uk") return "football-data.co.uk";
  return source || "mercado real";
}

export function betClv(bet, matches) {
  if (!bet || !["1", "X", "2"].includes(bet.sel)) return null;
  const match = findBetMatch(bet, matches);
  if (!match?.finished) return null;
  const closing = match.closing_odds;
  // CLV nunca se calcula contra cuotas sample, inferidas o sin procedencia real.
  if (closing?.is_real !== true) return null;
  const prices = closing?.["1x2"];
  if (!prices) return null;
  const taken = Number(bet.odds);
  const close = Number(prices[bet.sel]);
  const triple = ["1", "X", "2"].map((selection) => Number(prices[selection]));
  if (!(taken > 1) || !(close > 1) || triple.some((price) => !(price > 1))) return null;

  const inverse = triple.map((price) => 1 / price);
  const totalInverse = inverse.reduce((sum, value) => sum + value, 0);
  const selectionIndex = ["1", "X", "2"].indexOf(bet.sel);
  const closingFairProb = inverse[selectionIndex] / totalInverse;
  const breakEvenProb = 1 / taken;
  const priceClvPct = 100 * (taken / close - 1);
  const fairEdgePp = 100 * (closingFairProb - breakEvenProb);

  return {
    bet,
    match,
    takenOdds: taken,
    closingOdds: close,
    priceClvPct: +priceClvPct.toFixed(2),
    closingFairProbPct: +(closingFairProb * 100).toFixed(2),
    breakEvenProbPct: +(breakEvenProb * 100).toFixed(2),
    fairEdgePp: +fairEdgePp.toFixed(2),
    source: closingSourceLabel(closing),
    capturedAt: closing.captured_at || null,
    captureKind: closing.capture_kind || null,
  };
}

export function portfolioClv(bets, matches) {
  const rows = (bets || []).map((bet) => betClv(bet, matches)).filter(Boolean);
  if (!rows.length) {
    return { rows: [], n: 0, averagePct: null, stakeWeightedPct: null, positiveRatePct: null, averageFairEdgePp: null };
  }
  const averagePct = rows.reduce((sum, row) => sum + row.priceClvPct, 0) / rows.length;
  const weightedStake = rows.reduce((sum, row) => sum + Math.max(0, Number(row.bet.stake) || 0), 0);
  const stakeWeightedPct = weightedStake
    ? rows.reduce((sum, row) => sum + row.priceClvPct * Math.max(0, Number(row.bet.stake) || 0), 0) / weightedStake
    : averagePct;
  const positiveRatePct = 100 * rows.filter((row) => row.priceClvPct > 0).length / rows.length;
  const averageFairEdgePp = rows.reduce((sum, row) => sum + row.fairEdgePp, 0) / rows.length;
  return {
    rows,
    n: rows.length,
    averagePct: +averagePct.toFixed(2),
    stakeWeightedPct: +stakeWeightedPct.toFixed(2),
    positiveRatePct: +positiveRatePct.toFixed(1),
    averageFairEdgePp: +averageFairEdgePp.toFixed(2),
  };
}
