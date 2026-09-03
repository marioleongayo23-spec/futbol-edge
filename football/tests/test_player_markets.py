"""Top-5 por jugador y métrica: línea over recomendada, orden y ventana temporal."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from futbol_pred.model.player_markets import player_line, build_player_markets
from futbol_pred.matchday_player_props_fill import attach_player_markets


def test_player_line_sube_hasta_perder_solidez():
    pick = player_line(2.4)
    assert pick and pick["over"] >= 0.55
    # una línea por encima de la elegida ya no debe ser "sólida"
    import math
    from scipy.stats import poisson
    k = int(round(pick["line"] - 0.5))
    assert float(poisson.sf(k + 1, 2.4)) < 0.55


def test_player_line_none_si_muy_bajo():
    assert player_line(0.02) is None


def _rows(prefix, shots):
    return [
        {"jugador": f"{prefix}{i}", "position": "DC", "g": 0.2 * i, "a": 0.1, "r": shots[i],
         "rp": shots[i] * 0.4, "fc": 0.5, "fr": 0.8, "t": 0.1,
         "evidence_type": "model_estimate"}
        for i in range(len(shots))
    ]


def test_build_top5_ordena_y_destaca():
    home = _rows("H", [3.1, 0.5, 2.2, 1.0, 0.3, 0.9])
    away = _rows("A", [1.4, 2.6, 0.4, 0.2, 1.1, 0.7])
    pm = build_player_markets(home, away)
    shots = next(m for m in pm["metrics"] if m["metric"] == "r")
    # top-5 y ordenados de mayor a menor
    vals = [p["value"] for p in shots["home"]]
    assert vals == sorted(vals, reverse=True) and len(shots["home"]) == 5
    # la mejor apuesta de remates es el de mayor valor esperado (H0 = 3.1)
    assert shots["best"]["jugador"] == "H0" and shots["best"]["side"] == "home"


def _match(days_ahead):
    ko = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    xi = [f"P{i}" for i in range(11)]
    pos = ["POR", "LI", "DFC", "DFC", "LD", "MC", "MCD", "MC", "EI", "DC", "ED"]
    return {
        "finished": False, "kickoff": ko.isoformat(), "xg": [1.4, 1.1],
        "stats": {"shots": {"home": 12, "away": 10}, "sot": {"home": 4, "away": 3},
                  "fouls": {"home": 13, "away": 12}, "yellows": {"home": 2, "away": 2}},
        "alineacion": {"local": xi, "visitante": xi,
                       "posiciones_local": pos, "posiciones_visitante": pos,
                       "status": "probable"},
    }


def test_attach_respeta_ventana_y_once():
    cercano = _match(3)
    lejano = _match(30)
    n = attach_player_markets([cercano, lejano])
    assert n == 1
    assert cercano.get("player_markets") and "metrics" in cercano["player_markets"]
    assert "player_markets" not in lejano  # fuera de la ventana


def test_attach_salta_once_retenido():
    m = _match(2)
    m["alineacion"]["display_withheld"] = True
    assert attach_player_markets([m]) == 0
    assert "player_markets" not in m
