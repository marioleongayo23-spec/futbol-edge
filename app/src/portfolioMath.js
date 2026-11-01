// Importes de cartera en números finitos; apuestas nulas no cuentan como stake liquidado.
export function validBet(odds, stake) {
  return Number.isFinite(odds) && odds > 1 && Number.isFinite(stake) && stake > 0;
}

export function portfolioStats(bets = []) {
  const settled = bets.filter((bet) => bet.result === "won" || bet.result === "lost");
  const staked = settled.reduce((sum, bet) => sum + Number(bet.stake || 0), 0);
  const profit = settled.reduce((sum, bet) => sum + (bet.result === "won"
    ? Number(bet.stake || 0) * (Number(bet.odds || 1) - 1)
    : -Number(bet.stake || 0)), 0);
  const wins = settled.filter((bet) => bet.result === "won").length;
  return {
    settled: settled.length,
    staked, profit, wins,
    roi: staked > 0 ? profit / staked * 100 : null,
    hit: settled.length ? wins / settled.length * 100 : null,
  };
}
