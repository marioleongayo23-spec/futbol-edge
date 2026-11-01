"""Read-only paired comparison of dynamic strength against published snapshots.

Strictly pre-kickoff snapshots, league-local chronological training, prior-day
embargo and equal matches for both candidates. It CANNOT promote a model.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, time
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .backtest.dynamic_strength import DynamicStrengthPredictor
from .backtest.metrics import aggregate
from .feed_audit import _outcome, _probs, _block_bootstrap
from .prediction_snapshots import latest_pre_match_snapshot, _parse

MADRID = ZoneInfo("Europe/Madrid")


def evaluate_dynamic_shadow(matches: list[dict], league: str) -> dict:
    finished = []
    for match in matches:
        if not isinstance(match, dict) or match.get("league") != league:
            continue
        kickoff = _parse(match.get("kickoff"))
        outcome = _outcome(match)
        if kickoff is None or outcome is None:
            continue
        if match.get("kickoff_precision") == "date_only":
            continue
        result = match["result"]
        finished.append((kickoff, match, result, outcome))
    finished.sort(key=lambda row: row[0])
    candidate_rows: list[tuple[dict, str]] = []
    baseline_rows: list[tuple[dict, str]] = []
    paired: list[tuple[str, dict, dict, str]] = []
    for kickoff, match, result, outcome in finished:
        day = kickoff.astimezone(MADRID).date()
        # Conservative delay: no game from the preceding local calendar day
        # or later is admitted to the training pool.
        cutoff = datetime.combine(day - timedelta(days=1), time.min, tzinfo=MADRID)
        training = [
            {"kickoff": past_kickoff, "home": prev["home"], "away": prev["away"],
             "home_goals": prev_result[0], "away_goals": prev_result[1]}
            for past_kickoff, prev, prev_result, _ in finished if past_kickoff < cutoff
        ]
        if len(training) < 30:
            continue
        snapshot = latest_pre_match_snapshot(match)
        baseline = _probs((snapshot or {}).get("probs"))
        if baseline is None:
            continue
        model = DynamicStrengthPredictor().fit(training, as_of=cutoff)
        challenger = model.predict(match.get("home"), match.get("away"), as_of=cutoff)
        if challenger is None:
            continue
        candidate_rows.append((challenger, outcome))
        baseline_rows.append((baseline, outcome))
        paired.append((day.isoformat(), challenger, baseline, outcome))
    if not paired:
        return {"league": league, "n": 0, "promotion": "disabled",
                "reason": "not enough comparable pre-match evidence"}
    challenger = aggregate(candidate_rows)
    published = aggregate(baseline_rows)
    return {
        "league": league,
        "n": len(paired),
        "days": len({row[0] for row in paired}),
        "shadow": {key: round(value, 5) for key, value in challenger.items()},
        "published": {key: round(value, 5) for key, value in published.items()},
        "delta_shadow_minus_published": {
            key: round(challenger[key] - published[key], 5)
            for key in ("log_loss", "brier", "rps")
        },
        "bootstrap": _block_bootstrap(paired),
        "promotion": "disabled",
        "caveat": "descriptive historical audit, not a pre-registered independent holdout",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate dynamic challenger without changing production")
    parser.add_argument("dashboard", type=Path)
    parser.add_argument("--league", action="append", default=[])
    args = parser.parse_args(argv)
    payload = json.loads(args.dashboard.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("matches"), list):
        raise ValueError("invalid dashboard payload")
    leagues = args.league or sorted({
        str(m.get("league")) for m in payload["matches"] if isinstance(m, dict) and m.get("league")
    })
    report = {league: evaluate_dynamic_shadow(payload["matches"], league) for league in leagues}
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
