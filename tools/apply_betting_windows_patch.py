from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"No encuentro ancla para {label}")
    return text.replace(old, new, 1)


root = Path(__file__).resolve().parents[1]

# --- operational.py: dos ventanas oficiales explícitas T-60 / T-30 ---
path = root / "football/src/futbol_pred/operational.py"
text = path.read_text(encoding="utf-8")
start = text.index("def attach_official_context(")
end = text.index("\n\n\ndef _merge_absences", start)
new_function = '''def _official_poll_window(minutes_to_kickoff: float, attempts: dict) -> str | None:
    """Ventanas de publicación del XI: primero T-60 y fallback T-30."""
    if 45 <= minutes_to_kickoff <= 75 and not attempts.get("T-60"):
        return "T-60"
    if 15 <= minutes_to_kickoff < 45 and not attempts.get("T-30"):
        return "T-30"
    return None


def attach_official_context(matches: list[dict], now: datetime, client: ApiFootballClient | None = None, limit: int = 8, stats_models: dict[str, object] | None = None) -> int:
    """Busca el XI oficial en T-60 y, si aún no existe, reintenta en T-30."""
    client = client or ApiFootballClient()
    if client.offline:
        return 0
    now_local = _aware(now).astimezone(MADRID)
    candidates = []
    for match in matches:
        kickoff = _parse(match.get("kickoff"))
        if not kickoff or kickoff.date() != now_local.date():
            continue
        minutes_to_kickoff = (kickoff - now_local).total_seconds() / 60
        if minutes_to_kickoff <= 0:
            continue
        lineup = match.get("alineacion") or {}
        if (
            lineup.get("status") == "confirmado"
            and len(lineup.get("local") or []) == 11
            and len(lineup.get("visitante") or []) == 11
        ):
            continue
        attempts = dict(lineup.get("official_poll_windows") or {})
        poll_window = _official_poll_window(minutes_to_kickoff, attempts)
        if not poll_window:
            continue
        candidates.append((kickoff, match, poll_window))

    resolved = []
    for kickoff, match, poll_window in sorted(candidates, key=lambda item: item[0])[:limit]:
        fixture = client.find_fixture(match.get("home", ""), match.get("away", ""), kickoff)
        fixture_id = ((fixture or {}).get("fixture") or {}).get("id")
        if fixture_id:
            resolved.append((kickoff, match, poll_window, int(fixture_id), fixture))
    details = client.get_fixture_details([item[3] for item in resolved]) if hasattr(client, "get_fixture_details") else {}
    updated = 0
    for kickoff, match, poll_window, fixture_id, fixture in resolved:
        detail = details.get(fixture_id) or fixture
        official = client.lineup_from_fixture(detail) if hasattr(client, "lineup_from_fixture") and details else client.get_official_lineup(fixture_id)
        absences = client.get_absences(fixture_id)
        old = match.get("alineacion") or {}
        attempts = dict(old.get("official_poll_windows") or {})
        attempts[poll_window] = now_local.isoformat()
        old["official_poll_windows"] = attempts
        old["official_poll_at"] = now_local.isoformat()  # compatibilidad con feeds previos
        old["official_poll_window_last_attempt"] = poll_window
        match["alineacion"] = old
        if hasattr(client, "fixture_context"):
            official_context = client.fixture_context(detail)
            if official_context:
                official_context["source_updated_at"] = now_local.isoformat()
                official_context["official_poll_window"] = poll_window
                stats_model = (stats_models or {}).get(match.get("league"))
                referee_model = getattr(stats_model, "referee_model", None)
                referee = official_context.get("referee")
                if referee_model is not None and referee:
                    try:
                        profile = referee_model.context(referee)
                        if profile:
                            official_context["referee_profile"] = profile
                        adjusted, applied = referee_model.adjust_stats(match.get("stats"), referee)
                        if applied:
                            match["stats"] = adjusted
                            official_context["referee_adjustment_applied"] = applied
                    except Exception:
                        pass
                match["official_context"] = official_context
        if not official:
            _merge_absences(match.get("alineacion") or {}, match, absences, now_local)
            continue
        by_side = {}
        for team in official:
            side = _side_for(team.get("team", ""), match.get("home", ""), match.get("away", ""))
            if side:
                by_side[side] = team
        if set(by_side) != {"local", "visitante"}:
            continue
        old = match.get("alineacion") or {}
        local = [row["name"] for row in by_side["local"]["starters"]]
        visitor = [row["name"] for row in by_side["visitante"]["starters"]]
        positions_local = [row["position"] for row in by_side["local"]["starters"]]
        positions_visitor = [row["position"] for row in by_side["visitante"]["starters"]]
        if len(local) != 11 or len(visitor) != 11:
            continue
        real_local = _real_starter_props(client, match, match.get("home", ""), local, kickoff)
        real_visitor = _real_starter_props(client, match, match.get("away", ""), visitor, kickoff)
        key_local = real_local or []
        key_visitor = real_visitor or []
        real_count = len(key_local) + len(key_visitor)
        props_source = (
            f"API-Football · players ({real_count}/22 con muestra)"
            if real_count else "sin datos reales suficientes"
        )
        stamp = now_local.isoformat()
        lineup = {
            **old,
            "local": local,
            "visitante": visitor,
            "posiciones_local": positions_local,
            "posiciones_visitante": positions_visitor,
            "formacion_local": by_side["local"].get("formation") or _formation(positions_local),
            "formacion_visitante": by_side["visitante"].get("formation") or _formation(positions_visitor),
            "positions_inferred": False,
            "clave_local": key_local,
            "clave_visitante": key_visitor,
            "best_props": _best_props(key_local, key_visitor),
            "status": "confirmado",
            "phase": "final",
            "provider": "API-Football",
            "model": "alineación oficial",
            "fuente": f"API-Football · fixtures/lineups · {poll_window}",
            "official_poll_window": poll_window,
            "player_props_source": props_source,
            "numeric_props_source": "API-Football · players" if real_count else "pending_real_data",
            "source_updated_at": stamp,
            "generated_at": stamp,
            "ts": stamp,
            "official_fixture_id": fixture_id,
            "quality": {
                "complete": True,
                "lineup_players": 22,
                "positions_players": 22,
                "props_players": len(key_local) + len(key_visitor),
                "score": 1.0,
                "official": True,
                "official_poll_window": poll_window,
                "real_player_props": real_count,
                "player_props_source": props_source,
            },
        }
        _merge_absences(lineup, match, absences, now_local)
        match["alineacion"] = lineup
        updated += 1
    return updated
'''
text = text[:start] + new_function + text[end:]
path.write_text(text, encoding="utf-8")

# --- dashboard.py: refresco PRE-FINAL antes del poll oficial ---
path = root / "football/src/futbol_pred/dashboard.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from .prediction_snapshots import apply_prediction_snapshots, latest_pre_match_snapshot\n",
    "from .prediction_snapshots import apply_prediction_snapshots, latest_pre_match_snapshot\nfrom .prefinal_lineups import refresh_prefinal_lineups\n",
    "import prefinal",
)
text = replace_once(
    text,
    "    _attach_previews(matches, now)\n    _attach_lineups(matches, now, squads=all_squads)\n    official_updates = attach_official_context(matches, now, stats_models=stats_models_by_league)\n",
    "    _attach_previews(matches, now)\n    _attach_lineups(matches, now, squads=all_squads)\n    prefinal_updates = refresh_prefinal_lineups(matches, now)\n    official_updates = attach_official_context(matches, now, stats_models=stats_models_by_league)\n",
    "pipeline prefinal",
)
text = replace_once(
    text,
    '    audit["official_lineup_updates"] = official_updates\n',
    '    audit["prefinal_lineup_updates"] = prefinal_updates\n    audit["official_lineup_updates"] = official_updates\n',
    "audit prefinal",
)
text = replace_once(
    text,
    '            "lineups": "API-Football para onces oficiales y bajas cerca del partido; football-data.org para plantillas",\n            "ai": "Gemini dinámico → Groq → motor estadístico local gratuito; control del día a las 00:15 y 10:15 Europe/Madrid, con presupuesto y caché",\n',
    '            "lineups": "PRE-FINAL T-3h con once probable refrescado y señales de medios; FINAL oficial API-Football en T-60 y fallback T-30; football-data.org para plantillas",\n            "ai": "Gemini dinámico → Groq → motor estadístico local; revisiones 00:15/10:15 más PRE-FINAL T-3h bajo presupuesto y caché",\n',
    "sources lineups",
)
path.write_text(text, encoding="utf-8")

# --- tests snapshots: migrar evento oficial + añadir pre-final/final ---
path = root / "football/tests/test_prediction_snapshots.py"
text = path.read_text(encoding="utf-8")
text = text.replace('"source_updated_at": "2026-08-24T19:45:00+02:00",\n    }', '"source_updated_at": "2026-08-24T19:45:00+02:00",\n        "official_poll_window": "T-60",\n    }', 1)
text = text.replace('assert snapshot["window"] == "official_lineup"', 'assert snapshot["window"] == "final_T-60_official"', 1)
text = text.replace('assert repeated["prediction_snapshot"]["window"] == "official_lineup"\n    assert sum(row.get("window") == "official_lineup" for row in repeated["prediction_history"]) == 1', 'assert repeated["prediction_snapshot"]["window"] == "final_T-60_official"\n    assert sum(row.get("window") == "final_T-60_official" for row in repeated["prediction_history"]) == 1', 1)
append = '''\n\ndef test_t3_es_prefinal_solo_con_once_probable_completo_refrescado():
    old = _match([50, 30, 20])
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    current = _match([54, 28, 18])
    current["alineacion"] = {
        "status": "probable", "phase": "pre_final",
        "local": [f"L{i}" for i in range(11)],
        "visitante": [f"V{i}" for i in range(11)],
        "media_sources": [{"source": "AS", "title": "Once probable"}],
    }
    apply_prediction_snapshots([current], [old], datetime(2026, 8, 24, 18, tzinfo=MADRID))
    assert current["prediction_snapshot"]["window"] == "pre_final_T-3h"
    assert len(current["prediction_snapshot"]["alineacion"]["local"]) == 11


def test_t3_sin_once_completo_no_finge_prefinal():
    old = _match([50, 30, 20])
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    current = _match([54, 28, 18])
    current["alineacion"] = {"status": "probable", "phase": "pre_final", "local": ["L"] * 9, "visitante": ["V"] * 11}
    apply_prediction_snapshots([current], [old], datetime(2026, 8, 24, 18, tzinfo=MADRID))
    assert current["prediction_snapshot"]["window"] == "T-3h"


def test_final_t30_si_el_once_oficial_no_estaba_disponible_a_t60():
    old = _match([50, 30, 20])
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))
    final = _match([56, 27, 17])
    final["alineacion"] = {
        "status": "confirmado", "phase": "final", "official_poll_window": "T-30",
        "local": [f"L{i}" for i in range(11)], "visitante": [f"V{i}" for i in range(11)],
    }
    apply_prediction_snapshots([final], [old], datetime(2026, 8, 24, 20, 30, tzinfo=MADRID))
    assert final["prediction_snapshot"]["window"] == "final_T-30_official"


def test_final_t60_no_se_reemplaza_por_una_segunda_final_t30():
    first = _match([55, 28, 17])
    first["alineacion"] = {
        "status": "confirmado", "phase": "final", "official_poll_window": "T-60",
        "local": [f"L{i}" for i in range(11)], "visitante": [f"V{i}" for i in range(11)],
    }
    apply_prediction_snapshots([first], [], datetime(2026, 8, 24, 20, tzinfo=MADRID))
    second = _match([70, 20, 10])
    second["alineacion"] = {**first["alineacion"], "official_poll_window": "T-30"}
    apply_prediction_snapshots([second], [first], datetime(2026, 8, 24, 20, 30, tzinfo=MADRID))
    assert second["prediction_snapshot"]["window"] == "final_T-60_official"
    assert second["probs"] == [55, 28, 17]
'''
if "test_t3_es_prefinal_solo_con_once_probable_completo_refrescado" not in text:
    text += append
path.write_text(text, encoding="utf-8")

# --- operational tests: doble ventana, sin repoll tras oficial ---
path = root / "football/tests/test_operational_performance.py"
text = path.read_text(encoding="utf-8")
append = '''\n\ndef test_poll_oficial_usa_t60_y_no_repite_si_ya_confirma():
    now = datetime(2026, 8, 24, 19, tzinfo=MADRID)
    match = {"id": "win", "home": "A", "away": "B", "kickoff": (now + timedelta(hours=1)).isoformat(), "xg": [1.1, 1.0], "stats": {}}

    class WindowClient:
        offline = False
        calls = 0
        def find_fixture(self, *_args): return {"fixture": {"id": 9}}
        def get_official_lineup(self, _id):
            self.calls += 1
            positions = ["POR", "LI", "DFC", "DFC", "LD", "MC", "MCD", "MC", "EI", "DC", "ED"]
            return [
                {"team": "A", "formation": "4-3-3", "starters": [{"name": f"A{i}", "position": p} for i, p in enumerate(positions)]},
                {"team": "B", "formation": "4-3-3", "starters": [{"name": f"B{i}", "position": p} for i, p in enumerate(positions)]},
            ]
        def get_absences(self, _id): return []

    client = WindowClient()
    assert attach_official_context([match], now, client) == 1
    assert match["alineacion"]["official_poll_window"] == "T-60"
    assert "T-60" in match["alineacion"]["official_poll_windows"]
    assert attach_official_context([match], now + timedelta(minutes=30), client) == 0
    assert client.calls == 1


def test_poll_oficial_reintenta_t30_si_t60_no_tenia_once():
    kickoff = datetime(2026, 8, 24, 20, tzinfo=MADRID)
    match = {"id": "retry", "home": "A", "away": "B", "kickoff": kickoff.isoformat(), "xg": [1.1, 1.0], "stats": {}, "alineacion": {}}

    class RetryClient:
        offline = False
        calls = 0
        def find_fixture(self, *_args): return {"fixture": {"id": 10}}
        def get_official_lineup(self, _id):
            self.calls += 1
            if self.calls == 1: return None
            positions = ["POR", "LI", "DFC", "DFC", "LD", "MC", "MCD", "MC", "EI", "DC", "ED"]
            return [
                {"team": "A", "formation": "4-3-3", "starters": [{"name": f"A{i}", "position": p} for i, p in enumerate(positions)]},
                {"team": "B", "formation": "4-3-3", "starters": [{"name": f"B{i}", "position": p} for i, p in enumerate(positions)]},
            ]
        def get_absences(self, _id): return []

    client = RetryClient()
    assert attach_official_context([match], kickoff - timedelta(hours=1), client) == 0
    assert match["alineacion"]["official_poll_window_last_attempt"] == "T-60"
    assert attach_official_context([match], kickoff - timedelta(minutes=30), client) == 1
    assert match["alineacion"]["official_poll_window"] == "T-30"
    assert set(match["alineacion"]["official_poll_windows"]) == {"T-60", "T-30"}
'''
if "test_poll_oficial_usa_t60_y_no_repite_si_ya_confirma" not in text:
    text += append
path.write_text(text, encoding="utf-8")
