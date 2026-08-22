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

    # Partido ya jugado: mostramos el resultado real, no predicción.
    if finished and fixture.home_goals is not None:
        payload["result"] = [fixture.home_goals, fixture.away_goals]
        payload["engine"] = "resultado-real"
        return payload

    if model is None:
        return payload
    home_id, away_id = _canon(fixture.home_team), _canon(fixture.away_team)
    try:
        prediction = predict_match(
            model,
            home_id,
            away_id,
            kickoff=fixture.kickoff,
        )
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
        payload["engine"] = "datos-insuficientes"
        payload["nota"] = "Modelo aún sin muestra fiable de la temporada"
        return payload

    top = matrix.top_correct_scores(1)[0]
    payload.update({
        "probs": [
            round(probs["1"] * 100),
            round(probs["X"] * 100),
            round(probs["2"] * 100),
        ],
        "xg": [round(value, 2) for value in prediction.expected_goals],
        "markets": {
            "over_2_5": round(matrix.over(2.5), 3),
            "over_1_5": round(matrix.over(1.5), 3),
            "over_3_5": round(matrix.over(3.5), 3),
            "btts": round(matrix.btts()["yes"], 3),
            "marcador": f"{top[0]}-{top[1]}",
        },
        "engine": "dixon-coles",
    })

    # Si algún equipo aún no tiene histórico (recién ascendido, sin datos de la
    # temporada), la predicción usa prior neutro: la marcamos como provisional.
    if not (model.is_known(home_id) and model.is_known(away_id)):
        payload["provisional"] = True
        payload["nota"] = "Predicción provisional: algún equipo aún sin histórico"

    # Estadísticas por equipo y totales (córners, tarjetas, remates, faltas...).
    if stats is not None:
        try:
            sp = stats.predict_fixture(fixture.home_team, fixture.away_team)
            if sp:
                payload["stats"] = {
                    k: {"home": v["home"], "away": v["away"], "total": v["total"]}
                    for k, v in sp.items()
                }
        except (KeyError, ValueError):
            pass
    return payload


def build_dashboard(
    now: datetime | None = None,
    horizon_days: int = 10,  # sin uso: ahora incluimos TODA la temporada
) -> dict:
    now = now or datetime.now(timezone.utc)
    now = ensure_aware(now)
    season = current_season(now)
    generated_at = now.astimezone(MADRID).isoformat()
    matches: list[dict] = []
    errors: list[dict] = []

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
            # TODOS los partidos de la temporada (resultados + próximos).
            matches.extend(
                fixture_payload(fx, model, generated_at, stats=stats, team_meta=meta)
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
    return {
        "schema_version": 2,
        "generated_at": generated_at,
        "season": season,
        "quiniela": _load_quiniela_oficial(),
        "players": _load_players(season),
        "model": _load_model_report(season),
        "engine": "dixon-coles" if any(item["engine"] == "dixon-coles" for item in matches) else "calendar-only",
        "data_sources": {
            "fixtures": "football-data.org (LaLiga) · football-data.co.uk (Segunda)",
            "stats": "football-data.co.uk (remates, córners, faltas, tarjetas)",
            "players": "football-data.org (/scorers: goleadores y asistencias)",
            "odds": "pendiente (requiere The Odds API u similar)",
        },
        "disclaimer": "Probabilidades y ventaja estadística, no certezas. "
                      "Los datos de jugadores y cuotas se muestran como pendientes "
                      "hasta conectar una fuente real.",
        "counts": {
            "total": len(matches),
            "jugados": sum(1 for m in matches if m.get("finished")),
            "proximos": sum(1 for m in matches if not m.get("finished")),
            "con_prediccion": sum(1 for m in matches if m.get("engine") == "dixon-coles"),
        },
        "matches": matches,
        "errors": errors,
    }


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

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Feed actualizado: {len(payload['matches'])} partidos en {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
