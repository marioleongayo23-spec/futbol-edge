"""Sembrado del modelo con datos históricos para equipos recién ascendidos.

El problema: un ascendido (p. ej. Málaga) no está en la temporada anterior de
Primera, así que el modelo lo trataba con prior neutro y sus partidos salían
como "datos-insuficientes" (sin predicción). La solución: sembrar también con
Segunda y temporadas previas, y canonicalizar nombres para que el histórico
enlace aunque la fuente use un alias distinto.
"""

from datetime import datetime, timedelta

from futbol_pred import dashboard
from futbol_pred.ingest.api_football import Fixture
from futbol_pred.pipeline import fit_model_from_fixtures, predict_match


def _fx(hid, home, away, hg, ag, days_ago, league="segunda", season=2025):
    return Fixture(
        api_id=hid,
        league=league,
        season=season,
        kickoff=datetime(2026, 1, 1) - timedelta(days=days_ago),
        home_team=home,
        away_team=away,
        status="FT",
        home_goals=hg,
        away_goals=ag,
        source="test",
    )


def test_seed_plan_incluye_division_y_temporadas_previas(monkeypatch):
    calls = []

    def fake_get_fixtures(league, season=None):
        calls.append((league, season))
        return []

    monkeypatch.setattr(dashboard, "get_fixtures", fake_get_fixtures)
    dashboard._seed_fixtures("laliga", 2026)

    # Siembra con Primera (2 temporadas atrás) y Segunda del año anterior:
    # así los ascendidos desde Segunda tienen histórico real.
    assert ("laliga", 2025) in calls
    assert ("laliga", 2024) in calls
    assert ("segunda", 2025) in calls


def test_seed_fixtures_deduplica(monkeypatch):
    dup = _fx(1, "A", "B", 2, 1, 10)

    monkeypatch.setattr(dashboard, "get_fixtures", lambda league, season=None: [dup])
    seeds = dashboard._seed_fixtures("laliga", 2026)
    # El mismo (source, api_id, liga, temporada) no se cuenta dos veces aunque
    # varias entradas del plan devuelvan el mismo partido.
    keys = {(s.source, s.api_id, s.league) for s in seeds}
    assert len(keys) == len(seeds)


def test_ascendido_con_historico_recibe_prediccion_no_degenerada():
    # Liga sintética con 5 equipos; "Málaga CF" (alias) juega en el histórico,
    # así que su canónico "Malaga" queda con fuerza estimada real.
    teams = ["Athletic Club", "Getafe CF", "Levante UD", "Málaga CF", "Elche CF"]
    seed = []
    fid = 0
    for rnd in range(6):  # varias vueltas -> muestra suficiente
        for i in range(len(teams)):
            for j in range(len(teams)):
                if i == j:
                    continue
                fid += 1
                # marcadores plausibles y variados
                hg, ag = (1 + (i + rnd) % 3), ((j + rnd) % 2)
                seed.append(_fx(fid, teams[i], teams[j], hg, ag, 30 + rnd * 7))

    model = fit_model_from_fixtures(seed, name_fn=dashboard._canon)

    # El alias "Málaga CF" del histórico debe enlazar con el canónico.
    assert model.is_known(dashboard._canon("Málaga CF"))
    assert model.is_known(dashboard._canon("Málaga"))  # otro alias -> mismo id

    pred = predict_match(
        model, dashboard._canon("Málaga"), dashboard._canon("Athletic Club")
    )
    probs = pred.one_x_two
    eh, ea = pred.expected_goals
    # No debe caer en el guard de "datos-insuficientes" de dashboard.py.
    assert max(probs.values()) < 0.985
    assert min(eh, ea) >= 0.05
    assert max(eh, ea) <= 4.5


def test_equipo_sin_historico_usa_prior_de_ascenso_no_degenerado():
    # Liga con fuerzas variadas; el ascendido NO aparece en el entrenamiento.
    strong = ["Barcelona", "Real Madrid", "Atletico"]
    mid = ["Sevilla", "Betis", "Valencia"]
    weak = ["Cadiz", "Almeria", "Leganes"]
    teams = strong + mid + weak
    goals = {**{t: 3 for t in strong}, **{t: 2 for t in mid}, **{t: 1 for t in weak}}
    seed, fid = [], 0
    for rnd in range(4):
        for i in range(len(teams)):
            for j in range(len(teams)):
                if i == j:
                    continue
                fid += 1
                hg = max(0, goals[teams[i]] - (1 if teams[j] in strong else 0))
                ag = max(0, goals[teams[j]] - 1)
                seed.append(_fx(fid, teams[i], teams[j], hg, ag, 20 + rnd * 7))

    model = fit_model_from_fixtures(seed)  # sin name_fn: nombres tal cual

    # "Nuevo Ascendido" nunca visto -> usa prior de ascenso, no media de liga.
    assert not model.is_known("Nuevo Ascendido")
    assert model.promoted_attack <= 0.0  # ataque flojo respecto a la media (0)

    for rival in ("Barcelona", "Valencia", "Cadiz"):
        pred = predict_match(model, rival, "Nuevo Ascendido")
        probs = pred.one_x_two
        eh, ea = pred.expected_goals
        assert max(probs.values()) < 0.985
        assert min(eh, ea) >= 0.05
        assert max(eh, ea) <= 4.5
