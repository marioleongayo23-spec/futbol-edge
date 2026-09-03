"""Mercados que "se mojan": por cada estadística, P(por encima) / P(por debajo)
/ valor EXACTO más probable, en las líneas que de verdad se juegan.

La hoja del partido pedía que TODO mercado dijera lo mismo con la misma vara:
la probabilidad de quedar por encima o por debajo de una línea y cuál es el
resultado exacto más probable. Aquí está esa vara, en un solo sitio y sin
inventar: los goles salen de la matriz Dixon-Coles completa (coherente con el
1X2), y el resto de conteos (córners, tarjetas, remates, faltas...) de una
Poisson/Negative-Binomial cuya sobredispersión se estima con la MISMA muestra
histórica que ya usa el predictor de estadísticas.

Nada de esto crea una predicción nueva: reexpresa la que ya existe (medias
esperadas + matriz de goles) como probabilidades de mercado, que es lo que hace
falta para decidir over/under/exacto y para "mojarse" en un marcador.
"""

from __future__ import annotations

import math

from scipy.stats import nbinom, poisson

# Etiqueta legible por estadística (para la hoja).
STAT_LABEL = {
    "goals": "Goles",
    "shots": "Remates",
    "sot": "Tiros a puerta",
    "corners": "Córners",
    "fouls": "Faltas",
    "yellows": "Tarjetas",
    "reds": "Rojas",
    "offsides": "Fueras de juego",
}


def _is_poisson(dispersion: float) -> bool:
    # Por debajo de un 5% de sobredispersión, la Poisson y la NB coinciden en la
    # práctica; usar Poisson evita parámetros degenerados (varianza≈media).
    return dispersion <= 1.05


def _nb_params(mean: float, dispersion: float) -> tuple[float, float]:
    variance = dispersion * mean
    size = max(1e-6, mean * mean / max(1e-6, variance - mean))
    success = size / (size + mean)
    return size, success


def prob_exact(mean: float, k: int, dispersion: float = 1.0) -> float:
    """P(recuento == k) para una media dada, Poisson o NB según dispersión."""
    if mean <= 0:
        return 1.0 if k == 0 else 0.0
    if k < 0:
        return 0.0
    if _is_poisson(dispersion):
        return float(poisson.pmf(k, mean))
    size, success = _nb_params(mean, dispersion)
    return float(nbinom.pmf(k, size, success))


def prob_over(mean: float, line: float, dispersion: float = 1.0) -> float:
    """P(recuento > line). Con línea .5 no hay push."""
    if mean <= 0:
        return 0.0
    floor = math.floor(line)
    if _is_poisson(dispersion):
        return float(1.0 - poisson.cdf(floor, mean))
    size, success = _nb_params(mean, dispersion)
    return float(1.0 - nbinom.cdf(floor, size, success))


def _push(mean: float, line: float, dispersion: float) -> float:
    """Masa exactamente en una línea entera (posible empate/push)."""
    if abs(line - round(line)) > 1e-9:
        return 0.0
    return prob_exact(mean, int(round(line)), dispersion)


def _nearest_half(x: float) -> float:
    """Línea .5 más próxima a la media (evita el push de las líneas enteras)."""
    return round(x - 0.5) + 0.5


def _lean(prob: float) -> str:
    """Fuerza de la inclinación de una línea (para no vender un 51% como certeza)."""
    if prob >= 0.68:
        return "fuerte"
    if prob >= 0.58:
        return "claro"
    return "ligero"


def _distribution(mean: float, dispersion: float) -> tuple[list[float], int]:
    """PMF del recuento hasta una cola razonable; devuelve (pmf, k_mas_probable)."""
    cap = max(6, int(math.ceil(mean * 2.2)) + 8)
    pmf = [prob_exact(mean, k, dispersion) for k in range(cap + 1)]
    k_star = max(range(len(pmf)), key=lambda k: pmf[k]) if pmf else 0
    return pmf, k_star


def _range_80(pmf: list[float]) -> list[int]:
    """[P10, P90] del recuento a partir de su PMF acumulada."""
    acc = 0.0
    lo = hi = 0
    lo_done = False
    for k, p in enumerate(pmf):
        acc += p
        if not lo_done and acc >= 0.10:
            lo = k
            lo_done = True
        if acc >= 0.90:
            hi = k
            break
    else:
        hi = len(pmf) - 1
    return [lo, max(hi, lo)]


def count_market(
    stat: str,
    mean_total: float,
    dispersion: float = 1.0,
    *,
    mean_home: float | None = None,
    mean_away: float | None = None,
    trend: dict | None = None,
    lines: list[float] | None = None,
) -> dict:
    """Reexpresa un recuento esperado como mercado over/under/exacto.

    El total se modela directamente con su media (mean_total) y la MISMA razón de
    sobredispersión que el predictor observa por lado —la razón varianza/media se
    conserva al sumar los dos lados, así que es la sobredispersión correcta para
    la línea del total—.
    """
    mean_total = max(0.0, float(mean_total))
    pmf, k_star = _distribution(mean_total, dispersion)
    if lines is None:
        base = _nearest_half(mean_total)
        step = 1.0 if mean_total < 6 else 2.0
        lines = [round(base - step, 1), base, round(base + step, 1)]
        lines = [line for line in lines if line >= 0.5]
    main = min(lines, key=lambda line: abs(line - mean_total)) if lines else _nearest_half(mean_total)

    rows = []
    for line in lines:
        over = prob_over(mean_total, line, dispersion)
        push = _push(mean_total, line, dispersion)
        under = max(0.0, 1.0 - over - push)
        side = "over" if over >= under else "under"
        rows.append({
            "line": round(line, 1),
            "over": round(over, 3),
            "under": round(under, 3),
            "push": round(push, 3),
            "pick": side,
            "pick_prob": round(max(over, under), 3),
            "main": abs(line - main) < 1e-9,
        })

    over_main = prob_over(mean_total, main, dispersion)
    push_main = _push(mean_total, main, dispersion)
    under_main = max(0.0, 1.0 - over_main - push_main)
    side = "over" if over_main >= under_main else "under"
    pick_prob = max(over_main, under_main)

    out = {
        "stat": stat,
        "label": STAT_LABEL.get(stat, stat.title()),
        "expected": {
            "home": round(mean_home, 2) if mean_home is not None else None,
            "away": round(mean_away, 2) if mean_away is not None else None,
            "total": round(mean_total, 2),
        },
        "distribution": "poisson" if _is_poisson(dispersion) else "negative-binomial",
        "dispersion": round(float(dispersion), 3),
        "most_likely": {"value": k_star, "prob": round(pmf[k_star], 3) if pmf else None},
        "range_80": _range_80(pmf),
        "main_line": round(main, 1),
        "lines": rows,
        "pick": {
            "side": side,
            "line": round(main, 1),
            "prob": round(pick_prob, 3),
            "lean": _lean(pick_prob),
        },
    }
    if trend:
        out["trend"] = {"dir": trend.get("dir"), "pct": trend.get("pct"), "reason": trend.get("reason")}
        # ¿La tendencia empuja hacia el mismo lado que la probabilidad?
        if trend.get("dir") == "up" and side == "over":
            out["pick"]["trend_agrees"] = True
        elif trend.get("dir") == "down" and side == "under":
            out["pick"]["trend_agrees"] = True
        elif trend.get("dir") in ("up", "down"):
            out["pick"]["trend_agrees"] = False
    return out


def goals_market(matrix, mean_home: float, mean_away: float, trend: dict | None = None) -> dict:
    """Mercado de goles desde la matriz Dixon-Coles (coherente con el 1X2)."""
    dist = matrix.total_goals_dist()
    total = [float(v) for v in dist]
    k_star = max(range(len(total)), key=lambda k: total[k]) if total else 0
    lines = [1.5, 2.5, 3.5]
    rows = []
    for line in lines:
        over = matrix.over(line)
        under = matrix.under(line)
        push = max(0.0, 1.0 - over - under)
        side = "over" if over >= under else "under"
        rows.append({
            "line": line,
            "over": round(over, 3),
            "under": round(under, 3),
            "push": round(push, 3),
            "pick": side,
            "pick_prob": round(max(over, under), 3),
            "main": abs(line - 2.5) < 1e-9,
        })
    over_main = matrix.over(2.5)
    under_main = matrix.under(2.5)
    side = "over" if over_main >= under_main else "under"
    pick_prob = max(over_main, under_main)
    out = {
        "stat": "goals",
        "label": STAT_LABEL["goals"],
        "expected": {
            "home": round(float(mean_home), 2),
            "away": round(float(mean_away), 2),
            "total": round(float(mean_home) + float(mean_away), 2),
        },
        "distribution": "dixon-coles",
        "most_likely": {"value": k_star, "prob": round(total[k_star], 3) if total else None},
        "range_80": matrix.distribution_summary()["total_goals_p10_p50_p90"][::2],
        "main_line": 2.5,
        "lines": rows,
        "pick": {"side": side, "line": 2.5, "prob": round(pick_prob, 3), "lean": _lean(pick_prob)},
    }
    if trend:
        out["trend"] = {"dir": trend.get("dir"), "pct": trend.get("pct"), "reason": trend.get("reason")}
        if trend.get("dir") == "up" and side == "over":
            out["pick"]["trend_agrees"] = True
        elif trend.get("dir") == "down" and side == "under":
            out["pick"]["trend_agrees"] = True
        elif trend.get("dir") in ("up", "down"):
            out["pick"]["trend_agrees"] = False
    return out


def committed_scoreline(matrix, probs: dict, home: str, away: str) -> dict:
    """Nos mojamos: UN marcador exacto, con su probabilidad, margen sobre el
    segundo y un nivel de confianza honesto (un marcador exacto rara vez pasa
    del ~15%, así que la confianza mide *cuánto destaca*, no una certeza)."""
    top = matrix.top_correct_scores(2)
    (hx, ax, p1) = top[0]
    p2 = top[1][2] if len(top) > 1 else 0.0
    gap = p1 - p2
    sign = "1" if hx > ax else "2" if hx < ax else "X"
    sign_prob = float(probs.get(sign, 0.0))
    # El signo del marcador exacto más probable NO siempre es el favorito del 1X2
    # (en un partido igualado, el exacto más probable suele ser un empate corto
    # aunque el 1X2 se incline por un lado). Lo decimos con honestidad.
    fav_sign = max(("1", "X", "2"), key=lambda s: float(probs.get(s, 0.0)))
    fav_prob = float(probs.get(fav_sign, 0.0))
    aligned = sign == fav_sign
    # Confianza: cuánto destaca el marcador, cuánto lo respalda el 1X2 y si el
    # signo del marcador coincide con el favorito del partido.
    if p1 >= 0.11 and gap >= 0.02 and sign_prob >= 0.45 and aligned:
        confidence = "alta"
    elif p1 >= 0.08 and sign_prob >= 0.33:
        confidence = "media"
    else:
        confidence = "baja"
    winner = home if sign == "1" else away if sign == "2" else None
    fav_name = home if fav_sign == "1" else away if fav_sign == "2" else "el empate"
    if sign == "X":
        tail = ("y el 1X2 no tiene un favorito claro" if fav_prob < 0.45
                else f"aunque el 1X2 se incline por {fav_name} ({round(fav_prob * 100)}%)")
        why = f"El empate {hx}-{ax} es el resultado exacto más probable, {tail}."
    elif aligned:
        why = (f"{winner} gana {hx}-{ax}: es el marcador exacto más probable "
               f"y el 1X2 apoya el {sign} ({round(sign_prob * 100)}%).")
    else:
        why = (f"{winner} {hx}-{ax} es el marcador exacto más probable, pero el 1X2 se "
               f"inclina por {fav_name} ({round(fav_prob * 100)}%): partido abierto.")
    return {
        "scoreline": f"{hx}-{ax}",
        "home_goals": hx,
        "away_goals": ax,
        "sign": sign,
        "probability": round(p1, 3),
        "margin_over_next": round(gap, 3),
        "next_scoreline": f"{top[1][0]}-{top[1][1]}" if len(top) > 1 else None,
        "sign_probability": round(sign_prob, 3),
        "favourite_sign": fav_sign,
        "favourite_prob": round(fav_prob, 3),
        "sign_aligned": aligned,
        "confidence": confidence,
        "why": why,
    }
