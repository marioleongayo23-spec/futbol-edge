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
from .ingest.rfef_referees import RefereeDirectory, load_directory as _load_rfef_designations
from .normalize import canonical_team
from .market_calibration import learn_market_calibration
from .model.market_lines import committed_scoreline, count_market, goals_market
from .operational import (
    annotate_prediction_context, attach_official_context, attach_state_simulations,
    build_alerts, content_audit,
)
from .performance import build_performance
from .picks import build_picks
from .finished_stats import attach_finished_stats
from .accuracy_detail import enrich_accuracy
from .real_market import attach_closing_snapshots, attach_extended_market_value
from .weather_effects import apply_weather_adjustments
from .historical_seed import build_historical_seeds
from .pipeline import fit_model_from_fixtures, get_fixtures, predict_match, run_model_report
from .prediction_snapshots import apply_prediction_snapshots, latest_pre_match_snapshot
from .prefinal_lineups import refresh_prefinal_lineups

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


_RFEF_DIRECTORY: RefereeDirectory | None = None


def _rfef_directory() -> RefereeDirectory:
    """Designaciones RFEF cacheadas una vez por proceso (lectura de fichero,
    sin red). Ausente/ilegible -> directorio vacío (feed idéntico)."""
    global _RFEF_DIRECTORY
    if _RFEF_DIRECTORY is None:
        _RFEF_DIRECTORY = _load_rfef_designations()
    return _RFEF_DIRECTORY


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
    stats_method: dict | None = None,
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
                applied: dict = {}
                hmap = (stats_method or {}).get(home_id, {})
                amap = (stats_method or {}).get(away_id, {})
                for k, v in sp.items():
                    if k == "goals":
                        h, a = round(eh, 2), round(ea, 2)
                    elif k in ("shots", "sot", "corners"):
                        t = v["total"]
                        h, a = round(t * hshare, 1), round(t * (1 - hshare), 1)
                    else:  # faltas, amarillas, rojas: sin sesgo por dominio
                        h, a = v["home"], v["away"]
                        # Método por-equipo validado en el banco 80/20 (con guardia):
                        # si "equipo" gana de forma robusta, se usa la tasa propia.
                        if hmap.get(k) == "equipo":
                            own = stats.home.get(home_id, {}).get(k)
                            if own is not None and own.for_avg is not None:
                                h = round(own.for_avg, 2); applied.setdefault(k, {})["home"] = "equipo"
                        if amap.get(k) == "equipo":
                            own = stats.away.get(away_id, {}).get(k)
                            if own is not None and own.for_avg is not None:
                                a = round(own.for_avg, 2); applied.setdefault(k, {})["away"] = "equipo"
                    out_stats[k] = {"home": h, "away": a, "total": round(h + a, 2)}
                payload["stats"] = out_stats
                if applied:
                    payload["stats_method"] = applied
        except (KeyError, ValueError):
            pass

    # Árbitro designado: si se conoce el árbitro del partido, su perfil histórico
    # ajusta faltas/tarjetas ANTES de construir los mercados y se expone como
    # official_context. Reutiliza el modelo validado del Bloque 2. Fuentes, por
    # orden: lo que traiga la API (football-data.org) y, si no, las designaciones
    # de la RFEF (publicadas ~1 día antes; único origen pre-partido gratis).
    # (Latente si ninguna fuente trae árbitro; API-Football lo sobrescribe más
    # tarde en attach_official_context cuando existe.)
    if not finished_with_result and not getattr(fixture, "referee", None):
        designated = _rfef_directory().lookup(fixture.home_team, fixture.away_team)
        if designated:
            fixture.referee = designated
            fixture.referee_source = "RFEF"
    if not finished_with_result and getattr(fixture, "referee", None) and stats is not None:
        ref_model = getattr(stats, "referee_model", None)
        if ref_model is not None:
            try:
                _ref_src = getattr(fixture, "referee_source", None) or "football-data.org"
                oc = {"referee": fixture.referee, "source": _ref_src,
                      "provider": _ref_src,
                      "source_updated_at": generated_at}
                profile = ref_model.context(fixture.referee)
                if profile:
                    oc["referee_profile"] = profile
                if payload.get("stats"):
                    adjusted, applied = ref_model.adjust_stats(payload["stats"], fixture.referee)
                    if applied:
                        payload["stats"] = adjusted
                        oc["referee_adjustment_applied"] = applied
                payload["official_context"] = oc
            except Exception:  # noqa: BLE001 - el árbitro nunca tumba el feed
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

    # Mercados "que se mojan": cada estadística como P(por encima)/P(por debajo)/
    # exacto, con su tendencia; y UN marcador al que nos mojamos. Reexpresa lo que
    # ya predice el modelo (matriz de goles + medias esperadas), sin inventar.
    try:
        tend = payload.get("tendencias") or {}
        trend_for = {
            "goals": tend.get("goals"),
            "corners": tend.get("corners"),
            "yellows": tend.get("yellows"),
            "shots": tend.get("shots"),
            "sot": tend.get("shots"),  # tiros a puerta comparten señal con remates
            "fouls": tend.get("fouls"),
        }
        detail = [goals_market(matrix, eh, ea, trend_for["goals"])]
        st = payload.get("stats") or {}
        for stat in ("corners", "yellows", "shots", "sot", "fouls"):
            row = st.get(stat)
            if not row:
                continue
            detail.append(count_market(
                stat, row["total"], stats.dispersion(stat) if stats is not None else 1.0,
                mean_home=row["home"], mean_away=row["away"], trend=trend_for.get(stat),
            ))
        applied_ref = set((payload.get("official_context") or {}).get("referee_adjustment_applied") or [])
        for mk in detail:
            if mk.get("stat") in applied_ref:
                mk["referee_moved"] = True
        payload["markets_detail"] = detail
        if not finished_with_result:
            payload["committed"] = committed_scoreline(
                matrix, probs, fixture.home_team, fixture.away_team)
    except Exception:  # noqa: BLE001 - los mercados nunca tumban el feed
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
    """Dos refrescos de IA al día: madrugada (~00 h) y media mañana (~10 h).

    El cron dispara a los minutos :13 y :43, pero GitHub Actions arrastra
    retrasos que van de unos minutos a más de una hora, sobre todo en horas
    punta. La ventana anterior (``minuto 15-44``) era tan estrecha que casi
    ningún cron caía dentro —los :13 quedaban SIEMPRE fuera y un :43 con dos
    minutos de retraso también—, así que la IA se congelaba en el último feed
    bueno. Ahora la ventana abarca la hora objetivo y la siguiente (00-01 y
    10-11 h) para que cualquier cron retrasado siga entrando.

    Esto NO multiplica el gasto: el límite real no es la ventana sino el
    enfriamiento por partido (``_can_attempt``, 6 h) y el presupuesto diario
    (``AI_DAILY_CALL_BUDGET``). Con la ventana abierta durante varias horas, el
    primer cron elegible genera y los siguientes se saltan por enfriamiento, de
    modo que siguen saliendo ~2 sesiones de IA al día.
    """

    if _force_ai():
        return True
    # En Actions un push puede coincidir por casualidad con la hora. Si el
    # workflow declara el tipo de ejecución, solo el cron abre la ventana.
    import os
    refresh_run = os.environ.get("AI_REFRESH_RUN")
    if refresh_run is not None and not _env_true("AI_REFRESH_RUN"):
        return False
    local = ensure_aware(now).astimezone(MADRID)
    return local.hour in {0, 1, 10, 11}


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


# Modelos de once que produjeron versiones antiguas del pipeline y que ya no
# son fiables (plantillas de temporadas pasadas). Se reconstruyen desde cero.
_LEGACY_LINEUP_MODELS = {"squad-stats-v1"}


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

    # Invalida onces de modelos legacy que el código actual ya no genera (p. ej.
    # "squad-stats-v1", construido con estadísticas de temporadas anteriores y que
    # arrastraba jugadores que ya no están en el club). Se descartan para que se
    # reconstruyan más abajo desde la PLANTILLA ACTUAL. Nunca se descarta un once
    # oficial confirmado: es histórico valioso para el "último XI oficial".
    for match in matches:
        lineup = match.get("alineacion")
        if lineup and lineup.get("model") in _LEGACY_LINEUP_MODELS and lineup.get("status") != "confirmado":
            match["alineacion"] = None

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


def _player_key(name) -> str:
    """Clave de jugador insensible a acentos y espacios ('David' == 'Dávid')."""

    import unicodedata

    stripped = unicodedata.normalize("NFKD", str(name or ""))
    stripped = "".join(ch for ch in stripped if not unicodedata.combining(ch))
    return " ".join(stripped.casefold().split())


def _merge_player_rows(base: dict, other: dict) -> dict:
    """Funde dos filas del mismo jugador: una de plantilla actual, otra de stats.

    La plantilla (``current_squad_member``) aporta posición, dorsal y foto; las
    stats aportan el rendimiento (goles, asistencias, minutos), que la plantilla
    trae a cero. Así un jugador que aparecía bajo el nombre corto y el largo del
    club queda como una sola fila enriquecida.
    """

    squad, stats = (base, other) if base.get("current_squad_member") else (other, base)
    merged = dict(stats)
    for key, value in squad.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    for field in ("goals", "assists", "shots", "yc", "min"):
        stat_value = stats.get(field)
        if isinstance(stat_value, (int, float)) and stat_value:
            merged[field] = stat_value
    return merged


def _dedupe_players_by_team(players: dict | None, matches: list[dict]) -> dict | None:
    """Funde equipos duplicados por alias en una sola entrada por club.

    El bloque de jugadores mezclaba dos fuentes con nombres distintos para el mismo
    club: las estadísticas (nombre corto, p. ej. ``Atletico Madrid``) y la plantilla
    actual de football-data (nombre largo, ``Club Atlético de Madrid``). Al cotejar
    por el nombre EXACTO quedaban 34 «equipos» en LaLiga en vez de 20, con rosters
    fantasma. Ahora se agrupa por equipo canónico + jugador (sin acentos), se
    conserva el nombre que usa el calendario y cada jugador se enriquece en lugar de
    duplicarse. No se pierden datos: es solo fusión.
    """

    if not players:
        return players
    display_by_canon: dict[str, str] = {}
    for match in matches or []:
        for team in (match.get("home"), match.get("away")):
            team = str(team or "").strip()
            if team:
                display_by_canon.setdefault(_canon(team), team)
    for bucket in players.values():
        if not isinstance(bucket, dict):
            continue
        by_key: dict[tuple[str, str], dict] = {}
        order: list[tuple[str, str]] = []
        for row in bucket.get("players") or []:
            if not isinstance(row, dict):
                continue
            team = str(row.get("team") or "").strip()
            canon = _canon(team) if team else ""
            key = (canon, _player_key(row.get("player")))
            new_row = dict(row)
            new_row["team"] = display_by_canon.get(canon) or team
            if key in by_key:
                by_key[key] = _merge_player_rows(by_key[key], new_row)
            else:
                by_key[key] = new_row
                order.append(key)
        bucket["players"] = [by_key[key] for key in order]
    return players


def _merge_lineup_players(players: dict | None, matches: list[dict]) -> dict:
    """Indexa y enriquece jugadores mostrados en onces con evidencia real de API-Football.

    Nunca sustituye acumulados de Understat por expectativas de un único partido.
    Los datos de temporada, perfil y rol se añaden en campos separados para UI y
    futuros challengers. Si un jugador ya existe, se enriquece en lugar de saltarlo.
    """

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
        positions_by_key = {
            (str(row.get("team")).casefold(), str(row.get("player")).casefold()): i
            for i, row in enumerate(flat)
        }
        for side, team, positions, props in (
            (lineup.get("local") or [], match.get("home"), lineup.get("posiciones_local") or [], lineup.get("clave_local") or []),
            (lineup.get("visitante") or [], match.get("away"), lineup.get("posiciones_visitante") or [], lineup.get("clave_visitante") or []),
        ):
            prop_by_name = {str(row.get("jugador")).casefold(): row for row in props if isinstance(row, dict)}
            for index, name in enumerate(side):
                if not team or not name:
                    continue
                key = (str(team).casefold(), str(name).casefold())
                prop = prop_by_name.get(str(name).casefold()) or {}
                expected = {
                    k: prop.get(k) for k in ("g", "a", "r", "rp", "fc", "fr", "t")
                    if prop.get(k) is not None
                }
                if prop.get("extended"):
                    expected["extended"] = prop.get("extended")
                rich = {
                    "player_id": prop.get("player_id"),
                    "profile": prop.get("profile") or None,
                    "api_position": prop.get("position"),
                    "rating": prop.get("rating"),
                    "pass_accuracy_pct": prop.get("pass_accuracy_pct"),
                    "expected_minutes": prop.get("min"),
                    "starter_probability": prop.get("tit"),
                    "sample_minutes": prop.get("sample_minutes"),
                    "season": prop.get("season") or None,
                    "expected_match": expected or None,
                    "rich_source": prop.get("source"),
                    "lineup_status": lineup.get("status") or "estimado",
                }
                if key in positions_by_key:
                    row = flat[positions_by_key[key]]
                    if not row.get("position"):
                        row["position"] = (positions[index] if index < len(positions) else None) or prop.get("position") or ""
                    for field, value in rich.items():
                        if value not in (None, {}, []):
                            row[field] = value
                    continue

                season = prop.get("season") or {}
                row = {
                    "player": name, "team": team,
                    "position": (positions[index] if index < len(positions) else None) or prop.get("position") or "",
                    "goals": 0, "assists": 0, "shots": 0, "yc": 0,
                    "min": season.get("minutes") or prop.get("sample_minutes") or 0,
                    "source": lineup.get("provider") or "once cacheado",
                }
                for field, value in rich.items():
                    if value not in (None, {}, []):
                        row[field] = value
                positions_by_key[key] = len(flat)
                flat.append(row)
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
    stats_backtest = _load_stats_backtest(season)
    stats_method_by_league = _build_stats_method(stats_backtest)
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
    matches: list[dict] = []
    errors: list[dict] = []
    squads_by_league: dict[str, dict[str, list[dict]]] = {}
    stats_models_by_league: dict[str, object] = {}
    # Bundle por liga con TODO lo que necesita fixture_payload, para poder
    # predecir después partidos que no vienen en el calendario del feed (p. ej.
    # los de Segunda de la quiniela, que co.uk solo publica como resultados).
    league_bundles: dict[str, dict] = {}

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
            if model is not None:
                league_bundles[league] = {
                    "model": model, "elo": elo, "stats": stats, "team_meta": meta,
                    "real_stats": real_stats, "odds_map": odds_map,
                    "closing_odds_map": closing_odds_map, "model_weight": model_w,
                    "h2h": h2h, "trends": trends, "ensemble_params": ensemble_params,
                    "residual_params": residual_params,
                    "market_temperature": market_temperature,
                }
            # TODOS los partidos de la temporada (resultados + próximos).
            matches.extend(
                fixture_payload(fx, model, generated_at, stats=stats, team_meta=meta,
                                real_stats=real_stats, odds_map=odds_map,
                                closing_odds_map=closing_odds_map,
                                model_weight=model_w, h2h=h2h, trends=trends,
                                elo=elo, ensemble_params=ensemble_params,
                                residual_params=residual_params,
                                market_temperature=market_temperature,
                                stats_method=stats_method_by_league.get(LEAGUES.get(league, league)))
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
    weather_updates = _attach_venue_weather(matches, now)
    weather_adjustments = apply_weather_adjustments(matches, now)
    closing_snapshot_updates = attach_closing_snapshots(
        matches, now, previous_matches=(previous or {}).get("matches")
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
    prefinal_updates = refresh_prefinal_lineups(matches, now)
    official_updates = attach_official_context(matches, now, stats_models=stats_models_by_league)
    finished_stats_updates = attach_finished_stats(
        matches, now, previous_matches=(previous or {}).get("matches")
    )
    state_simulations = attach_state_simulations(matches)
    from .matchday_player_props_fill import attach_player_markets
    player_markets_count = attach_player_markets(matches, now)
    players = _merge_lineup_players(players, matches)
    annotate_prediction_context(matches)
    market_value = attach_extended_market_value(
        matches, now, previous_matches=(previous or {}).get("matches"),
        stats_models=stats_models_by_league,
    )
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
    players = _dedupe_players_by_team(players, matches)
    audit = content_audit(matches, players, now)
    audit["selective_retries"] = retried
    audit["prefinal_lineup_updates"] = prefinal_updates
    audit["official_lineup_updates"] = official_updates
    audit["weather_updates"] = weather_updates
    audit["weather_adjustments"] = weather_adjustments
    audit["closing_snapshot_updates"] = closing_snapshot_updates
    audit["extended_market_updates"] = market_value.get("refreshed", 0)
    audit["archived_weather_updates"] = archived_weather_updates
    audit["state_simulations"] = state_simulations
    ai_events = diagnostics()
    payload = {
        "schema_version": 7,
        "generated_at": generated_at,
        "season": season,
        "quiniela": _resolve_quiniela(
            _load_quiniela_oficial(), matches, league_bundles, generated_at, now
        ),
        "players": players,
        "model": model_report,
        "stats_backtest": stats_backtest,
        "market_calibration": market_calibration or None,
        "historical_seed": historical_seeds or None,
        "value_ranking": market_value.get("ranking") or [],
        "picks": build_picks(matches, now),
        "market_value_source": market_value.get("source"),
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
            "players": "API-Football /players para tasas individuales reales por-90; football-data.org para plantillas; IA solo once y bajas",
            "odds": "The Odds API cuando hay ODDS_API_KEY (consenso + submercados); football-data.co.uk como fallback real 1X2/O-U2.5/AH cuando publica columnas",
            "lineups": "PRE-FINAL T-3h con once probable refrescado y señales de medios; FINAL oficial API-Football en T-60 y fallback T-30; football-data.org para plantillas",
            "ai": "Gemini dinámico → Groq → motor estadístico local; revisiones 00:15/10:15 más PRE-FINAL T-3h bajo presupuesto y caché",
            "weather": "Open-Meteo (CC BY 4.0): forecast horario cuantifica xG/remates/disciplina; histórico separado para validación",
            "tactics": "football-data.co.uk, perfiles observados casa/fuera de remates, córners, faltas, tarjetas y goles",
        },
        "disclaimer": "Probabilidades y ventaja estadística, no certezas. "
                      "Las plantillas gratuitas y los onces del motor local son provisionales; los props numéricos solo se muestran con muestra real; "
                      "las cuotas se muestran como pendientes cuando no existe una fuente real.",
        "counts": {
            "total": len(matches),
            "jugados": sum(1 for m in matches if m.get("finished")),
            "proximos": sum(1 for m in matches if not m.get("finished")),
            "con_prediccion": sum(1 for m in matches if m.get("engine") in {"dixon-coles", "ensemble", "residual"}),
            "con_cuotas": sum(1 for m in matches if isinstance(m.get("odds"), dict)),
            "con_arbitro": sum(1 for m in matches if (m.get("official_context") or {}).get("referee")),
            "con_arbitro_rfef": sum(1 for m in matches if (m.get("official_context") or {}).get("provider") == "RFEF"),
            "con_player_markets": sum(1 for m in matches if m.get("player_markets")),
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
    rel_samples: list[tuple[float, int]] = []  # (prob del favorito, acierto)
    mkt: dict = {}  # mercado -> {n, hits, brier}
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
            fav_i = max(range(3), key=lambda i: probs[i])
            fav = ["1", "X", "2"][fav_i]
            real = _sign(res[0], res[1])
            n_sign += 1
            hit = int(fav == real)
            hits += hit
            try:
                rel_samples.append((float(probs[fav_i]), hit))
            except (TypeError, ValueError):
                pass
        # Acierto y calibración (Brier) de los mercados binarios que sí se
        # resuelven solo con el resultado: Over 2.5 y Ambos Marcan.
        snap_mk = snapshot.get("markets") or {}
        total_goles = res[0] + res[1]
        for key, actual in (("over_2_5", int(total_goles > 2.5)),
                            ("btts", int(res[0] > 0 and res[1] > 0))):
            p = snap_mk.get(key)
            if not isinstance(p, (int, float)):
                continue
            p = float(p)
            d = mkt.setdefault(key, {"n": 0, "hits": 0, "brier": 0.0})
            d["n"] += 1
            d["hits"] += int((p >= 0.5) == bool(actual))
            d["brier"] += (p - actual) ** 2
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
        "reliability": _reliability(rel_samples),
        "market_accuracy": [
            {"key": k, "label": {"over_2_5": "Over 2.5 goles", "btts": "Ambos marcan"}.get(k, k),
             "n": d["n"], "hits": d["hits"],
             "hit_rate": round(100 * d["hits"] / d["n"]),
             "brier": round(d["brier"] / d["n"], 3)}
            for k, d in mkt.items() if d["n"]
        ] or None,
        "source": "pre_match_snapshots",
        "excluded_without_snapshot": max(
            0,
            sum(1 for m in matches if m.get("finished") and m.get("result")) - evaluated,
        ),
    }


def _reliability(samples: list[tuple[float, int]]) -> dict | None:
    """¿Está calibrado el modelo? Agrupa por confianza del favorito y compara la
    probabilidad media que dio con el acierto real observado. Bien calibrado =
    ambas cifras se parecen (si dice 60%, acierta ~60%). Bandas anchas para tener
    muestra en cada una; se afina según avanza la temporada."""
    samples = [(p, h) for p, h in samples if p is not None]
    if len(samples) < 6:
        return None
    edges = ((0, 52, "Ajustado (<52%)"), (52, 65, "Claro (52-65%)"), (65, 101, "Muy claro (≥65%)"))
    bands = []
    for lo, hi, label in edges:
        pts = [(p, h) for p, h in samples if lo <= p < hi]
        if not pts:
            continue
        n = len(pts)
        bands.append({
            "label": label,
            "n": n,
            "hits": sum(h for _, h in pts),
            "hit_rate": round(100 * sum(h for _, h in pts) / n),
            "avg_pred": round(sum(p for p, _ in pts) / n),
        })
    if not bands:
        return None
    return {"bands": bands, "n": len(samples)}


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


def _load_stats_backtest(season: int) -> dict | None:
    """Validación 80/20 (hold-out) por liga desde la temporada 2024/25.

    Entrena con el 80% de los partidos más antiguos (co.uk: cada acción de juego)
    y predice el 20% más reciente, comparando con la realidad el 1X2 y cada
    estadística. Corte cronológico (el modelo es temporal) y contraste contra la
    media de liga, para medir con verdad de campo cuánta señal aporta el modelo.
    """
    try:
        from .backtest.holdout import holdout_report
        from .ingest.football_data_uk import FootballDataUKClient
    except Exception:
        return None
    client = FootballDataUKClient()
    out: dict = {}
    for league, label in (("laliga", "LaLiga"), ("segunda", "LaLiga Hypermotion")):
        rows: list = []
        for year in range(2024, season + 1):  # desde 24/25 hasta la temporada actual
            try:
                rows += client.get_stats(league, year)
            except Exception:
                continue
        try:
            rep = holdout_report(rows)
        except Exception:
            rep = None
        if rep:
            rep["label"] = label
            out[label] = rep
    return out or None


# Estadísticas cuyo método por-equipo SÍ se aplica en producción: las de
# disciplina, que el pipeline predice por lado directamente (faltas/tarjetas).
# Goles/remates/córners siguen alineados al xG (dominio), no se tocan.
_ADOPT_STATS = {"fouls", "yellows", "reds"}


def _build_stats_method(stats_backtest: dict | None) -> dict:
    """Mapa {liga: {equipo_canónico: {estadística: método}}} con los cambios de
    método por equipo que la guardia del banco 80/20 aprobó (solo disciplina)."""
    out: dict = {}
    for league_label, rep in (stats_backtest or {}).items():
        tmap: dict = {}
        for team, info in (rep.get("by_team") or {}).items():
            overrides = {
                st: v["adopt"]
                for st, v in (info.get("stats") or {}).items()
                if st in _ADOPT_STATS and v.get("adopt") and v["adopt"] != "ataque_defensa"
            }
            if overrides:
                tmap[team] = overrides
        if tmap:
            out[league_label] = tmap
    return out


def _load_players(season: int) -> dict | None:
    """Rankings de jugadores (goleadores, asistencias...) por liga, AUTO-REFRESCADOS.

    Antes se devolvía tal cual football/data/players.json (una foto estática que
    tapaba el fetch en vivo y se quedaba desactualizada). Ahora se REFRESCA en
    cada ejecución desde football-data.org (misma clave que los fixtures, fiable
    en CI): goleadores y asistentes de LaLiga y Champions. Ese fetch se SUPERPONE
    sobre el fichero estático, que queda solo como base/fallback para las
    categorías que la fuente en vivo no da (remates/xG/amarillas de understat) y
    para cuando no hay clave. Así los goleadores están siempre al día y Champions
    —que antes salía vacío— se rellena.

    Devuelve {liga: {label, rankings:{cat:{label, players[]}}}} o None.
    """
    # 1) Base estática (understat, más categorías pero puede envejecer).
    static: dict = {}
    path = Path(DATA_DIR) / "players.json"
    if path.exists():
        try:
            static = {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items()
                      if not k.startswith("_")}
        except Exception:
            static = {}

    # 2) Fetch en vivo (football-data.org /scorers: LaLiga PD y Champions CL).
    live: dict = {}
    try:
        from .ingest.players_football_data import get_top_players

        for league, label in (("laliga", "LaLiga"), ("segunda", "LaLiga Hypermotion"),
                              ("champions", "Champions League")):
            try:
                r = get_top_players(season, league=league)
            except Exception:
                r = None
            if r:
                live[league] = {"label": label, "rankings": r}
    except Exception:
        live = {}

    # 3) Fusión: base estática + categorías frescas del vivo (el vivo manda en
    #    goles/asistencias; se conservan las categorías extra del estático).
    out: dict = {}
    for league in set(static) | set(live):
        s = static.get(league) or {}
        lv = live.get(league) or {}
        rankings = dict(s.get("rankings") or {})
        rankings.update(lv.get("rankings") or {})
        if rankings:
            out[league] = {
                "label": lv.get("label") or s.get("label") or league,
                "rankings": rankings,
            }
    return out or None


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


def _quiniela_kickoff(fecha: str | None, now: datetime) -> datetime:
    """Saque sintético para un partido de la quiniela sin fixture en el feed."""
    if fecha:
        try:
            d = datetime.fromisoformat(fecha)
            return d.replace(hour=18, minute=0, tzinfo=MADRID) if d.tzinfo is None else d
        except ValueError:
            pass
    return (ensure_aware(now) + timedelta(days=2)).astimezone(MADRID)


def _quiniela_from_match(m: dict) -> dict:
    """Extrae el pronóstico ya calculado de un partido del feed (Tier A)."""
    probs = m.get("probs")
    signo = ["1", "X", "2"][max(range(3), key=lambda i: probs[i])]
    return {
        "probs": probs,
        "signo": signo,
        "marcador": (m.get("markets") or {}).get("marcador"),
        "xg": m.get("xg"),
        "league": m.get("league"),
        "kickoff": m.get("kickoff"),
        "matchday": m.get("matchday"),
        "fuente": "feed",
        "match_id": m.get("id"),
    }


def _quiniela_from_payload(payload: dict, league_label: str) -> dict | None:
    """Pronóstico desde un fixture_payload recién calculado (Tier B: modelo de liga)."""
    probs = payload.get("probs")
    if not isinstance(probs, list):
        return None
    signo = ["1", "X", "2"][max(range(3), key=lambda i: probs[i])]
    return {
        "probs": probs,
        "signo": signo,
        "marcador": (payload.get("markets") or {}).get("marcador"),
        "xg": payload.get("xg"),
        "league": league_label,
        "kickoff": payload.get("kickoff"),
        "matchday": payload.get("matchday"),
        "fuente": "modelo",
    }


def _quiniela_predict_one(local, visit, feed_idx, league_bundles, team_league, kickoff, generated_at) -> dict | None:
    """Resuelve el pronóstico de UN partido de la quiniela con grounding en cascada.

    A) Reutiliza el partido del feed si existe (misma tarjeta que ve el usuario).
    B) Si no, predice con el modelo de la liga que conozca a ambos equipos
       (clave para Segunda: co.uk solo da resultados, sin calendario próximo).
    C) Si es femenino o el equipo es desconocido, usa el modelo curado de Liga F
       (prior de jerarquía). Así NINGÚN partido queda "sin predicción".
    """
    from . import ligaf

    ch, ca = _canon(local), _canon(visit)
    femenino = ligaf.is_femenino(local) or ligaf.is_femenino(visit)

    if not femenino:
        # Tier A: partido próximo con predicción en el feed.
        m = feed_idx.get((ch, ca))
        if m:
            return _quiniela_from_match(m)
        # Tier B: modelo de la liga que conozca a ambos equipos. Se prioriza la
        # división donde JUEGAN hoy (según el feed): así un equipo que también
        # está en el sembrado de otra liga (Girona/Almería/Cádiz, ex-Primera) se
        # predice y etiqueta con su división actual (Segunda), no con la sembrada.
        label_to_key = {v: k for k, v in LEAGUES.items()}
        pref_label = team_league.get(ch) if team_league.get(ch) == team_league.get(ca) else None
        pref_key = label_to_key.get(pref_label) if pref_label else None
        order = sorted(league_bundles.items(), key=lambda kv: kv[0] != pref_key)
        for league, bundle in order:
            model = bundle.get("model")
            if model is None or not (model.is_known(ch) and model.is_known(ca)):
                continue
            fixture = Fixture(
                api_id=abs(hash((local, visit))) % 10_000_000,
                league=league, season=current_season(),
                kickoff=kickoff, home_team=local, away_team=visit,
                status="SCHEDULED", source="quiniela",
            )
            payload = fixture_payload(
                fixture, model, generated_at,
                stats=bundle.get("stats"), team_meta=bundle.get("team_meta"),
                real_stats=bundle.get("real_stats"), odds_map=bundle.get("odds_map"),
                closing_odds_map=bundle.get("closing_odds_map"),
                model_weight=bundle.get("model_weight", 0.6), h2h=bundle.get("h2h"),
                trends=bundle.get("trends"), elo=bundle.get("elo"),
                ensemble_params=bundle.get("ensemble_params"),
                residual_params=bundle.get("residual_params"),
                market_temperature=bundle.get("market_temperature", 1.0),
            )
            resolved = _quiniela_from_payload(payload, LEAGUES.get(league, league))
            if resolved:
                return resolved

    # Tier C: modelo curado (Liga F para femeninos; base con ventaja de campo si
    # el equipo es desconocido en todas las ligas masculinas).
    lf = ligaf.predict(local, visit)
    probs = lf["probs"]
    signo = max(probs, key=probs.get)
    return {
        "probs": [round(probs["1"] * 100), round(probs["X"] * 100), round(probs["2"] * 100)],
        "signo": signo,
        "marcador": lf["marcador"],
        "xg": list(lf["xg"]),
        "league": "Liga F" if femenino else "—",
        "kickoff": ensure_aware(kickoff).astimezone(MADRID).isoformat(),
        "matchday": None,
        "fuente": "liga_f" if femenino else "base",
    }


def _resolve_quiniela(quiniela, matches, league_bundles, generated_at, now) -> dict | None:
    """Adjunta a CADA partido de la quiniela oficial su pronóstico fundamentado.

    El frontend ya no adivina cruzando nombres contra el feed (lo que dejaba los
    de Segunda sin predicción y —peor— emparejaba los femeninos con el equipo
    masculino homónimo): el signo viaja calculado y con su procedencia.
    """
    if not quiniela or not quiniela.get("partidos"):
        return quiniela
    feed_idx: dict[tuple[str, str], dict] = {}
    team_league: dict[str, str] = {}  # equipo canónico -> liga donde juega HOY
    for m in matches:
        league_label = m.get("league")
        for side in ("home", "away"):
            team = m.get(side)
            if team:
                team_league[_canon(team)] = league_label
        if m.get("finished") or not isinstance(m.get("probs"), list):
            continue
        feed_idx.setdefault((_canon(m.get("home", "")), _canon(m.get("away", ""))), m)
    kickoff = _quiniela_kickoff(quiniela.get("fecha"), now)
    resolved = 0
    for p in quiniela["partidos"]:
        try:
            pred = _quiniela_predict_one(
                p.get("local", ""), p.get("visitante", ""),
                feed_idx, league_bundles, team_league, kickoff, generated_at,
            )
        except Exception:  # noqa: BLE001 - un partido nunca tumba la quiniela
            pred = None
        if pred and isinstance(pred.get("probs"), list):
            p.update(pred)
            resolved += 1
    quiniela["con_prediccion"] = resolved
    quiniela["fuentes"] = sorted({p.get("fuente") for p in quiniela["partidos"] if p.get("fuente")})
    return quiniela


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
        model = TrendModel().fit(fixtures, rows, _canon)
        try:  # diagnóstico: por qué las tendencias salen (o no) planas
            disp = model._signal_dispersion()
            thr = {m: round(model._threshold(m), 4) for m in disp}
            print(f"[trends] {league}: equipos={len(model.totals)} "
                  f"co.uk_filas={len(rows)} umbrales={thr}")
        except Exception:  # noqa: BLE001 - el diagnóstico nunca tumba el feed
            pass
        return model
    except Exception as exc:  # noqa: BLE001
        # Sin esto el fallo era invisible y dejaba las tendencias congeladas
        # (se conservaba el last-known-good) sin ninguna señal en los logs.
        print(f"[trends] modelo no construido ({league}): {type(exc).__name__}: {exc}")
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
