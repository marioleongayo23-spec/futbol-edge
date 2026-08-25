"""Snapshots inmutables de predicción publicados antes del partido."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")
MODEL_VERSION = "edge-2.0"

_SNAPSHOT_FIELDS = (
    "probs",
    "model_probs",
    "xg",
    "markets",
    "stats",
    "tendencias",
    "odds",
    "value",
    "calibrated",
    "market_calibration",
    "model_meta",
    "venue_meta",
    "weather",
    "tactical_matchup",
    "lineup_impact",
    "state_simulation",
    "prediction_confidence",
    "prediction_factors",
    "recommendation",
    "score_distribution",
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=MADRID)


def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        return _aware(datetime.fromisoformat(str(value)))
    except (TypeError, ValueError):
        return None


def _identity(match: dict) -> str:
    date = str(match.get("date") or match.get("kickoff") or "")[:10]
    return "|".join(
        str(value or "").strip().casefold()
        for value in (match.get("league"), match.get("home"), match.get("away"), date)
    )


def _snapshot(match: dict, now: datetime, window: str) -> dict | None:
    probs = match.get("probs")
    if not isinstance(probs, list) or len(probs) != 3:
        return None
    out = {
        "generated_at": _aware(now).isoformat(),
        "window": window,
        "model_version": (match.get("model_meta") or {}).get("version", MODEL_VERSION),
    }
    for field in _SNAPSHOT_FIELDS:
        if field in match:
            out[field] = deepcopy(match[field])
    return out


def latest_pre_match_snapshot(match: dict) -> dict | None:
    """Último snapshot estrictamente anterior al inicio del partido."""

    kickoff = _parse(match.get("kickoff"))
    valid = []
    for snapshot in match.get("prediction_history") or []:
        generated = _parse(snapshot.get("generated_at")) if isinstance(snapshot, dict) else None
        if generated and (kickoff is None or generated < kickoff):
            valid.append((generated, snapshot))
    current = match.get("prediction_snapshot")
    if isinstance(current, dict):
        generated = _parse(current.get("generated_at"))
        if generated and (kickoff is None or generated < kickoff):
            valid.append((generated, current))
    return deepcopy(max(valid, key=lambda item: item[0])[1]) if valid else None


def _restore(match: dict, snapshot: dict, *, finished: bool) -> None:
    for field in _SNAPSHOT_FIELDS:
        if field in snapshot:
            match[field] = deepcopy(snapshot[field])
    match["prediction_snapshot"] = deepcopy(snapshot)
    # El estado real del partido manda sobre el motor histórico mostrado.
    if not finished:
        residual = (snapshot.get("model_meta") or {}).get("residual") or {}
        ensemble = (snapshot.get("model_meta") or {}).get("ensemble") or {}
        match["engine"] = (
            "residual" if residual.get("accepted")
            else "ensemble" if ensemble.get("accepted") else "dixon-coles"
        )


def apply_prediction_snapshots(
    matches: list[dict],
    previous_matches: list[dict] | None,
    now: datetime,
    force: bool = False,
    max_history: int = 8,
    capture: bool = True,
) -> None:
    """Congela producción y solo crea revisiones 00:15/10:15 para el día.

    En la primera ejecución se crea una referencia para todos los próximos
    partidos, de modo que nunca desaparezca una predicción. A partir de ahí solo
    los encuentros del día se revisan en las dos ventanas acordadas.
    """

    now = _aware(now).astimezone(MADRID)
    old_by_id = {
        item.get("id"): item for item in (previous_matches or []) if isinstance(item, dict) and item.get("id")
    }
    old_by_key = {
        _identity(item): item for item in (previous_matches or []) if isinstance(item, dict)
    }
    for match in matches:
        old = old_by_id.get(match.get("id")) or old_by_key.get(_identity(match)) or {}
        history = deepcopy(old.get("prediction_history") or [])
        old_current = old.get("prediction_snapshot")
        if isinstance(old_current, dict) and not any(
            item.get("generated_at") == old_current.get("generated_at") for item in history if isinstance(item, dict)
        ):
            history.append(deepcopy(old_current))

        kickoff = _parse(match.get("kickoff"))
        same_day = bool(kickoff and kickoff.astimezone(MADRID).date() == now.date())
        before_kickoff = kickoff is None or now < kickoff.astimezone(MADRID)
        in_window = now.hour in {0, 10} and 15 <= now.minute < 45
        has_previous = bool(history or old_current)
        window_label = f"{now.hour:02d}:15"
        window_already_captured = any(
            isinstance(item, dict)
            and item.get("window") == window_label
            and str(item.get("generated_at") or "")[:10] == now.date().isoformat()
            for item in history
        )
        should_capture = (
            capture
            and before_kickoff
            and not match.get("finished")
            and (
                not has_previous
                or (same_day and force)
                or (same_day and in_window and not window_already_captured)
            )
        )

        if should_capture:
            label = window_label if same_day and (in_window or force) else "initial"
            candidate = _snapshot(match, now, label)
            if candidate:
                # Una ejecución repetida dentro de la misma ventana sustituye
                # su intento, pero nunca duplica ni reescribe ventanas anteriores.
                history = [
                    item for item in history
                    if not (
                        isinstance(item, dict)
                        and item.get("window") == label
                        and str(item.get("generated_at", ""))[:10] == now.date().isoformat()
                    )
                ]
                history.append(candidate)
                old_current = candidate

        match["prediction_history"] = sorted(
            (item for item in history if isinstance(item, dict)),
            key=lambda item: str(item.get("generated_at") or ""),
        )[-max_history:]
        chosen = latest_pre_match_snapshot(match)
        if chosen:
            _restore(match, chosen, finished=bool(match.get("finished")))
        elif match.get("finished") or (kickoff is not None and now >= kickoff.astimezone(MADRID)):
            # Los partidos históricos previos a schema v5 no tenían snapshot.
            # Es preferible mostrar solo el resultado real que atribuir al
            # modelo una predicción reconstruida con información futura.
            for field in _SNAPSHOT_FIELDS:
                match.pop(field, None)
            match.pop("prediction_snapshot", None)
            match["prediction_unavailable_reason"] = "sin_snapshot_prepartido"
