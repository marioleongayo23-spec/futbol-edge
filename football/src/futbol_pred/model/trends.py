"""Tendencia de las estadísticas esperadas (al alza / a la baja).

La predicción base (Dixon-Coles / medias de stats) dice el valor ESPERADO. Pero
un valor esperado es difícil de clavar: este módulo estima si, para un partido
concreto, cabe esperar MÁS o MENOS de lo habitual, mirando el contexto:

  * forma reciente de cada equipo en esa métrica vs su propia media,
  * días de descanso (menos descanso -> menos goles, más faltas/tarjetas).

No sustituye a la predicción: la matiza con una flecha ↑/→/↓, una magnitud (%)
y un motivo legible. Métricas: goles (total), córners, tarjetas, remates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

RECENT = 5      # ventana de "forma reciente"
MIN_N = 3       # mínimo de partidos para dar tendencia
UP = 0.06       # umbral relativo para marcar ↑/↓ (6%)
REST_LOW = 3    # días de descanso "justo" (fatiga)

# Métricas de TOTAL de partido y cómo les afecta el poco descanso.
#   fatigue = signo del efecto de MENOS descanso sobre la métrica.
METRICS = {
    "goals": {"label": "Goles", "fatigue": -1},
    "corners": {"label": "Córners", "fatigue": 0},
    "yellows": {"label": "Tarjetas", "fatigue": +1},
    "shots": {"label": "Remates", "fatigue": -1},
}


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


@dataclass
class TrendModel:
    # equipo -> métrica -> lista de TOTALES de partido (orden cronológico)
    totals: dict = field(default_factory=dict)
    last_played: dict = field(default_factory=dict)  # equipo -> fecha último jugado

    def _add(self, team: str, metric: str, total: float) -> None:
        self.totals.setdefault(team, {}).setdefault(metric, []).append(total)

    def fit(self, fixtures, stats_rows, canon) -> "TrendModel":
        """fixtures: con goles reales (para 'goals' y descanso).
        stats_rows: MatchStats de co.uk (córners, tarjetas, remates)."""
        for fx in sorted(
            (f for f in fixtures if f.home_goals is not None),
            key=lambda f: f.kickoff,
        ):
            h, a = canon(fx.home_team), canon(fx.away_team)
            tot = fx.home_goals + fx.away_goals
            self._add(h, "goals", tot)
            self._add(a, "goals", tot)
            self.last_played[h] = fx.kickoff
            self.last_played[a] = fx.kickoff
        for r in stats_rows:
            h, a = canon(r.home_team), canon(r.away_team)
            for metric in ("corners", "yellows", "shots"):
                if metric in r.stats:
                    tot = r.stats[metric][0] + r.stats[metric][1]
                    self._add(h, metric, tot)
                    self._add(a, metric, tot)
        return self

    def _delta(self, team: str, metric: str):
        """(delta_relativo, media_equipo) de la forma reciente vs su media, o None."""
        seq = self.totals.get(team, {}).get(metric)
        if not seq or len(seq) < MIN_N:
            return None
        base = _mean(seq)
        recent = _mean(seq[-RECENT:])
        if not base:
            return None
        return (recent - base) / base, base

    def _rest_days(self, team: str, kickoff) -> int | None:
        prev = self.last_played.get(team)
        if prev is None:
            return None
        try:
            return max(0, (kickoff - prev).days)
        except (TypeError, ValueError):
            return None

    def trend(self, home: str, away: str, kickoff=None) -> dict:
        """Tendencia por métrica: {metric: {dir, pct, label, reason}}."""
        out: dict = {}
        rest_h = self._rest_days(home, kickoff) if kickoff else None
        rest_a = self._rest_days(away, kickoff) if kickoff else None
        for metric, cfg in METRICS.items():
            dh, da = self._delta(home, metric), self._delta(away, metric)
            deltas = [d for d, _ in (x for x in (dh, da) if x)]
            if not deltas:
                # Siempre devolvemos algo: neutro cuando no hay muestra fiable.
                out[metric] = {"dir": "flat", "pct": 0, "label": cfg["label"],
                               "reason": "sin muestra suficiente todavía"}
                continue
            signal = sum(deltas) / len(deltas)

            # Modificador por descanso (fatiga) sobre goles/tarjetas/remates.
            reasons = []
            both_up = dh and da and dh[0] > 0 and da[0] > 0
            both_down = dh and da and dh[0] < 0 and da[0] < 0
            if both_up:
                reasons.append(f"ambos por encima de su media reciente en {cfg['label'].lower()}")
            elif both_down:
                reasons.append(f"ambos por debajo de su media reciente en {cfg['label'].lower()}")
            elif abs(signal) >= UP:
                who = home if (dh and abs(dh[0]) >= abs(da[0] if da else 0)) else away
                reasons.append(f"{who} marca la tendencia en {cfg['label'].lower()}")

            fat = cfg["fatigue"]
            if fat and ((rest_h is not None and rest_h <= REST_LOW) or
                        (rest_a is not None and rest_a <= REST_LOW)):
                signal += fat * 0.05
                reasons.append("poco descanso" + (" (menos goles/remates)" if fat < 0 else " (más tarjetas)"))

            direction = "up" if signal >= UP else "down" if signal <= -UP else "flat"
            out[metric] = {
                "dir": direction,
                "pct": round(signal * 100),
                "label": cfg["label"],
                "reason": "; ".join(reasons) or "sin señal clara",
            }
        return out
