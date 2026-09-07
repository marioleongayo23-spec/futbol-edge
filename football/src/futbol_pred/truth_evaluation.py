"""P3.3: evaluación histórica leakage-safe contra la verdad postpartido.

Este módulo convierte ``final_stats_truth`` en evidencia cuantitativa para decidir
qué señales merecen entrar en futuros challengers. Solo usa snapshots publicados
antes del saque inicial, conserva revisiones si la verdad cambia y nunca modifica
las probabilidades ni los lambdas de producción.

El archivo de evaluación es acumulativo: guarda la predicción prepartido usada en
cada partido para poder re-evaluar una corrección posterior del proveedor aunque
ese partido ya no aparezca en el dashboard de serving.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import warnings
from zoneinfo import ZoneInfo

from .config import DATA_DIR, settings
from .final_stats_truth import LEAGUE_LABELS, SCHEMA as TRUTH_SCHEMA
from .normalize import canonical_team
from .prediction_snapshots import latest_pre_match_snapshot

MADRID = ZoneInfo("Europe/Madrid")
SCHEMA = "truth-evaluation-v1"
STAT_KEYS = ("goals", "xg", "shots", "sot", "corners", "fouls", "yellows", "reds", "offsides")
MONITORING_SAMPLE = 30
EVALUATION_READY_SAMPLE = 80
DEFAULT_DASHBOARD = Path(DATA_DIR) / "dashboard.json"
DEFAULT_TRUTH = Path(DATA_DIR) / "final_stats_truth.json"
DEFAULT_OUTPUT = Path(DATA_DIR) / "truth_evaluation.json"


def _num(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _pair(value) -> dict | None:
    try:
        if isinstance(value, dict):
            home, away = _num(value.get("home")), _num(value.get("away"))
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            home, away = _num(value[0]), _num(value[1])
        else:
            return None
    except (TypeError, ValueError, IndexError):
        return None
    if home is None or away is None:
        return None
    return {"home": home, "away": away, "total": home + away}


def _canon(value: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return canonical_team(str(value or "").strip())


def _date(value) -> str | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(MADRID).date().isoformat()


def _league(value) -> str:
    raw = str(value or "").strip()
    if raw in LEAGUE_LABELS:
        return LEAGUE_LABELS[raw]
    folded = raw.casefold()
    aliases = {
        "laliga": "laliga",
        "la liga": "laliga",
        "laliga hypermotion": "segunda",
        "segunda": "segunda",
        "segunda division": "segunda",
        "champions": "champions",
        "champions league": "champions",
        "uefa champions league": "champions",
    }
    return aliases.get(folded, folded)


def _match_identity(match: dict) -> tuple[str, str, str, str] | None:
    date = _date(match.get("kickoff") or match.get("date"))
    home, away = str(match.get("home") or ""), str(match.get("away") or "")
    if not date or not home or not away:
        return None
    return (_league(match.get("league")), date, _canon(home), _canon(away))


def _truth_identity(entry: dict) -> tuple[str, str, str, str] | None:
    league, date = str(entry.get("league") or ""), str(entry.get("date") or "")
    home, away = str(entry.get("home") or ""), str(entry.get("away") or "")
    if not league or not date or not home or not away:
        return None
    return (_league(league), date, _canon(home), _canon(away))


def _prediction_from_snapshot(snapshot: dict | None) -> dict[str, dict]:
    snapshot = snapshot or {}
    stats = snapshot.get("stats") or {}
    out: dict[str, dict] = {}
    for stat in STAT_KEYS:
        raw = snapshot.get("xg") if stat == "xg" else stats.get(stat)
        pair = _pair(raw)
        if pair is not None:
            out[stat] = pair
    return out


def _truth_digest(entry: dict) -> str:
    semantic = {
        "status": entry.get("status"),
        "consensus": entry.get("consensus") or {},
    }
    return hashlib.sha256(
        json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _comparison(predicted: dict, truth_row: dict) -> dict | None:
    if not isinstance(truth_row, dict) or not truth_row.get("usable"):
        return None
    actual = _pair(truth_row)
    if actual is None:
        return None
    error = {
        key: predicted[key] - actual[key]
        for key in ("home", "away", "total")
    }
    absolute_error = {key: abs(value) for key, value in error.items()}
    sources = truth_row.get("sources")
    if isinstance(sources, dict):
        source_list = sorted(str(key) for key in sources)
    elif isinstance(sources, list):
        source_list = sorted(str(key) for key in sources)
    else:
        source_list = []
    return {
        "predicted": {key: round(predicted[key], 6) for key in ("home", "away", "total")},
        "actual": {key: round(actual[key], 6) for key in ("home", "away", "total")},
        "error": {key: round(error[key], 6) for key in error},
        "absolute_error": {key: round(absolute_error[key], 6) for key in absolute_error},
        "truth_status": truth_row.get("status"),
        "truth_sources": source_list,
        "truth_confidence": truth_row.get("confidence"),
    }


def _previous_latest(previous_archive: dict | None, match_id: str) -> dict | None:
    record = ((previous_archive or {}).get("records") or {}).get(match_id) or {}
    latest = record.get("latest")
    return latest if isinstance(latest, dict) else None


def build_observations(
    matches: list[dict],
    truth: dict,
    *,
    previous_archive: dict | None = None,
) -> tuple[list[dict], dict]:
    """Une verdad y predicción por identidad exacta; jamás hace fuzzy matching.

    Si el dashboard ya no conserva un partido, reutiliza únicamente la predicción
    prepartido que P3.3 había archivado antes. Esto permite procesar correcciones
    tardías sin convertir información postpartido en una nueva feature.
    """

    if not isinstance(truth, dict) or truth.get("schema") != TRUTH_SCHEMA:
        return [], {"status": "truth_schema_invalid", "affects_1x2": False}

    index: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for match in matches or []:
        if not isinstance(match, dict):
            continue
        identity = _match_identity(match)
        if identity is not None:
            index[identity].append(match)

    observations: list[dict] = []
    missing_dashboard = 0
    ambiguous_dashboard = 0
    missing_snapshot = 0
    reused_prediction = 0
    truth_usable = Counter()
    evaluated = Counter()

    for match_id, entry in sorted((truth.get("matches") or {}).items()):
        if not isinstance(entry, dict):
            continue
        identity = _truth_identity(entry)
        if identity is None:
            continue
        candidates = index.get(identity) or []
        previous = _previous_latest(previous_archive, str(match_id))

        prediction: dict[str, dict] = {}
        snapshot_at = None
        snapshot_window = None
        model_version = None
        prediction_origin = None

        if len(candidates) == 1:
            snapshot = latest_pre_match_snapshot(candidates[0])
            if snapshot:
                prediction = _prediction_from_snapshot(snapshot)
                snapshot_at = snapshot.get("generated_at")
                snapshot_window = snapshot.get("window")
                model_version = snapshot.get("model_version") or ((snapshot.get("model_meta") or {}).get("version"))
                prediction_origin = "dashboard_pre_match_snapshot"
            elif previous:
                prediction = deepcopy(previous.get("prediction") or {})
                snapshot_at = previous.get("snapshot_at")
                snapshot_window = previous.get("snapshot_window")
                model_version = previous.get("model_version")
                prediction_origin = "archived_pre_match_prediction"
                reused_prediction += 1
            else:
                missing_snapshot += 1
                continue
        elif len(candidates) > 1:
            ambiguous_dashboard += 1
            if not previous:
                continue
        else:
            missing_dashboard += 1
            if not previous:
                continue

        if not prediction and previous:
            prediction = deepcopy(previous.get("prediction") or {})
            snapshot_at = previous.get("snapshot_at")
            snapshot_window = previous.get("snapshot_window")
            model_version = previous.get("model_version")
            prediction_origin = "archived_pre_match_prediction"
            reused_prediction += 1
        if not prediction:
            continue

        comparisons: dict[str, dict] = {}
        consensus = entry.get("consensus") or {}
        for stat in STAT_KEYS:
            truth_row = consensus.get(stat)
            if isinstance(truth_row, dict) and truth_row.get("usable"):
                truth_usable[stat] += 1
            predicted = prediction.get(stat)
            if predicted is None:
                continue
            row = _comparison(predicted, truth_row)
            if row is not None:
                comparisons[stat] = row
                evaluated[stat] += 1

        observations.append({
            "match_id": str(match_id),
            "league": entry.get("league"),
            "season": entry.get("season"),
            "date": entry.get("date"),
            "home": entry.get("home"),
            "away": entry.get("away"),
            "snapshot_at": snapshot_at,
            "snapshot_window": snapshot_window,
            "model_version": model_version,
            "prediction_origin": prediction_origin,
            "prediction": prediction,
            "truth_digest": _truth_digest(entry),
            "truth_match_status": entry.get("status"),
            "stats": comparisons,
            "evaluation_status": "evaluated" if comparisons else "no_comparable_stats",
            "affects_1x2": False,
        })

    return observations, {
        "status": "ok",
        "truth_matches": len(truth.get("matches") or {}),
        "dashboard_matches": len(matches or []),
        "observations": len(observations),
        "missing_dashboard": missing_dashboard,
        "ambiguous_dashboard": ambiguous_dashboard,
        "missing_pre_match_snapshot": missing_snapshot,
        "reused_archived_prediction": reused_prediction,
        "truth_usable_by_stat": dict(sorted(truth_usable.items())),
        "evaluated_by_stat": dict(sorted(evaluated.items())),
        "affects_1x2": False,
    }


def empty_archive() -> dict:
    return {
        "schema": SCHEMA,
        "updated_at": None,
        "records": {},
        "summary": {},
        "last_run_audit": {},
        "affects_1x2": False,
    }


def load_archive(path: str | Path = DEFAULT_OUTPUT) -> dict:
    target = Path(path)
    if not target.exists():
        return empty_archive()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_archive()
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA or not isinstance(raw.get("records"), dict):
        return empty_archive()
    raw.setdefault("summary", {})
    raw.setdefault("last_run_audit", {})
    raw["affects_1x2"] = False
    return raw


def _observation_digest(observation: dict) -> str:
    semantic = {
        key: observation.get(key)
        for key in (
            "match_id", "league", "season", "date", "home", "away",
            "snapshot_at", "snapshot_window", "model_version", "prediction",
            "truth_digest", "truth_match_status", "stats", "evaluation_status",
        )
    }
    return hashlib.sha256(
        json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _sample_stage(n: int) -> str:
    if n >= EVALUATION_READY_SAMPLE:
        return "evaluation_ready"
    if n >= MONITORING_SAMPLE:
        return "monitoring"
    return "insufficient_sample"


def _metrics(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    errors = {key: [float(row["error"][key]) for row in rows] for key in ("home", "away", "total")}
    absolute = {key: [abs(value) for value in errors[key]] for key in errors}
    n = len(rows)
    status_counts = Counter(str(row.get("truth_status") or "unknown") for row in rows)
    source_counts = Counter(
        "+".join(row.get("truth_sources") or []) or "unknown"
        for row in rows
    )
    return {
        "n": n,
        "sample_stage": _sample_stage(n),
        "mae": {key: round(sum(absolute[key]) / n, 4) for key in absolute},
        "bias_predicted_minus_actual": {key: round(sum(errors[key]) / n, 4) for key in errors},
        "rmse_total": round(math.sqrt(sum(value * value for value in errors["total"]) / n), 4),
        "median_absolute_error_total": round(statistics.median(absolute["total"]), 4),
        "truth_statuses": dict(sorted(status_counts.items())),
        "source_mix": dict(sorted(source_counts.items())),
    }


def _summary(records: dict[str, dict]) -> dict:
    latest = [
        row.get("latest")
        for row in records.values()
        if isinstance(row, dict) and isinstance(row.get("latest"), dict)
    ]
    by_stat: dict[str, list[dict]] = defaultdict(list)
    by_league: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    by_window: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    model_versions = Counter()
    truth_match_statuses = Counter()
    stat_observations = 0

    for observation in latest:
        league = str(observation.get("league") or "unknown")
        window = str(observation.get("snapshot_window") or "unknown")
        model_versions[str(observation.get("model_version") or "unknown")] += 1
        truth_match_statuses[str(observation.get("truth_match_status") or "unknown")] += 1
        for stat, row in (observation.get("stats") or {}).items():
            if stat not in STAT_KEYS or not isinstance(row, dict):
                continue
            by_stat[stat].append(row)
            by_league[league][stat].append(row)
            by_window[window][stat].append(row)
            stat_observations += 1

    return {
        "evaluated_matches": sum(1 for row in latest if row.get("stats")),
        "archived_matches": len(latest),
        "stat_observations": stat_observations,
        "by_stat": {
            stat: metrics
            for stat in STAT_KEYS
            if (metrics := _metrics(by_stat.get(stat, []))) is not None
        },
        "by_league": {
            league: {
                stat: metrics
                for stat in STAT_KEYS
                if (metrics := _metrics(stat_rows.get(stat, []))) is not None
            }
            for league, stat_rows in sorted(by_league.items())
        },
        "by_snapshot_window": {
            window: {
                stat: metrics
                for stat in STAT_KEYS
                if (metrics := _metrics(stat_rows.get(stat, []))) is not None
            }
            for window, stat_rows in sorted(by_window.items())
        },
        "model_versions": dict(sorted(model_versions.items())),
        "truth_match_statuses": dict(sorted(truth_match_statuses.items())),
        "promotion_policy": {
            "status": "evaluation_only",
            "minimum_monitoring_sample": MONITORING_SAMPLE,
            "minimum_evaluation_ready_sample": EVALUATION_READY_SAMPLE,
            "automatic_production_promotion": False,
        },
        "affects_1x2": False,
    }


def update_archive(
    archive: dict,
    observations: list[dict],
    *,
    updated_at: str,
    run_audit: dict | None = None,
) -> tuple[dict, dict]:
    out = deepcopy(archive if archive.get("schema") == SCHEMA else empty_archive())
    records = out.setdefault("records", {})
    added_revisions = 0
    unchanged = 0

    for observation in observations or []:
        match_id = str(observation.get("match_id") or "")
        if not match_id:
            continue
        record = records.setdefault(match_id, {"latest": None, "history": []})
        digest = _observation_digest(observation)
        known = {
            _observation_digest(row)
            for row in (record.get("history") or [])
            if isinstance(row, dict)
        }
        if digest in known:
            unchanged += 1
            continue
        record.setdefault("history", []).append(deepcopy(observation))
        record["latest"] = deepcopy(observation)
        added_revisions += 1

    out["summary"] = _summary(records)
    out["last_run_audit"] = deepcopy(run_audit or {})
    if added_revisions:
        out["updated_at"] = updated_at
    out["affects_1x2"] = False
    return out, {
        "added_revisions": added_revisions,
        "unchanged_observations": unchanged,
        **out["summary"],
        "affects_1x2": False,
    }


def write_archive(path: str | Path, archive: dict) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(archive, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def refresh_truth_evaluation(
    dashboard_path: str | Path = DEFAULT_DASHBOARD,
    truth_path: str | Path = DEFAULT_TRUTH,
    output_path: str | Path = DEFAULT_OUTPUT,
    *,
    generated_at: str | None = None,
) -> dict:
    stamp = generated_at or datetime.now(timezone.utc).isoformat()
    dashboard_target, truth_target = Path(dashboard_path), Path(truth_path)
    if not truth_target.exists():
        return {"status": "truth_unavailable", "affects_1x2": False}
    if not dashboard_target.exists():
        return {"status": "dashboard_unavailable", "affects_1x2": False}
    try:
        truth = json.loads(truth_target.read_text(encoding="utf-8"))
        dashboard = json.loads(dashboard_target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "input_invalid", "affects_1x2": False}
    if truth.get("schema") != TRUTH_SCHEMA:
        return {"status": "truth_schema_invalid", "affects_1x2": False}

    previous = load_archive(output_path)
    matches = [row for row in (dashboard.get("matches") or []) if isinstance(row, dict)]
    observations, audit = build_observations(matches, truth, previous_archive=previous)
    updated, summary = update_archive(
        previous,
        observations,
        updated_at=stamp,
        run_audit=audit,
    )
    if summary["added_revisions"]:
        write_archive(output_path, updated)
        status = "updated"
    elif previous.get("records"):
        status = "no_change"
    else:
        status = "no_evaluable_data"
    return {
        "status": status,
        "output": str(output_path),
        "run_audit": audit,
        **summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evalúa snapshots prepartido contra final_stats_truth")
    parser.add_argument("--dashboard", default=str(DEFAULT_DASHBOARD))
    parser.add_argument("--truth", default=str(DEFAULT_TRUTH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)
    report = refresh_truth_evaluation(args.dashboard, args.truth, args.output)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
