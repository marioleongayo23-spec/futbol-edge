"""Genera el feed JSON que consume la app privada Fútbol Edge.

El cron usa las claves ya configuradas en GitHub Secrets. Si no hay ninguna
fuente real configurada, no sobrescribe el último feed válido con datos demo.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import DATA_DIR
from .feed_quality import load_feed, preserve_last_known_good, write_feed_safely
from .ingest.api_football import ApiFootballClient, Fixture
from .ingest.football_data import FootballDataClient
from .normalize import canonical_team
from .pipeline import fit_model_from_fixtures, get_fixtures, predict_match, run_model_report

MADRID = ZoneInfo("Europe/Madrid")
OUTPUT = Path(DATA_DIR) / "dashboard.json"


def _canon(name: str) -> str:
    """canonical_team sin ruido de warnings (equipos desconocidos se dejan igual)."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return canonical_team(name)


# Plan de sembrado por liga: temporadas y divisiones previas con las que se
# ajusta el modelo, para que los recién ascendidos tengan histórico real. El
# solape de equipos entre temporadas/divisiones (ascensos y descensos) calibra
# la escala de fuerza entre Primera y Segunda; el decaimiento temporal ya
# pondera menos lo antiguo.
SEED_PLAN = {
    "laliga": [("laliga", 1), ("laliga", 2), ("segunda", 1)],
    "segunda": [("segunda", 1), ("segunda", 2), ("laliga", 1)],
    "champions": [("champions", 1)],
}
LEAGUES = {
    "laliga": "LaLiga",
    "segunda": "LaLiga Hypermotion",
    "champions": "Champions League",
}
FINISHED = {"FINISHED", "AWARDED", "FT", "AET", "PEN"}


def current_season(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    return now.year if now.month >= 7 else now.year - 1


def is_pending(fixture: Fixture) -> bool:
    return (
        fixture.home_goals is None
        and fixture.away_goals is None
        and fixture.status.upper() not in FINISHED
    )


def ensure_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def fixture_payload(
    fixture: Fixture,
    model,
    generated_at: str,
    stats=None,
    team_meta: dict | None = None,
    real_stats: dict | None = None,
    odds_map: dict | None = None,
    model_weight: float = 0.6,
    h2h: dict | None = None,
    trends=None,
) -> dict:
    kickoff = ensure_aware(fixture.kickoff).astimezone(MADRID)
    team_meta = team_meta or {}
    hmeta = team_meta.get(fixture.home_team, {})
    ameta = team_meta.get(fixture.away_team, {})
    finished = not is_pending(fixture)
    payload = {
        "id": f"{fixture.source}-{fixture.api_id}",
        "date": kickoff.date().isoformat(),
        "kickoff": kickoff.isoformat(),
        "matchday": fixture.matchday,
        "stage": fixture.stage,
        "home": fixture.home_team,
        "away": fixture.away_team,
        "homeCrest": fixture.home_crest or hmeta.get("crest"),
        "awayCrest": fixture.away_crest or ameta.get("crest"),
        "homeTla": fixture.home_tla or hmeta.get("tla"),
        "awayTla": fixture.away_tla or ameta.get("tla"),
        "homeColors": hmeta.get("colors"),
        "awayColors": ameta.get("colors"),
        "league": LEAGUES.get(fixture.league, fixture.league),
        "venue": "Por confirmar",
        "status": fixture.status or "SCHEDULED",
        "finished": finished,
        "source": fixture.source,
        "engine": "calendar-only",
        "updatedAt": generated_at,
    }
    # Honestidad: lo que aún no tenemos de una fuente real va como "pendiente",
    # nunca inventado (jugadores/alineaciones y cuotas requieren fuente de pago).
    payload["players"] = "pendiente_fuente_de_pago"
    payload["odds"] = "pendiente_odds_api"

    # Enfrentamientos directos pasados (hasta 6 más recientes).
    if h2h:
        meetings = h2h.get(frozenset((_canon(fixture.home_team), _canon(fixture.away_team))))
        if meetings:
            payload["h2h"] = meetings[-6:]

    # Partido ya jugado: resultado real + estadísticas reales para el post-partido.
    finished_with_result = finished and fixture.home_goals is not None
    if finished_with_result:
        payload["result"] = [fixture.home_goals, fixture.away_goals]
        payload["engine"] = "resultado-real"
        if real_stats:
            sr = real_stats.get((_canon(fixture.home_team), _canon(fixture.away_team)))
            if sr:
                payload["statsReal"] = sr

    if model is None:
        return payload
    home_id, away_id = _canon(fixture.home_team), _canon(fixture.away_team)
    try:
        prediction = predict_match(model, home_id, away_id, kickoff=fixture.kickoff)
        matrix = model.predict_matrix(home_id, away_id)
    except (KeyError, ValueError):
        return payload

    probs = prediction.one_x_two
    eh, ea = prediction.expected_goals
    # Guard de sanidad: descarta predicciones REALMENTE rotas (p. ej. un único
    # resultado al ~100%). El umbral inferior de goles es laxo a propósito: un
    # equipo muy flojo (recién ascendido) contra una gran defensa puede tener un
    # xG legítimamente bajo (~0.1) y merece predicción, no "datos insuficientes".
    degenerate = (
        max(probs.values()) >= 0.985
        or min(eh, ea) < 0.05
        or max(eh, ea) > 4.5
    )
    if degenerate:
        # En un partido jugado conservamos el resultado real; solo marcamos que
        # la predicción no era fiable.
        if not finished_with_result:
            payload["engine"] = "datos-insuficientes"
        payload["nota"] = "Modelo aún sin muestra fiable de la temporada"
        return payload

    top = matrix.top_correct_scores(1)[0]
    # Bloque de predicción. En un jugado sirve para comparar con lo real
    # (esperado vs real); NO tocamos engine, que sigue siendo 'resultado-real'.
    payload.update({
        "probs": [round(probs["1"] * 100), round(probs["X"] * 100), round(probs["2"] * 100)],
        "xg": [round(value, 2) for value in prediction.expected_goals],
        "markets": {
            "over_2_5": round(matrix.over(2.5), 3),
            "over_1_5": round(matrix.over(1.5), 3),
            "over_3_5": round(matrix.over(3.5), 3),
            "btts": round(matrix.btts()["yes"], 3),
            "marcador": f"{top[0]}-{top[1]}",
        },
    })
    if not finished_with_result:
        payload["engine"] = "dixon-coles"

    # Si algún equipo aún no tiene histórico (recién ascendido, sin datos de la
    # temporada), la predicción usa prior neutro: la marcamos como provisional.
    if not (model.is_known(home_id) and model.is_known(away_id)):
        payload["provisional"] = True
        payload["nota"] = "Predicción provisional: algún equipo aún sin histórico"

    # Estadísticas ESPERADAS por equipo (córners, tarjetas, remates, faltas...).
    # El predictor de stats (co.uk) cae a la media de liga cuando un equipo aún
    # no tiene muestra, y esa media está sesgada al local → contradecía al modelo
    # (p. ej. el favorito visitante salía con menos goles/remates). Se ALINEA con
    # la fuerza del modelo: goles = xG; remates/tiros/córners se reparten según la
    # cuota de dominio (xG); faltas/tarjetas se dejan neutras (no dependen de quién
    # domina). Total conservado.
    if stats is not None:
        try:
            sp = stats.predict_fixture(fixture.home_team, fixture.away_team)
            if sp:
                tot_g = eh + ea
                hshare = (eh / tot_g) if tot_g > 0 else 0.5
                out_stats = {}
                for k, v in sp.items():
                    if k == "goals":
                        h, a = round(eh, 2), round(ea, 2)
                    elif k in ("shots", "sot", "corners"):
                        t = v["total"]
                        h, a = round(t * hshare, 1), round(t * (1 - hshare), 1)
                    else:  # faltas, amarillas, rojas: sin sesgo por dominio
                        h, a = v["home"], v["away"]
                    out_stats[k] = {"home": h, "away": a, "total": round(h + a, 2)}
                payload["stats"] = out_stats
        except (KeyError, ValueError):
            pass

    # Tendencia (↑/→/↓) de las stats esperadas: forma reciente + lo que espera el
    # modelo vs la media de liga + descanso. Solo en próximos con predicción.
    if not finished_with_result and trends is not None:
        try:
            st = payload.get("stats") or {}
            predicted = {"goals": eh + ea}
            for k in ("shots", "corners", "yellows"):
                if st.get(k):
                    predicted[k] = st[k]["total"]
            t = trends.trend(home_id, away_id, kickoff=fixture.kickoff, predicted=predicted)
            if t:
                payload["tendencias"] = t
        except Exception:  # noqa: BLE001 - la tendencia nunca tumba el feed
            pass

    # Cuotas y value bets solo para partidos por jugar.
    if not finished_with_result and odds_map:
        mo = odds_map.get((_canon(fixture.home_team), _canon(fixture.away_team)))
        if mo:
            _attach_odds_value(payload, mo, prediction.one_x_two, matrix, model_weight)
    return payload


def _attach_odds_value(payload: dict, market_odds: dict, one_x_two: dict, matrix,
                       model_weight: float = 0.6) -> None:
    """Añade payload['odds'] (mercado + prob. justa sin vig) y payload['value'].

    CALIBRACIÓN: con pocas jornadas el modelo va sobreconfiado, así que las
    probabilidades finales se mezclan con las del mercado (sin margen) según
    ``model_weight`` (crece con la temporada). El value se calcula con la
    probabilidad calibrada → edges realistas, no inflados. Actualiza también
    payload['probs'] (1X2) con la versión calibrada."""
    from .value.odds import remove_vig

    block: dict = {}
    value: list[dict] = []

    o = market_odds.get("1x2")
    if o and all(o.get(k) for k in ("1", "X", "2")):
        fair = remove_vig([o["1"], o["X"], o["2"]])
        fair_probs = {"1": fair[0], "X": fair[1], "2": fair[2]}
        # Mezcla modelo ↔ mercado y renormaliza.
        w = max(0.0, min(1.0, model_weight))
        cal = {s: w * one_x_two.get(s, 0.0) + (1 - w) * fair_probs[s] for s in ("1", "X", "2")}
        tot = sum(cal.values()) or 1.0
        cal = {s: cal[s] / tot for s in cal}
        block["1x2"] = {
            "odds": {k: round(o[k], 2) for k in ("1", "X", "2")},
            "fair": {k: round(fair_probs[k], 3) for k in ("1", "X", "2")},
        }
        payload["probs"] = [round(cal["1"] * 100), round(cal["X"] * 100), round(cal["2"] * 100)]
        payload["calibrated"] = True
        for sel in ("1", "X", "2"):
            value.append({
                "market": "1x2", "selection": sel, "odds": round(o[sel], 2),
                "modelProb": round(cal[sel], 3), "edge": round(cal[sel] * o[sel] - 1.0, 3),
            })

    ou = market_odds.get("ou25")
    if ou and ou.get("over") and ou.get("under"):
        try:
            p_over = matrix.over(2.5)
        except (KeyError, ValueError):
            p_over = None
        if p_over is not None:
            fair = remove_vig([ou["over"], ou["under"]])
            w = max(0.0, min(1.0, model_weight))
            cal_over = w * p_over + (1 - w) * fair[0]
            block["ou25"] = {
                "odds": {"over": round(ou["over"], 2), "under": round(ou["under"], 2)},
                "fair": {"over": round(fair[0], 3), "under": round(fair[1], 3)},
            }
            for sel, mp in (("over", cal_over), ("under", 1.0 - cal_over)):
                value.append({
                    "market": "ou25", "selection": sel, "odds": round(ou[sel], 2),
                    "modelProb": round(mp, 3), "edge": round(mp * ou[sel] - 1.0, 3),
                })

    if block:
        payload["odds"] = block
        value.sort(key=lambda v: v["edge"], reverse=True)
        payload["value"] = value


def _env_true(name: str) -> bool:
    import os

    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _force_ai() -> bool:
    """Solo se activa de forma explícita (workflow_dispatch o ejecución local)."""

    return _env_true("FORCE_AI")


def _ai_window(now: datetime) -> bool:
    """IA únicamente por la mañana (06-10) o noche (20-23), hora de Madrid."""

    if _force_ai():
        return True
    hour = ensure_aware(now).astimezone(MADRID).hour
    return 6 <= hour < 10 or 20 <= hour < 23


def _age_hours(now: datetime, value: str | None) -> float | None:
    try:
        stamp = ensure_aware(datetime.fromisoformat(str(value)))
    except (TypeError, ValueError):
        return None
    return (ensure_aware(now) - stamp).total_seconds() / 3600


def _within_horizon(match: dict, now: datetime, horizon_days: int) -> bool:
    try:
        delta = ensure_aware(datetime.fromisoformat(match["kickoff"])) - ensure_aware(now)
    except (KeyError, TypeError, ValueError):
        return False
    return -3 * 3600 <= delta.total_seconds() <= horizon_days * 86400


def _can_attempt(match: dict, kind: str, now: datetime, cooldown_hours: int = 6) -> bool:
    if _force_ai():
        return True
    attempted = (match.get("ai_attempts") or {}).get(kind)
    age = _age_hours(now, attempted)
    return age is None or age >= cooldown_hours


def _mark_attempt(match: dict, kind: str, now: datetime) -> None:
    attempts = dict(match.get("ai_attempts") or {})
    attempts[kind] = ensure_aware(now).isoformat()
    match["ai_attempts"] = attempts


def _attach_previews(
    matches: list[dict],
    now: datetime,
    horizon_days: int = 2,
    limit: int = 5,
    ttl_hours: int = 10,
) -> None:
    """Actualiza con IA en ventana y rellena gratis cualquier hueco restante."""

    try:
        from .ingest.ai_client import available
        from .ingest.preview_gemini import generate_preview, generate_statistical_preview
    except Exception:
        return

    candidates = []
    if available() and _ai_window(now):
        for match in matches:
            if match.get("finished") or not match.get("probs") or not _within_horizon(match, now, horizon_days):
                continue
            meta = match.get("preview_meta") or {}
            age = _age_hours(now, meta.get("generated_at"))
            is_local_fallback = meta.get("provider") == "Motor estadístico local"
            fresh = bool(match.get("preview")) and not is_local_fallback and age is not None and age < ttl_hours
            if fresh and not _force_ai():
                continue
            if _can_attempt(match, "preview", now):
                candidates.append(match)
        candidates.sort(key=lambda match: match.get("kickoff") or "")

        for match in candidates[:limit]:
            _mark_attempt(match, "preview", now)
            try:
                result = generate_preview(match)
            except Exception:
                result = None
            if not result:
                continue
            match["preview"] = result.text
            match["preview_meta"] = {
                "provider": result.provider,
                "model": result.model,
                "generated_at": ensure_aware(now).isoformat(),
                "quality": result.quality,
            }

    # Nunca se publica un próximo partido con predicción sin resumen. El texto
    # local no consume cuota y la IA lo sustituye en la siguiente ventana.
    stamp = ensure_aware(now).isoformat()
    for match in matches:
        if match.get("finished") or not match.get("probs") or match.get("preview"):
            continue
        result = generate_statistical_preview(match)
        if result:
            match["preview"] = result.text
            match["preview_meta"] = {
                "provider": result.provider,
                "model": result.model,
                "generated_at": stamp,
                "quality": result.quality,
                "provisional": True,
            }


def _attach_lineups(
    matches: list[dict],
    now: datetime,
    squads: dict[str, list[dict]] | None = None,
    horizon_days: int = 2,
    limit: int = 10,
    ttl_hours: int = 10,
) -> None:
    """Actualiza onces con IA y cae a plantillas reales + motor local gratis."""

    try:
        from .ingest.ai_client import available
        from .ingest.lineups_ai import build_statistical_lineup, fetch_lineups
    except Exception:
        return

    stale = []
    stamp = ensure_aware(now).isoformat()
    if available() and _ai_window(now):
        for match in matches:
            if match.get("finished") or not match.get("probs") or not _within_horizon(match, now, horizon_days):
                continue
            lineup = match.get("alineacion") or {}
            generated_at = lineup.get("generated_at") or lineup.get("ts")
            age = _age_hours(now, generated_at)
            is_local_fallback = lineup.get("provider") == "Motor estadístico local"
            fresh = bool(lineup) and not is_local_fallback and age is not None and age < ttl_hours
            if fresh and not _force_ai():
                continue
            if _can_attempt(match, "lineup", now):
                stale.append(match)
        stale.sort(key=lambda match: match.get("kickoff") or "")
        stale = stale[:limit]
        for match in stale:
            _mark_attempt(match, "lineup", now)
        query = [{"partido": f"{match['home']} vs {match['away']}"} for match in stale]
        try:
            generated = fetch_lineups(query) if query else {}
        except Exception:
            generated = {}
        for match in stale:
            data = generated.get(f"{match['home']} vs {match['away']}")
            if data:
                match["alineacion"] = {
                    **data,
                    "generated_at": stamp,
                    "ts": stamp,
                    "fuente": data.get("provider"),
                }

    squads = squads or {}
    for match in matches:
        if match.get("finished") or not match.get("probs") or match.get("alineacion"):
            continue
        home_squad = _squad_for(squads, match.get("home"))
        away_squad = _squad_for(squads, match.get("away"))
        data = build_statistical_lineup(match, home_squad, away_squad)
        if data:
            match["alineacion"] = {
                **data,
                "generated_at": stamp,
                "ts": stamp,
                "fuente": data.get("provider"),
            }

    # Excepción de seguridad: fuera de ventana, la IA no refresca contenido ya
    # existente, pero sí completa una sola vez los huecos de toda la temporada
    # que las plantillas gratuitas no cubren. Al quedar cacheados no se repite.
    if available() and not _ai_window(now):
        emergency = sorted([
            match for match in matches
            if not match.get("finished") and match.get("probs") and not match.get("alineacion")
            and _can_attempt(match, "lineup", now)
        ], key=lambda match: match.get("kickoff") or "")[:10]
        for match in emergency:
            _mark_attempt(match, "lineup", now)
        query = [{"partido": f"{match['home']} vs {match['away']}"} for match in emergency]
        try:
            generated = fetch_lineups(query) if query else {}
        except Exception:
            generated = {}
        for match in emergency:
            data = generated.get(f"{match['home']} vs {match['away']}")
            if data:
                match["alineacion"] = {
                    **data,
                    "generated_at": stamp,
                    "ts": stamp,
                    "fuente": data.get("provider"),
                    "emergency_backfill": True,
                }


def _squad_for(squads: dict[str, list[dict]], team: str | None) -> list[dict]:
    if not team:
        return []
    if team in squads:
        return squads[team]
    wanted = _canon(team)
    for name, squad in squads.items():
        if _canon(name) == wanted:
            return squad
    return []


def _merge_squad_players(
    players: dict | None,
    squads_by_league: dict[str, dict],
    previous_players: dict | None = None,
) -> dict | None:
    """Completa el feed de jugadores con las plantillas gratuitas oficiales."""

    out = json.loads(json.dumps(previous_players or {}))
    for league, current in (players or {}).items():
        bucket = out.setdefault(league, {"label": current.get("label", league), "rankings": {}, "players": []})
        bucket["label"] = current.get("label") or bucket.get("label") or league
        bucket.setdefault("rankings", {}).update(current.get("rankings") or {})
        flat = bucket.setdefault("players", [])
        positions = {(str(p.get("team")).casefold(), str(p.get("player")).casefold()): i for i, p in enumerate(flat)}
        for player in current.get("players") or []:
            key = (str(player.get("team")).casefold(), str(player.get("player")).casefold())
            if key in positions:
                flat[positions[key]] = player
            else:
                positions[key] = len(flat)
                flat.append(player)
    labels = {"laliga": "LaLiga", "segunda": "LaLiga Hypermotion", "champions": "Champions League"}
    for league, teams in squads_by_league.items():
        bucket = out.setdefault(league, {"label": labels.get(league, league), "rankings": {}, "players": []})
        bucket.setdefault("rankings", {})
        flat = bucket.setdefault("players", [])
        existing = {(str(p.get("team")).casefold(), str(p.get("player")).casefold()) for p in flat}
        for team, squad in teams.items():
            for raw in squad:
                name = str(raw.get("name") or "").strip()
                key = (team.casefold(), name.casefold())
                if not name or key in existing:
                    continue
                flat.append({
                    "player": name, "team": team, "position": raw.get("position") or "",
                    "goals": 0, "assists": 0, "shots": 0, "yc": 0, "min": 0,
                    "source": "football-data.org squad",
                })
                existing.add(key)
    return out or None


def _squads_from_players(players: dict | None) -> dict[str, dict[str, list[dict]]]:
    out: dict[str, dict[str, list[dict]]] = {}
    for league, bucket in (players or {}).items():
        teams: dict[str, list[dict]] = {}
        for player in bucket.get("players") or []:
            team = str(player.get("team") or "").strip()
            name = str(player.get("player") or "").strip()
            if team and name:
                teams.setdefault(team, []).append({"name": name, "position": player.get("position") or ""})
        out[league] = {team: squad for team, squad in teams.items() if len(squad) >= 11}
    return out


def _fill_missing_free_squads(
    matches: list[dict],
    now: datetime,
    squads_by_league: dict[str, dict[str, list[dict]]],
    max_teams: int = 12,
) -> None:
    """Consulta API-Football solo para próximos equipos sin plantilla cacheada."""

    client = ApiFootballClient()
    if client.offline:
        return
    league_keys = {"LaLiga": "laliga", "LaLiga Hypermotion": "segunda", "Champions League": "champions"}
    pending: list[tuple[str, str]] = []
    seen = set()
    flat = {team: squad for teams in squads_by_league.values() for team, squad in teams.items()}
    for match in matches:
        if match.get("finished") or not match.get("probs") or not _within_horizon(match, now, 3):
            continue
        league = league_keys.get(match.get("league"), "laliga")
        for team in (match.get("home"), match.get("away")):
            if not team or _squad_for(flat, team) or _canon(team) in seen:
                continue
            seen.add(_canon(team))
            pending.append((league, team))
    for league, team in pending[:max_teams]:
        squad = client.get_squad(team)
        if len(squad) >= 11:
            squads_by_league.setdefault(league, {})[team] = squad


def build_dashboard(
    now: datetime | None = None,
    horizon_days: int = 10,  # sin uso: ahora incluimos TODA la temporada
) -> dict:
    now = now or datetime.now(timezone.utc)
    now = ensure_aware(now)
    season = current_season(now)
    generated_at = now.astimezone(MADRID).isoformat()
    previous = load_feed(OUTPUT)
    matches: list[dict] = []
    errors: list[dict] = []
    squads_by_league: dict[str, dict[str, list[dict]]] = {}

    for league in LEAGUES:
        try:
            fixtures = get_fixtures(league, season=season)
            if not fixtures:
                continue
            # Sembrado: el modelo se ajusta con la temporada ANTERIOR + la
            # actual, así hay predicciones fiables desde la jornada 1
            # (el decaimiento temporal ya pondera más lo reciente).
            train = _seed_fixtures(league, season) + fixtures
            try:
                model = fit_model_from_fixtures(
                    train, as_of=now.replace(tzinfo=None), name_fn=_canon
                )
            except (ValueError, KeyError):
                model = None
            stats = _fit_stats(league, season)
            meta = _team_meta(league, season)
            squads_by_league[league] = {
                team: info.get("squad") or []
                for team, info in meta.items()
                if len(info.get("squad") or []) >= 11
            }
            real_stats = _real_stats_map(league, season)
            trends = _fit_trends(league, season, train)
            odds_map = _odds_map(league)
            # Peso del modelo vs mercado para calibrar: con pocas jornadas jugadas
            # el modelo va sobreconfiado, así que pesa más el mercado; según avanza
            # la liga, el modelo gana peso. mpt = media de partidos por equipo.
            played_n = sum(1 for f in fixtures if f.home_goals is not None)
            teams_n = len({f.home_team for f in fixtures} | {f.away_team for f in fixtures})
            mpt = (2 * played_n / teams_n) if teams_n else 0
            model_w = max(0.2, min(0.9, mpt / 12))
            h2h = _h2h_map(train)  # incluye temporadas previas (sembrado)
            # TODOS los partidos de la temporada (resultados + próximos).
            matches.extend(
                fixture_payload(fx, model, generated_at, stats=stats, team_meta=meta,
                                real_stats=real_stats, odds_map=odds_map,
                                model_weight=model_w, h2h=h2h, trends=trends)
                for fx in sorted(fixtures, key=lambda item: ensure_aware(item.kickoff))
            )
        except Exception as exc:  # una liga no debe tumbar el resto del feed
            status = getattr(getattr(exc, "response", None), "status_code", None)
            errors.append({
                "league": league,
                "error": type(exc).__name__,
                "http_status": status,
            })

    matches.sort(key=lambda item: item["kickoff"])
    # Recupera predicciones/IA/odds anteriores antes de intentar refrescarlas.
    # De esta forma un timeout, una cuota agotada o una respuesta parcial jamás
    # convierte una tarjeta que funcionaba en un hueco en blanco.
    if previous:
        preserve_last_known_good({"matches": matches}, {"matches": previous.get("matches", [])})
    base_players = _merge_squad_players(
        _load_players(season), squads_by_league, (previous or {}).get("players")
    )
    for league, teams in _squads_from_players(base_players).items():
        known = squads_by_league.setdefault(league, {})
        for team, squad in teams.items():
            known.setdefault(team, squad)
    _fill_missing_free_squads(matches, now, squads_by_league)
    players = _merge_squad_players(base_players, squads_by_league, (previous or {}).get("players"))
    all_squads = {
        team: squad
        for league_squads in squads_by_league.values()
        for team, squad in league_squads.items()
    }
    _attach_previews(matches, now)
    _attach_lineups(matches, now, squads=all_squads)
    payload = {
        "schema_version": 4,
        "generated_at": generated_at,
        "season": season,
        "quiniela": _load_quiniela_oficial(),
        "players": players,
        "model": _load_model_report(season),
        "accuracy": _aggregate_accuracy(matches),
        "engine": "dixon-coles" if any(item["engine"] == "dixon-coles" for item in matches) else "calendar-only",
        "data_sources": {
            "fixtures": "football-data.org (LaLiga) · football-data.co.uk (Segunda)",
            "stats": "football-data.co.uk (remates, córners, faltas, tarjetas — reales y esperadas)",
            "players": "football-data.org (plantillas, goleadores y asistencias)",
            "odds": "football-data.co.uk (media de mercado: 1X2 y over/under 2.5)",
            "ai": "Gemini dinámico → Groq → motor local gratuito; refresco IA 06-10 y 20-23 Europe/Madrid, con backfill solo si un próximo partido sigue vacío",
        },
        "disclaimer": "Probabilidades y ventaja estadística, no certezas. "
                      "Las plantillas gratuitas y los onces del motor local son provisionales; "
                      "las cuotas se muestran como pendientes cuando no existe una fuente real.",
        "counts": {
            "total": len(matches),
            "jugados": sum(1 for m in matches if m.get("finished")),
            "proximos": sum(1 for m in matches if not m.get("finished")),
            "con_prediccion": sum(1 for m in matches if m.get("engine") == "dixon-coles"),
        },
        "matches": matches,
        "errors": errors,
    }
    return preserve_last_known_good(payload, previous)


def _aggregate_accuracy(matches: list[dict]) -> dict | None:
    """Bucle de mejora: acierto histórico del modelo comparando lo estimado con lo
    realmente ocurrido en los partidos ya jugados. % de acierto 1X2 y error medio
    (MAE) + sesgo por métrica (córners, remates, faltas...), leyendo los campos que
    ya lleva cada partido jugado (probs/result y stats/statsReal)."""
    labels = {"shots": "Remates", "sot": "Tiros a puerta", "corners": "Córners",
              "fouls": "Faltas", "yellows": "Amarillas"}
    hits = n_sign = 0
    per: dict = {}
    for m in matches:
        res = m.get("result")
        if not m.get("finished") or not res:
            continue
        # Acierto 1X2: favorito del modelo vs signo real.
        probs = m.get("probs")
        if probs and len(probs) == 3:
            fav = ["1", "X", "2"][max(range(3), key=lambda i: probs[i])]
            real = _sign(res[0], res[1])
            n_sign += 1
            hits += int(fav == real)
        # Error por métrica: esperado (stats) vs real (statsReal).
        pred, real_stats = m.get("stats"), m.get("statsReal")
        if not pred or not real_stats:
            continue
        for key in labels:
            if key not in pred or key not in real_stats:
                continue
            try:
                pred_total = float(pred[key]["total"])
                rk = real_stats[key]
                # statsReal puede venir como {home,away,total} o como (home, away).
                if isinstance(rk, dict):
                    real_total = float(rk.get("total", rk.get("home", 0) + rk.get("away", 0)))
                else:
                    real_total = float(rk[0]) + float(rk[1])
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            d = per.setdefault(key, {"abs": 0.0, "signed": 0.0, "n": 0})
            d["abs"] += abs(real_total - pred_total)
            d["signed"] += real_total - pred_total
            d["n"] += 1
    if not n_sign and not per:
        return None
    metrics = [
        {"key": k, "label": labels[k], "n": d["n"],
         "mae": round(d["abs"] / d["n"], 2),
         "sesgo": round(d["signed"] / d["n"], 2)}
        for k, d in per.items() if d["n"]
    ]
    metrics.sort(key=lambda x: x["mae"])
    return {
        "n_partidos": sum(1 for m in matches if m.get("finished") and m.get("result")),
        "aciertos_1x2": hits,
        "n_1x2": n_sign,
        "pct_1x2": round(100 * hits / n_sign) if n_sign else None,
        "metrics": metrics,
    }


def _sign(h: int, a: int) -> str:
    return "1" if h > a else ("X" if h == a else "2")


def _load_model_report(season: int) -> dict | None:
    """Calibración y comparación de modelos por liga (para 'Datos y modelos')."""
    out: dict = {}
    for league, label in (("laliga", "LaLiga"), ("segunda", "LaLiga Hypermotion")):
        try:
            rep = run_model_report(league=league, season=season)
        except Exception:
            rep = None
        if rep:
            rep["label"] = label
            out[league] = rep
    return out or None


def _load_players(season: int) -> dict | None:
    """Rankings de jugadores (goleadores, asistencias...) por liga.

    Orden de preferencia:
    1) Override manual: football/data/players.json (fiable; se rellena a mano o
       con los scrapers ejecutados desde una IP no bloqueada).
    2) FBref (tablas HTML reales) — bloquea IPs de datacenter/CI con 403.
    3) as.com (rankings de temporada) — página renderizada por JS, sin tabla.
    Devuelve {liga: {label, rankings:{cat:{label, players[]}}}} o None.
    """
    path = Path(DATA_DIR) / "players.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data = {k: v for k, v in data.items() if not k.startswith("_")}
            if data:
                return data
        except Exception:
            pass

    fetchers = []
    for modname, fn in (("players_football_data", "get_top_players"),
                        ("fbref_players", "get_top_players"),
                        ("players_as", "get_top_players")):
        try:
            mod = __import__(f"futbol_pred.ingest.{modname}", fromlist=[fn])
            fetchers.append(getattr(mod, fn))
        except Exception:
            continue

    data: dict = {}
    for league, label in (("laliga", "LaLiga"), ("segunda", "LaLiga Hypermotion")):
        p = None
        for fetch in fetchers:
            try:
                p = fetch(season, league=league)
            except Exception:
                p = None
            if p:
                break
        if p:
            data[league] = {"label": label, "rankings": p}
    return data or None


def _load_quiniela_oficial() -> dict | None:
    """Combinación oficial de la quiniela (14 + Pleno al 15).

    1) Override manual: football/data/quiniela.json (fiable; se puede rellenar a
       mano o con el fetch de LAE desde una IP española).
    2) Intento a la API de LAE (suele dar 403 fuera de España / en runners CI).
    Devuelve {jornada, fecha, partidos:[{orden, local, visitante}]} o None.
    """
    path = Path(DATA_DIR) / "quiniela.json"
    if path.exists():
        try:
            q = json.loads(path.read_text(encoding="utf-8"))
            if q.get("partidos"):
                return q
        except Exception:
            pass
    # Fuentes en cascada: LAE (oficial, suele dar 403 a scripts) y luego
    # quinielafutbol.info (gratis y scrapeable, vía JSON-LD).
    for module in ("quiniela_lae", "quiniela_quinifutbol"):
        try:
            mod = __import__(f"futbol_pred.ingest.{module}", fromlist=["get_current_quiniela"])
            q = mod.get_current_quiniela()
            if q and q.partidos:
                return {
                    "jornada": q.jornada,
                    "fecha": q.fecha,
                    "partidos": [
                        {"orden": m.orden, "local": m.local, "visitante": m.visitante}
                        for m in q.partidos
                    ],
                }
        except Exception:
            continue
    return None


def _seed_fixtures(league: str, season: int) -> list:
    """Partidos jugados con los que sembrar el modelo.

    Incluye temporadas anteriores de la propia liga y de la otra división,
    para que los recién ascendidos (p. ej. de Segunda a Primera) tengan
    fuerza estimada a partir de sus datos reales y no de un prior neutro.
    """
    seeds: list = []
    seen: set = set()
    for src_league, back in SEED_PLAN.get(league, [(league, 1)]):
        try:
            prev = get_fixtures(src_league, season=season - back)
        except Exception:
            continue
        for fx in prev:
            if fx.home_goals is None:
                continue
            key = (fx.source, fx.league, fx.season, fx.api_id)
            if key in seen:
                continue
            seen.add(key)
            seeds.append(fx)
    return seeds


def _team_meta(league: str, season: int) -> dict:
    """Escudos y colores de club (gratis). {} si falla (no es crítico)."""
    try:
        return FootballDataClient().get_team_meta(league, season)
    except Exception:
        return {}


def _fit_stats(league: str, season: int):
    """Ajusta el modelo de estadísticas (córners, tarjetas...) para 1ª/2ª."""
    if league not in ("laliga", "segunda"):
        return None
    try:
        from .ingest.football_data_uk import FootballDataUKClient
        from .model.stats_markets import StatsPredictor

        rows = FootballDataUKClient().get_stats(league, season)
        return StatsPredictor().fit(rows)
    except Exception:
        return None


def _fit_trends(league: str, season: int, fixtures):
    """Modelo de tendencias por ESTILO de cada equipo (local/visitante) con
    histórico de varias temporadas. None si no aplica.

    `fixtures` ya incluye el sembrado multi-temporada (goles). Para las stats
    con split (córners, remates, faltas, tarjetas) juntamos co.uk de la temporada
    actual y las dos anteriores."""
    if league not in ("laliga", "segunda"):
        return None
    try:
        from .ingest.football_data_uk import FootballDataUKClient
        from .model.trends import TrendModel

        client = FootballDataUKClient()
        rows = []
        for back in (0, 1, 2):
            try:
                rows += client.get_stats(league, season - back)
            except Exception:
                continue
        return TrendModel().fit(fixtures, rows, _canon)
    except Exception:
        return None


def _real_stats_map(league: str, season: int) -> dict:
    """Estadísticas REALES por partido jugado (co.uk), clave (canon_local, canon_visitante)."""
    if league not in ("laliga", "segunda"):
        return {}
    try:
        from .ingest.football_data_uk import FootballDataUKClient

        rows = FootballDataUKClient().get_stats(league, season)
    except Exception:
        return {}
    out: dict = {}
    for ms in rows:
        key = (_canon(ms.home_team), _canon(ms.away_team))
        out[key] = {
            k: {"home": v[0], "away": v[1], "total": v[0] + v[1]}
            for k, v in ms.stats.items()
        }
    return out


def _h2h_map(fixtures) -> dict:
    """Enfrentamientos directos pasados, clave = par canónico (sin orden).
    Devuelve {frozenset(canon_a, canon_b): [ {date, home, away, hg, ag} ]}."""
    out: dict = {}
    for f in fixtures:
        if f.home_goals is None or f.away_goals is None:
            continue
        key = frozenset((_canon(f.home_team), _canon(f.away_team)))
        if len(key) != 2:
            continue
        ko = f.kickoff
        out.setdefault(key, []).append({
            "date": (ko.date().isoformat() if ko else ""),
            "home": f.home_team, "away": f.away_team,
            "hg": f.home_goals, "ag": f.away_goals,
        })
    for meetings in out.values():
        meetings.sort(key=lambda m: m["date"])
    return out


def _odds_map(league: str) -> dict:
    """Cuotas de próximos partidos (co.uk fixtures.csv), clave (canon_local, canon_visitante)."""
    if league not in ("laliga", "segunda"):
        return {}
    try:
        from .ingest.football_data_uk import DIV_CODE, FootballDataUKClient

        rows = FootballDataUKClient().get_odds(DIV_CODE.get(league))
    except Exception:
        return {}
    return {(_canon(r["home"]), _canon(r["away"])): r["odds"] for r in rows}


def main() -> int:
    football_data = FootballDataClient()
    api_football = ApiFootballClient()
    if football_data.offline and api_football.offline:
        print("Feed no actualizado: faltan FOOTBALL_DATA_API_KEY o API_FOOTBALL_KEY")
        return 2

    payload = build_dashboard()
    if not payload["matches"]:
        print("Feed no actualizado: las fuentes no devolvieron próximos partidos")
        return 3

    ok, report = write_feed_safely(OUTPUT, payload)
    if not ok:
        print("Feed no actualizado: guard de calidad rechazó la regresión: "
              + ", ".join(report["issues"][:8]))
        return 4
    metrics = report["metrics"]
    print(f"Feed actualizado: {metrics['matches']} partidos en {OUTPUT} "
          f"(predicciones={metrics['predictions']}, previas={metrics['previews']}, "
          f"onces={metrics['lineups']}, calidad={report['score']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
