"""Validación 80/20 (hold-out) sobre datos reales.

Entrena con el 80% de los partidos MÁS ANTIGUOS y predice el 20% MÁS RECIENTE,
comparando con la realidad tanto el RESULTADO (1X2) como cada ESTADÍSTICA (goles,
remates, tiros a puerta, córners, faltas, tarjetas). Es la prueba honesta de
"supuestos reales": el modelo nunca vio el partido que predice.

Decisiones metodológicas:
- El corte es CRONOLÓGICO, no aleatorio. El modelo es temporal (decaimiento por
  antigüedad, forma reciente); entrenar con partidos del futuro para predecir el
  pasado falsearía el resultado (fuga de información). Por eso "80% anterior →
  20% posterior".
- Se compara SIEMPRE contra una base ingenua: media de liga por estadística y
  frecuencia base 1/X/2 del entrenamiento. El "skill" (cuánto baja el error
  frente a esa base) demuestra que el modelo aporta señal real y no acierta por
  el mero promedio.
- Es EVALUACIÓN, no el modelo de producción: producción entrena con toda la
  historia. Aquí se aparta el 20% solo para medir con verdad de campo.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from statistics import fmean

from ..model import DixonColesModel
from ..model.stats_markets import StatsPredictor
from ..normalize import canonical_team
from .metrics import aggregate

# Estadísticas evaluadas (las que el modelo muestra en la ficha). Se omiten
# rojas y fueras de juego: muestra escasa y ruido cerca de cero, poco informativo.
STATS = ("goals", "shots", "sot", "corners", "fouls", "yellows")
STAT_LABEL = {
    "goals": "Goles", "shots": "Remates", "sot": "Tiros a puerta",
    "corners": "Córners", "fouls": "Faltas", "yellows": "Amarillas",
}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _canon(name: str) -> str:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return canonical_team(name)


def _sign(hg: float, ag: float) -> str:
    return "1" if hg > ag else "2" if ag > hg else "X"


def chronological_split(matches: list, train_frac: float = 0.8) -> tuple[list, list]:
    """Ordena por fecha y parte en (train más antiguo, test más reciente)."""
    dated = [m for m in matches if _aware(getattr(m, "kickoff", None)) is not None]
    dated.sort(key=lambda m: _aware(m.kickoff))
    if len(dated) < 10:
        return dated, []
    cut = min(len(dated) - 1, max(1, round(len(dated) * train_frac)))
    return dated[:cut], dated[cut:]


def _fit_outcome_model(train: list) -> DixonColesModel:
    ref = _aware(train[-1].kickoff)
    ht, at, hg, ag, days = [], [], [], [], []
    for m in train:
        g = m.stats.get("goals")
        if not g:
            continue
        ht.append(_canon(m.home_team))
        at.append(_canon(m.away_team))
        hg.append(int(round(g[0])))
        ag.append(int(round(g[1])))
        days.append(max(0.0, (ref - _aware(m.kickoff)).total_seconds() / 86400))
    model = DixonColesModel()
    model.fit(ht, at, hg, ag, days_ago=days)
    return model


def _outcome_report(model, train: list, test: list) -> dict | None:
    counts = Counter(
        _sign(m.stats["goals"][0], m.stats["goals"][1])
        for m in train if m.stats.get("goals")
    )
    total = sum(counts.values())
    base = ({k: counts.get(k, 0) / total for k in ("1", "X", "2")}
            if total else {"1": 0.45, "X": 0.27, "2": 0.28})

    preds: list[tuple[dict, str]] = []
    base_preds: list[tuple[dict, str]] = []
    for m in test:
        g = m.stats.get("goals")
        if not g:
            continue
        actual = _sign(g[0], g[1])
        try:
            probs = model.predict_matrix(_canon(m.home_team), _canon(m.away_team)).one_x_two()
        except (KeyError, ValueError):
            continue
        preds.append((probs, actual))
        base_preds.append((base, actual))
    if not preds:
        return None
    model_metrics = aggregate(preds)
    base_metrics = aggregate(base_preds)
    return {
        "n": model_metrics["n"],
        "accuracy": round(model_metrics["accuracy"], 3),
        "rps": round(model_metrics["rps"], 4),
        "brier": round(model_metrics["brier"], 4),
        "log_loss": round(model_metrics["log_loss"], 4),
        "baseline_accuracy": round(base_metrics["accuracy"], 3),
        "baseline_rps": round(base_metrics["rps"], 4),
        "rps_skill_pct": (round((1 - model_metrics["rps"] / base_metrics["rps"]) * 100, 1)
                          if base_metrics["rps"] else None),
    }


def _stats_report(train: list, test: list) -> dict:
    predictor = StatsPredictor().fit(train, fit_pseudo_xg=False)
    base_home, base_away = {}, {}
    for s in STATS:
        hv = [m.stats[s][0] for m in train if m.stats.get(s)]
        av = [m.stats[s][1] for m in train if m.stats.get(s)]
        if hv and av:
            base_home[s] = fmean(hv)
            base_away[s] = fmean(av)

    acc: dict[str, dict[str, list]] = {
        s: {"err": [], "signed": [], "berr": [], "real": []} for s in STATS
    }
    for m in test:
        try:
            pf = predictor.predict_fixture(m.home_team, m.away_team)
        except (KeyError, ValueError):
            continue
        for s in STATS:
            real = m.stats.get(s)
            pv = pf.get(s)
            if not real or not pv:
                continue
            a = acc[s]
            for side, real_v in (("home", real[0]), ("away", real[1])):
                a["err"].append(abs(pv[side] - real_v))
                a["signed"].append(pv[side] - real_v)
                a["real"].append(real_v)
                base_v = base_home[s] if side == "home" else base_away.get(s)
                if base_v is not None:
                    a["berr"].append(abs(base_v - real_v))

    out = {}
    for s in STATS:
        a = acc[s]
        if not a["err"]:
            continue
        mae = fmean(a["err"])
        bmae = fmean(a["berr"]) if a["berr"] else None
        out[s] = {
            "label": STAT_LABEL[s],
            "n": len(a["err"]),
            "mae": round(mae, 3),
            "bias": round(fmean(a["signed"]), 3),
            "real_mean": round(fmean(a["real"]), 2),
            "baseline_mae": round(bmae, 3) if bmae is not None else None,
            "skill_pct": (round((1 - mae / bmae) * 100, 1)
                          if bmae else None),
        }
    return out


def holdout_report(matches: list, train_frac: float = 0.8) -> dict | None:
    """Informe 80/20 completo para una lista de MatchStats de una liga.

    Devuelve None si no hay muestra suficiente para un corte honesto.
    """
    train, test = chronological_split(matches, train_frac)
    if len(train) < 40 or len(test) < 10:
        return None
    try:
        model = _fit_outcome_model(train)
    except (ValueError, KeyError):
        model = None
    outcome = _outcome_report(model, train, test) if model is not None else None
    stats = _stats_report(train, test)
    if not stats and not outcome:
        return None

    def _season_of(m):
        d = _aware(m.kickoff)
        return d.year if d.month >= 7 else d.year - 1

    seasons = sorted({_season_of(m) for m in train + test})
    return {
        "train_frac": train_frac,
        "train_n": len(train),
        "test_n": len(test),
        "train_end": _aware(train[-1].kickoff).date().isoformat(),
        "test_start": _aware(test[0].kickoff).date().isoformat(),
        "test_end": _aware(test[-1].kickoff).date().isoformat(),
        "seasons": [f"{y % 100:02d}/{(y + 1) % 100:02d}" for y in seasons],
        "outcome": outcome,
        "stats": stats,
    }
