"""Diagnóstico legible del estado T-2h para GitHub Actions.

No modifica el feed ni expone secretos. Imprime únicamente timestamps, estado de
fuentes, XI, bajas y cobertura de props de los partidos críticos para poder
verificar automáticamente que la app está usando inputs recientes.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

from .config import DATA_DIR
from .feed_quality import load_feed
from .hot_refresh import MADRID, _aware, _parse

OUTPUT = DATA_DIR / "dashboard.json"


def _compact_absences(lineup: dict, side: str):
    out = []
    for row in lineup.get(f"disponibilidad_{side}") or []:
        if not isinstance(row, dict):
            continue
        out.append({
            "jugador": row.get("jugador") or row.get("player") or row.get("name"),
            "estado": row.get("estado") or row.get("status"),
            "official": bool(row.get("official")),
        })
    return out


def critical_snapshot(payload: dict, now: datetime | None = None) -> list[dict]:
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    out = []
    for match in payload.get("matches") or []:
        if not isinstance(match, dict) or match.get("finished"):
            continue
        kickoff = _parse(match.get("kickoff"))
        if not kickoff or kickoff.date() != now_local.date():
            continue
        minutes = (kickoff - now_local).total_seconds() / 60.0
        if not -5 <= minutes <= 120:
            continue
        lineup = match.get("alineacion") if isinstance(match.get("alineacion"), dict) else {}
        checks = match.get("operational_checks") if isinstance(match.get("operational_checks"), dict) else {}
        market = match.get("market_hot_refresh") if isinstance(match.get("market_hot_refresh"), dict) else {}
        weather = match.get("weather") if isinstance(match.get("weather"), dict) else {}
        pred = match.get("prediction_live_refresh") if isinstance(match.get("prediction_live_refresh"), dict) else {}
        odds = match.get("odds")
        out.append({
            "partido": f"{match.get('home')} - {match.get('away')}",
            "kickoff": match.get("kickoff"),
            "minutes_to_kickoff": round(minutes, 1),
            "feed_generated_at": payload.get("generated_at"),
            "weather": {
                "forecast_for": weather.get("forecast_for"),
                "checked_at": checks.get("weather_checked_at") or weather.get("source_updated_at"),
                "temp_c": weather.get("temperature_c"),
                "precipitation_probability_pct": weather.get("precipitation_probability_pct"),
            },
            "lineup": {
                "status": lineup.get("status"),
                "kind": lineup.get("lineup_kind"),
                "source_quality": lineup.get("source_quality"),
                "probable_checked_at": lineup.get("critical_probable_checked_at") or lineup.get("source_updated_at"),
                "official_checked_at": checks.get("lineup_checked_at") or lineup.get("official_poll_at"),
                "local": lineup.get("local") or [],
                "visitante": lineup.get("visitante") or [],
                "integrity_replacements": lineup.get("integrity_replacements") or [],
            },
            "absences": {
                "checked_at": checks.get("absences_checked_at"),
                "local": _compact_absences(lineup, "local"),
                "visitante": _compact_absences(lineup, "visitante"),
            },
            "odds": {
                "available": isinstance(odds, dict) and isinstance(odds.get("1x2"), dict),
                "provider": market.get("provider"),
                "checked_at": market.get("checked_at") or (((odds or {}).get("meta") or {}).get("checked_at") if isinstance(odds, dict) else None),
                "ttl_minutes": market.get("ttl_minutes") or (((odds or {}).get("meta") or {}).get("ttl_minutes") if isinstance(odds, dict) else None),
            },
            "player_props": {
                "checked_at": lineup.get("player_props_checked_at") or checks.get("player_props_checked_at"),
                "real_players": len(lineup.get("clave_local") or []) + len(lineup.get("clave_visitante") or []),
                "source": lineup.get("player_props_source") or lineup.get("numeric_props_source"),
            },
            "prediction": {
                "checked_at": pred.get("checked_at") or ((match.get("prediction_confidence") or {}).get("refreshed_at") if isinstance(match.get("prediction_confidence"), dict) else None),
                "confidence": (match.get("prediction_confidence") or {}).get("score") if isinstance(match.get("prediction_confidence"), dict) else None,
                "recommendation": (match.get("recommendation") or {}).get("decision") if isinstance(match.get("recommendation"), dict) else None,
            },
            "freshness": match.get("matchday_freshness"),
            "api_football_health": ((payload.get("source_health") or {}).get("api_football") or {}),
            "odds_health": ((payload.get("source_health") or {}).get("the_odds_api") or {}),
        })
    return out


def main() -> int:
    payload = load_feed(OUTPUT) or {}
    snapshot = critical_snapshot(payload)
    print("MATCHDAY_DIAGNOSTIC=" + json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
