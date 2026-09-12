from futbol_pred.player_fair_lines import enrich_payload


def test_enrich_payload_solo_publica_fair_lines_para_fuente_real():
    payload = {
        "matches": [{
            "alineacion": {
                "clave_local": [
                    {"jugador": "Real", "source": "API-Football · players", "r": 2.0, "rp": 0.8, "fc": 1.2, "fr": 1.0, "t": 0.2},
                    {"jugador": "Modelo", "source": "Modelo · rol + predicción de equipo", "r": 2.0, "rp": 0.8, "fc": 1.2, "fr": 1.0, "t": 0.2, "fair_lines": {"r": []}, "fair_model": "poisson_baseline"},
                ],
                "clave_visitante": [],
            }
        }]
    }

    changed, enriched = enrich_payload(payload)

    assert changed is True
    assert enriched == 1
    assert payload["matches"][0]["alineacion"]["clave_local"][0]["fair_model"] == "poisson_baseline"
    assert "fair_lines" not in payload["matches"][0]["alineacion"]["clave_local"][1]


def test_enrich_payload_es_idempotente():
    payload = {
        "matches": [{
            "alineacion": {
                "clave_local": [{"jugador": "Real", "source": "API-Football · players", "r": 2.0, "rp": 0.8, "fc": 1.2, "fr": 1.0, "t": 0.2}],
                "clave_visitante": [],
            }
        }]
    }

    first_changed, _ = enrich_payload(payload)
    second_changed, _ = enrich_payload(payload)

    assert first_changed is True
    assert second_changed is False
