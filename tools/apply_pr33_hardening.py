from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise SystemExit(f"marker missing: {label}")
    if text.count(old) != 1:
        raise SystemExit(f"marker not unique: {label} ({text.count(old)})")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, new: str, label: str) -> str:
    a = text.find(start)
    if a < 0:
        if new.strip() in text:
            return text
        raise SystemExit(f"start missing: {label}")
    b = text.find(end, a + len(start))
    if b < 0:
        raise SystemExit(f"end missing: {label}")
    return text[:a] + new + text[b:]


# 1) IA: once/bajas únicamente; nunca numéricos individuales.
path = "football/src/futbol_pred/ingest/lineups_ai.py"
text = read(path)
start = text.index("_INSTR = (")
end = text.index("\n\n_DEFAULT_FORMATION", start)
new_prompt = '''_INSTR = (
    "Eres analista de fútbol experto en LaLiga y Segunda de España. Para CADA "
    "partido da exclusivamente: (1) el ONCE PROBABLE completo de cada equipo, "
    "exactamente 11 nombres únicos por lado; y (2) bajas por lesión, sanción, "
    "duda o rotación. NO estimes goles, asistencias, remates, faltas, tarjetas "
    "ni minutos: el sistema calcula esos números únicamente con datos reales. "
    "Devuelve EXCLUSIVAMENTE JSON válido:\\n"
    '[{"partido":"<tal cual te lo doy>",'
    '"local":[{"j":"nombre","pos":"POR|LD|DFC|LI|CAD|MCD|MC|MP|CAI|ED|EI|DC"}],'
    '"visitante":[{"j":"nombre","pos":"POR|LD|DFC|LI|CAD|MCD|MC|MP|CAI|ED|EI|DC"}],'
    '"bajas_local":["nombre (lesión|sanción|duda|rotación: motivo)"],'
    '"bajas_visitante":["nombre (lesión|sanción|duda|rotación: motivo)"]}]\\n'
    "Los 11 jugadores deben ir en su demarcación habitual REAL. Ordénalos desde "
    "el portero hasta el delantero. Incluye todos los partidos; si no puedes "
    "completar uno con suficiente calidad, omítelo y el sistema conservará caché."
)'''
text = text[:start] + new_prompt + text[end:]

ensure_start = text.index("def ensure_position_metadata(lineup: dict) -> bool:")
ensure_end = text.index("\n_PROP_LIMITS", ensure_start)
ensure_impl = '''def _verified_numeric_props(rows) -> list[dict]:
    """Solo conserva números derivados de una muestra individual real."""
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            sample = float(row.get("sample_minutes") or 0)
        except (TypeError, ValueError):
            sample = 0
        if str(row.get("source") or "").startswith("API-Football") and sample > 0:
            out.append(row)
    return out


def ensure_position_metadata(lineup: dict) -> bool:
    """Migra un once legado y elimina cualquier prop numérica no verificada."""
    if not isinstance(lineup, dict):
        return False
    had_positions = (
        len(lineup.get("posiciones_local") or []) == 11
        and len(lineup.get("posiciones_visitante") or []) == 11
    )
    local, positions_local = _lineup(lineup.get("local"), lineup.get("posiciones_local"))
    visitor, positions_visitor = _lineup(lineup.get("visitante"), lineup.get("posiciones_visitante"))
    if not local or not visitor:
        return False
    lineup["local"] = local
    lineup["visitante"] = visitor
    lineup["posiciones_local"] = positions_local
    lineup["posiciones_visitante"] = positions_visitor
    lineup["formacion_local"] = _formation(positions_local)
    lineup["formacion_visitante"] = _formation(positions_visitor)
    lineup["positions_inferred"] = bool(lineup.get("positions_inferred") or not had_positions)
    local_props = _verified_numeric_props(lineup.get("clave_local"))
    visitor_props = _verified_numeric_props(lineup.get("clave_visitante"))
    lineup["clave_local"] = local_props
    lineup["clave_visitante"] = visitor_props
    lineup["best_props"] = _best_props(local_props, visitor_props) if (local_props or visitor_props) else []
    lineup["numeric_props_source"] = "API-Football · players" if (local_props or visitor_props) else "pending_real_data"
    lineup.setdefault(
        "status", "estimado" if lineup.get("provider") == "Motor estadístico local" else "probable"
    )
    lineup.setdefault(
        "disponibilidad_local",
        _availability(lineup.get("bajas_local") or [], lineup.get("provider")),
    )
    lineup.setdefault(
        "disponibilidad_visitante",
        _availability(lineup.get("bajas_visitante") or [], lineup.get("provider")),
    )
    quality = dict(lineup.get("quality") or {})
    quality["positions_players"] = 22
    quality["props_players"] = len(local_props) + len(visitor_props)
    quality["real_player_props"] = quality["props_players"]
    quality["numeric_props_source"] = lineup["numeric_props_source"]
    lineup["quality"] = quality
    return True
'''
text = text[:ensure_start] + ensure_impl + text[ensure_end:]

validate_start = text.index("def _validate_item(item: dict) -> dict | None:")
validate_end = text.index("\n\ndef fetch_lineups", validate_start)
validate_impl = '''def _validate_item(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    local, positions_local = _lineup(item.get("local"), item.get("posiciones_local"))
    visitor, positions_visitor = _lineup(item.get("visitante"), item.get("posiciones_visitante"))
    if not local or not visitor:
        return None
    abs_local = _unique_names(item.get("bajas_local"), limit=8) or []
    abs_visitor = _unique_names(item.get("bajas_visitante"), limit=8) or []
    result = {
        "local": local,
        "visitante": visitor,
        "posiciones_local": positions_local,
        "posiciones_visitante": positions_visitor,
        "formacion_local": _formation(positions_local),
        "formacion_visitante": _formation(positions_visitor),
        "positions_inferred": False,
        "bajas_local": abs_local,
        "bajas_visitante": abs_visitor,
        "clave_local": [],
        "clave_visitante": [],
        "best_props": [],
        "numeric_props_source": "pending_real_data",
        "status": "probable",
        "quality": {
            "complete": True,
            "lineup_players": len(local) + len(visitor),
            "props_players": 0,
            "positions_players": len(positions_local) + len(positions_visitor),
            "score": 1.0,
            "numeric_props_source": "pending_real_data",
        },
    }
    result["disponibilidad_local"] = _availability(abs_local)
    result["disponibilidad_visitante"] = _availability(abs_visitor)
    return result
'''
text = text[:validate_start] + validate_impl + text[validate_end:]
text = text.replace(
    '"""Devuelve solo partidos completos; nunca publica onces o props parciales."""',
    '"""Devuelve onces y bajas completos; los props numéricos se calculan fuera de la IA."""',
)

build_start = text.index("def build_statistical_lineup(")
build_impl = '''def build_statistical_lineup(match: dict, home_squad: list[dict], away_squad: list[dict]) -> dict | None:
    """Once gratuito desde plantilla real; no inventa números individuales."""
    local, visitor = _probable_xi(home_squad), _probable_xi(away_squad)
    if not local or not visitor:
        return None
    positions_local = _probable_positions(home_squad, local)
    positions_visitor = _probable_positions(away_squad, visitor)
    return {
        "local": local,
        "visitante": visitor,
        "posiciones_local": positions_local,
        "posiciones_visitante": positions_visitor,
        "formacion_local": _formation(positions_local),
        "formacion_visitante": _formation(positions_visitor),
        "positions_inferred": True,
        "bajas_local": [],
        "bajas_visitante": [],
        "clave_local": [],
        "clave_visitante": [],
        "disponibilidad_local": [],
        "disponibilidad_visitante": [],
        "best_props": [],
        "numeric_props_source": "pending_real_data",
        "status": "estimado",
        "provider": "Motor estadístico local",
        "model": "squad-only-v3",
        "quality": {
            "complete": True,
            "lineup_players": 22,
            "props_players": 0,
            "positions_players": 22,
            "score": 0.72,
            "provisional": True,
            "numeric_props_source": "pending_real_data",
        },
    }
'''
text = text[:build_start] + build_impl
write(path, text)


# 2) Onces oficiales: props únicamente desde API-Football /players.
path = "football/src/futbol_pred/operational.py"
text = read(path)
text = replace_once(
    text,
    "from .ingest.lineups_ai import _best_props, _fallback_props, _formation\n",
    "from .ingest.lineups_ai import _best_props, _formation\n",
    "operational import",
)
text = replace_once(
    text,
    '''            if lineup.get("status") == "confirmado":
                continue
''',
    '''            if lineup.get("status") == "confirmado":
                real_rows = [
                    row for row in (lineup.get("clave_local") or []) + (lineup.get("clave_visitante") or [])
                    if isinstance(row, dict)
                    and str(row.get("source") or "").startswith("API-Football")
                    and row.get("sample_minutes")
                ]
                if len(real_rows) >= 6:
                    continue
''',
    "confirmed retry",
)
text = replace_once(
    text,
    '''        key_local = real_local or _starter_props(old.get("clave_local"), local, "home", match)
        key_visitor = real_visitor or _starter_props(old.get("clave_visitante"), visitor, "away", match)
        real_count = (len(real_local) if real_local else 0) + (len(real_visitor) if real_visitor else 0)
        props_source = "API-Football · players" if real_local and real_visitor else "mixta: API-Football + fallback" if real_local or real_visitor else "fallback estadístico/IA"
''',
    '''        key_local = real_local or []
        key_visitor = real_visitor or []
        real_count = len(key_local) + len(key_visitor)
        props_source = (
            f"API-Football · players ({real_count}/22 con muestra)"
            if real_count else "sin datos reales suficientes"
        )
''',
    "real props only",
)
text = text.replace(
    '            "player_props_source": props_source,\n',
    '            "player_props_source": props_source,\n            "numeric_props_source": "API-Football · players" if real_count else "pending_real_data",\n',
    1,
)
fn_start = text.index("\ndef _starter_props(")
fn_end = text.index("\ndef _merge_absences", fn_start)
text = text[:fn_start] + "\n" + text[fn_end:]
text = replace_once(
    text,
    '''        if len(lineup.get("clave_local") or []) < 3 or len(lineup.get("clave_visitante") or []) < 3:
            reasons.append("props")
''',
    "",
    "content audit props optional",
)
write(path, text)


# 3) Feed quality: ausencia de props es válida; una fila numérica debe ser real.
path = "football/src/futbol_pred/feed_quality.py"
text = read(path)
text = replace_once(
    text,
    '    "quiniela", "players", "model", "market_calibration",\n',
    '    "quiniela", "players", "model", "market_calibration", "historical_seed",\n',
    "historical seed LKG",
)
text = replace_once(
    text,
    '    "weather",\n    "weather_actual",\n',
    '    "weather",\n    "weather_actual",\n    "weather_adjustment",\n    "closing_odds",\n    "extended_market",\n    "extended_value",\n',
    "match evidence LKG",
)
qstart = text.index('    if len(lineup.get("clave_local") or []) < 3 or len(lineup.get("clave_visitante") or []) < 3:')
qend = text.index('    if schema_version >= 6 and lineup.get("status")', qstart)
verified = '''    if not lineup.get("provider"):
        issues.append(f"once_sin_provider:{match.get('id')}")
    rows = (lineup.get("clave_local") or []) + (lineup.get("clave_visitante") or [])
    if rows:
        required_props = {"jugador", "g", "a", "r", "rp", "fc", "fr", "t", "min", "tit"}
        for row in rows:
            if not isinstance(row, dict) or not required_props.issubset(row):
                issues.append(f"props_sin_campos_ampliados:{match.get('id')}")
                break
            try:
                sample = float(row.get("sample_minutes") or 0)
            except (TypeError, ValueError):
                sample = 0
            if not str(row.get("source") or "").startswith("API-Football") or sample <= 0:
                issues.append(f"props_sin_fuente_real:{match.get('id')}")
                break
'''
text = text[:qstart] + verified + text[qend:]
write(path, text)


# 4) Snapshots: guardar evidencia de clima y mercados secundarios.
path = "football/src/futbol_pred/prediction_snapshots.py"
text = read(path)
text = replace_once(
    text,
    '    "weather",\n    "tactical_matchup",\n',
    '    "weather",\n    "weather_adjustment",\n    "extended_market",\n    "extended_value",\n    "tactical_matchup",\n',
    "snapshot extra evidence",
)
write(path, text)


# 5) co.uk: AH solo si las columnas reales existen.
path = "football/src/futbol_pred/ingest/football_data_uk.py"
text = read(path)
under = '            under = _num(row.get("AvgC<2.5")) or _num(row.get("Avg<2.5")) or _num(row.get("B365C<2.5")) or _num(row.get("B365<2.5"))\n'
text = replace_once(
    text,
    under,
    under + '            ah_line = next((v for v in (_num(row.get("AHCh")), _num(row.get("AHh"))) if v is not None), None)\n'
    + '            ah_home = next((v for v in (_num(row.get("AvgCAHH")), _num(row.get("AvgAHH")), _num(row.get("B365CAHH")), _num(row.get("B365AHH"))) if v and v > 1), None)\n'
    + '            ah_away = next((v for v in (_num(row.get("AvgCAHA")), _num(row.get("AvgAHA")), _num(row.get("B365CAHA")), _num(row.get("B365AHA"))) if v and v > 1), None)\n',
    "co uk AH parse",
)
text = replace_once(
    text,
    '''            if over and under:
                odds["ou25"] = {"over": over, "under": under}
            if odds:
''',
    '''            if over and under:
                odds["ou25"] = {"over": over, "under": under}
            if ah_line is not None and ah_home and ah_away:
                odds["asian_handicap"] = {"line": ah_line, "home": ah_home, "away": ah_away, "source": "football-data.co.uk"}
            if odds:
''',
    "co uk AH output",
)
write(path, text)


# 6) Mercados secundarios: líneas solicitadas y AH fallback co.uk.
path = "football/src/futbol_pred/real_market.py"
text = read(path)
text = replace_once(
    text,
    '    "btts", "alternate_totals_corners", "alternate_totals_cards", "alternate_spreads",\n',
    '    "btts", "alternate_totals_corners", "alternate_totals_cards", "spreads", "alternate_spreads",\n',
    "extra spreads",
)
text = replace_once(
    text,
    '''        elif q.market in {"alternate_totals_corners", "alternate_totals_cards"} and q.point is not None:
            key = "corners" if "corners" in q.market else "yellows"
            expected = _num((stats.get(key) or {}).get("total"))
''',
    '''        elif q.market in {"alternate_totals_corners", "alternate_totals_cards"} and q.point is not None:
            allowed = {8.5, 9.5, 10.5} if "corners" in q.market else {3.5, 4.5}
            if float(q.point) not in allowed:
                continue
            key = "corners" if "corners" in q.market else "yellows"
            expected = _num((stats.get(key) or {}).get("total"))
''',
    "requested lines",
)
text = replace_once(
    text,
    '''    if not client.available:
        return {"refreshed": 0, "ranking": [], "source": "football-data.co.uk fallback: sin submercados fiables"}
    for match in matches:
''',
    '''    if not client.available:
        co_cache: dict[str, list[dict]] = {}
        for match in matches:
            if match.get("finished"):
                continue
            block = _co_uk_featured(match, co_cache)
            ah = block.get("asian_handicap") or {}
            line = _num(ah.get("line"))
            for side, selection in (("home", match.get("home")), ("away", match.get("away"))):
                price = _num(ah.get(side))
                signed_line = line if side == "home" else (-line if line is not None else None)
                probs = _asian_ev_prob(match.get("xg"), side, signed_line) if price and signed_line is not None else None
                if not probs:
                    continue
                pwin, ppush, _ = probs
                edge = pwin * price + ppush - 1.0
                row = {
                    "market": "spreads", "selection": selection, "line": signed_line,
                    "odds": round(price, 3), "modelProb": round(pwin, 4),
                    "edge": round(edge, 4), "market_source": "football-data.co.uk",
                }
                match.setdefault("extended_value", []).append(row)
            for row in (match.get("value") or []) + (match.get("extended_value") or []):
                try:
                    edge = float(row.get("edge", -99))
                except (TypeError, ValueError):
                    continue
                if edge > 0.02 and match.get("recommendation", {}).get("decision") != "no_pick":
                    global_rows.append({
                        **row, "match_id": match.get("id"), "home": match.get("home"),
                        "away": match.get("away"), "league": match.get("league"),
                        "kickoff": match.get("kickoff"),
                    })
        ranking = sorted(global_rows, key=lambda row: float(row.get("edge", -99)), reverse=True)[:40]
        return {"refreshed": 0, "ranking": ranking, "source": "football-data.co.uk fallback"}
    for match in matches:
''',
    "co uk fallback ranking",
)
write(path, text)


# 7) Dashboard: semilla histórica, clima, CLV y ranking global.
path = "football/src/futbol_pred/dashboard.py"
text = read(path)
text = replace_once(
    text,
    'from .accuracy_detail import enrich_accuracy\n',
    'from .accuracy_detail import enrich_accuracy\nfrom .real_market import attach_closing_snapshots, attach_extended_market_value\nfrom .weather_effects import apply_weather_adjustments\nfrom .historical_seed import build_historical_seeds\n',
    "dashboard imports",
)
text = replace_once(
    text,
    '''    model_report = _load_model_report(season)
    calibration_source = {"model": model_report} if model_report else previous
    market_calibration = {}
    for league, label in (("laliga", "LaLiga"), ("segunda", "LaLiga Hypermotion")):
        learned = learn_market_calibration((previous or {}).get("matches") or [], label)
        if learned:
            market_calibration[league] = learned
''',
    '''    model_report = _load_model_report(season)
    calibration_source = {"model": model_report} if model_report else previous
    previous_seed = (previous or {}).get("historical_seed") if (previous or {}).get("season") == season else None
    historical_seeds = previous_seed or build_historical_seeds(season)
    market_calibration = {}
    for league, label in (("laliga", "LaLiga"), ("segunda", "LaLiga Hypermotion")):
        learned = learn_market_calibration((previous or {}).get("matches") or [], label)
        if learned:
            market_calibration[league] = {**learned, "scope": "current_season"}
        else:
            seeded = ((historical_seeds.get(league) or {}).get("market_calibration") if historical_seeds else None)
            if seeded:
                market_calibration[league] = {**seeded, "scope": "historical_seed"}
''',
    "historical seed calibration",
)
text = replace_once(
    text,
    '''    matches.sort(key=lambda item: item["kickoff"])
    weather_updates = _attach_venue_weather(matches, now)
    apply_prediction_snapshots(
''',
    '''    matches.sort(key=lambda item: item["kickoff"])
    apply_prediction_snapshots(
''',
    "weather order",
)
text = replace_once(
    text,
    '''    if previous:
        preserve_last_known_good(
            {"schema_version": 7, "matches": matches},
            {"schema_version": previous.get("schema_version"), "matches": previous.get("matches", [])},
        )
    archived_weather_updates = _attach_archived_weather(matches, now)
''',
    '''    if previous:
        preserve_last_known_good(
            {"schema_version": 7, "matches": matches},
            {"schema_version": previous.get("schema_version"), "matches": previous.get("matches", [])},
        )
    weather_updates = _attach_venue_weather(matches, now)
    weather_adjustments = apply_weather_adjustments(matches, now)
    closing_snapshot_updates = attach_closing_snapshots(
        matches, now, previous_matches=(previous or {}).get("matches")
    )
    archived_weather_updates = _attach_archived_weather(matches, now)
''',
    "weather closing integration",
)
text = replace_once(
    text,
    '''    players = _merge_lineup_players(players, matches)
    annotate_prediction_context(matches)
    # Segunda fase: la revisión se captura cuando contexto, once e impacto ya
''',
    '''    players = _merge_lineup_players(players, matches)
    annotate_prediction_context(matches)
    market_value = attach_extended_market_value(
        matches, now, previous_matches=(previous or {}).get("matches"),
        stats_models=stats_models_by_league,
    )
    # Segunda fase: la revisión se captura cuando contexto, once e impacto ya
''',
    "extended value integration",
)
text = replace_once(
    text,
    '''    audit["weather_updates"] = weather_updates
    audit["archived_weather_updates"] = archived_weather_updates
    audit["state_simulations"] = state_simulations
''',
    '''    audit["weather_updates"] = weather_updates
    audit["weather_adjustments"] = weather_adjustments
    audit["closing_snapshot_updates"] = closing_snapshot_updates
    audit["extended_market_updates"] = market_value.get("refreshed", 0)
    audit["archived_weather_updates"] = archived_weather_updates
    audit["state_simulations"] = state_simulations
''',
    "audit counters",
)
text = replace_once(
    text,
    '''        "model": model_report,
        "market_calibration": market_calibration or None,
        "accuracy": enrich_accuracy(_aggregate_accuracy(matches), matches),
''',
    '''        "model": model_report,
        "market_calibration": market_calibration or None,
        "historical_seed": historical_seeds or None,
        "value_ranking": market_value.get("ranking") or [],
        "market_value_source": market_value.get("source"),
        "accuracy": enrich_accuracy(_aggregate_accuracy(matches), matches),
''',
    "payload ranking seed",
)
text = replace_once(
    text,
    '            "players": "football-data.org (plantillas, goleadores y asistencias)",\n            "odds": "football-data.co.uk (media de mercado: 1X2 y over/under 2.5)",\n',
    '            "players": "API-Football /players para tasas individuales reales por-90; football-data.org para plantillas; IA solo once y bajas",\n            "odds": "The Odds API cuando hay ODDS_API_KEY (consenso + submercados); football-data.co.uk como fallback real 1X2/O-U2.5/AH cuando publica columnas",\n',
    "data sources",
)
text = replace_once(
    text,
    '            "weather": "Open-Meteo (CC BY 4.0): previsión horaria + Historical Forecast archivado por estadio; el histórico es solo para validación hasta superar gate",\n',
    '            "weather": "Open-Meteo (CC BY 4.0): forecast horario cuantifica xG/remates/disciplina; histórico separado para validación",\n',
    "weather source",
)
text = replace_once(
    text,
    '                      "Las plantillas gratuitas y los onces del motor local son provisionales; "\n',
    '                      "Las plantillas gratuitas y los onces del motor local son provisionales; los props numéricos solo se muestran con muestra real; "\n',
    "props disclaimer",
)
write(path, text)


# 8) UI: ranking global + histórico separado.
path = "app/src/App.jsx"
text = read(path)
text = replace_once(
    text,
    'import ClvPanel from "./ClvPanel";\n',
    'import ClvPanel from "./ClvPanel";\nimport GlobalValuePanel from "./GlobalValuePanel";\nimport HistoricalQualityPanel from "./HistoricalQualityPanel";\n',
    "App imports",
)
text = replace_once(
    text,
    'function ValueBets({ matches, bank, setBank }) {\n',
    'function ValueBets({ matches, bank, setBank, globalValue }) {\n',
    "ValueBets signature",
)
text = replace_once(
    text,
    '''  return (
    <>
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
''',
    '''  return (
    <>
      <GlobalValuePanel rows={globalValue} />
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
''',
    "GlobalValuePanel render",
)
text = replace_once(
    text,
    '      <ProbabilityQualityPanel quality={perf.probability_quality} />\n      <AccuracyPanel acc={data.accuracy} />\n',
    '      <ProbabilityQualityPanel quality={perf.probability_quality} />\n      <HistoricalQualityPanel seeds={data.historical_seed} />\n      <AccuracyPanel acc={data.accuracy} />\n',
    "historical quality UI",
)
text = replace_once(
    text,
    '{view === "value" && <ValueBets matches={matches} bank={bank} setBank={setBank} />}\n',
    '{view === "value" && <ValueBets matches={matches} bank={bank} setBank={setBank} globalValue={data.value_ranking} />}\n',
    "ValueBets call",
)
text = text.replace(
    '<li><b>Clima del estadio</b>: previsión Open-Meteo a la hora del saque inicial. Por ahora ajusta confianza y explicación, no goles.</li>',
    '<li><b>Clima del estadio</b>: Open-Meteo cuantifica un ajuste conservador de xG, remates, faltas y tarjetas; el 1X2 queda intacto hasta validación histórica.</li>',
)
write(path, text)


# 9) Detalle: fuente de props visible y delta meteorológico explícito.
path = "app/src/MatchDetail.jsx"
text = read(path)
text = replace_once(
    text,
    'import OfficialStatsPanel from "./OfficialStatsPanel";\n',
    'import OfficialStatsPanel from "./OfficialStatsPanel";\nimport WeatherAdjustmentPanel from "./WeatherAdjustmentPanel";\n',
    "MatchDetail weather import",
)
text = replace_once(
    text,
    '              <td className="tl" title={p.source ? `${p.source}${p.sample_minutes ? ` · ${p.sample_minutes} min de muestra` : ""}` : undefined}>{highlighted.has(p.jugador) ? "★ " : ""}{p.jugador}</td>\n',
    '              <td className="tl" title={p.source ? `${p.source}${p.sample_minutes ? ` · ${p.sample_minutes} min de muestra` : ""}` : undefined}>{highlighted.has(p.jugador) ? "★ " : ""}{p.jugador}{p.source && <div className="mk-sub">{p.source}{p.sample_minutes ? ` · ${p.sample_minutes} min · per-90 × min previstos` : ""}</div>}</td>\n',
    "visible prop source",
)
text = replace_once(
    text,
    '''      <div className="xi-grid" style={{ marginTop: 10 }}>
        <PropsTable title={m.home} clave={a.clave_local} best={a.best_props} />
        <PropsTable title={m.away} clave={a.clave_visitante} best={a.best_props} />
      </div>
''',
    '''      {((a.clave_local || []).length > 0 || (a.clave_visitante || []).length > 0) ? <div className="xi-grid" style={{ marginTop: 10 }}>
        <PropsTable title={m.home} clave={a.clave_local} best={a.best_props} />
        <PropsTable title={m.away} clave={a.clave_visitante} best={a.best_props} />
      </div> : <div className="note" style={{ marginTop: 10 }}>Props numéricos: sin datos reales suficientes. La IA no rellena estimaciones individuales.</div>}
''',
    "real prop empty state",
)
text = replace_once(
    text,
    '      <OfficialStatsPanel match={m} />\n',
    '      <WeatherAdjustmentPanel adjustment={m.weather_adjustment} />\n      <OfficialStatsPanel match={m} />\n',
    "weather panel",
)
write(path, text)


# Invariantes del parche.
lineups = read("football/src/futbol_pred/ingest/lineups_ai.py")
operational = read("football/src/futbol_pred/operational.py")
quality = read("football/src/futbol_pred/feed_quality.py")
app = read("app/src/App.jsx")
match_detail = read("app/src/MatchDetail.jsx")
assert '"clave_local": []' in lineups and '"clave_visitante": []' in lineups
assert '_starter_props(' not in operational
assert 'props_sin_fuente_real' in quality
assert 'GlobalValuePanel' in app and 'HistoricalQualityPanel' in app
assert 'WeatherAdjustmentPanel' in match_detail
print("PR33 hardening integration applied")
