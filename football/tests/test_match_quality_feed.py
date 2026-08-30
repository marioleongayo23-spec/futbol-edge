import importlib.util
import json
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "enrich_match_quality.py"
_SPEC = importlib.util.spec_from_file_location("enrich_match_quality", _SCRIPT)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_MODULE)
enrich = _MODULE.enrich


def test_enrich_publica_match_quality_sin_tocar_probabilidades(tmp_path):
    path = tmp_path / "dashboard.json"
    payload = {
        "matches": [
            {
                "id": "m1",
                "probs": [45, 30, 25],
                "coverage": {
                    "items": {
                        "fixture": {"state": "ok", "required": True},
                        "weather": {"state": "ok", "required": True},
                        "absences": {"state": "ok", "required": True},
                        "lineup_probable": {"state": "ok", "required": True},
                        "lineup_official": {"state": "ok", "required": False},
                        "odds": {"state": "ok", "required": True},
                    },
                    "missing_required": [],
                },
                "alineacion": {"local": list(range(11)), "visitante": list(range(11))},
                "player_stats": {"home": [], "away": []},
            }
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert enrich(path) is True
    result = json.loads(path.read_text(encoding="utf-8"))
    match = result["matches"][0]

    assert match["probs"] == [45, 30, 25]
    assert 0 <= match["match_quality"]["score"] <= 100
    assert match["match_quality"]["tier"] in {"high", "medium", "limited", "insufficient", "blocked"}
