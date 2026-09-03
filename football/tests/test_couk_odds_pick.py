"""El fallback de cuotas por co.uk prueba muchas casas para no quedarse sin cuota
cuando fixtures.csv (pre-partido) no trae las columnas de media (Avg*)."""

from futbol_pred.ingest.football_data_uk import _pick, _ODDS_COLS


def test_usa_pinnacle_si_solo_hay_esa_casa():
    # fixtures.csv pre-partido: sin Avg/B365, solo Pinnacle.
    row = {"PSH": "2.10", "PSD": "3.40", "PSA": "3.30"}
    assert _pick(row, _ODDS_COLS["H"]) == 2.10
    assert _pick(row, _ODDS_COLS["D"]) == 3.40
    assert _pick(row, _ODDS_COLS["A"]) == 3.30


def test_prefiere_media_de_mercado_sobre_casa_individual():
    row = {"AvgH": "2.00", "PSH": "2.10", "B365H": "2.15"}
    assert _pick(row, _ODDS_COLS["H"]) == 2.00


def test_salta_cuotas_invalidas_y_vacias():
    row = {"PSH": "1.0", "B365H": "", "WHH": "2.5"}
    assert _pick(row, _ODDS_COLS["H"]) == 2.5


def test_over_under_desde_bet365_si_no_hay_media():
    row = {"B365>2.5": "1.90", "B365<2.5": "1.95"}
    assert _pick(row, _ODDS_COLS["OV"]) == 1.90
    assert _pick(row, _ODDS_COLS["UN"]) == 1.95
