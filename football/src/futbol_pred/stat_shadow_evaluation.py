"""P3.5: evaluación prospectiva de challengers estadísticos en sombra.

Une snapshots prepartido con ``final_stats_truth`` mediante identidad exacta y
mide cada método shadow contra la verdad final. El resultado es acumulativo y
solo recomienda; nunca modifica producción, mercados, pseudo-xG ni 1X2.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import warnings
from zoneinfo import ZoneInfo

from .final_stats_truth import SCHEMA as TRUTH_SCHEMA
from .normalize import canonical_team
from .prediction_snapshots import latest_pre_match_snapshot
from .stat_shadow import SCHEMA as SHADOW_SCHEMA, SHADOW_METHOD, SHADOW_STATS

MADRID = ZoneInfo("Europe/Madrid")
SCHEMA = "stat-shadow-evaluation-v1"
MIN_PROMOTION_SAMPLE = 80
MIN_TOTAL_MAE_GAIN = 0.05
MIN_SIDE_MAE_GAIN = 0.02
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DASHBOARD = REPO_ROOT / "football" / "data" / "dashboard.json"
DEFAULT_TRUTH = REPO_ROOT / "data-history" / "final_stats_truth.json"
DEFAULT_OUTPUT = REPO_ROOT / "data-history" / "stat_shadow_evaluation.json"

_LEAGUE_MAP = {
    "LaLiga": "laliga",
    "LaLiga Hypermotion": "segunda",
    "Champions League": "champions",
    "laliga": "laliga",
    "segunda": "segunda",
    "champions": "champions",
}


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
    return _LEAGUE_MAP.get(raw, raw.casefold())


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


def _num(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _pair(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    home, away = _num(value.get("home")), _num(value.get("away"))
    if home is None or away is None or home < 0 or away < 0:
        return None
    return {"home": home, "away": away, "total": home + away}


def _comparison(predicted: dict, truth_row: dict) -> dict | None:
    if not isinstance(truth_row, dict) or not truth_row.get("usable"):
        return None
    actual = _pair(truth_row)
    predicted = _pair(predicted)
    if actual is None or predicted is None:
        return None
    error = {key: predicted[key] - actual[key] for key in ("home", "away", "total")}
    return {
        "predicted": {key: round(predicted[key], 6) for key in predicted},
        "actual": {key: round(actual[key], 6) for key in actual},
        "error": {key: round(error[key], 6) for key in error},
        "absolute_error": {key: round(abs(error[key]), 6) for key in error},
        "truth_status": truth_row.get("status"),
        "truth_confidence": truth_row.get("confidence"),
    }


def build_observations(matches: list[dict], truth: dict) -> tuple[list[dict], dict]:
    if not isinstance(truth, dict) or truth.get("schema") != TRUTH_SCHEMA:
        return [], {"status": "truth_schema_invalid", "affects_1x2": False}

    index: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for match in matches or []:
        if not isinstance(match, dict):
            continue
        identity = _match_identity(match)
        if identity:
            index[identity].append(match)

    observations: list[dict] = []
    missing_dashboard = ambiguous_dashboard = missing_snapshot = missing_shadow = 0
    evaluated = 0
    for match_id, entry in sorted((truth.get("matches") or {}).items()):
        if not isinstance(entry, dict):
            continue
        identity = _truth_identity(entry)
        if identity is None:
            continue
        candidates = index.get(identity) or []
        if not candidates:
            missing_dashboard += 1
            continue
        if len(candidates) != 1:
            ambiguous_dashboard += 1
            continue
        snapshot = latest_pre_match_snapshot(candidates[0])
        if not snapshot:
            missing_snapshot += 1
            continue
        shadow = snapshot.get("stat_challengers") or {}
        if shadow.get("schema") != SHADOW_SCHEMA:
            missing_shadow += 1
            continue

        comparisons: dict[str, dict] = {}
        consensus = entry.get("consensus") or {}
        for stat in SHADOW_STATS:
            shadow_stat = ((shadow.get("stats") or {}).get(stat))
            truth_row = consensus.get(stat)
            if not isinstance(shadow_stat, dict) or not isinstance(truth_row, dict):
                continue
            methods: dict[str, dict] = {}
            for method in ("published", SHADOW_METHOD):
                row = _comparison(shadow_stat.get(method), truth_row)
                if row is not None:
                    methods[method] = row
            if methods:
                comparisons[stat] = {
                    "methods": methods,
                    "training": deepcopy(shadow_stat.get("training") or {}),
                }
                evaluated += 1
        if not comparisons:
            continue
        observations.append({
            "match_id": str(match_id),
            "league": entry.get("league"),
            "season": entry.get("season"),
            "date": entry.get("date"),
            "home": entry.get("home"),
            "away": entry.get("away"),
            "snapshot_at": snapshot.get("generated_at"),
            "snapshot_window": snapshot.get("window"),
            "model_version": snapshot.get("model_version"),
            "stats": comparisons,
            "affects_production": False,
            "affects_1x2": False,
        })

    return observations, {
        "status": "ok",
        "truth_matches": len(truth.get("matches") or {}),
        "dashboard_matches": len(matches or []),
        "shadow_observations": len(observations),
        "stat_method_comparisons": evaluated,
        "missing_dashboard": missing_dashboard,
        "ambiguous_dashboard": ambiguous_dashboard,
        "missing_pre_match_snapshot": missing_snapshot,
        "missing_shadow_snapshot": missing_shadow,
        "affects_1x2": False,
    }


def empty_archive() -> dict:
    return {
        "schema": SCHEMA,
        "updated_at": None,
        "records": {},
        "summary": {},
        "last_run_audit": {},
        "automatic_production_promotion": False,
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
    raw["automatic_production_promotion"] = False
    raw["affects_1x2"] = False
    return raw


def _digest(row: dict) -> str:
    semantic = {key: row.get(key) for key in (
        "match_id", "league", "season", "date", "home", "away",
        "snapshot_at", "snapshot_window", "model_version", "stats",
    )}
    return hashlib.sha256(
        json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _metrics(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    n = len(rows)
    return {
        "n": n,
        "mae": {
            side: round(sum(float(row["absolute_error"][side]) for row in rows) / n, 4)
            for side in ("home", "away", "total")
        },
        "bias_predicted_minus_actual": {
            side: round(sum(float(row["error"][side]) for row in rows) / n, 4)
            for side in ("home", "away", "total")
        },
    }


def _recommend(methods: dict[str, dict]) -> dict:
    baseline = methods.get("published") or {}
    challenger = methods.get(SHADOW_METHOD) or {}
    n = min(int(baseline.get("n") or 0), int(challenger.get("n") or 0))
    bmae, cmae = baseline.get("mae") or {}, challenger.get("mae") or {}
    bt, ct = _num(bmae.get("total")), _num(cmae.get("total"))
    if bt is None or ct is None or bt <= 0 or n <= 0:
        return {
            "status": "insufficient_comparable_data",
            "recommended": False,
            "automatic_production_promotion": False,
        }
    bside = (_num(bmae.get("home")) or 0.0) + (_num(bmae.get("away")) or 0.0)
    cside = (_num(cmae.get("home")) or 0.0) + (_num(cmae.get("away")) or 0.0)
    total_gain = 1.0 - ct / bt
    side_gain = 1.0 - cside / bside if bside > 0 else 0.0
    ready = n >= MIN_PROMOTION_SAMPLE
    recommended = ready and total_gain >= MIN_TOTAL_MAE_GAIN and side_gain >= MIN_SIDE_MAE_GAIN
    return {
        "status": "recommendation_ready" if ready else "collecting_prospective_sample",
        "recommended": recommended,
        "n": n,
        "challenger": SHADOW_METHOD,
        "total_mae_gain_pct": round(total_gain * 100.0, 2),
        "side_mae_gain_pct": round(side_gain * 100.0, 2),
        "gate": {
            "minimum_n": MIN_PROMOTION_SAMPLE,
            "minimum_total_mae_gain": MIN_TOTAL_MAE_GAIN,
            "minimum_side_mae_gain": MIN_SIDE_MAE_GAIN,
            "prospective_snapshots_only": True,
        },
        "automatic_production_promotion": False,
    }


def _summary(records: dict[str, dict]) -> dict:
    grouped: dict[str, dict[str, dict[str, list[dict]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    latest = []
    for record in records.values():
        row = record.get("latest") if isinstance(record, dict) else None
        if not isinstance(row, dict):
            continue
        latest.append(row)
        league = str(row.get("league") or "unknown")
        for stat, stat_row in (row.get("stats") or {}).items():
            for method, comparison in ((stat_row.get("methods") or {}).items()):
                if isinstance(comparison, dict):
                    grouped[league][stat][method].append(comparison)

    by_league: dict[str, dict] = {}
    recommendations: dict[str, dict] = {}
    for league, stat_map in sorted(grouped.items()):
        by_league[league] = {}
        recommendations[league] = {}
        for stat, method_map in sorted(stat_map.items()):
            methods = {
                method: metrics
                for method, rows in sorted(method_map.items())
                if (metrics := _metrics(rows)) is not None
            }
            by_league[league][stat] = methods
            recommendations[league][stat] = _recommend(methods)

    return {
        "evaluated_matches": len(latest),
        "by_league": by_league,
        "recommendations": recommendations,
        "policy": {
            "prospective_only": True,
            "minimum_promotion_sample": MIN_PROMOTION_SAMPLE,
            "automatic_production_promotion": False,
        },
        "affects_1x2": False,
    }


def update_archive(archive: dict, observations: list[dict], *, updated_at: str, audit: dict) -> tuple[dict, dict]:
    out = deepcopy(archive if archive.get("schema") == SCHEMA else empty_archive())
    records = out.setdefault("records", {})
    added = unchanged = 0
    for observation in observations:
        match_id = str(observation.get("match_id") or "")
        if not match_id:
            continue
        record = records.setdefault(match_id, {"latest": None, "history": []})
        digest = _digest(observation)
        known = {_digest(row) for row in (record.get("history") or []) if isinstance(row, dict)}
        if digest in known:
            unchanged += 1
            continue
        record.setdefault("history", []).append(deepcopy(observation))
        record["latest"] = deepcopy(observation)
        added += 1
    out["summary"] = _summary(records)
    out["last_run_audit"] = deepcopy(audit)
    if added:
        out["updated_at"] = updated_at
    out["automatic_production_promotion"] = False
    out["affects_1x2"] = False
    return out, {
        "added_revisions": added,
        "unchanged_observations": unchanged,
        **out["summary"],
        "automatic_production_promotion": False,
        "affects_1x2": False,
    }


def refresh_shadow_evaluation(
    dashboard_path: str | Path = DEFAULT_DASHBOARD,
    truth_path: str | Path = DEFAULT_TRUTH,
    output_path: str | Path = DEFAULT_OUTPUT,
    *,
    generated_at: str | None = None,
) -> dict:
    stamp = generated_at or datetime.now(timezone.utc).isoformat()
    dashboard_target, truth_target = Path(dashboard_path), Path(truth_path)
    if not dashboard_target.exists() or not truth_target.exists():
        return {"status": "inputs_unavailable", "affects_1x2": False}
    try:
        dashboard = json.loads(dashboard_target.read_text(encoding="utf-8"))
        truth = json.loads(truth_target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "inputs_invalid", "affects_1x2": False}
    matches = [row for row in (dashboard.get("matches") or []) if isinstance(row, dict)]
    observations, audit = build_observations(matches, truth)
    previous = load_archive(output_path)
    updated, summary = update_archive(previous, observations, updated_at=stamp, audit=audit)
    if summary["added_revisions"]:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        status = "updated"
    elif previous.get("records"):
        status = "no_change"
    else:
        status = "no_evaluable_shadow"
    return {"status": status, "output": str(output_path), "audit": audit, **summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evalúa challengers estadísticos shadow contra verdad final")
    parser.add_argument("--dashboard", default=str(DEFAULT_DASHBOARD))
    parser.add_argument("--truth", default=str(DEFAULT_TRUTH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)
    report = refresh_shadow_evaluation(args.dashboard, args.truth, args.output)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
