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
    real_stats: dict | None = None,
    odds_map: dict | None = None,
    model_weight: float = 0.6,
    h2h: dict | None = None,
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


def _attach_previews(matches: list[dict], now: datetime, horizon_days: int = 6, limit: int = 24) -> None:
    """Añade una previa narrativa (Gemini) a los próximos partidos con predicción.

    Reutiliza las previas del feed anterior (por id) para no re-llamar a Gemini
    cada hora, y limita por fecha y cantidad para respetar el plan gratuito.
    Sin clave (AI_API_KEY) no hace nada. Cualquier fallo se ignora en silencio.
    """
    try:
        from .ingest.preview_gemini import API_KEY, generate_preview
    except Exception:
        return
    if not API_KEY:
        return

    prev: dict[str, str] = {}
    try:
        old = json.loads(OUTPUT.read_text(encoding="utf-8"))
        for m in old.get("matches", []):
            if m.get("preview") and m.get("id"):
                prev[m["id"]] = m["preview"]
    except Exception:
        pass

    now = ensure_aware(now)
    cands = [m for m in matches if not m.get("finished") and m.get("probs")]
    cands.sort(key=lambda m: m.get("kickoff") or "")
    made = 0
    for m in cands:
        cached = prev.get(m.get("id"))
        if cached:
            m["preview"] = cached
            continue
        if made >= limit:
            continue
        try:
            days = (datetime.fromisoformat(m["kickoff"]) - now).days
        except Exception:
            days = 0
        if days > horizon_days:
            continue
        txt = generate_preview(m)
        if txt:
            m["preview"] = txt
            made += 1


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
            real_stats = _real_stats_map(league, season)
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
                                model_weight=model_w, h2h=h2h)
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
    _attach_previews(matches, now)
    return {
        "schema_version": 2,
        "generated_at": generated_at,
        "season": season,
        "quiniela": _load_quiniela_oficial(),
        "players": _load_players(season),
        "model": _load_model_report(season),
        "accuracy": _aggregate_accuracy(matches),
        "engine": "dixon-coles" if any(item["engine"] == "dixon-coles" for item in matches) else "calendar-only",
        "data_sources": {
            "fixtures": "football-data.org (LaLiga) · football-data.co.uk (Segunda)",
            "stats": "football-data.co.uk (remates, córners, faltas, tarjetas — reales y esperadas)",
            "players": "football-data.org (/scorers: goleadores y asistencias)",
            "odds": "football-data.co.uk (media de mercado: 1X2 y over/under 2.5)",
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
                real_total = float(real_stats[key][0]) + float(real_stats[key][1])
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

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Feed actualizado: {len(payload['matches'])} partidos en {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
