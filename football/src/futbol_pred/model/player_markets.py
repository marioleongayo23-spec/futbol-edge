"""Top-5 por jugador y métrica, con línea recomendada y su probabilidad.

Toma las predicciones por jugador que ya produce el reparto por rol
(matchday_player_props_fill._hybrid_side: real donde hay muestra, estimación por
rol donde no) y, para cada métrica (goles, remates, tiros, asistencias, faltas
recibidas/cometidas, tarjetas), elige los CINCO jugadores de cada equipo con
mayor valor esperado y les asigna una línea "over" recomendable con su
probabilidad (Poisson sobre el valor esperado). No inventa muestra: reexpresa la
predicción por jugador como apuesta.
"""

from __future__ import annotations

from scipy.stats import poisson

METRIC_LABEL = {
    "g": "Goles", "a": "Asistencias", "r": "Remates", "rp": "Tiros a puerta",
    "fc": "Faltas cometidas", "fr": "Faltas recibidas", "t": "Tarjetas",
}
# Orden de presentación (lo más apostado primero).
METRIC_ORDER = ("g", "r", "rp", "a", "fr", "fc", "t")


def player_line(mean: float) -> dict | None:
    """Mejor línea 'over' recomendable: la más alta cuya P siga siendo sólida
    (≥55%) pero no trivial. Devuelve None si ni el over 0.5 llega al umbral."""
    mean = float(mean or 0.0)
    if mean <= 0.05:
        return None
    best = None
    for k in range(0, 9):
        p = float(poisson.sf(k, mean))  # P(X > k) = P(over (k+0.5))
        if p >= 0.55:
            best = {"line": k + 0.5, "over": round(p, 3)}
        else:
            break
    return best


def _top5(rows: list[dict], metric: str) -> list[dict]:
    scored = []
    for row in rows:
        try:
            value = float(row.get(metric) or 0.0)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        scored.append((value, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    out = []
    for value, row in scored[:5]:
        pick = player_line(value)
        out.append({
            "jugador": row.get("jugador"),
            "pos": row.get("position"),
            "value": round(value, 2),
            "line": pick["line"] if pick else None,
            "over": pick["over"] if pick else None,
            # prob. de al menos 1 (útil sobre todo en goles/asistencias, donde
            # rara vez hay una línea "over" sólida por jugador).
            "over05": round(float(poisson.sf(0, value)), 3),
            # marca si la predicción de ese jugador viene de muestra REAL o del rol
            "real": str(row.get("evidence_type") or "") == "real_history_projection",
        })
    return out


def build_player_markets(home_rows: list[dict], away_rows: list[dict]) -> dict | None:
    """Estructura top-5 por métrica y equipo, con la mejor apuesta destacada."""
    metrics = []
    any_real = False
    for metric in METRIC_ORDER:
        home = _top5(home_rows, metric)
        away = _top5(away_rows, metric)
        if not home and not away:
            continue
        any_real = any_real or any(p["real"] for p in home + away)
        # "Mejor apuesta" de la métrica: el jugador con mayor valor esperado que
        # además tenga una línea recomendable.
        pool = [("home", p) for p in home if p["line"] is not None] + \
               [("away", p) for p in away if p["line"] is not None]
        best = max(pool, key=lambda item: item[1]["value"], default=None)
        metrics.append({
            "metric": metric,
            "label": METRIC_LABEL[metric],
            "home": home,
            "away": away,
            "best": {"side": best[0], **best[1]} if best else None,
        })
    if not metrics:
        return None
    return {
        "metrics": metrics,
        "has_real_sample": any_real,
        "method": ("predicción por jugador (muestra real donde existe; si no, "
                   "reparto por rol de la predicción de equipo) puesta como línea over"),
    }
