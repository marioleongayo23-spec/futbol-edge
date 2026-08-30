from futbol_pred.match_quality import calculate_match_quality


def _coverage(*, required_missing=None, states=None):
    states = states or {}
    keys = ["fixture", "weather", "absences", "lineup_probable", "lineup_official", "odds"]
    items = {}
    for key in keys:
        state = states.get(key, "ok")
        items[key] = {"state": state, "required": key in (required_missing or [])}
    return {"items": items, "missing_required": required_missing or []}


def test_calidad_alta_con_cobertura_completa():
    match = {
        "alineacion": {"local": list(range(11)), "visitante": list(range(11))},
        "player_stats": {"A": [{"id": 1}], "B": [{"id": 2}]},
    }
    result = calculate_match_quality(match, _coverage())
    assert result["score"] == 100.0
    assert result["tier"] == "high"
    assert result["required_missing"] == []


def test_calidad_no_confunde_estimada_con_verificada():
    match = {"alineacion": {"local": list(range(11)), "visitante": list(range(11))}}
    result = calculate_match_quality(
        match,
        _coverage(states={"lineup_probable": "estimated", "lineup_official": "scheduled"}),
    )
    assert result["score"] < 100
    assert result["components"]["lineup_probable"] == 45.0


def test_falta_requerida_impide_tier_high():
    match = {"alineacion": {"local": list(range(11)), "visitante": list(range(11))}}
    result = calculate_match_quality(
        match,
        _coverage(required_missing=["odds"], states={"odds": "missing"}),
    )
    assert result["tier"] != "high"
    assert result["tier"] == "limited"


def test_fixture_roto_bloquea_aunque_el_resto_este_completo():
    match = {}
    result = calculate_match_quality(
        match,
        _coverage(states={"fixture": "missing"}, required_missing=["fixture"]),
    )
    assert result["tier"] == "blocked"
