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

from collections import Counter, defaultdict
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


def _stats_report(predictor, train: list, test: list) -> dict:
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


def _rate(predictor, team: str, stat: str, home_side: bool, want_for: bool) -> float:
    """Tasa (a favor / en contra) del equipo como local o visitante, con media
    de liga como respaldo si aún no tiene muestra."""
    canon = _canon(team)
    acc = (predictor.home if home_side else predictor.away)[canon][stat]
    league = (predictor.league_home if home_side else predictor.league_away)[stat]
    if acc.n:
        v = acc.for_avg if want_for else acc.against_avg
        if v is not None:
            return v
    lv = league.for_avg
    return lv if lv is not None else 0.0


# Algoritmos candidatos para predecir una estadística. Cada uno combina las
# variables de otra forma. El banco 80/20 mide su error en partidos NO vistos y
# así se ve, por estadística, cuál predice mejor — el sustrato para iterar.
ALGO_LABEL = {
    "liga": "Media de liga",
    "equipo": "Media del equipo",
    "ataque_defensa": "Ataque × defensa",
    "regresion": "Regresión (equipo+rival)",
    "regresion_plus": "Regresión multi-variable",
}

FORM_WINDOW = 5   # partidos recientes para la forma
REST_CAP = 10.0   # tope de días de descanso (evita outliers de parón)
MIN_TEAM = 8      # partidos mínimos del equipo en el 20% para evaluarlo aparte
ADOPT_MIN = 12    # partidos mínimos del equipo para CAMBIAR su método en producción
ADOPT_MARGIN = 0.10  # el nuevo método debe bajar el error ≥10% para adoptarse

# Variables del modelo multi-variable por equipo (además de local/visitante, que
# entra como indicador). Orden = columnas de la regresión enriquecida.
PLUS_VARS = ["ataque_propio", "defensa_rival", "forma_reciente", "descanso", "arbitro", "local"]
PLUS_LABEL = {
    "ataque_propio": "Ataque propio", "defensa_rival": "Defensa rival",
    "forma_reciente": "Forma reciente", "descanso": "Descanso",
    "arbitro": "Árbitro", "local": "Local/visitante",
}


def _causal_context(matches: list, stat: str) -> dict:
    """Forma reciente y descanso por equipo en cada partido, usando SOLO partidos
    anteriores (sin fuga temporal). Clave = id(match)."""
    from collections import deque, defaultdict

    hist: dict = defaultdict(lambda: deque(maxlen=FORM_WINDOW))
    last: dict = {}
    ctx: dict = {}
    for m in sorted(matches, key=lambda x: _aware(x.kickoff)):
        d = _aware(m.kickoff)
        H, A = _canon(m.home_team), _canon(m.away_team)
        ctx[id(m)] = {
            "home": {"form": (fmean(hist[H]) if hist[H] else None),
                     "rest": (min(REST_CAP, (d - last[H]).days) if H in last else None)},
            "away": {"form": (fmean(hist[A]) if hist[A] else None),
                     "rest": (min(REST_CAP, (d - last[A]).days) if A in last else None)},
        }
        r = m.stats.get(stat)
        if r:
            hist[H].append(r[0]); hist[A].append(r[1])
        last[H] = d; last[A] = d
    return ctx


def _referee_means(train: list, stat: str):
    """Tendencia del árbitro para la estadística (media por equipo), desde el TRAIN."""
    from collections import defaultdict

    acc: dict = defaultdict(lambda: [0.0, 0])
    league = [0.0, 0]
    for m in train:
        r = m.stats.get(stat)
        if not r:
            continue
        per_team = (r[0] + r[1]) / 2.0
        league[0] += per_team; league[1] += 1
        if m.referee:
            acc[m.referee][0] += per_team; acc[m.referee][1] += 1
    league_mean = league[0] / league[1] if league[1] else 0.0
    means = {k: v[0] / v[1] for k, v in acc.items() if v[1] >= 6}
    return means, league_mean


def compare_stat_algorithms(predictor, train: list, test: list, stats=STATS) -> dict:
    """Enfrenta varios algoritmos por estadística sobre el 20% oculto.

    Incluye un modelo multi-variable por equipo (equipo+rival, forma reciente,
    descanso, árbitro, local/visitante) y expone qué variable influye en cada
    estadística. Devuelve, por estadística, el MAE de cada candidato, el ganador
    y la influencia de cada variable.
    """
    import numpy as np

    out: dict = {}
    team_acc: dict = {}  # equipo -> {stats: {stat: mejor método para ESE equipo}}
    for s in stats:
        lh = predictor.league_home[s].for_avg
        la = predictor.league_away[s].for_avg
        if lh is None or la is None:
            continue

        ctx = _causal_context(train + test, s)
        ref_means, ref_league = _referee_means(train, s)

        def _feat(m, home: bool):  # simple: [ataque propio, defensa rival, media liga]
            H, A = m.home_team, m.away_team
            if home:
                return [_rate(predictor, H, s, True, True), _rate(predictor, A, s, False, False), lh]
            return [_rate(predictor, A, s, False, True), _rate(predictor, H, s, True, False), la]

        def _feat_plus(m, home: bool):  # + forma, descanso, árbitro, local
            base = _feat(m, home)  # [own, opp, liga]
            c = ctx.get(id(m), {}).get("home" if home else "away", {})
            forma = c.get("form")
            forma = forma if forma is not None else base[0]
            descanso = c.get("rest")
            descanso = descanso if descanso is not None else REST_CAP
            arb = ref_means.get(m.referee, ref_league) if m.referee else ref_league
            return [base[0], base[1], forma, descanso, arb, 1.0 if home else 0.0]

        # Ajuste de las dos regresiones (pesos aprendidos) sobre el TRAIN.
        rows, rows_p, targets = [], [], []
        for m in train:
            r = m.stats.get(s)
            if not r:
                continue
            rows.append(_feat(m, True) + [1.0]); rows_p.append(_feat_plus(m, True) + [1.0]); targets.append(r[0])
            rows.append(_feat(m, False) + [1.0]); rows_p.append(_feat_plus(m, False) + [1.0]); targets.append(r[1])
        coef = coef_p = None
        if len(rows) >= 30:
            y = np.asarray(targets)
            coef, *_ = np.linalg.lstsq(np.asarray(rows), y, rcond=None)
            Xp = np.asarray(rows_p)
            coef_p, *_ = np.linalg.lstsq(Xp, y, rcond=None)

        errs: dict[str, list] = {k: [] for k in ALGO_LABEL}
        team_errs: dict = defaultdict(lambda: defaultdict(list))  # equipo -> método -> errores
        for m in test:
            r = m.stats.get(s)
            if not r:
                continue
            fh, fa = _feat(m, True), _feat(m, False)
            preds = {
                "liga": (lh, la),
                "equipo": (fh[0], fa[0]),
                "ataque_defensa": ((fh[0] + fh[1]) / 2, (fa[0] + fa[1]) / 2),
            }
            if coef is not None:
                preds["regresion"] = (float(np.dot(coef, fh + [1.0])), float(np.dot(coef, fa + [1.0])))
            if coef_p is not None:
                preds["regresion_plus"] = (float(np.dot(coef_p, _feat_plus(m, True) + [1.0])),
                                           float(np.dot(coef_p, _feat_plus(m, False) + [1.0])))
            Hc, Ac = _canon(m.home_team), _canon(m.away_team)
            for name, (ph, pa) in preds.items():
                errs[name].append(abs(ph - r[0]))
                errs[name].append(abs(pa - r[1]))
                if name != "liga":  # POR EQUIPO nunca usamos la media de liga
                    team_errs[Hc][name].append(abs(ph - r[0]))
                    team_errs[Ac][name].append(abs(pa - r[1]))

        algos = {k: round(fmean(v), 3) for k, v in errs.items() if v}
        if not algos:
            continue
        best = min(algos, key=algos.get)
        entry = {
            "label": STAT_LABEL[s],
            "n": len(errs[best]),
            "algorithms": algos,
            "best": best,
            "best_label": ALGO_LABEL[best],
            "best_mae": algos[best],
        }
        # Influencia: aporte real de cada variable = |peso| × dispersión de esa
        # variable en el train, normalizado (suma 1). Dice qué mueve cada stat.
        if coef_p is not None:
            Xp = np.asarray(rows_p)
            contrib = np.abs(coef_p[:len(PLUS_VARS)]) * Xp[:, :len(PLUS_VARS)].std(axis=0)
            tot = float(contrib.sum())
            if tot > 0:
                entry["influence"] = {
                    PLUS_VARS[i]: round(float(contrib[i] / tot), 3) for i in range(len(PLUS_VARS))
                }
        out[s] = entry

        # --- POR EQUIPO: mejor método para ESTE equipo en ESTA estadística ---
        # Se evalúa sobre los partidos del propio equipo en el 20% oculto; la
        # base es su PROPIA media (no la de liga), como pediste.
        for team, methods in team_errs.items():
            own = methods.get("equipo")
            if not own or len(own) < MIN_TEAM:
                continue
            maes = {k: fmean(v) for k, v in methods.items() if len(v) >= MIN_TEAM}
            if "equipo" not in maes:
                continue
            bteam = min(maes, key=maes.get)
            base = maes["equipo"]
            # Guardia de adopción en producción: por defecto se mantiene el
            # método actual (ataque_defensa). Solo se cambia el método de ESTE
            # equipo+estadística si "equipo" (el único no-default aplicable hoy
            # en el pipeline) lo supera de forma ROBUSTA en su propio 20%.
            default_mae = maes.get("ataque_defensa")
            adopt, adopt_gain = "ataque_defensa", None
            if default_mae and len(own) >= ADOPT_MIN:
                eq = maes.get("equipo")
                if eq is not None and eq <= default_mae * (1 - ADOPT_MARGIN):
                    adopt, adopt_gain = "equipo", round((1 - eq / default_mae) * 100, 1)
            team_acc.setdefault(team, {"equipo": team, "stats": {}})["stats"][s] = {
                "label": STAT_LABEL[s],
                "n": len(own),
                "best": bteam,
                "best_label": ALGO_LABEL[bteam],
                "best_mae": round(maes[bteam], 3),
                "baseline_mae": round(base, 3),
                "skill_pct": round((1 - maes[bteam] / base) * 100, 1) if base else None,
                "default_mae": round(default_mae, 3) if default_mae is not None else None,
                "adopt": adopt,
                "adopt_gain": adopt_gain,
            }
    return {"comparison": out, "by_team": team_acc}


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
    predictor = StatsPredictor().fit(train, fit_pseudo_xg=False)
    stats = _stats_report(predictor, train, test)
    bench = compare_stat_algorithms(predictor, train, test)
    comparison, by_team = bench["comparison"], bench["by_team"]
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
        "comparison": comparison,
        "by_team": by_team,
    }
