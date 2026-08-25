"""Genera el feed JSON que consume la app privada Fútbol Edge.

El cron usa las claves ya configuradas en GitHub Secrets. Si no hay ninguna
fuente real configurada, no sobrescribe el último feed válido con datos demo.
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import DATA_DIR
from .backtest import ensemble_probabilities
from .backtest.ensemble import temperature_scale
from .backtest.residual import residual_probabilities
from .context import WeatherClient, venue_for
from .elo import EloRatings
from .feed_quality import load_feed, preserve_last_known_good, write_feed_safely
from .ingest.api_football import ApiFootballClient, Fixture
from .ingest.football_data import FootballDataClient
from .normalize import canonical_team
from .market_calibration import learn_market_calibration
from .operational import (
    annotate_prediction_context, attach_official_context, attach_state_simulations,
    build_alerts, content_audit,
)
from .performance import build_performance
from .finished_stats import attach_finished_stats
from .accuracy_detail import enrich_accuracy
from .pipeline import fit_model_from_fixtures, get_fixtures, predict_match, run_model_report
from .prediction_snapshots import apply_prediction_snapshots, latest_pre_match_snapshot

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


def _fit_elo_from_fixtures(fixtures: list[Fixture]) -> EloRatings:
    """Elo actual usando solo resultados anteriores, en orden cronológico."""

    elo = EloRatings()
    played = sorted(
        (fixture for fixture in fixtures if fixture.home_goals is not None and fixture.away_goals is not None),
        key=lambda fixture: ensure_aware(fixture.kickoff),
    )
    for fixture in played:
        elo.update(
            _canon(fixture.home_team),
            _canon(fixture.away_team),
            int(fixture.home_goals),
            int(fixture.away_goals),
        )
    return elo


def _previous_ensemble_params(previous: dict | None, league: str) -> dict:
    """Parámetros OOF del feed anterior; defaults conservadores si aún no hay muestra."""

    try:
        ensemble = previous["model"][league]["ensemble"]
        if not ensemble.get("accepted"):
            return {"dc_weight": 1.0, "temperature": 1.0, "accepted": False}
        production = ensemble["production"]
    except (KeyError, TypeError):
        return {"dc_weight": 1.0, "temperature": 1.0, "accepted": False}
    try:
        return {
            "dc_weight": max(0.05, min(0.95, float(production["dc_weight"]))),
            "temperature": max(0.65, min(1.8, float(production["temperature"]))),
            "accepted": True,
        }
    except (KeyError, TypeError, ValueError):
        return {"dc_weight": 1.0, "temperature": 1.0, "accepted": False}


def _previous_residual_params(previous: dict | None, league: str) -> dict:
    """Solo expone pesos residuales si el informe temporal aprobó el gate."""
    try:
        residual = previous["model"][league]["residual"]
        production = residual["production"]
        if not residual.get("accepted") or not production.get("converged"):
            return {"accepted": False}
        return {**production, "accepted": True}
    except (KeyError, TypeError):
        return {"accepted": False}


def fixture_payload(
    fixture: Fixture,
    model,
    generated_at: str,
    stats=None,
    team_meta: dict | None = None,
    real_stats: dict | None = None,
    odds_map: dict | None = None,
    closing_odds_map: dict | None = None,
    model_weight: float = 0.6,
    h2h: dict | None = None,
    trends=None,
    elo: EloRatings | None = None,
    ensemble_params: dict | None = None,
    residual_params: dict | None = None,
    market_temperature: float = 1.0,
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
        if closing_odds_map:
            closing = closing_odds_map.get((_canon(fixture.home_team), _canon(fixture.away_team)))
            if closing:
                payload["closing_odds"] = closing

    if model is None:
        return payload
    home_id, away_id = _canon(fixture.home_team), _canon(fixture.away_team)
    try:
        prediction = predict_match(model, home_id, away_id, kickoff=fixture.kickoff)
        matrix = model.predict_matrix(home_id, away_id)
    except (KeyError, ValueError):
        return payload

    dc_probs = prediction.one_x_two
    eh, ea = prediction.expected_goals
    pseudo_xg = None
    if stats is not None:
        try:
            pseudo_xg = stats.pseudo_xg(fixture.home_team, fixture.away_team)
        except (KeyError, TypeError, ValueError):
            pseudo_xg = None
    if pseudo_xg and pseudo_xg.get("weight", 0) > 0:
        weight = float(pseudo_xg["weight"])
        # El proxy nunca puede desplazar bruscamente al score model: primero se
        # limita a ±35% y después entra con un peso máximo del 25%.
        proxy_home = min(eh * 1.35, max(eh * 0.65, float(pseudo_xg["home"])))
        proxy_away = min(ea * 1.35, max(ea * 0.65, float(pseudo_xg["away"])))
        eh = (1.0 - weight) * eh + weight * proxy_home
        ea = (1.0 - weight) * ea + weight * proxy_away
        matrix = model.predict_matrix(home_id, away_id, lambdas=(eh, ea))
        dc_probs = matrix.one_x_two()

    params = ensemble_params or {}
    dc_weight = float(params.get("dc_weight", 0.75))
    temperature = float(params.get("temperature", 1.0))
    elo_probs = elo.match_probabilities(home_id, away_id) if elo is not None else dc_probs
    ensemble_active = bool(params.get("accepted")) and elo is not None
    ensemble_probs = (
        ensemble_probabilities(dc_probs, elo_probs, dc_weight, temperature)
        if ensemble_active else dc_probs
    )
    residual_active = bool((residual_params or {}).get("accepted")) and elo is not None
    probs = (
        residual_probabilities(dc_probs, elo_probs, residual_params or {})
        if residual_active else ensemble_probs
    )
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
        "model_probs": [round(probs["1"] * 100, 2), round(probs["X"] * 100, 2), round(probs["2"] * 100, 2)],
        "xg": [round(eh, 2), round(ea, 2)],
        "model_meta": {
            "version": "edge-2.0",
            "provider": (
                "Residual validado (Dixon-Coles + Elo)" if residual_active
                else "Dixon-Coles + Elo calibrado" if ensemble_active else "Dixon-Coles híbrido"
            ),
            "components": {
                "dixon_coles": {key: round(value, 4) for key, value in dc_probs.items()},
                "elo": {key: round(value, 4) for key, value in elo_probs.items()},
            },
            "ensemble": {
                "dc_weight": round(dc_weight, 4),
                "elo_weight": round(1.0 - dc_weight, 4),
                "temperature": round(temperature, 4),
                "accepted": ensemble_active,
            },
            "residual": {
                "accepted": residual_active,
                "gate": "log_loss+rps_vs_dc_y_elo",
            },
            "pseudo_xg": pseudo_xg,
        },
        "markets": {
            "over_2_5": round(matrix.over(2.5), 3),
            "over_1_5": round(matrix.over(1.5), 3),
            "over_3_5": round(matrix.over(3.5), 3),
            "btts": round(matrix.btts()["yes"], 3),
            "marcador": f"{top[0]}-{top[1]}",
        },
        "score_distribution": matrix.distribution_summary(),
    })
    if not finished_with_result:
        payload["engine"] = "residual" if residual_active else "ensemble" if ensemble_active else "dixon-coles"

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
            tactical = trends.matchup_profile(home_id, away_id)
            if tactical:
                payload["tactical_matchup"] = tactical
        except Exception:  # noqa: BLE001 - la tendencia nunca tumba el feed
            pass

    # Cuotas y value bets solo para partidos por jugar.
    if not finished_with_result and odds_map:
        mo = odds_map.get((_canon(fixture.home_team), _canon(fixture.away_team)))
        if mo:
            _attach_odds_value(payload, mo, probs, matrix, model_weight, market_temperature)
    return payload


def _attach_odds_value(payload: dict, market_odds: dict, one_x_two: dict, matrix,
                       model_weight: float = 0.6, market_temperature: float = 1.0) -> None:
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
        cal = temperature_scale(cal, market_temperature)
        block["1x2"] = {
            "odds": {k: round(o[k], 2) for k in ("1", "X", "2")},
            "fair": {k: round(fair_probs[k], 3) for k in ("1", "X", "2")},
        }
        payload["probs"] = [round(cal["1"] * 100), round(cal["X"] * 100), round(cal["2"] * 100)]
        payload["calibrated"] = True
        payload["market_calibration"] = {
            "model_weight": round(w, 4),
            "market_weight": round(1.0 - w, 4),
            "temperature": round(market_temperature, 4),
        }
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
        if isinstance(market_odds.get("_meta"), dict):
            block["meta"] = market_odds["_meta"]
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
    """Dos controles diarios a las 00:15 y 10:15, tolerando retraso del cron."""

    if _force_ai():
        return True
    # En Actions un push puede coincidir por casualidad con la hora. Si el
    # workflow declara el tipo de ejecución, solo el cron abre la ventana.
    import os
    refresh_run = os.environ.get("AI_REFRESH_RUN")
    if refresh_run is not None and not _env_true("AI_REFRESH_RUN"):
        return False
    local = ensure_aware(now).astimezone(MADRID)
    return local.hour in {0, 10} and 15 <= local.minute < 45


def _same_match_day(match: dict, now: datetime) -> bool:
    try:
        kickoff = ensure_aware(datetime.fromisoformat(match["kickoff"])).astimezone(MADRID)
    except (KeyError, TypeError, ValueError):
        return False
    return kickoff.date() == ensure_aware(now).astimezone(MADRID).date()


def _attach_venue_weather(matches: list[dict], now: datetime, client: WeatherClient | None = None) -> int:
    """Geolocaliza todos los partidos y refresca el tiempo solo en las dos ventanas."""

    refresh = _ai_window(now)
    weather = client or WeatherClient()
    updated = 0
    for match in matches:
        venue = venue_for(match.get("home", ""))
        if not venue:
            continue
        match["venue"] = venue["name"]
        match["venue_meta"] = venue
        if not refresh or match.get("finished") or not _same_match_day(match, now):
            continue
        try:
            kickoff = ensure_aware(datetime.fromisoformat(match["kickoff"])).astimezone(MADRID)
        except (KeyError, TypeError, ValueError):
            continue
        forecast = weather.forecast(venue, kickoff)
        if forecast:
            forecast["source_updated_at"] = ensure_aware(now).astimezone(MADRID).isoformat()
            match["weather"] = forecast
            updated += 1
    return updated


def _attach_archived_weather(
    matches: list[dict],
    now: datetime,
    client: WeatherClient | None = None,
    limit: int = 6,
) -> int:
    """Backfill incremental de tiempo pasado sin modificar predicciones.

    Solo consulta partidos terminados hace al menos 12 horas y sin caché. Se
    procesan primero los más antiguos para que un dato reciente aún no archivado
    no bloquee el relleno del resto de la temporada.
    """

    weather = client or WeatherClient()
    cutoff = ensure_aware(now) - timedelta(hours=12)
    candidates: list[tuple[datetime, dict, dict]] = []
    for match in matches:
        if not match.get("finished") or match.get("weather_actual"):
            continue
        venue = match.get("venue_meta") or venue_for(match.get("home", ""))
        if not venue:
            continue
        try:
            kickoff = ensure_aware(datetime.fromisoformat(match["kickoff"])).astimezone(MADRID)
        except (KeyError, TypeError, ValueError):
            continue
        if kickoff > cutoff:
            continue
        candidates.append((kickoff, match, venue))

    candidates.sort(key=lambda row: row[0])
    updated = 0
    for kickoff, match, venue in candidates[:max(0, limit)]:
        historical = weather.historical(venue, kickoff)
        if not historical:
            continue
        historical["source_updated_at"] = ensure_aware(now).astimezone(MADRID).isoformat()
        match["weather_actual"] = historical
        updated += 1
    return updated


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


def _content_fingerprint(match: dict, kind: str) -> str:
    """Huella de los datos que justifican regenerar contenido con IA."""

    fields = ["home", "away", "kickoff", "probs", "xg", "stats", "tendencias"]
    if kind == "lineup":
        fields.extend(["players", "status"])
    raw = {field: match.get(field) for field in fields}
    return hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _attach_previews(
    matches: list[dict],
    now: datetime,
    horizon_days: int = 2,
    limit: int = 5,
    ttl_hours: int = 8,
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
            if match.get("finished") or not match.get("probs") or not _same_match_day(match, now):
                continue
            meta = match.get("preview_meta") or {}
            age = _age_hours(now, meta.get("generated_at"))
            is_local_fallback = meta.get("provider") == "Motor estadístico local"
            fingerprint = _content_fingerprint(match, "preview")
            unchanged = meta.get("input_fingerprint") == fingerprint
            fresh = bool(match.get("preview")) and not is_local_fallback and age is not None and age < ttl_hours
            if (fresh or (unchanged and not is_local_fallback)) and not _force_ai():
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
                "input_fingerprint": _content_fingerprint(match, "preview"),
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
                "input_fingerprint": _content_fingerprint(match, "preview"),
            }


def _attach_lineups(
    matches: list[dict],
    now: datetime,
    squads: dict[str, list[dict]] | None = None,
    horizon_days: int = 2,
    limit: int = 10,
    ttl_hours: int = 8,
) -> None:
    """Actualiza onces con IA y cae a plantillas reales + motor local gratis."""

    try:
        from .ingest.ai_client import available
        from .ingest.lineups_ai import build_statistical_lineup, ensure_position_metadata, fetch_lineups
    except Exception:
        return

    # Migra onces cacheados del formato anterior. Se muestran completos desde ya,
    # pero se refrescan con posiciones reales en la siguiente pasada IA.
    for match in matches:
        if match.get("alineacion"):
            ensure_position_metadata(match["alineacion"])
            lineup = match["alineacion"]
            lineup.setdefault(
                "status",
                "estimado" if lineup.get("provider") == "Motor estadístico local" else "probable",
            )

    stale = []
    stamp = ensure_aware(now).isoformat()
    if available() and _ai_window(now):
        for match in matches:
            if match.get("finished") or not match.get("probs") or not _same_match_day(match, now):
                continue
            lineup = match.get("alineacion") or {}
            generated_at = lineup.get("generated_at") or lineup.get("ts")
            age = _age_hours(now, generated_at)
            is_local_fallback = lineup.get("provider") == "Motor estadístico local"
            fingerprint = _content_fingerprint(match, "lineup")
            unchanged = lineup.get("input_fingerprint") == fingerprint
            has_positions = (
                len(lineup.get("posiciones_local") or []) == 11
                and len(lineup.get("posiciones_visitante") or []) == 11
            )
            fresh = (
                bool(lineup) and has_positions and not lineup.get("positions_inferred")
                and not is_local_fallback and age is not None and age < ttl_hours
            )
            if (fresh or (unchanged and not is_local_fallback)) and not _force_ai():
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
                    "status": data.get("status") or "probable",
                    "input_fingerprint": _content_fingerprint(match, "lineup"),
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
                "status": data.get("status") or "estimado",
                "input_fingerprint": _content_fingerprint(match, "lineup"),
            }

def _retry_incomplete(matches: list[dict], audit: dict, now: datetime, limit: int = 5) -> int:
    """Segundo intento granular: una petición por partido, solo si falta contenido."""

    if not _ai_window(now):
        return 0
    try:
        from .ingest.ai_client import available
        from .ingest.lineups_ai import fetch_lineups
        from .ingest.preview_gemini import generate_preview
    except Exception:
        return 0
    if not available():
        return 0
    by_id = {match.get("id"): match for match in matches}
    stamp = ensure_aware(now).isoformat()
    retried = 0
    for issue in (audit.get("incomplete") or [])[:limit]:
        match = by_id.get(issue.get("id"))
        if not match:
            continue
        missing = set(issue.get("missing") or [])
        _mark_attempt(match, "selective_retry", now)
        if "previa" in missing:
            try:
                preview = generate_preview(match)
            except Exception:
                preview = None
            if preview:
                match["preview"] = preview.text
                match["preview_meta"] = {
                    "provider": preview.provider, "model": preview.model,
                    "generated_at": stamp, "quality": preview.quality,
                }
        if missing.intersection({"once", "posiciones", "props"}):
            key = f"{match['home']} vs {match['away']}"
            try:
                data = fetch_lineups([{"partido": key}]).get(key)
            except Exception:
                data = None
            if data:
                match["alineacion"] = {
                    **data, "generated_at": stamp, "ts": stamp,
                    "fuente": data.get("provider"), "status": data.get("status") or "probable",
                    "input_fingerprint": _content_fingerprint(match, "lineup"),
                    "selective_retry": True,
                }
        retried += 1
    return retried


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


def _merge_lineup_players(players: dict | None, matches: list[dict]) -> dict:
    """Garantiza que todo jugador mostrado en un once exista en el índice global."""

    out = players or {}
    league_keys = {
        "LaLiga": "laliga", "LaLiga Hypermotion": "segunda",
        "Champions League": "champions",
    }
    labels = {"laliga": "LaLiga", "segunda": "LaLiga Hypermotion", "champions": "Champions League"}
    for match in matches:
        lineup = match.get("alineacion") or {}
        if not lineup:
            continue
        league = league_keys.get(match.get("league"), "segunda")
        bucket = out.setdefault(league, {"label": labels.get(league, league), "rankings": {}, "players": []})
        flat = bucket.setdefault("players", [])
        existing = {(str(row.get("team")).casefold(), str(row.get("player")).casefold()) for row in flat}
        for side, team, positions, props in (
            (lineup.get("local") or [], match.get("home"), lineup.get("posiciones_local") or [], lineup.get("clave_local") or []),
            (lineup.get("visitante") or [], match.get("away"), lineup.get("posiciones_visitante") or [], lineup.get("clave_visitante") or []),
        ):
            prop_by_name = {str(row.get("jugador")).casefold(): row for row in props if isinstance(row, dict)}
            for index, name in enumerate(side):
                key = (str(team).casefold(), str(name).casefold())
                if not team or not name or key in existing:
                    continue
                prop = prop_by_name.get(str(name).casefold()) or {}
                flat.append({
                    "player": name, "team": team,
                    "position": positions[index] if index < len(positions) else "",
                    "goals": prop.get("g", 0), "assists": prop.get("a", 0),
                    "shots": prop.get("r", 0), "yc": prop.get("t", 0),
                    "min": prop.get("min", 0),
                    "source": lineup.get("provider") or "once cacheado",
                    "lineup_status": lineup.get("status") or "estimado",
                })
                existing.add(key)
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
    from .ingest.ai_client import configure_daily_budget, diagnostics, usage_snapshot

    configure_daily_budget((previous or {}).get("ai_usage"), now.astimezone(MADRID))
    model_report = _load_model_report(season)
    calibration_source = {"model": model_report} if model_report else previous
    market_calibration = {}
    for league, label in (("laliga", "LaLiga"), ("segunda", "LaLiga Hypermotion")):
        learned = learn_market_calibration((previous or {}).get("matches") or [], label)
        if learned:
            market_calibration[league] = learned
    matches: list[dict] = []
    errors: list[dict] = []
    squads_by_league: dict[str, dict[str, list[dict]]] = {}
    stats_models_by_league: dict[str, object] = {}

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
            elo = _fit_elo_from_fixtures(train)
            ensemble_params = _previous_ensemble_params(calibration_source, league)
            residual_params = _previous_residual_params(calibration_source, league)
            stats = _fit_stats(league, season)
            if stats is not None:
                stats_models_by_league[LEAGUES.get(league, league)] = stats
            meta = _team_meta(league, season)
            squads_by_league[league] = {
                team: info.get("squad") or []
                for team, info in meta.items()
                if len(info.get("squad") or []) >= 11
            }
            real_stats = _real_stats_map(league, season)
            trends = _fit_trends(league, season, train)
            odds_map = _odds_map(league)
            closing_odds_map = _closing_odds_map(league, season)
            # Peso del modelo vs mercado para calibrar: con pocas jornadas jugadas
            # el modelo va sobreconfiado, así que pesa más el mercado; según avanza
            # la liga, el modelo gana peso. mpt = media de partidos por equipo.
            played_n = sum(1 for f in fixtures if f.home_goals is not None)
            teams_n = len({f.home_team for f in fixtures} | {f.away_team for f in fixtures})
            mpt = (2 * played_n / teams_n) if teams_n else 0
            model_w = max(0.2, min(0.9, mpt / 12))
            market_temperature = 1.0
            learned_market = market_calibration.get(league)
            if learned_market and learned_market.get("accepted"):
                production = learned_market["production"]
                model_w = float(production["model_weight"])
                market_temperature = float(production["temperature"])
            h2h = _h2h_map(train)  # incluye temporadas previas (sembrado)
            # TODOS los partidos de la temporada (resultados + próximos).
            matches.extend(
                fixture_payload(fx, model, generated_at, stats=stats, team_meta=meta,
                                real_stats=real_stats, odds_map=odds_map,
                                closing_odds_map=closing_odds_map,
                                model_weight=model_w, h2h=h2h, trends=trends,
                                elo=elo, ensemble_params=ensemble_params,
                                residual_params=residual_params,
                                market_temperature=market_temperature)
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
    weather_updates = _attach_venue_weather(matches, now)
    apply_prediction_snapshots(
        matches,
        (previous or {}).get("matches"),
        now,
        force=_force_ai(),
        capture=False,
    )
    # Recupera predicciones/IA/odds anteriores antes de intentar refrescarlas.
    # De esta forma un timeout, una cuota agotada o una respuesta parcial jamás
    # convierte una tarjeta que funcionaba en un hueco en blanco.
    if previous:
        preserve_last_known_good(
            {"schema_version": 7, "matches": matches},
            {"schema_version": previous.get("schema_version"), "matches": previous.get("matches", [])},
        )
    archived_weather_updates = _attach_archived_weather(matches, now)
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
    official_updates = attach_official_context(matches, now, stats_models=stats_models_by_league)
    finished_stats_updates = attach_finished_stats(
        matches, now, previous_matches=(previous or {}).get("matches")
    )
    state_simulations = attach_state_simulations(matches)
    players = _merge_lineup_players(players, matches)
    annotate_prediction_context(matches)
    # Segunda fase: la revisión se captura cuando contexto, once e impacto ya
    # están completos. Después se vuelve a anotar para mantener vivo el estado
    # oficial aunque fuera de las ventanas que congelan la probabilidad.
    apply_prediction_snapshots(
        matches,
        (previous or {}).get("matches"),
        now,
        force=_force_ai(),
    )
    annotate_prediction_context(matches)
    first_audit = content_audit(matches, players, now)
    retried = _retry_incomplete(matches, first_audit, now)
    players = _merge_lineup_players(players, matches)
    audit = content_audit(matches, players, now)
    audit["selective_retries"] = retried
    audit["official_lineup_updates"] = official_updates
    audit["weather_updates"] = weather_updates
    audit["archived_weather_updates"] = archived_weather_updates
    audit["state_simulations"] = state_simulations
    ai_events = diagnostics()
    payload = {
        "schema_version": 7,
        "generated_at": generated_at,
        "season": season,
        "quiniela": _load_quiniela_oficial(),
        "players": players,
        "model": model_report,
        "market_calibration": market_calibration or None,
        "accuracy": enrich_accuracy(_aggregate_accuracy(matches), matches),
        "performance": build_performance(matches),
        "content_audit": audit,
        "postmatch_stats_updates": finished_stats_updates,
        "ai_usage": usage_snapshot(),
        "ai_health": {"events": ai_events[-30:]},
        "alerts": build_alerts(previous, audit, ai_events, now),
        "engine": (
            "residual" if any(item["engine"] == "residual" for item in matches)
            else "ensemble" if any(item["engine"] == "ensemble" for item in matches)
            else "dixon-coles" if any(item["engine"] == "dixon-coles" for item in matches)
            else "calendar-only"
        ),
        "data_sources": {
            "fixtures": "football-data.org (LaLiga) · football-data.co.uk (Segunda)",
            "stats": "football-data.co.uk (3 temporadas; pseudo-xG, remates, córners, faltas y tarjetas)",
            "players": "football-data.org (plantillas, goleadores y asistencias)",
            "odds": "football-data.co.uk (media de mercado: 1X2 y over/under 2.5)",
            "lineups": "API-Football para onces oficiales y bajas cerca del partido; football-data.org para plantillas",
            "ai": "Gemini dinámico → Groq → motor estadístico local gratuito; control del día a las 00:15 y 10:15 Europe/Madrid, con presupuesto y caché",
            "weather": "Open-Meteo (CC BY 4.0): previsión horaria + Historical Forecast archivado por estadio; el histórico es solo para validación hasta superar gate",
            "tactics": "football-data.co.uk, perfiles observados casa/fuera de remates, córners, faltas, tarjetas y goles",
        },
        "disclaimer": "Probabilidades y ventaja estadística, no certezas. "
                      "Las plantillas gratuitas y los onces del motor local son provisionales; "
                      "las cuotas se muestran como pendientes cuando no existe una fuente real.",
        "counts": {
            "total": len(matches),
            "jugados": sum(1 for m in matches if m.get("finished")),
            "proximos": sum(1 for m in matches if not m.get("finished")),
            "con_prediccion": sum(1 for m in matches if m.get("engine") in {"dixon-coles", "ensemble", "residual"}),
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
    labels = {"goals": "Goles", "shots": "Remates", "sot": "Tiros a puerta",
              "corners": "Córners", "fouls": "Faltas", "yellows": "Amarillas",
              "reds": "Rojas"}
    hits = n_sign = evaluated = 0
    per: dict = {}
    for m in matches:
        res = m.get("result")
        if not m.get("finished") or not res:
            continue
        snapshot = latest_pre_match_snapshot(m)
        if not snapshot:
            # Nunca puntuamos una predicción recalculada después del resultado.
            continue
        evaluated += 1
        # Acierto 1X2: favorito del modelo vs signo real.
        probs = snapshot.get("probs")
        if probs and len(probs) == 3:
            fav = ["1", "X", "2"][max(range(3), key=lambda i: probs[i])]
            real = _sign(res[0], res[1])
            n_sign += 1
            hits += int(fav == real)
        # Error por métrica: esperado (stats) vs real (statsReal).
        pred, real_stats = snapshot.get("stats"), m.get("statsReal")
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
        "n_partidos": evaluated,
        "aciertos_1x2": hits,
        "n_1x2": n_sign,
        "pct_1x2": round(100 * hits / n_sign) if n_sign else None,
        "metrics": metrics,
        "source": "pre_match_snapshots",
        "excluded_without_snapshot": max(
            0,
            sum(1 for m in matches if m.get("finished") and m.get("result")) - evaluated,
        ),
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
        # En agosto la temporada actual aún no tiene muestra suficiente. Se usa
        # la última temporada cerrada para aprender pesos y validar al challenger.
        if not rep or not (rep.get("ensemble") or {}).get("production"):
            try:
                historic = run_model_report(league=league, season=season - 1)
            except Exception:
                historic = None
            if historic:
                historic["evaluation_season"] = season - 1
                historic["current_season"] = season
                rep = historic
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
    """Ajusta props con liga objetivo + memoria de equipos que cambiaron de división.

    La otra división nunca entra en medias, dispersión, pseudo-xG ni gate
    temporal: solo aporta acumuladores por equipo al StatsPredictor.
    """
    if league not in ("laliga", "segunda"):
        return None
    try:
        from .ingest.football_data_uk import FootballDataUKClient
        from .model.stats_markets import StatsPredictor

        client = FootballDataUKClient()
        rows = []
        for back in (2, 1, 0):
            try:
                rows.extend(client.get_stats(league, season - back))
            except Exception:
                continue

        other = "segunda" if league == "laliga" else "laliga"
        auxiliary = []
        for back in (2, 1):
            try:
                auxiliary.extend(client.get_stats(other, season - back))
            except Exception:
                continue
        predictor = StatsPredictor().fit(rows, auxiliary_matches=auxiliary)
        try:
            from .model.referee_adjustment import RefereeAdjustmentModel

            predictor.referee_model = RefereeAdjustmentModel().fit(rows)
        except Exception:
            predictor.referee_model = None
        return predictor
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
        if ms.referee:
            out[key]["meta"] = {"referee": ms.referee, "source": "football-data.co.uk"}
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


def _closing_odds_map(league: str, season: int) -> dict:
    """Cierre histórico real de partidos jugados, separado de las cuotas live."""
    if league not in ("laliga", "segunda"):
        return {}
    try:
        from .ingest.football_data_uk import FootballDataUKClient

        rows = FootballDataUKClient().get_historical_closing_odds(league, season)
    except Exception:
        return {}
    return {
        (_canon(row["home"]), _canon(row["away"])): row["closing_odds"]
        for row in rows
    }


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
