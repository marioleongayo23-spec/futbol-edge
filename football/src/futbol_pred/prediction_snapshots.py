"""Snapshots inmutables de predicción publicados antes del partido."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")
MODEL_VERSION = "edge-2.0"

# El cron corre cada 15 minutos. La tolerancia absorbe pequeños retrasos del
# runner sin etiquetar una captura lejana como si fuera el hito exacto.
MILESTONE_TOLERANCE_HOURS = 0.35
MILESTONES = ((24, "T-24h"), (12, "T-12h"), (6, "T-6h"))
FINAL_WINDOWS = {"T-60": "final_T-60_official", "T-30": "final_T-30_official"}

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
    "weather_adjustment",
    "extended_market",
    "extended_value",
    "tactical_matchup",
    "alineacion",
    "official_context",
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


def _captured(history: list[dict], label: str, date: str | None = None) -> bool:
    for item in history:
        if not isinstance(item, dict) or item.get("window") != label:
            continue
        if date is None or str(item.get("generated_at") or "")[:10] == date:
            return True
    return False


def _lineup_complete(lineup: dict) -> bool:
    return (
        isinstance(lineup, dict)
        and len(lineup.get("local") or []) == 11
        and len(lineup.get("visitante") or []) == 11
    )


def _milestone_label(kickoff: datetime | None, now: datetime, history: list[dict]) -> str | None:
    if kickoff is None:
        return None
    hours = (kickoff - now).total_seconds() / 3600
    if hours <= 0:
        return None
    for target, label in MILESTONES:
        if abs(hours - target) <= MILESTONE_TOLERANCE_HOURS and not _captured(history, label):
            return label
    return None


def _prefinal_label(kickoff: datetime | None, now: datetime, history: list[dict], lineup: dict) -> str | None:
    if kickoff is None:
        return None
    hours = (kickoff - now).total_seconds() / 3600
    if hours <= 0 or abs(hours - 3.0) > MILESTONE_TOLERANCE_HOURS:
        return None
    if _captured(history, "pre_final_T-3h") or _captured(history, "T-3h"):
        return None
    # Solo llamamos PRE-FINAL a un estado que contiene 11+11 probables y que ha
    # pasado por el refresco específico T-3h. Si falló la fuente, archivamos T-3h
    # sin venderlo como pre-final completa.
    if _lineup_complete(lineup) and lineup.get("phase") == "pre_final":
        return "pre_final_T-3h"
    return "T-3h"


def _official_final_label(lineup: dict, history: list[dict], before_kickoff: bool) -> str | None:
    if not before_kickoff or lineup.get("status") != "confirmado" or not _lineup_complete(lineup):
        return None
    if any(_captured(history, label) for label in (*FINAL_WINDOWS.values(), "official_lineup")):
        return None
    poll_window = lineup.get("official_poll_window")
    # Feeds antiguos no guardaban la ventana del poll; mantenemos compatibilidad
    # sin confundirlos con las nuevas finales T-60/T-30.
    return FINAL_WINDOWS.get(poll_window, "official_lineup")


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
    max_history: int = 16,
    capture: bool = True,
) -> None:
    """Congela producción y crea versiones útiles para apostar sin leakage.

    Ciclo nuevo:
      initial → T-24h → T-12h → T-6h → PRE-FINAL T-3h
      → FINAL oficial T-60 (o T-30 si todavía no estaba publicada).

    Se conservan 00:15/10:15 por compatibilidad histórica. Ninguna captura se
    crea después del saque inicial y la final oficial se archiva una sola vez.
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
        kickoff_local = kickoff.astimezone(MADRID) if kickoff else None
        same_day = bool(kickoff_local and kickoff_local.date() == now.date())
        before_kickoff = kickoff_local is None or now < kickoff_local
        in_legacy_window = now.hour in {0, 10} and 15 <= now.minute < 45
        has_previous = bool(history or old_current)

        lineup = match.get("alineacion") or {}
        final_label = _official_final_label(lineup, history, before_kickoff)
        prefinal_label = _prefinal_label(kickoff_local, now, history, lineup) if before_kickoff else None
        milestone = _milestone_label(kickoff_local, now, history) if before_kickoff else None
        legacy_label = f"{now.hour:02d}:15" if same_day and in_legacy_window else None
        if legacy_label and _captured(history, legacy_label, now.date().isoformat()):
            legacy_label = None

        # La información más cercana al partido manda: final oficial > pre-final
        # > hitos tempranos > ventanas legacy > primera captura.
        capture_label = None
        if final_label:
            capture_label = final_label
        elif prefinal_label:
            capture_label = prefinal_label
        elif milestone:
            capture_label = milestone
        elif same_day and force:
            capture_label = f"{now.hour:02d}:15"
        elif legacy_label:
            capture_label = legacy_label
        elif not has_previous:
            capture_label = "initial"

        should_capture = (
            capture
            and before_kickoff
            and not match.get("finished")
            and capture_label is not None
        )

        if should_capture:
            candidate = _snapshot(match, now, capture_label)
            if candidate:
                # Solo las ventanas legacy forzadas pueden sustituirse dentro del
                # mismo día. Los hitos de apuesta son inmutables.
                if capture_label in {"00:15", "10:15"} or force:
                    history = [
                        item for item in history
                        if not (
                            isinstance(item, dict)
                            and item.get("window") == capture_label
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
        elif match.get("finished") or (kickoff_local is not None and now >= kickoff_local):
            # Los partidos históricos previos a schema v5 no tenían snapshot.
            # Es preferible mostrar solo el resultado real que atribuir al
            # modelo una predicción reconstruida con información futura.
            for field in _SNAPSHOT_FIELDS:
                match.pop(field, None)
            match.pop("prediction_snapshot", None)
            match["prediction_unavailable_reason"] = "sin_snapshot_prepartido"
