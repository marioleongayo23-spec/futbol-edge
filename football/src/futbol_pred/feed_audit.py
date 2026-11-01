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
from pathlib import Path
import sys

from .backtest.metrics import aggregate
from .prediction_snapshots import latest_pre_match_snapshot

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


def _bucket():
    return {
        "matches": 0, "finished": 0, "finished_with_snapshot": 0,
        "finished_without_valid_snapshot": 0,
        "future_with_valid_prediction": 0,
        "published": [], "model": [], "market": [], "uniform": [],
        "published_model": [], "paired_model": [],
        "published_market": [], "paired_market": [],
    }


def audit_payload(payload: dict) -> dict:
    """A descriptive audit, NOT a statistical claim of model superiority."""
    if not isinstance(payload, dict) or not isinstance(payload.get("matches"), list):
        return {"status": "invalid_feed", "reason": "matches must be a list"}
    groups = defaultdict(_bucket)
    for match in payload["matches"]:
        if not isinstance(match, dict):
            continue
        league = str(match.get("league") or "Sin competición")
        group = groups[league]
        group["matches"] += 1
        outcome = _outcome(match)
        if outcome is None:
            if not match.get("finished") and _probs(match.get("probs")):
                group["future_with_valid_prediction"] += 1
            continue
        group["finished"] += 1
        snapshot = latest_pre_match_snapshot(match)
        published = _probs((snapshot or {}).get("probs"))
        if not published:
            group["finished_without_valid_snapshot"] += 1
            continue
        group["finished_with_snapshot"] += 1
        group["published"].append((published, outcome))
        group["uniform"].append((UNIFORM, outcome))

        model = _probs(snapshot.get("model_probs"))
        if model:
            group["model"].append((model, outcome))
            group["published_model"].append((published, outcome))
            group["paired_model"].append((model, outcome))

        odds = snapshot.get("odds")
        market_fair = (odds.get("1x2") or {}).get("fair") if isinstance(odds, dict) and isinstance(odds.get("1x2"), dict) else None
        market = _probs(market_fair)
        if market:
            group["market"].append((market, outcome))
            group["published_market"].append((published, outcome))
            group["paired_market"].append((market, outcome))

    out = {}
    for league, group in sorted(groups.items()):
        report = {key: group[key] for key in (
            "matches", "finished", "finished_with_snapshot",
            "finished_without_valid_snapshot", "future_with_valid_prediction"
        )}
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
            } if left and right else None
        out[league] = report
    return {
        "status": "ok", "generated_at": payload.get("generated_at"),
        "season": payload.get("season"), "schema_version": payload.get("schema_version"),
        "total_matches": len(payload["matches"]),
        "leagues": out,
        "limitations": "Snapshots prepartido del dashboard, no holdout ni prueba de edge. Comparaciones emparejadas; n<30 preliminar. ROI requiere cuotas reales fechadas.",
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
