"""Leakage-safe historical feature store for Fútbol Edge.

The store records immutable source observations instead of overwriting the
latest value. Training code can therefore reconstruct exactly what was known at
an arbitrary historical ``as_of`` timestamp.

SQLite is used deliberately for the first production contract: it is in the
standard library, deterministic in CI/Colab and can later be exported to
Parquet/DuckDB without changing the observation schema.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from .data_contract import enrich_feed_contract, iso_utc, source_observation

STORE_SCHEMA_VERSION = 1
VALID_PHASES = {"prematch", "live", "postmatch"}


class HistoricalFeatureStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS matches (
                    match_uid TEXT PRIMARY KEY,
                    league TEXT NOT NULL,
                    season INTEGER NOT NULL,
                    kickoff TEXT NOT NULL,
                    home_team TEXT NOT NULL,
                    away_team TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_uid TEXT NOT NULL,
                    feature TEXT NOT NULL,
                    entity TEXT NOT NULL DEFAULT 'match',
                    value_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_id TEXT NOT NULL DEFAULT '',
                    available_at TEXT NOT NULL,
                    observed_at TEXT,
                    phase TEXT NOT NULL,
                    quality TEXT NOT NULL,
                    ingested_at TEXT NOT NULL,
                    FOREIGN KEY(match_uid) REFERENCES matches(match_uid) ON DELETE CASCADE,
                    UNIQUE(match_uid, feature, entity, source, source_id, available_at)
                );

                CREATE INDEX IF NOT EXISTS idx_observation_snapshot
                    ON observations(match_uid, feature, entity, available_at);
                CREATE INDEX IF NOT EXISTS idx_observation_available
                    ON observations(available_at, phase);
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(STORE_SCHEMA_VERSION),),
            )

    def upsert_match(
        self,
        *,
        match_uid: str,
        league: str,
        season: int,
        kickoff: datetime | str,
        home_team: str,
        away_team: str,
        updated_at: datetime | str | None = None,
    ) -> None:
        stamp = iso_utc(updated_at or datetime.now(timezone.utc))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO matches(match_uid, league, season, kickoff, home_team, away_team, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(match_uid) DO UPDATE SET
                    league=excluded.league,
                    season=excluded.season,
                    kickoff=excluded.kickoff,
                    home_team=excluded.home_team,
                    away_team=excluded.away_team,
                    updated_at=excluded.updated_at
                """,
                (
                    match_uid,
                    league,
                    int(season),
                    iso_utc(kickoff),
                    home_team,
                    away_team,
                    stamp,
                ),
            )

    def append_observation(
        self,
        *,
        match_uid: str,
        feature: str,
        value,
        source: str,
        available_at: datetime | str,
        entity: str = "match",
        source_id: object | None = None,
        phase: str = "prematch",
        quality: str = "observed",
        observed_at: datetime | str | None = None,
    ) -> bool:
        if not feature or not entity:
            raise ValueError("feature and entity are required")
        provenance = source_observation(
            source=source,
            source_id=source_id,
            available_at=available_at,
            phase=phase,
            quality=quality,
            observed_at=observed_at,
        )
        ingested_at = iso_utc(datetime.now(timezone.utc))
        serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO observations(
                    match_uid, feature, entity, value_json, source, source_id,
                    available_at, observed_at, phase, quality, ingested_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_uid,
                    feature,
                    entity,
                    serialized,
                    provenance["source"],
                    provenance.get("source_id") or "",
                    provenance["available_at"],
                    provenance.get("observed_at"),
                    provenance["phase"],
                    provenance["quality"],
                    ingested_at,
                ),
            )
            return cursor.rowcount > 0

    def snapshot_as_of(
        self,
        match_uid: str,
        as_of: datetime | str,
        *,
        phases: Iterable[str] = ("prematch",),
        features: Iterable[str] | None = None,
    ) -> dict[tuple[str, str], dict]:
        """Return the latest causally available observation per feature/entity."""
        allowed_phases = tuple(dict.fromkeys(str(phase) for phase in phases))
        if not allowed_phases or any(phase not in VALID_PHASES for phase in allowed_phases):
            raise ValueError("invalid phases")
        params: list[object] = [match_uid, iso_utc(as_of), *allowed_phases]
        where = [
            "match_uid = ?",
            "available_at <= ?",
            f"phase IN ({','.join('?' for _ in allowed_phases)})",
        ]
        selected_features = tuple(dict.fromkeys(str(feature) for feature in (features or ()) if feature))
        if selected_features:
            where.append(f"feature IN ({','.join('?' for _ in selected_features)})")
            params.extend(selected_features)
        query = f"""
            SELECT feature, entity, value_json, source, source_id, available_at,
                   observed_at, phase, quality
            FROM observations
            WHERE {' AND '.join(where)}
            ORDER BY available_at DESC, id DESC
        """
        out: dict[tuple[str, str], dict] = {}
        with self._connect() as conn:
            for row in conn.execute(query, params):
                key = (row["feature"], row["entity"])
                if key in out:
                    continue
                out[key] = {
                    "value": json.loads(row["value_json"]),
                    "source": row["source"],
                    "source_id": row["source_id"] or None,
                    "available_at": row["available_at"],
                    "observed_at": row["observed_at"],
                    "phase": row["phase"],
                    "quality": row["quality"],
                }
        return out

    def observation_count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0])

    def archive_feed(self, payload: dict) -> dict[str, int]:
        """Archive provenance-backed final facts from a dashboard payload.

        At this stage we intentionally persist only fields with a defensible
        availability timestamp: final result and final ``statsReal``. Prematch
        odds/weather/lineups will join this path once each adapter exposes its
        own source timestamp instead of a generic feed-generation time.
        """
        enrich_feed_contract(payload)
        season = int(payload.get("season"))
        generated_at = payload.get("generated_at") or datetime.now(timezone.utc)
        counts = {"matches": 0, "observations": 0}
        for match in payload.get("matches") or []:
            if not isinstance(match, dict) or not match.get("match_uid"):
                continue
            match_uid = str(match["match_uid"])
            self.upsert_match(
                match_uid=match_uid,
                league=str(match.get("league") or ""),
                season=season,
                kickoff=str(match.get("kickoff")),
                home_team=str(match.get("home") or ""),
                away_team=str(match.get("away") or ""),
                updated_at=match.get("updatedAt") or generated_at,
            )
            counts["matches"] += 1

            provenance = match.get("provenance") or {}
            result_provenance = provenance.get("result") or provenance.get("fixture") or {}
            if match.get("finished") and isinstance(match.get("result"), list):
                if self.append_observation(
                    match_uid=match_uid,
                    feature="result.score",
                    value=match["result"],
                    source=result_provenance.get("source") or match.get("source") or "legacy-feed",
                    source_id=result_provenance.get("source_id"),
                    available_at=result_provenance.get("available_at") or generated_at,
                    observed_at=result_provenance.get("observed_at"),
                    phase="postmatch",
                    quality=result_provenance.get("quality") or "observed",
                ):
                    counts["observations"] += 1

            real_stats = match.get("statsReal")
            if not isinstance(real_stats, dict):
                continue
            stats_available = match.get("statsRealUpdatedAt") or generated_at
            stats_source = match.get("statsRealSource") or "historical-stats"
            for metric, values in real_stats.items():
                if not isinstance(values, dict):
                    continue
                for entity in ("home", "away", "total"):
                    if entity not in values:
                        continue
                    if self.append_observation(
                        match_uid=match_uid,
                        feature=f"stats.{metric}",
                        entity=entity,
                        value=values[entity],
                        source=stats_source,
                        source_id=None,
                        available_at=stats_available,
                        observed_at=stats_available,
                        phase="postmatch",
                        quality="verified",
                    ):
                        counts["observations"] += 1
        return counts
