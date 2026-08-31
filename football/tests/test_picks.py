"""Picks del día: valor cuando hay cuotas, confianza cuando no."""

from datetime import datetime, timedelta, timezone

from futbol_pred.picks import build_picks

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _match(mid, probs, hours=6, **extra):
    base = {
        "id": mid,
        "home": f"Local {mid}", "away": f"Visitante {mid}",
        "league": "LaLiga",
        "kickoff": (NOW + timedelta(hours=hours)).isoformat(),
        "finished": False,
        "probs": probs,
    }
    base.update(extra)
    return base


def test_pick_de_valor_cuando_hay_cuota_con_edge():
    m = _match("v", [40, 30, 30], value=[
        {"market": "1x2", "selection": "1", "odds": 3.5, "modelProb": 0.40, "edge": 0.40},
    ], prediction_confidence={"score": 70})
    picks = build_picks([m], now=NOW)
    assert len(picks) == 1
    assert picks[0]["kind"] == "value"
    assert picks[0]["selection"] == "1" and picks[0]["edge"] == 0.4


def test_cae_a_confianza_cuando_no_hay_cuotas():
    # Sin 'value': si el modelo ve un resultado >50%, se sugiere como confianza.
    m = _match("c", [70, 18, 12], prediction_confidence={"score": 80})
    picks = build_picks([m], now=NOW)
    assert len(picks) == 1
    assert picks[0]["kind"] == "confianza"
    assert picks[0]["selection"] == "1"
    assert picks[0]["modelProb"] == 0.7
    assert picks[0]["fairOdds"] == round(1 / 0.7, 2)
    assert picks[0]["edge"] is None


def test_sin_pick_si_edge_bajo_y_prob_baja():
    # Edge < 3% y ningún resultado supera el 50%: no se sugiere nada.
    m = _match("n", [40, 33, 27], value=[
        {"market": "1x2", "selection": "1", "odds": 2.4, "modelProb": 0.40, "edge": 0.01},
    ])
    assert build_picks([m], now=NOW) == []


def test_excluye_terminados_y_fuera_de_horizonte():
    finished = _match("f", [70, 20, 10], finished=True)
    far = _match("lejos", [70, 20, 10], hours=24 * 10)
    assert build_picks([finished, far], now=NOW) == []


def test_valor_ordena_antes_que_confianza():
    valor = _match("v", [45, 30, 25], value=[
        {"market": "1x2", "selection": "1", "odds": 3.0, "modelProb": 0.45, "edge": 0.35},
    ], prediction_confidence={"score": 60})
    confianza = _match("c", [88, 8, 4], prediction_confidence={"score": 99})
    picks = build_picks([confianza, valor], now=NOW)
    assert [p["kind"] for p in picks] == ["value", "confianza"]
