"""Tendencia de las estadísticas esperadas, por ESTILO de los dos equipos.

No mira la media de la liga: mira a ESTE local y ESTE visitante y sus condiciones,
con histórico de varias temporadas separando local/visitante y a favor/en contra.

Ejemplo: Atlético (local, dominador) vs Elche (visitante, se encierra) → más
córners y remates, y sobre todo para el Atlético, porque genera mucho en casa y
el Elche concede fuera. La tendencia (↑/→/↓) compara lo esperado de ESTE
emparejamiento con lo normal PARA ESTOS DOS EQUIPOS, y explica el motivo por
estilo. Un modificador por días de descanso ajusta goles/remates/tarjetas.
"""

from __future__ import annotations

from dataclasses import dataclass, field

RECENT = 5      # ventana de "forma reciente"
MIN_SPLIT = 2   # mínimo de partidos (local o visitante) para señal de estilo
UP = 0.06       # umbral relativo para marcar ↑/↓ (6%)
DOM = 0.18      # cuánto debe pesar un lado para decir "más para X"
REST_LOW = 3    # días de descanso "justo" (fatiga)

# Métricas con split local/visitante (de co.uk) + goles (de resultados).
#   fatigue = efecto de MENOS descanso sobre la métrica.
METRICS = {
    "goals": {"label": "Goles", "fatigue": -1},
    "shots": {"label": "Remates", "fatigue": -1},
    "corners": {"label": "Córners", "fatigue": 0},
    "fouls": {"label": "Faltas", "fatigue": +1},
    "yellows": {"label": "Tarjetas", "fatigue": +1},
}
_SPLIT_METRICS = ("shots", "corners", "fouls", "yellows")


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


@dataclass
class TrendModel:
    # equipo -> métrica -> {hf,ha,af,aa}: a favor/en contra como local/visitante.
    stat: dict = field(default_factory=dict)
    # equipo -> métrica -> lista de TOTALES de partido (para forma y referencia).
    totals: dict = field(default_factory=dict)
    last_played: dict = field(default_factory=dict)

    def _bucket(self, team, metric):
        return self.stat.setdefault(team, {}).setdefault(
            metric, {"hf": [], "ha": [], "af": [], "aa": []})

    def _add(self, home, away, metric, vh, va):
        """vh/va = valor del local/visitante en esa métrica en ese partido."""
        bh = self._bucket(home, metric)
        bh["hf"].append(vh)   # local: a favor en casa
        bh["ha"].append(va)   # local: en contra en casa
        ba = self._bucket(away, metric)
        ba["af"].append(va)   # visitante: a favor fuera
        ba["aa"].append(vh)   # visitante: en contra fuera
        self.totals.setdefault(home, {}).setdefault(metric, []).append(vh + va)
        self.totals.setdefault(away, {}).setdefault(metric, []).append(vh + va)

    def fit(self, fixtures, stats_rows, canon) -> "TrendModel":
        for fx in sorted((f for f in fixtures if f.home_goals is not None),
                         key=lambda f: f.kickoff):
            h, a = canon(fx.home_team), canon(fx.away_team)
            self._add(h, a, "goals", fx.home_goals, fx.away_goals)
            self.last_played[h] = fx.kickoff
            self.last_played[a] = fx.kickoff
        for r in stats_rows:
            h, a = canon(r.home_team), canon(r.away_team)
            for m in _SPLIT_METRICS:
                if m in r.stats:
                    self._add(h, a, m, r.stats[m][0], r.stats[m][1])
        return self

    def _avg(self, team, metric, key):
        return _mean(self.stat.get(team, {}).get(metric, {}).get(key, []))

    def _overall(self, team, metric):
        return _mean(self.totals.get(team, {}).get(metric, []))

    def _recent_delta(self, team, metric):
        seq = self.totals.get(team, {}).get(metric, [])
        base = _mean(seq)
        rec = _mean(seq[-RECENT:])
        if base and rec is not None and len(seq) >= MIN_SPLIT:
            return (rec - base) / base
        return None

    def _rest_days(self, team, kickoff):
        prev = self.last_played.get(team)
        if prev is None:
            return None
        try:
            return max(0, (kickoff - prev).days)
        except (TypeError, ValueError):
            return None

    def trend(self, home, away, kickoff=None, predicted=None) -> dict:
        out = {}
        rest_h = self._rest_days(home, kickoff) if kickoff else None
        rest_a = self._rest_days(away, kickoff) if kickoff else None
        for metric, cfg in METRICS.items():
            lab = cfg["label"].lower()
            hf, ha = self._avg(home, metric, "hf"), self._avg(home, metric, "ha")
            af, aa = self._avg(away, metric, "af"), self._avg(away, metric, "aa")
            # Lado local del partido: lo que genera el local en casa y lo que
            # concede el visitante fuera. Lado visitante, simétrico.
            exp_home = _mean([x for x in (hf, aa) if x is not None])
            exp_away = _mean([x for x in (af, ha) if x is not None])
            reasons = []
            signal = None

            if exp_home is not None and exp_away is not None:
                match_exp = exp_home + exp_away
                ref = _mean([x for x in (self._overall(home, metric),
                                         self._overall(away, metric)) if x is not None])
                if ref:
                    signal = (match_exp - ref) / ref
                # Reparto: ¿para quién? (estilo local vs visitante)
                if match_exp > 0:
                    share_h = exp_home / match_exp
                    if share_h - 0.5 >= DOM:
                        reasons.append(f"más {lab} para {home} (genera en casa y {away} concede fuera)")
                    elif 0.5 - share_h >= DOM:
                        reasons.append(f"más {lab} para {away}")
                if signal is not None and abs(signal) >= UP:
                    reasons.append(f"emparejamiento de {'mucho' if signal > 0 else 'poco'} {lab} por el estilo de ambos")

            # Forma reciente como matiz secundario (condición del momento).
            if signal is None:
                rd = self._recent_delta(home, metric)
                rd2 = self._recent_delta(away, metric)
                ds = [d for d in (rd, rd2) if d is not None]
                if ds:
                    signal = sum(ds) / len(ds)
                    reasons.append("por la forma reciente de los equipos")

            if signal is None:
                out[metric] = {"dir": "flat", "pct": 0, "label": cfg["label"],
                               "reason": "sin histórico suficiente de estos equipos"}
                continue

            fat = cfg["fatigue"]
            if fat and ((rest_h is not None and rest_h <= REST_LOW) or
                        (rest_a is not None and rest_a <= REST_LOW)):
                signal += fat * 0.05
                reasons.append("poco descanso")

            direction = "up" if signal >= UP else "down" if signal <= -UP else "flat"
            out[metric] = {
                "dir": direction,
                "pct": round(signal * 100),
                "label": cfg["label"],
                "reason": "; ".join(reasons) or "equilibrado para estos equipos",
            }
        return out
