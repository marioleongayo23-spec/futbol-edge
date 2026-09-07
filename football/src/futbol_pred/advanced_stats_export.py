"""Exportador reproducible de snapshots avanzados xG/npxG/PSxG.

Este módulo NO consulta la red. Convierte observaciones por equipo/partido ya
terminado en ``advanced-stats-snapshot-v1`` y las agrupa en un archivo histórico
consumible por :mod:`futbol_pred.advanced_stats`.

Principio anti-leakage:
- un backfill histórico no pretende saber cuándo FBref publicó realmente cada
  fila antigua;
- por ello cada observación se hace disponible de forma conservadora al día
  siguiente a las 12:00 UTC;
- un snapshot live sí conserva la hora real de captura.

Nada de esta capa modifica Dixon-Coles, lambdas ni 1X2. Solo prepara evidencia
reproducible para un challenger posterior.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import warnings

from .advanced_stats import ARCHIVE_SCHEMA, SCHEMA, normalise_snapshot
from .normalize import canonical_team

BACKFILL_AVAILABILITY_POLICY = "historical_backfill_conservative_next_day_12utc"
LIVE_AVAILABILITY_POLICY = "live_capture_timestamp"
EXPORT_SCHEMA = "advanced-stats-export-v1"


def _dt(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _num(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _canon(team: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return canonical_team(str(team or "").strip())


def conservative_available_at(match_at) -> datetime | None:
    """Día siguiente a las 12:00 UTC: política deliberadamente conservadora."""
    stamp = _dt(match_at)
    if stamp is None:
        return None
    next_day = stamp.date() + timedelta(days=1)
    return datetime.combine(next_day, time(12, 0), tzinfo=timezone.utc)


def normalise_match_record(raw: dict) -> dict | None:
    """Normaliza una observación de un equipo en un partido terminado.

    Campos mínimos: ``match_at`` y ``team``. Las métricas pueden ser parciales;
    una fila sin ninguna señal avanzada se descarta.
    """
    if not isinstance(raw, dict):
        return None
    match_at = _dt(raw.get("match_at") or raw.get("date") or raw.get("kickoff"))
    team = _canon(raw.get("team") or raw.get("squad") or "")
    if match_at is None or not team:
        return None

    metrics = {
        "xg_for": _num(raw.get("xg_for")),
        "npxg_for": _num(raw.get("npxg_for")),
        "xg_against": _num(raw.get("xg_against")),
        "npxg_against": _num(raw.get("npxg_against")),
        "keeper_psxg90": _num(raw.get("keeper_psxg90")),
        "keeper_psxg_plus_minus90": _num(raw.get("keeper_psxg_plus_minus90")),
    }
    if all(value is None for value in metrics.values()):
        return None

    minutes = _num(raw.get("keeper_minutes"))
    if minutes is None:
        minutes = 90.0 if (
            metrics["keeper_psxg90"] is not None
            or metrics["keeper_psxg_plus_minus90"] is not None
        ) else 0.0
    minutes = max(0.0, minutes)

    return {
        "match_at": match_at,
        "team": team,
        "team_source_name": str(raw.get("team") or raw.get("squad") or team),
        "opponent": _canon(raw.get("opponent") or "") or None,
        **metrics,
        "keeper_player": str(raw.get("keeper_player") or "").strip() or None,
        "keeper_minutes": minutes,
    }


def _new_team_state(source_name: str) -> dict:
    return {
        "team_source_name": source_name,
        "matches": 0,
        "sums": {field: 0.0 for field in ("xg_for", "npxg_for", "xg_against", "npxg_against")},
        "counts": {field: 0 for field in ("xg_for", "npxg_for", "xg_against", "npxg_against")},
        "keepers": {},
    }


def _apply_record(state: dict, row: dict) -> None:
    state["matches"] += 1
    for field in ("xg_for", "npxg_for", "xg_against", "npxg_against"):
        value = row.get(field)
        if value is not None:
            state["sums"][field] += float(value)
            state["counts"][field] += 1

    minutes = float(row.get("keeper_minutes") or 0.0)
    if minutes <= 0:
        return
    player = row.get("keeper_player") or "Team goalkeeper unit"
    keeper = state["keepers"].setdefault(
        player,
        {
            "player": None if player == "Team goalkeeper unit" else player,
            "minutes": 0.0,
            "psxg_weighted": 0.0,
            "psxg_minutes": 0.0,
            "plusminus_weighted": 0.0,
            "plusminus_minutes": 0.0,
        },
    )
    keeper["minutes"] += minutes
    psxg = row.get("keeper_psxg90")
    if psxg is not None:
        keeper["psxg_weighted"] += float(psxg) * minutes
        keeper["psxg_minutes"] += minutes
    plusminus = row.get("keeper_psxg_plus_minus90")
    if plusminus is not None:
        keeper["plusminus_weighted"] += float(plusminus) * minutes
        keeper["plusminus_minutes"] += minutes


def _team_snapshot(state: dict) -> dict:
    row: dict = {
        "team_source_name": state["team_source_name"],
        "matches": int(state["matches"]),
    }
    mapping = {
        "xg_for": "xg_for90",
        "npxg_for": "npxg_for90",
        "xg_against": "xg_against90",
        "npxg_against": "npxg_against90",
    }
    for source, target in mapping.items():
        n = state["counts"][source]
        if n:
            row[target] = round(state["sums"][source] / n, 5)

    keepers = []
    for keeper in sorted(
        state["keepers"].values(),
        key=lambda item: (-(item.get("minutes") or 0.0), str(item.get("player") or "")),
    ):
        item = {
            "player": keeper.get("player"),
            "minutes": round(float(keeper["minutes"]), 1),
        }
        if keeper["psxg_minutes"] > 0:
            item["psxg90"] = round(
                keeper["psxg_weighted"] / keeper["psxg_minutes"], 5
            )
        if keeper["plusminus_minutes"] > 0:
            item["psxg_plus_minus90"] = round(
                keeper["plusminus_weighted"] / keeper["plusminus_minutes"], 5
            )
        keepers.append(item)
    row["goalkeepers"] = keepers
    return row


def _league_keeper_rate(teams: dict[str, dict]) -> float:
    weighted = 0.0
    minutes = 0.0
    for team in teams.values():
        for keeper in team.get("goalkeepers") or []:
            rate = _num(keeper.get("psxg_plus_minus90"))
            mins = _num(keeper.get("minutes"))
            if rate is None or mins is None or mins <= 0:
                continue
            weighted += rate * mins
            minutes += mins
    return round(weighted / minutes, 5) if minutes else 0.0


def build_historical_archive(
    records: list[dict],
    *,
    league: str,
    season: int,
    source: str,
    source_version: str | None = None,
    generated_at=None,
    min_team_matches: int = 1,
) -> dict:
    """Construye snapshots acumulativos causales desde partidos terminados.

    Todas las filas de un mismo ``available_at`` se incorporan antes de emitir el
    snapshot de ese corte, por lo que una jornada con varios partidos queda
    representada como un único estado consistente.
    """
    generated = _dt(generated_at) or datetime.now(timezone.utc)
    clean = [
        row for raw in records
        if (row := normalise_match_record(raw)) is not None
    ]
    clean.sort(
        key=lambda row: (row["match_at"], row["team"], row.get("opponent") or "")
    )

    grouped: dict[datetime, list[dict]] = {}
    for row in clean:
        available = conservative_available_at(row["match_at"])
        if available is not None:
            grouped.setdefault(available, []).append(row)

    states: dict[str, dict] = {}
    snapshots: list[dict] = []
    for available in sorted(grouped):
        for row in grouped[available]:
            state = states.setdefault(
                row["team"], _new_team_state(row["team_source_name"])
            )
            _apply_record(state, row)
        teams = {
            team: _team_snapshot(state)
            for team, state in sorted(states.items())
            if state["matches"] >= max(1, int(min_team_matches))
        }
        if not teams:
            continue
        snapshot = {
            "schema": SCHEMA,
            "source": source,
            "source_version": source_version,
            "generated_at": generated.isoformat(),
            "available_at": available.isoformat(),
            "availability_policy": BACKFILL_AVAILABILITY_POLICY,
            "historical_backfill": True,
            "league": league,
            "season": int(season),
            "league_keeper_psxg_plus_minus90": _league_keeper_rate(teams),
            "teams": teams,
        }
        snapshots.append(normalise_snapshot(snapshot))
    return {"schema": ARCHIVE_SCHEMA, "snapshots": snapshots}


def build_live_snapshot(
    teams: dict[str, dict],
    *,
    league: str,
    season: int,
    source: str,
    source_version: str | None = None,
    captured_at=None,
) -> dict:
    """Crea un snapshot live cuya disponibilidad es la hora real de captura."""
    captured = _dt(captured_at) or datetime.now(timezone.utc)
    snapshot = {
        "schema": SCHEMA,
        "source": source,
        "source_version": source_version,
        "generated_at": captured.isoformat(),
        "available_at": captured.isoformat(),
        "availability_policy": LIVE_AVAILABILITY_POLICY,
        "historical_backfill": False,
        "league": league,
        "season": int(season),
        "teams": deepcopy(teams),
    }
    normal = normalise_snapshot(snapshot)
    normal["league_keeper_psxg_plus_minus90"] = _league_keeper_rate(
        normal["teams"]
    )
    return normal


def _snapshot_key(snapshot: dict) -> tuple:
    return (
        str(snapshot.get("league") or ""),
        int(snapshot.get("season") or 0),
        str(snapshot.get("available_at") or ""),
        str(snapshot.get("source") or ""),
        str(snapshot.get("source_version") or ""),
    )


def merge_archives(*archives: dict | list | None) -> dict:
    """Fusiona archivos, deduplica y ordena de forma determinista."""
    merged: dict[tuple, dict] = {}
    for archive in archives:
        snapshots = archive.get("snapshots") if isinstance(archive, dict) else archive
        for raw in snapshots or []:
            try:
                snapshot = normalise_snapshot(raw)
            except (TypeError, ValueError):
                continue
            merged[_snapshot_key(snapshot)] = snapshot
    snapshots = sorted(
        merged.values(),
        key=lambda row: (
            str(row.get("available_at") or ""),
            str(row.get("league") or ""),
            int(row.get("season") or 0),
            str(row.get("source") or ""),
            str(row.get("source_version") or ""),
        ),
    )
    return {"schema": ARCHIVE_SCHEMA, "snapshots": snapshots}


def _semantic_snapshot(snapshot: dict) -> dict:
    """Quita solo metadatos de ejecución que no cambian la evidencia estadística."""
    semantic = deepcopy(snapshot)
    semantic.pop("generated_at", None)
    return semantic


def archive_digest(archive: dict | list) -> str:
    """SHA256 semántico estable frente a orden y hora de re-exportación.

    ``available_at`` sí forma parte del hash porque define causalidad. También
    cuentan fuente, versión, política de disponibilidad, equipos y métricas. Solo
    se excluye ``generated_at`` porque indica cuándo se re-ejecutó el exportador,
    no qué información era elegible en cada corte.
    """
    canonical = merge_archives(archive)
    semantic = [_semantic_snapshot(row) for row in canonical["snapshots"]]
    raw = json.dumps(
        semantic,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def archive_manifest(archive: dict | list) -> dict:
    canonical = merge_archives(archive)
    snapshots = canonical["snapshots"]
    leagues = sorted(
        {str(row.get("league")) for row in snapshots if row.get("league")}
    )
    seasons = sorted(
        {
            int(row.get("season"))
            for row in snapshots
            if row.get("season") is not None
        }
    )
    teams = sorted(
        {team for row in snapshots for team in (row.get("teams") or {})}
    )
    return {
        "schema": EXPORT_SCHEMA,
        "snapshot_count": len(snapshots),
        "leagues": leagues,
        "seasons": seasons,
        "teams": len(teams),
        "first_available_at": snapshots[0].get("available_at") if snapshots else None,
        "last_available_at": snapshots[-1].get("available_at") if snapshots else None,
        "sha256": archive_digest(canonical),
    }


def write_archive(path: str | Path, archive: dict | list) -> dict:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    canonical = merge_archives(archive)
    payload = {**canonical, "manifest": archive_manifest(canonical)}
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


# ------------------------------ DataFrame adapter ------------------------------

def _column_token(value) -> str:
    text = (
        " ".join(
            str(part)
            for part in value
            if str(part) not in {"", "nan", "None"}
        )
        if isinstance(value, tuple)
        else str(value)
    )
    text = text.replace("+/-", " plusminus ").replace("±", " plusminus ")
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _flatten_frame(frame):
    """Aplana columnas/índice de pandas sin importar pandas al cargar el módulo."""
    if frame is None:
        return None
    df = frame.copy()
    try:
        df = df.reset_index()
    except Exception:
        return None
    df.columns = [_column_token(col) for col in df.columns]
    return df


def _find_column(
    columns,
    candidates: tuple[str, ...],
    *,
    exclude: tuple[str, ...] = (),
) -> str | None:
    cols = [str(col) for col in columns]
    for candidate in candidates:
        token = _column_token(candidate)
        for col in cols:
            if col == token and not any(
                _column_token(bad) in col for bad in exclude
            ):
                return col
    for candidate in candidates:
        token = _column_token(candidate)
        for col in cols:
            if token and token in col and not any(
                _column_token(bad) in col for bad in exclude
            ):
                return col
    return None


def _frame_index(
    frame,
    *,
    value_candidates: tuple[str, ...],
    label: str,
) -> dict[tuple[str, str], float]:
    del label  # solo documenta la intención de la llamada
    df = _flatten_frame(frame)
    if df is None or getattr(df, "empty", True):
        return {}
    team_col = _find_column(df.columns, ("team", "squad"))
    date_col = _find_column(df.columns, ("date", "matchdate", "game"))
    value_col = _find_column(df.columns, value_candidates)
    if not team_col or not date_col or not value_col:
        return {}
    out = {}
    for _, row in df.iterrows():
        team = _canon(row.get(team_col))
        stamp = _dt(row.get(date_col))
        value = _num(row.get(value_col))
        if team and stamp is not None and value is not None:
            out[(stamp.date().isoformat(), team)] = value
    return out


def fbref_frames_to_records(
    schedule_frame,
    *,
    shooting_frame=None,
    opponent_shooting_frame=None,
    keeper_frame=None,
) -> list[dict]:
    """Convierte tablas de ``soccerdata.FBref`` a registros del exportador.

    El adaptador tolera MultiIndex y columnas ligeramente distintas. ``schedule``
    es la única tabla obligatoria; npxG/PSxG son enriquecimientos opcionales.
    """
    schedule = _flatten_frame(schedule_frame)
    if schedule is None or getattr(schedule, "empty", True):
        return []
    team_col = _find_column(schedule.columns, ("team", "squad"))
    date_col = _find_column(schedule.columns, ("date", "matchdate", "game"))
    opponent_col = _find_column(schedule.columns, ("opponent", "opp"))
    xg_col = _find_column(
        schedule.columns, ("xg",), exclude=("xga", "opponent")
    )
    xga_col = _find_column(schedule.columns, ("xga", "opponentxg"))
    if not team_col or not date_col:
        return []

    npxg_for = _frame_index(
        shooting_frame,
        value_candidates=("npxg",),
        label="npxg_for",
    )
    npxg_against = _frame_index(
        opponent_shooting_frame,
        value_candidates=("npxg",),
        label="npxg_against",
    )
    psxg = _frame_index(
        keeper_frame,
        value_candidates=("psxg",),
        label="keeper_psxg90",
    )
    psxg_pm = _frame_index(
        keeper_frame,
        value_candidates=(
            "psxg plusminus 90",
            "psxg plusminus",
            "psxg+/-",
        ),
        label="keeper_psxg_plus_minus90",
    )

    records = []
    for _, row in schedule.iterrows():
        stamp = _dt(row.get(date_col))
        team = _canon(row.get(team_col))
        if stamp is None or not team:
            continue
        key = (stamp.date().isoformat(), team)
        raw = {
            "match_at": stamp,
            "team": row.get(team_col),
            "opponent": row.get(opponent_col) if opponent_col else None,
            "xg_for": row.get(xg_col) if xg_col else None,
            "xg_against": row.get(xga_col) if xga_col else None,
            "npxg_for": npxg_for.get(key),
            "npxg_against": npxg_against.get(key),
            "keeper_psxg90": psxg.get(key),
            "keeper_psxg_plus_minus90": psxg_pm.get(key),
            "keeper_minutes": 90.0 if key in psxg or key in psxg_pm else 0.0,
        }
        if normalise_match_record(raw) is not None:
            records.append(raw)
    return records
