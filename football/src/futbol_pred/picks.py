"""Picks del día: apuestas de valor cuando hay cuotas, predicciones de confianza
cuando no las hay.

El «valor» (edge = probabilidad · cuota − 1) SOLO existe frente a un mercado: sin
cuotas de The Odds API no se puede calcular. Para que la sección «Picks del día»
nunca quede vacía cuando la cuota está agotada, se cae a la mejor predicción por
CONFIANZA del modelo (resultado más probable + cuota justa implícita), marcada
como tal para no confundirla con una apuesta de valor real.

Este módulo no llama a ninguna API ni escribe caché: solo lee lo que el pipeline
ya calculó (probs calibradas, value/edge, prediction_confidence).
"""

from __future__ import annotations

from datetime import datetime, timezone

MIN_EDGE = 0.03          # 3%: mismo umbral que el pipeline de valor.
MIN_CONFIDENCE_PROB = 0.50   # solo se sugiere una predicción si el modelo la ve >50%.
HORIZON_HOURS = 72       # «del día» con margen: próximos 3 días.


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _kickoff_hours(match: dict, now: datetime) -> float | None:
    try:
        kickoff = _aware(datetime.fromisoformat(str(match.get("kickoff"))))
    except (TypeError, ValueError):
        return None
    return (kickoff - _aware(now)).total_seconds() / 3600.0


def _best_value(match: dict) -> dict | None:
    rows = [
        row for row in (match.get("value") or [])
        if isinstance(row, dict) and isinstance(row.get("edge"), (int, float))
        and isinstance(row.get("odds"), (int, float))
    ]
    return max(rows, key=lambda row: row["edge"], default=None)


def build_picks(matches: list[dict], now: datetime | None = None, limit: int = 6) -> list[dict]:
    """Devuelve hasta ``limit`` picks de partidos próximos, valor primero."""

    now = _aware(now or datetime.now(timezone.utc))
    picks: list[dict] = []
    for match in matches or []:
        if not isinstance(match, dict) or match.get("finished"):
            continue
        probs = match.get("probs")
        if not (isinstance(probs, list) and len(probs) == 3 and all(isinstance(x, (int, float)) for x in probs)):
            continue
        hours = _kickoff_hours(match, now)
        if hours is None or not (-2.0 <= hours <= HORIZON_HOURS):
            continue
        total = sum(probs) or 1
        norm = [x / total for x in probs]
        confidence = (match.get("prediction_confidence") or {}).get("score")
        base = {
            "match_id": match.get("id"),
            "home": match.get("home"),
            "away": match.get("away"),
            "league": match.get("league"),
            "kickoff": match.get("kickoff"),
            "confidence": confidence,
        }

        best = _best_value(match)
        if best and best["edge"] >= MIN_EDGE:
            picks.append({
                **base,
                "kind": "value",
                "market": best.get("market"),
                "selection": best.get("selection"),
                "modelProb": best.get("modelProb"),
                "odds": round(float(best["odds"]), 2),
                "edge": round(float(best["edge"]), 3),
            })
            continue

        # Sin valor: mejor predicción 1X2 por confianza, con cuota justa implícita.
        index = max(range(3), key=lambda i: norm[i])
        prob = norm[index]
        if prob >= MIN_CONFIDENCE_PROB:
            picks.append({
                **base,
                "kind": "confianza",
                "market": "1x2",
                "selection": ("1", "X", "2")[index],
                "modelProb": round(prob, 3),
                "fairOdds": round(1.0 / prob, 2) if prob else None,
                "edge": None,
            })

    def _rank(pick: dict) -> tuple:
        is_value = pick["kind"] == "value"
        # Valor primero (edge desc); luego confianza (score desc, y prob desc).
        strength = pick["edge"] if is_value else (
            (pick.get("confidence") or 0) / 100.0 + (pick.get("modelProb") or 0)
        )
        return (0 if is_value else 1, -strength)

    picks.sort(key=_rank)
    return picks[:limit]
