"""La quiniela oficial: TODO partido queda con predicción fundamentada.

Cubre el bug reportado ("me salen sin predicción; en la quiniela jamás puede
salir sin predicción... no solo los de Segunda, todos"): el resolver adjunta a
cada partido su pronóstico por (A) tarjeta del feed, (B) modelo de la liga
—Segunda incluida, sin calendario próprio— o (C) modelo curado de Liga F para
femeninos, sin heredar jamás la predicción del club masculino homónimo.
"""

from __future__ import annotations

from datetime import datetime, timezone

from futbol_pred import dashboard as D
from futbol_pred import ligaf
from futbol_pred.normalize import canonical_team
from futbol_pred.pipeline import fit_model_from_fixtures
from futbol_pred.ingest.api_football import Fixture


# --- normalización: los nombres de la quiniela casan con las claves del modelo -
def test_alias_segunda_de_la_quiniela():
    assert canonical_team("Real Sociedad B") == canonical_team("Sociedad B")
    assert canonical_team("Sporting de Gijón") == canonical_team("Sp Gijon")
    assert canonical_team("Racing de Santander") == canonical_team("Santander")
    # El filial NO colisiona con el primer equipo.
    assert canonical_team("Real Sociedad B") != canonical_team("Real Sociedad")


# --- modelo curado de Liga F ------------------------------------------------
def test_ligaf_detecta_femenino():
    assert ligaf.is_femenino("Sevilla (F)")
    assert ligaf.is_femenino("Real Madrid femenino")
    assert not ligaf.is_femenino("Sevilla FC")


def test_ligaf_respeta_jerarquia():
    # Barcelona femenino aplasta fuera; probs suman 1 y el signo es visitante.
    p = ligaf.predict("Sevilla (F)", "Barcelona (F)")["probs"]
    assert abs(sum(p.values()) - 1.0) < 1e-9
    assert max(p, key=p.get) == "2"
    # Gran local femenino: signo 1 claro.
    q = ligaf.predict("Real Madrid (F)", "Eibar (F)")["probs"]
    assert max(q, key=q.get) == "1" and q["1"] > 0.6


def test_ligaf_equipo_desconocido_no_rompe():
    r = ligaf.predict("Equipo Inventado (F)", "Otro Inventado (F)")
    assert isinstance(r["probs"]["1"], float)
    assert not r["curado"]  # sin rating curado: prior neutro con ventaja de campo


def _segunda_bundle():
    """Modelo Dixon-Coles real ajustado con resultados sintéticos de Segunda."""
    teams = ["Sociedad B", "Tenerife", "Sp Gijon", "Girona", "Almeria", "Cadiz"]
    fx, i = [], 0
    for round_ in range(6):
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                i += 1
                # Resultados variados y deterministas para dar fuerza a cada equipo.
                hg, ag = (i % 3), ((i + 1) % 3)
                fx.append(Fixture(api_id=i, league="segunda", season=2026,
                    kickoff=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    home_team=h, away_team=a, status="FINISHED",
                    home_goals=hg, away_goals=ag, source="test"))
    model = fit_model_from_fixtures(fx, name_fn=D._canon)
    elo = D._fit_elo_from_fixtures(fx)
    return {"segunda": {"model": model, "elo": elo, "ensemble_params": {},
                        "residual_params": {}, "model_weight": 0.6,
                        "market_temperature": 1.0}}


def _quiniela():
    return {
        "jornada": 4, "fecha": "2026-09-05",
        "partidos": [
            {"orden": 1, "local": "Valencia", "visitante": "Barcelona"},      # feed
            {"orden": 2, "local": "Real Sociedad B", "visitante": "Tenerife"},  # modelo
            {"orden": 3, "local": "Sevilla (F)", "visitante": "Barcelona (F)"},  # liga_f
        ],
    }


def _feed_matches():
    return [{
        "id": "fd-1", "home": "Valencia CF", "away": "FC Barcelona",
        "league": "LaLiga", "finished": False, "matchday": 4,
        "kickoff": "2026-09-05T18:00:00+02:00",
        "probs": [30, 25, 45], "markets": {"marcador": "1-2"}, "xg": [1.1, 1.6],
    }]


def test_resolver_pone_prediccion_a_todos():
    q = D._resolve_quiniela(_quiniela(), _feed_matches(), _segunda_bundle(),
                            "2026-09-05T00:00:00+02:00", datetime.now(timezone.utc))
    assert q["con_prediccion"] == 3
    by_orden = {p["orden"]: p for p in q["partidos"]}
    # Todos con probs válidas (3 enteros que suman ~100).
    for p in q["partidos"]:
        assert isinstance(p["probs"], list) and len(p["probs"]) == 3
        assert 95 <= sum(p["probs"]) <= 105
        assert p["signo"] in ("1", "X", "2")

    # A) LaLiga reutiliza la tarjeta exacta del feed.
    assert by_orden[1]["fuente"] == "feed"
    assert by_orden[1]["probs"] == [30, 25, 45]
    assert by_orden[1]["match_id"] == "fd-1"

    # B) Segunda: predicción directa del modelo (co.uk no da calendario próximo).
    assert by_orden[2]["fuente"] == "modelo"
    assert by_orden[2]["league"] == "LaLiga Hypermotion"

    # C) Femenino: modelo curado Liga F, NUNCA la tarjeta masculina del Barça.
    assert by_orden[3]["fuente"] == "liga_f"
    assert by_orden[3]["league"] == "Liga F"
    assert by_orden[3].get("match_id") is None
    assert by_orden[3]["signo"] == "2"  # Barcelona (F) favorito visitante


def test_resolver_sin_quiniela_es_inocuo():
    assert D._resolve_quiniela(None, [], {}, "x", datetime.now(timezone.utc)) is None
