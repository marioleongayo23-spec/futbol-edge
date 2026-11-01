"""Read-only audit of published football prediction snapshots.

This command never calls APIs or modifies the feed. It evaluates historical
predictions strictly before kickoff and reports only aggregate statistics.
Run: python -m futbol_pred.feed_audit football/data/dashboard.json
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import math
import random
from pathlib import Path
import sys

from .backtest.metrics import aggregate, rps
from .prediction_snapshots import latest_pre_match_snapshot, _parse

SIGNS = ("1", "X", "2")
UNIFORM = {key: 1.0 / 3 for key in SIGNS}


def _probs(values) -> dict[str, float] | None:
    """Reject invalid/non-finite vectors, rather than laundering them by normalization."""
    if isinstance(values, list) and len(values) == 3:
        raw = dict(zip(SIGNS, values))
        scale = 100
    elif isinstance(values, dict) and all(key in values for key in SIGNS):
        raw = {key: values[key] for key in SIGNS}
        scale = 1
    else:
        return None
    if any(isinstance(x, bool) or not isinstance(x, (int, float))
           or not math.isfinite(x) or x < 0 or x > scale for x in raw.values()):
        return None
    total = sum(raw.values()) / scale
    if not 0.98 <= total <= 1.02:
        return None
    return {key: raw[key] / (scale * total) for key in SIGNS}


def _outcome(match: dict) -> str | None:
    result = match.get("result")
    if (not match.get("finished") or not isinstance(result, list) or len(result) != 2
            or any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in result)):
        return None
    return "1" if result[0] > result[1] else "2" if result[0] < result[1] else "X"


def _metrics(rows: list[tuple[dict, str]]) -> dict | None:
    if not rows:
        return None
    a = aggregate(rows)
    return {
        "n": a["n"],
        "log_loss": round(a["log_loss"], 4),
        "brier": round(a["brier"], 4),
        "rps": round(a["rps"], 4),
        "accuracy_pct": round(a["accuracy"] * 100, 1),
    }


def _block_bootstrap(paired: list[tuple[str, dict, dict, str]]) -> dict | None:
    """95% descriptive uncertainty for a paired delta, resampling match days.

    This is NOT out-of-sample evaluation and never authorizes promotion.
    """
    if len(paired) < 30:
        return None
    days = defaultdict(list)
    for day, candidate, baseline, actual in paired:
        diff_loss = math.log(max(1e-12, baseline[actual])) - math.log(max(1e-12, candidate[actual]))
        diff_rps = rps(candidate, actual) - rps(baseline, actual)
        days[day].append((diff_loss, diff_rps))
    keys = sorted(days)
    if len(keys) < 8:
        return None
    rng = random.Random(20261101)
    draws_loss, draws_rps = [], []
    for _ in range(1200):
        sampled = [v for day in (keys[rng.randrange(len(keys))] for _ in keys) for v in days[day]]
        n = len(sampled)
        draws_loss.append(sum(v[0] for v in sampled) / n)
        draws_rps.append(sum(v[1] for v in sampled) / n)
    def bounds(values):
        ordered = sorted(values)
        return [round(ordered[int(.025 * (len(ordered)-1))], 4),
                round(ordered[int(.975 * (len(ordered)-1))], 4)]
    return {"method": "paired_day_block_bootstrap_descriptive",
            "n_days": len(keys), "resamples": 1200,
            "delta_log_loss_ci95": bounds(draws_loss),
            "delta_rps_ci95": bounds(draws_rps)}


def _snapshot_gap_reason(match: dict) -> str:
    """Reason for absent historical evidence; do not reconstruct predictions."""
    kickoff = _parse(match.get("kickoff"))
    if kickoff is None:
        return "kickoff_missing_or_invalid"
    items = [
        *(item for item in (match.get("prediction_history") or []) if isinstance(item, dict)),
        *([match["prediction_snapshot"]] if isinstance(match.get("prediction_snapshot"), dict) else []),
    ]
    if not items:
        return "no_snapshots_preserved"
    dated = [(_parse(item.get("generated_at")), item) for item in items]
    valid = [(when, item) for when, item in dated if when is not None]
    if not valid:
        return "capture_timestamps_missing_or_invalid"
    pre = [item for when, item in valid if when < kickoff]
    if not pre:
        return "captured_only_after_kickoff"
    if not any(_probs(item.get("probs")) for item in pre):
        return "pre_kickoff_probs_invalid"
    return "other"


def _bucket():
    return {
        "matches": 0, "finished": 0, "finished_with_snapshot": 0,
        "finished_without_valid_snapshot": 0,
        "missing_snapshot_reasons": defaultdict(int),
        "upcoming_48h": 0,
        "upcoming_48h_without_snapshot": 0,
        "future_with_valid_prediction": 0,
        "published": [], "model": [], "market": [], "uniform": [],
        "published_model": [], "paired_model": [],
        "published_market": [], "paired_market": [],
        "paired_model_records": [], "paired_market_records": [],
    }


def audit_payload(payload: dict) -> dict:
    """A descriptive audit, NOT a statistical claim of model superiority."""
    if not isinstance(payload, dict) or not isinstance(payload.get("matches"), list):
        return {"status": "invalid_feed", "reason": "matches must be a list"}
    groups = defaultdict(_bucket)
    observed_at = _parse(payload.get("generated_at"))
    for match in payload["matches"]:
        if not isinstance(match, dict):
            continue
        league = str(match.get("league") or "Sin competición")
        group = groups[league]
        group["matches"] += 1
        outcome = _outcome(match)
        if outcome is None:
            if not match.get("finished"):
                if _probs(match.get("probs")):
                    group["future_with_valid_prediction"] += 1
                kickoff = _parse(match.get("kickoff"))
                if observed_at is not None and kickoff is not None:
                    hours_to = (kickoff - observed_at).total_seconds() / 3600
                    if 0 < hours_to <= 48:
                        group["upcoming_48h"] += 1
                        if not _probs((latest_pre_match_snapshot(match) or {}).get("probs")):
                            group["upcoming_48h_without_snapshot"] += 1
            continue
        group["finished"] += 1
        snapshot = latest_pre_match_snapshot(match)
        published = _probs((snapshot or {}).get("probs"))
        if not published:
            group["finished_without_valid_snapshot"] += 1
            group["missing_snapshot_reasons"][_snapshot_gap_reason(match)] += 1
            continue
        group["finished_with_snapshot"] += 1
        group["published"].append((published, outcome))
        group["uniform"].append((UNIFORM, outcome))

        model = _probs(snapshot.get("model_probs"))
        if model:
            group["model"].append((model, outcome))
            group["published_model"].append((published, outcome))
            group["paired_model"].append((model, outcome))
            group["paired_model_records"].append((str(match.get("kickoff"))[:10], published, model, outcome))

        odds = snapshot.get("odds")
        market_fair = (odds.get("1x2") or {}).get("fair") if isinstance(odds, dict) and isinstance(odds.get("1x2"), dict) else None
        market = _probs(market_fair)
        if market:
            group["market"].append((market, outcome))
            group["published_market"].append((published, outcome))
            group["paired_market"].append((market, outcome))
            group["paired_market_records"].append((str(match.get("kickoff"))[:10], published, market, outcome))

    out = {}
    for league, group in sorted(groups.items()):
        report = {key: group[key] for key in (
            "matches", "finished", "finished_with_snapshot",
            "finished_without_valid_snapshot", "future_with_valid_prediction",
            "upcoming_48h", "upcoming_48h_without_snapshot",
        )}
        report["missing_snapshot_reasons"] = dict(sorted(group["missing_snapshot_reasons"].items()))
        report["probability_quality"] = {key: _metrics(group[key]) for key in ("published", "model", "market", "uniform")}
        for label, lhs, rhs in (
            ("published_vs_model_paired", "published_model", "paired_model"),
            ("published_vs_market_paired", "published_market", "paired_market"),
        ):
            left, right = _metrics(group[lhs]), _metrics(group[rhs])
            report[label] = {
                "n": left["n"],
                "published": left,
                "reference": right,
                "delta_log_loss": round(left["log_loss"] - right["log_loss"], 4),
                "delta_rps": round(left["rps"] - right["rps"], 4),
                "better_both": left["log_loss"] < right["log_loss"] and left["rps"] < right["rps"],
                "preliminary": left["n"] < 30,
                "uncertainty": _block_bootstrap(group["paired_model_records" if label == "published_vs_model_paired" else "paired_market_records"]),
            } if left and right else None
        out[league] = report
    return {
        "status": "ok", "generated_at": payload.get("generated_at"),
        "season": payload.get("season"), "schema_version": payload.get("schema_version"),
        "total_matches": len(payload["matches"]),
        "leagues": out,
        "limitations": "Snapshots prepartido del dashboard, no holdout ni prueba de edge. Comparaciones emparejadas; CI por fecha describe incertidumbre y no demuestra causalidad. ROI requiere cuotas reales fechadas.",
    }


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/dashboard.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        print("EDGE_FEED_AUDIT_JSON=" + json.dumps({"status": "unreadable", "error": type(exc).__name__}))
        return 0  # Observability step should not mask the existing strict feed guard.
    report = audit_payload(payload)
    print("EDGE_FEED_AUDIT_JSON=" + json.dumps(report, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
