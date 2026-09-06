"""Actualización postpartido de estadísticas reales para evaluación histórica.

La alineación oficial y las estadísticas finales tienen ciclos distintos. Un once
puede quedar confirmado una hora antes del partido; eso no debe impedir volver a
consultar API-Football tras el pitido final. Este módulo actualiza ``statsReal``
solo cuando el proveedor confirma FT/AET/PEN y mantiene football-data.co.uk como
fallback cuando API-Football no devuelve cobertura.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .ingest.api_football import ApiFootballClient
from .normalize import same_team

MADRID = ZoneInfo("Europe/Madrid")
FINAL_STATUSES = {"FT", "AET", "PEN"}
REAL_STAT_KEYS = ("goals", "shots", "sot", "corners", "fouls", "yellows", "reds")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=MADRID)


def _parse(value) -> datetime | None:
    try:
        return _aware(datetime.fromisoformat(str(value))).astimezone(MADRID)
    except (TypeError, ValueError):
        return None


def _team_key(value: str) -> str:
    return ApiFootballClient._team_key(value)


def _identity(match: dict) -> str:
    return "|".join(
        str(value or "").strip().casefold()
        for value in (
            match.get("league"), match.get("home"), match.get("away"),
            str(match.get("date") or match.get("kickoff") or "")[:10],
        )
    )


def _pick_team_stats(rows: dict, wanted: str) -> dict | None:
    candidates = [values for name, values in rows.items() if same_team(name, wanted)]
    return candidates[0] if len(candidates) == 1 else None


def _real_stats_from_detail(detail: dict, home: str, away: str, result=None) -> dict | None:
    fixture = detail.get("fixture") or {}
    status = ((fixture.get("status") or {}).get("short") or "").upper()
    if status not in FINAL_STATUSES:
        return None
    context = ApiFootballClient.fixture_context(detail)
    rows = context.get("live_or_post_stats") or {}
    home_stats = _pick_team_stats(rows, home)
    away_stats = _pick_team_stats(rows, away)
    if not home_stats or not away_stats:
        return None

    out = {}
    for key in REAL_STAT_KEYS:
        if key == "goals":
            if not isinstance(result, (list, tuple)) or len(result) != 2:
                continue
            hv, av = result[0], result[1]
        else:
            hv, av = home_stats.get(key), away_stats.get(key)
        if hv is None or av is None:
            continue
        try:
            home_value, away_value = float(hv), float(av)
        except (TypeError, ValueError):
            continue
        if home_value.is_integer():
            home_value = int(home_value)
        if away_value.is_integer():
            away_value = int(away_value)
        out[key] = {
            "home": home_value,
            "away": away_value,
            "total": home_value + away_value,
        }
    return out or None


def _inherit_previous_stats(match: dict, previous: dict | None) -> None:
    if not previous or not previous.get("statsReal"):
        return
    current = dict(match.get("statsReal") or {})
    old = dict(previous.get("statsReal") or {})
    # Si el feed anterior ya tenía el cierre de API-Football, esa captura final
    # tiene prioridad frente a una fuente histórica que pueda llegar después.
    if previous.get("statsRealSource") == "API-Football · final":
        current = {**current, **old}
    else:
        current = {**old, **current}
    match["statsReal"] = current
    if previous.get("statsRealSource"):
        match["statsRealSource"] = previous["statsRealSource"]
    if previous.get("statsRealUpdatedAt"):
        match["statsRealUpdatedAt"] = previous["statsRealUpdatedAt"]
    if previous.get("official_context") and not match.get("official_context"):
        match["official_context"] = previous["official_context"]


def attach_finished_stats(
    matches: list[dict],
    now: datetime,
    client: ApiFootballClient | None = None,
    previous_matches: list[dict] | None = None,
    lookback_days: int = 3,
    limit: int = 40,
) -> int:
    """Refresca stats finales de partidos recientes, aunque el once esté confirmado.

    Primero hereda cualquier captura final del feed anterior para no consumir API
    cada 15 minutos. Después solo consulta partidos terminados recientes que sigan
    sin las métricas principales. Los detalles se recuperan en batch.
    """

    client = client or ApiFootballClient()
    now_local = _aware(now).astimezone(MADRID)
    cutoff = now_local - timedelta(days=max(1, int(lookback_days)))
    required = {"shots", "sot", "corners", "fouls", "yellows"}
    old_by_id = {
        row.get("id"): row for row in (previous_matches or [])
        if isinstance(row, dict) and row.get("id")
    }
    old_by_key = {
        _identity(row): row for row in (previous_matches or []) if isinstance(row, dict)
    }

    candidates = []
    for match in matches:
        old = old_by_id.get(match.get("id")) or old_by_key.get(_identity(match))
        _inherit_previous_stats(match, old)
        if not match.get("finished") or not match.get("result"):
            continue
        kickoff = _parse(match.get("kickoff"))
        if not kickoff or kickoff < cutoff or kickoff > now_local:
            continue
        existing = match.get("statsReal") or {}
        if required.issubset(existing):
            continue
        if client.offline:
            continue
        fixture_id = ((match.get("alineacion") or {}).get("official_fixture_id"))
        if not fixture_id:
            try:
                fixture = client.find_fixture(
                    match.get("home", ""), match.get("away", ""), kickoff
                )
                fixture_id = ((fixture or {}).get("fixture") or {}).get("id")
            except Exception:
                fixture_id = None
        if fixture_id:
            candidates.append((kickoff, match, int(fixture_id)))

    candidates = sorted(candidates, key=lambda item: item[0], reverse=True)[: max(0, int(limit))]
    if not candidates:
        return 0
    details = client.get_fixture_details([fixture_id for _, _, fixture_id in candidates])
    updated = 0
    for _, match, fixture_id in candidates:
        detail = details.get(fixture_id)
        if not detail:
            continue
        real = _real_stats_from_detail(
            detail, match.get("home", ""), match.get("away", ""), match.get("result")
        )
        if not real:
            continue
        merged = dict(match.get("statsReal") or {})
        merged.update(real)
        match["statsReal"] = merged
        match["statsRealSource"] = "API-Football · final"
        match["statsRealUpdatedAt"] = now_local.isoformat()
        context = ApiFootballClient.fixture_context(detail)
        if context:
            context["source_updated_at"] = now_local.isoformat()
            match["official_context"] = {**(match.get("official_context") or {}), **context}
        updated += 1
    return updated
