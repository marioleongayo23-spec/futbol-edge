"""Explicitly licensed CSV -> immutable SQLite observations, shadow only.

The input is an export from the Apps Script OpenFootball collector. No crawler,
paid-data proxy or automatic production model injection is included.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path

from .feature_store import HistoricalFeatureStore

REQUIRED = (
    "record_id", "match_uid", "league", "season", "kickoff", "kickoff_precision",
    "home", "away", "feature", "value_json", "source", "source_url",
    "license", "available_at", "phase", "quality",
)
ALLOWED_SOURCE = "openfootball"
ALLOWED_LICENSE = "CC0-1.0"
ALLOWED_PREFIX = "https://raw.githubusercontent.com/openfootball/football.json/"
ALLOWED_FEATURE = "result.score"
MAX_ROWS = 25000


def _utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp missing")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if stamp.tzinfo is None:
        raise ValueError("naive timestamp")
    return stamp.astimezone(timezone.utc)


def parse_rows(path: str | Path, *, now: datetime | None = None) -> list[dict]:
    """Validate every input row *before* allowing writes to the feature store."""
    now = now or datetime.now(timezone.utc)
    rows: list[dict] = []
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not set(REQUIRED).issubset(reader.fieldnames):
            raise ValueError("required bridge columns missing")
        for idx, row in enumerate(reader, start=2):
            if len(rows) >= MAX_ROWS:
                raise ValueError("bridge batch too large")
            if not row or any(not row.get(key) for key in REQUIRED):
                raise ValueError(f"missing field at row {idx}")
            if row["source"] != ALLOWED_SOURCE or row["license"] != ALLOWED_LICENSE:
                raise ValueError(f"source/license not allowlisted at row {idx}")
            if not row["source_url"].startswith(ALLOWED_PREFIX):
                raise ValueError(f"unapproved origin at row {idx}")
            if row["feature"] != ALLOWED_FEATURE or row["phase"] != "postmatch":
                raise ValueError(f"unexpected feature/phase at row {idx}")
            # Date-only schedules are not valid pre-match kickoff times. We can
            # archive scores, but cannot use these timestamps to train as-of.
            if row["kickoff_precision"] not in ("date_only", "minute"):
                raise ValueError(f"unknown kickoff precision at row {idx}")
            if row["quality"] not in ("observed_date_only", "observed"):
                raise ValueError(f"invalid quality at row {idx}")
            if not row["match_uid"].startswith("openfootball:"):
                raise ValueError(f"invalid match_uid at row {idx}")
            available = _utc(row["available_at"])
            kickoff = _utc(row["kickoff"])
            if available > now + timedelta(minutes=5):
                raise ValueError(f"observation from the future at row {idx}")
            if available < kickoff and row["kickoff_precision"] == "minute":
                raise ValueError(f"result predates kickoff at row {idx}")
            try:
                values = json.loads(row["value_json"])
                season = int(row["season"])
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid value/year at row {idx}") from exc
            if (not isinstance(values, list) or len(values) != 2
                    or any(type(goal) is not int or not 0 <= goal <= 30 for goal in values)
                    or not 1990 <= season <= 2100):
                raise ValueError(f"invalid score/season at row {idx}")
            rows.append({
                "match_uid": row["match_uid"], "league": row["league"],
                "season": season, "kickoff": kickoff.isoformat(),
                "home_team": row["home"], "away_team": row["away"],
                "feature": row["feature"], "value": values,
                "source": row["source"], "source_id": row["record_id"],
                "available_at": available.isoformat(), "phase": "postmatch",
                "quality": row["quality"],
            })
    return rows


def import_csv(path: str | Path, db_path: str | Path) -> dict:
    parsed = parse_rows(path)
    store = HistoricalFeatureStore(db_path)
    inserted = 0
    match_ids = set()
    for row in parsed:
        store.upsert_match(
            match_uid=row["match_uid"], league=row["league"],
            season=row["season"], kickoff=row["kickoff"],
            home_team=row["home_team"], away_team=row["away_team"],
            updated_at=row["available_at"],
        )
        match_ids.add(row["match_uid"])
        inserted += int(store.append_observation(
            match_uid=row["match_uid"], feature=row["feature"],
            value=row["value"], source=row["source"],
            source_id=row["source_id"], available_at=row["available_at"],
            phase=row["phase"], quality=row["quality"],
        ))
    return {
        "rows_checked": len(parsed), "matches": len(match_ids),
        "observations_added": inserted,
        "promotion": "disabled", "source": ALLOWED_SOURCE,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import lawful OpenFootball sheet CSV into shadow SQLite store")
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("sqlite_file", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(import_csv(args.csv_file, args.sqlite_file), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
