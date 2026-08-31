"""Tendencia de las estadísticas esperadas, por ESTILO de los dos equipos.

Cruza el histórico multi-temporada de ESTE local y ESTE visitante (separando
local/visitante y a favor/en contra) para estimar lo que producirá el partido, y
compara ese total esperado con la MEDIA DE LA LIGA para marcar ↑/→/↓.

Ejemplo: Atlético (local, dominador) vs Elche (visitante, se encierra) → más
córners y remates, y sobre todo para el Atlético, porque genera mucho en casa y
el Elche concede fuera. La dirección (↑/→/↓) dice si el emparejamiento produce
más o menos que un partido TÍPICO DE LA LIGA (antes se comparaba con la media de
los propios equipos y por eso casi todo salía plano), y el motivo explica el
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


def _percentile(value, population):
    """Percentil inclusivo, estable también con muestras pequeñas o empatadas."""
    if value is None:
        return None
    peers = sorted(float(item) for item in population if item is not None)
    if not peers:
        return None
    below = sum(item < value for item in peers)
    equal = sum(item == value for item in peers)
    return round(100 * (below + 0.5 * equal) / len(peers))


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

    def _league_avg(self, metric):
        """Media de la métrica en TODA la liga (referencia para ↑/↓).

        Antes se comparaba el emparejamiento con la media de LOS PROPIOS dos
        equipos, pero como lo esperado se deriva de esos mismos equipos la señal
        era casi siempre ~0 (todo salía 'flat'). Comparar con la media de la liga
        hace que un cruce ofensivo destaque al alza y uno defensivo a la baja.
        """
        vals = [self._overall(team, metric) for team in self.totals]
        return _mean([v for v in vals if v is not None])

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
                # Referencia = media de la LIGA (no de estos dos equipos): así el
                # ↑/↓ significa "más/menos que un partido típico de la liga".
                ref = self._league_avg(metric)
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
                "model_total": round(float(predicted[metric]), 2) if predicted and metric in predicted else None,
            }
        return out

    def matchup_profile(self, home, away) -> dict:
        """Vector táctico empírico a partir de acciones, sin inventar formaciones."""

        def peer_values(metric: str, key: str):
            return [
                self._avg(team, metric, key)
                for team in self.stat
                if self._avg(team, metric, key) is not None
            ]

        def side(team, venue: str) -> dict:
            fav = "hf" if venue == "home" else "af"
            against = "ha" if venue == "home" else "aa"
            samples = len(self.stat.get(team, {}).get("shots", {}).get(fav, []))
            values = {}
            for metric in ("shots", "corners", "fouls", "yellows", "goals"):
                values[metric] = {
                    "for": self._avg(team, metric, fav),
                    "against": self._avg(team, metric, against),
                }
            shots = values["shots"]["for"]
            goals = values["goals"]["for"]
            efficiency = goals / shots if shots and goals is not None else None
            contact = _mean([
                value for value in (
                    values["fouls"]["for"],
                    (values["yellows"]["for"] or 0) * 3
                    if values["yellows"]["for"] is not None else None,
                ) if value is not None
            ])

            def dimension(label, value, population, unit):
                return {
                    "label": label,
                    "score": _percentile(value, population),
                    "observed": round(value, 2) if value is not None else None,
                    "unit": unit,
                }

            efficiencies = []
            contacts = []
            for peer in self.stat:
                peer_shots = self._avg(peer, "shots", fav)
                peer_goals = self._avg(peer, "goals", fav)
                if peer_shots and peer_goals is not None:
                    efficiencies.append(peer_goals / peer_shots)
                peer_fouls = self._avg(peer, "fouls", fav)
                peer_cards = self._avg(peer, "yellows", fav)
                if peer_fouls is not None or peer_cards is not None:
                    contacts.append(_mean([
                        item for item in (
                            peer_fouls,
                            (peer_cards or 0) * 3 if peer_cards is not None else None,
                        ) if item is not None
                    ]))
            return {
                "samples": samples,
                "venue_split": "casa" if venue == "home" else "fuera",
                "actions": values,
                "attack_efficiency_goals_per_shot": round(efficiency, 3) if efficiency is not None else None,
                "style_vector": {
                    "attack_volume": dimension(
                        "Volumen ofensivo", shots, peer_values("shots", fav), "remates/partido"
                    ),
                    "territorial_pressure": dimension(
                        "Presión territorial", values["corners"]["for"],
                        peer_values("corners", fav), "córners/partido",
                    ),
                    "defensive_exposure": dimension(
                        "Exposición defensiva", values["shots"]["against"],
                        peer_values("shots", against), "remates concedidos/partido",
                    ),
                    "finishing_efficiency": dimension(
                        "Eficacia de remate", efficiency, efficiencies, "goles/remate"
                    ),
                    "contact_intensity": dimension(
                        "Intensidad de contacto", contact, contacts, "índice faltas+tarjetas"
                    ),
                },
            }

        hp, ap = side(home, "home"), side(away, "away")
        hs = hp["actions"]["shots"]["for"]
        ac = ap["actions"]["shots"]["against"]
        ass = ap["actions"]["shots"]["for"]
        hc = hp["actions"]["shots"]["against"]
        home_pressure = _mean([value for value in (hs, ac) if value is not None])
        away_pressure = _mean([value for value in (ass, hc) if value is not None])
        evidence = min(hp["samples"], ap["samples"])
        notes = []
        if home_pressure is not None and away_pressure is not None:
            if home_pressure >= away_pressure * 1.2:
                notes.append(f"{home} proyecta más volumen de remate por generación propia y concesión rival")
            elif away_pressure >= home_pressure * 1.2:
                notes.append(f"{away} proyecta más volumen de remate pese a jugar fuera")
            else:
                notes.append("volumen de ataque equilibrado entre ambos perfiles")
        fouls = [
            hp["actions"]["fouls"]["for"], ap["actions"]["fouls"]["for"],
        ]
        if all(value is not None for value in fouls) and sum(fouls) >= 27:
            notes.append("emparejamiento de contacto alto por faltas cometidas")
        clashes = []
        home_attack = hp["style_vector"]["attack_volume"]["score"]
        away_exposure = ap["style_vector"]["defensive_exposure"]["score"]
        away_attack = ap["style_vector"]["attack_volume"]["score"]
        home_exposure = hp["style_vector"]["defensive_exposure"]["score"]
        if home_attack is not None and away_exposure is not None and min(home_attack, away_exposure) >= 65:
            clashes.append({
                "edge": "home_attack",
                "label": f"Volumen de {home} contra exposición de {away}",
                "strength": round((home_attack + away_exposure) / 2),
            })
        if away_attack is not None and home_exposure is not None and min(away_attack, home_exposure) >= 65:
            clashes.append({
                "edge": "away_attack",
                "label": f"Volumen de {away} contra exposición de {home}",
                "strength": round((away_attack + home_exposure) / 2),
            })
        contact_scores = [
            hp["style_vector"]["contact_intensity"]["score"],
            ap["style_vector"]["contact_intensity"]["score"],
        ]
        if all(score is not None for score in contact_scores) and min(contact_scores) >= 65:
            clashes.append({
                "edge": "contact",
                "label": "Cruce de dos perfiles de contacto alto",
                "strength": round(sum(contact_scores) / 2),
            })
        return {
            "method": "percentiles de splits observados casa/fuera; no infiere una formación",
            "home": hp,
            "away": ap,
            "expected_shot_pressure": {
                "home": round(home_pressure, 1) if home_pressure is not None else None,
                "away": round(away_pressure, 1) if away_pressure is not None else None,
            },
            "reliability": "alta" if evidence >= 10 else "media" if evidence >= 5 else "baja",
            "minimum_samples": evidence,
            "style_clashes": clashes,
            "notes": notes or ["muestra insuficiente para caracterizar el emparejamiento"],
        }
