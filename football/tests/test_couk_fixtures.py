"""Fixtures de Segunda desde football-data.co.uk (resultados + próximos)."""

from futbol_pred.ingest.football_data_uk import _parse_fixtures, _parse_results

RESULTS_CSV = (
    "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HS,AS,HC,AC\n"
    "SP2,16/08/2026,18:30,Malaga,Almeria,2,1,H,12,9,6,4\n"
    "SP2,17/08/2026,20:00,Cadiz,Huesca,0,0,D,8,7,3,5\n"
    "SP2,,,,,,,,,,,\n"  # fila basura: se ignora
)

FIXTURES_CSV = (
    "Div,Date,Time,HomeTeam,AwayTeam\n"
    "SP1,23/08/2026,21:00,Barcelona,Getafe\n"      # otra división: se filtra
    "SP2,23/08/2026,19:30,Almeria,Cadiz\n"
    "SP2,24/08/2026,17:00,Huesca,Malaga\n"
)


def test_parse_results_segunda():
    out = _parse_results(RESULTS_CSV, "segunda", 2026)
    assert len(out) == 2
    m = out[0]
    assert m.home_team == "Malaga" and m.away_team == "Almeria"
    assert m.home_goals == 2 and m.away_goals == 1
    assert m.status == "FINISHED"
    assert m.source == "football_data_uk"
    assert m.kickoff.year == 2026 and m.kickoff.month == 8 and m.kickoff.day == 16


def test_parse_fixtures_filtra_division():
    out = _parse_fixtures(FIXTURES_CSV, "segunda", 2026, "SP2")
    assert len(out) == 2  # solo SP2
    assert {m.home_team for m in out} == {"Almeria", "Huesca"}
    assert all(m.status == "SCHEDULED" and m.home_goals is None for m in out)


def test_ids_estables_y_unicos():
    a = _parse_results(RESULTS_CSV, "segunda", 2026)
    b = _parse_results(RESULTS_CSV, "segunda", 2026)
    assert [m.api_id for m in a] == [m.api_id for m in b]  # deterministas
    assert len({m.api_id for m in a}) == len(a)  # únicos
