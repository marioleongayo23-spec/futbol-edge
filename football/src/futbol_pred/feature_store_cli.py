"""CLI for the leakage-safe historical feature store.

Examples:
    python -m futbol_pred.feature_store_cli archive football/data/dashboard.json /tmp/features.sqlite
    python -m futbol_pred.feature_store_cli snapshot /tmp/features.sqlite <match_uid> 2026-09-10T18:00:00+00:00
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .feature_store import HistoricalFeatureStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fútbol Edge historical feature store")
    sub = parser.add_subparsers(dest="command", required=True)

    archive = sub.add_parser("archive", help="archive provenance-backed facts from dashboard JSON")
    archive.add_argument("dashboard", type=Path)
    archive.add_argument("store", type=Path)

    snapshot = sub.add_parser("snapshot", help="reconstruct latest features available as-of a timestamp")
    snapshot.add_argument("store", type=Path)
    snapshot.add_argument("match_uid")
    snapshot.add_argument("as_of")
    snapshot.add_argument(
        "--phase",
        action="append",
        dest="phases",
        choices=("prematch", "live", "postmatch"),
        help="allowed phase; repeat to include more than one (default: prematch)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "archive":
        payload = json.loads(args.dashboard.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("dashboard must be a JSON object")
        store = HistoricalFeatureStore(args.store)
        print(json.dumps(store.archive_feed(payload), ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "snapshot":
        store = HistoricalFeatureStore(args.store)
        snapshot = store.snapshot_as_of(
            args.match_uid,
            args.as_of,
            phases=tuple(args.phases or ("prematch",)),
        )
        serializable = {
            f"{feature}|{entity}": observation
            for (feature, entity), observation in snapshot.items()
        }
        print(json.dumps(serializable, ensure_ascii=False, sort_keys=True, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
