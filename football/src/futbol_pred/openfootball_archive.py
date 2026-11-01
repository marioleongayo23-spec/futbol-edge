"""Public-domain OpenFootball -> append-only observation CSV (no token/API).

An optional daily GitHub Action archives *changes*, not repeated snapshots.
CSV can be imported into HistoricalFeatureStore SQLite via open_data_bridge.
No current odds, fake xG, private web pages or pre-match recommendations.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .open_data_bridge import REQUIRED, parse_rows

ORIGIN = "https://raw.githubusercontent.com/openfootball/football.json/master"
DIVISIONS = (("es.1.json", "laliga", "es1"), ("es.2.json", "segunda", "es2"))
MADRID = ZoneInfo("Europe/Madrid")


def _slug(value: str) -> str:
    chars = unicodedata.normalize("NFD", str(value or ""))
    chars = "".join(ch for ch in chars if not unicodedata.combining(ch))
    return re.sub(r"(^-+|-+$)", "", re.sub(r"[^a-z0-9]+", "-", chars.lower()))


def season_slug(year: int) -> str:
    return f"{year}-{(year + 1) % 100:02d}"


def source_urls(season: int, seasons_back: int = 1) -> list[tuple[str, str, str, int]]:
    if not 1990 <= season <= 2100 or not 0 <= seasons_back <= 4:
        raise ValueError("invalid season range")
    return [
        (f"{ORIGIN}/{season_slug(year)}/{filename}", league, code, year)
        for year in range(season - seasons_back, season + 1)
        for filename, league, code in DIVISIONS
    ]


def _read_json(url: str) -> dict | None:
    request = Request(url, headers={"Accept": "application/json",
                                    "User-Agent": "FutbolEdge-OpenData-CC0/1.0"})
    try:
        with urlopen(request, timeout=20) as resp:
            payload = json.load(resp)
    except HTTPError as err:
        if err.code == 404:
            return None
        raise
    if not isinstance(payload, dict) or not isinstance(payload.get("matches"), list):
        raise ValueError("unexpected OpenFootball JSON schema")
    return payload


def _observation(match: dict, league: str, code: str, year: int,
                 url: str, observed_at: str) -> dict | None:
    if not isinstance(match, dict):
        return None
    date = match.get("date")
    if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return None
    try:
        datetime.fromisoformat(date)
    except ValueError:
        return None
    home, away = str(match.get("team1") or "").strip(), str(match.get("team2") or "").strip()
    if not home or not away or home == away:
        return None
    raw_score = match.get("score")
    score = raw_score.get("ft") if isinstance(raw_score, dict) else raw_score
    if (not isinstance(score, list) or len(score) != 2 or
            any(type(v) is not int or not 0 <= v <= 30 for v in score)):
        return None
    uid = f"openfootball:{code}:{year}:{_slug(home)}:{_slug(away)}"
    value_json = json.dumps(score, separators=(",", ":"))
    revision = f"{date}|{uid}|{value_json}"
    return {
        "record_id": "of-" + hashlib.sha256(revision.encode("utf-8")).hexdigest()[:20],
        "match_uid": uid,
        "league": league, "season": str(year),
        # Provider typically supplies date only; NEVER call this exact kickoff.
        "kickoff": date + "T00:00:00Z", "kickoff_precision": "date_only",
        "home": home, "away": away, "feature": "result.score",
        "value_json": value_json, "source": "openfootball",
        "source_url": url, "license": "CC0-1.0",
        "available_at": observed_at, "phase": "postmatch",
        "quality": "observed_date_only",
    }


def collect_rows(season: int, *, seasons_back: int = 1,
                 observed_at: str | None = None, fetch=_read_json) -> list[dict]:
    observed_at = observed_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    seen: set[str] = set()
    for url, league, code, year in source_urls(season, seasons_back):
        payload = fetch(url)
        if payload is None:
            continue
        matches = payload.get("matches")
        if not isinstance(matches, list):
            raise ValueError("unexpected OpenFootball payload")
        for match in matches:
            row = _observation(match, league, code, year, url, observed_at)
            if row is not None and row["record_id"] not in seen:
                rows.append(row)
                seen.add(row["record_id"])
    return rows


def update_csv(path: str | Path, fresh: list[dict]) -> dict:
    target = Path(path)
    existing: list[dict] = []
    if target.is_file():
        # Existing CSV is subject to the exact same strict source/license gate.
        parse_rows(target)
        with target.open(encoding="utf-8-sig", newline="") as stream:
            existing = list(csv.DictReader(stream))
    known = {row["record_id"] for row in existing}
    additions = [row for row in fresh if row["record_id"] not in known]
    if not additions:
        return {"prior": len(existing), "new": 0, "total": len(existing)}
    if len(existing) + len(additions) > 25000:
        raise ValueError("archive exceeds allowed row limit")
    # Ensure every new candidate is strictly validated before any disk change.
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".openfootball-", suffix=".csv", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=REQUIRED, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(existing + additions)
        parse_rows(tmp_name)
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return {"prior": len(existing), "new": len(additions), "total": len(existing) + len(additions)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Archive public-domain football scores as append-only CSV")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--season", type=int)
    parser.add_argument("--seasons-back", type=int, default=1)
    args = parser.parse_args(argv)
    today = datetime.now(MADRID)
    season = args.season if args.season is not None else today.year - (today.month < 7)
    rows = collect_rows(season, seasons_back=args.seasons_back)
    print(json.dumps(update_csv(args.output, rows), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
