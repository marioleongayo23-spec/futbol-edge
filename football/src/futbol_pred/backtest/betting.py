"""Simulación de apuestas sobre un backtest: ROI, yield, drawdown, hit rate.

Convierte predicciones + cuotas históricas en una curva de bankroll realista
(tu #44, #58). Solo apuesta cuando hay edge suficiente; stake por Kelly
fraccionado. Esta es la prueba de fuego: ¿el edge del modelo sobrevive al
margen de la casa?
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..value.bankroll import BankrollPolicy


@dataclass
class BetLog:
    round: object
    match: str
    selection: str
    odds: float
    prob: float
    edge: float
    stake: float
    won: bool
    pnl: float
    bankroll_after: float


@dataclass
class BettingResult:
    log: list[BetLog] = field(default_factory=list)
    start_bankroll: float = 1000.0
    end_bankroll: float = 1000.0

    @property
    def n_bets(self) -> int:
        return len(self.log)

    @property
    def total_staked(self) -> float:
        return sum(b.stake for b in self.log)

    @property
    def profit(self) -> float:
        return self.end_bankroll - self.start_bankroll

    @property
    def roi(self) -> float:
        """Retorno sobre lo apostado (yield)."""
        return self.profit / self.total_staked if self.total_staked else 0.0

    @property
    def hit_rate(self) -> float:
        return sum(1 for b in self.log if b.won) / self.n_bets if self.n_bets else 0.0

    @property
    def max_drawdown(self) -> float:
        """Máxima caída desde un pico del bankroll (fracción)."""
        peak = self.start_bankroll
        mdd = 0.0
        for b in self.log:
            peak = max(peak, b.bankroll_after)
            if peak > 0:
                mdd = max(mdd, (peak - b.bankroll_after) / peak)
        return mdd

    def summary(self) -> dict:
        return {
            "n_bets": self.n_bets,
            "total_staked": round(self.total_staked, 2),
            "profit": round(self.profit, 2),
            "roi": round(self.roi, 4),
            "hit_rate": round(self.hit_rate, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "end_bankroll": round(self.end_bankroll, 2),
        }


def simulate_bets(
    records: list[dict],
    policy: BankrollPolicy | None = None,
    start_bankroll: float = 1000.0,
) -> BettingResult:
    """Simula apuestas sobre los registros de un backtest.

    Cada registro necesita: 'probs' (dict 1X2), 'actual', y 'odds' (dict 1X2
    con cuotas decimales). Los que no traen cuotas se ignoran.
    El stake se recalcula sobre el bankroll vivo (compounding).
    """
    policy = policy or BankrollPolicy()
    bankroll = start_bankroll
    result = BettingResult(start_bankroll=start_bankroll)

    for rec in records:
        odds = rec.get("odds")
        if not odds:
            continue
        probs = rec["probs"]
        actual = rec["actual"]
        # Elegimos la selección con mayor edge positivo.
        best = None
        for sel in ("1", "X", "2"):
            if sel not in odds:
                continue
            edge = probs[sel] * odds[sel] - 1.0
            if best is None or edge > best[1]:
                best = (sel, edge)
        if best is None:
            continue
        sel, edge = best
        stake = policy.stake(bankroll, probs[sel], odds[sel])
        if stake <= 0:
            continue
        won = actual == sel
        pnl = stake * (odds[sel] - 1.0) if won else -stake
        bankroll += pnl
        result.log.append(BetLog(
            round=rec.get("round"),
            match=f"{rec.get('home')} vs {rec.get('away')}",
            selection=sel,
            odds=odds[sel],
            prob=probs[sel],
            edge=edge,
            stake=stake,
            won=won,
            pnl=round(pnl, 2),
            bankroll_after=round(bankroll, 2),
        ))

    result.end_bankroll = bankroll
    return result
