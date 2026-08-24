from futbol_pred.ingest.football_data_uk import _movement_meta


def test_movimiento_prefiere_media_de_mercado_cuando_hay_pareja_completa():
    row = {
        "AvgH": "2.20", "AvgD": "3.40", "AvgA": "3.10",
        "AvgCH": "2.05", "AvgCD": "3.50", "AvgCA": "3.35",
        "B365H": "2.30", "B365D": "3.30", "B365A": "3.00",
        "B365CH": "2.15", "B365CD": "3.40", "B365CA": "3.25",
    }

    meta = _movement_meta(row)

    assert meta["movement_source"] == "market_average"
    assert meta["opening_1x2"] == {"1": 2.2, "X": 3.4, "2": 3.1}
    assert meta["latest_1x2"] == {"1": 2.05, "X": 3.5, "2": 3.35}
    assert meta["closing_1x2"] == meta["latest_1x2"]
    assert meta["movement_pct"]["1"] == -6.8


def test_movimiento_cae_a_bet365_solo_si_la_pareja_avg_no_esta_completa():
    row = {
        "AvgH": "2.20", "AvgD": "3.40", "AvgA": "3.10",
        "AvgCH": "", "AvgCD": "3.50", "AvgCA": "3.35",
        "B365H": "2.30", "B365D": "3.30", "B365A": "3.00",
        "B365CH": "2.15", "B365CD": "3.40", "B365CA": "3.25",
    }

    meta = _movement_meta(row)

    assert meta["movement_source"] == "Bet365"
    assert meta["opening_1x2"] == {"1": 2.3, "X": 3.3, "2": 3.0}
    assert meta["latest_1x2"] == {"1": 2.15, "X": 3.4, "2": 3.25}


def test_movimiento_no_mezcla_fuentes_si_no_hay_pareja_completa():
    row = {
        "AvgH": "2.20", "AvgD": "3.40", "AvgA": "3.10",
        "AvgCH": "2.05", "AvgCD": "", "AvgCA": "3.35",
        "B365H": "2.30", "B365D": "", "B365A": "3.00",
        "B365CH": "2.15", "B365CD": "3.40", "B365CA": "3.25",
    }

    assert _movement_meta(row) is None
