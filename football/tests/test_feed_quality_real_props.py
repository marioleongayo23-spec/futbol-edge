from futbol_pred.feed_quality import _ai_complete


def _lineup(props):
    return {
        "local": [f"L{i}" for i in range(11)],
        "visitante": [f"V{i}" for i in range(11)],
        "posiciones_local": ["POR"] + ["DFC"] * 10,
        "posiciones_visitante": ["POR"] + ["DFC"] * 10,
        "formacion_local": "4-3-3",
        "formacion_visitante": "4-3-3",
        "provider": "API-Football",
        "status": "confirmado",
        "clave_local": props,
        "clave_visitante": [],
    }


def test_feed_quality_acepta_once_sin_props_si_no_hay_muestra_real():
    issues = []
    _ai_complete({"id": "m1", "alineacion": _lineup([])}, issues, schema_version=7)
    assert issues == []


def test_feed_quality_rechaza_prop_numerica_sin_fuente_y_muestra_real():
    issues = []
    fake = {"jugador": "L1", "g": .2, "a": .1, "r": 2, "rp": 1, "fc": 1, "fr": 1, "t": .1, "min": 80, "tit": 1}
    _ai_complete({"id": "m1", "alineacion": _lineup([fake])}, issues, schema_version=7)
    assert "props_sin_fuente_real:m1" in issues


def test_feed_quality_acepta_prop_api_football_con_muestra():
    issues = []
    real = {"jugador": "L1", "g": .2, "a": .1, "r": 2, "rp": 1, "fc": 1, "fr": 1, "t": .1, "min": 80, "tit": 1,
            "source": "API-Football · players", "sample_minutes": 900}
    _ai_complete({"id": "m1", "alineacion": _lineup([real])}, issues, schema_version=7)
    assert issues == []
