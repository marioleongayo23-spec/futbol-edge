"""Trazabilidad operativa de las señales que alimentan Fútbol Edge.

La tabla no decide si una feature se promociona: hace visible qué fuente la
respalda, cuándo estaba disponible, su cobertura, para qué se usa y qué gate
anti-leakage debe superar. Se genera a partir del feed publicado para que la
observabilidad describa producción, no una documentación estática.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from .config import DATA_DIR
from .feed_quality import load_feed, write_feed_safely

OUTPUT = Path(DATA_DIR) / "dashboard.json"


def _nested(row: dict, *path: str):
    value = row
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _stamp(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _latest(values: Iterable[object]) -> str | None:
    parsed = [(dt, str(raw)) for raw in values if (dt := _stamp(raw)) is not None]
    if not parsed:
        return None
    return max(parsed, key=lambda item: item[0])[1]


def _eligible(matches: list[dict]) -> list[dict]:
    """Partidos pre-match con una predicción utilizable."""
    return [
        match for match in matches
        if isinstance(match, dict)
        and not match.get("finished")
        and isinstance(match.get("probs"), list)
        and len(match.get("probs") or []) == 3
    ]


def _coverage(matches: list[dict], predicate: Callable[[dict], bool]) -> dict:
    eligible = _eligible(matches)
    covered = sum(bool(predicate(match)) for match in eligible)
    total = len(eligible)
    return {
        "covered": covered,
        "eligible": total,
        "pct": round(100.0 * covered / total, 1) if total else 0.0,
        "scope": "upcoming_with_prediction",
    }


def _row(
    *,
    feature: str,
    source: str,
    coverage: dict,
    available_at: str | None,
    uses: list[str],
    gate: str,
    leakage_risk: str,
    status: str,
    notes: str,
) -> dict:
    return {
        "feature": feature,
        "source": source,
        "available_at": available_at,
        "coverage": coverage,
        "uses": uses,
        "gate": gate,
        "leakage_risk": leakage_risk,
        "status": status,
        "notes": notes,
    }


def build_feature_truth_table(payload: dict) -> dict:
    matches = [match for match in (payload.get("matches") or []) if isinstance(match, dict)]
    generated_at = payload.get("generated_at")

    market_stamp = _latest(
        value
        for match in matches
        for value in (
            _nested(match, "odds", "meta", "source_updated_at"),
            _nested(match, "odds", "meta", "checked_at"),
            _nested(match, "market_hot_refresh", "source_updated_at"),
            _nested(match, "market_hot_refresh", "captured_at"),
        )
    )
    weather_stamp = _latest(
        value
        for match in matches
        for value in (
            _nested(match, "weather", "source_updated_at"),
            _nested(match, "weather", "forecast_for"),
            _nested(match, "weather_adjustment", "weather_source_updated_at"),
        )
    )
    lineup_stamp = _latest(
        value
        for match in matches
        for value in (
            _nested(match, "alineacion", "source_updated_at"),
            _nested(match, "alineacion", "generated_at"),
            _nested(match, "alineacion", "ts"),
        )
    )

    ensemble_accepted = any(
        bool(_nested(match, "model_meta", "ensemble", "accepted"))
        for match in matches
    )
    residual_accepted = any(
        bool(_nested(match, "model_meta", "residual", "accepted"))
        for match in matches
    )

    features = [
        _row(
            feature="dixon_coles_score_model",
            source="Resultados históricos reales · Football-Data/API-Football + score model Dixon-Coles",
            coverage=_coverage(matches, lambda m: isinstance(_nested(m, "model_meta", "components", "dixon_coles"), dict)),
            available_at=generated_at,
            uses=["1x2", "xg", "secondary_markets", "confidence", "display"],
            gate="baseline_production + walk_forward_monitoring",
            leakage_risk="low",
            status="production",
            notes="Baseline principal; solo usa información anterior al kickoff.",
        ),
        _row(
            feature="elo",
            source="Resultados históricos reales transformados en rating Elo",
            coverage=_coverage(matches, lambda m: isinstance(_nested(m, "model_meta", "components", "elo"), dict)),
            available_at=generated_at,
            uses=["1x2_challenger", "ensemble", "confidence", "display"],
            gate="walk_forward_log_loss_rps_vs_dixon_coles",
            leakage_risk="low",
            status="production_gated" if ensemble_accepted or residual_accepted else "challenger",
            notes="Solo altera producción cuando el gate temporal del ensemble/residual está aceptado.",
        ),
        _row(
            feature="team_stat_model",
            source="football-data.co.uk · históricos de remates, SOT, córners, faltas y tarjetas",
            coverage=_coverage(matches, lambda m: isinstance(m.get("stats"), dict) and bool(m.get("stats"))),
            available_at=generated_at,
            uses=["secondary_markets", "player_context", "confidence", "display"],
            gate="temporal_mae_by_stat + fallback_to_league_mean",
            leakage_risk="low",
            status="production",
            notes="Las métricas ofensivas se alinean con la fuerza/xG sin introducir resultados futuros.",
        ),
        _row(
            feature="market_odds",
            source="The Odds API · consenso europeo; football-data.co.uk como fallback real",
            coverage=_coverage(matches, lambda m: isinstance(_nested(m, "odds", "1x2"), dict)),
            available_at=market_stamp,
            uses=["1x2_calibration", "value", "ou25", "spreads", "display"],
            gate="remove_vig + historical_market_calibration + pre_kickoff_only",
            leakage_risk="low",
            status="production",
            notes="Opening/current se conserva con timestamp; closing solo puede puntuar históricos si fue capturado antes del cierre definido.",
        ),
        _row(
            feature="weather_forecast",
            source="Open-Meteo forecast horario; histórico archivado separado",
            coverage=_coverage(matches, lambda m: isinstance(m.get("weather"), dict) and bool(m.get("weather"))),
            available_at=weather_stamp,
            uses=["xg_candidate", "secondary_markets", "discipline_candidate", "display"],
            gate="historical_weather_walk_forward_pending",
            leakage_risk="medium",
            status="candidate",
            notes="No toca 1X2; el ajuste sigue acotado hasta demostrar mejora histórica con forecast disponible as-of.",
        ),
        _row(
            feature="lineups_absences_minutes",
            source="API-Football oficial + medios recientes + continuidad histórica + snapshots pre-match",
            coverage=_coverage(matches, lambda m: isinstance(m.get("alineacion"), dict) and bool(m.get("alineacion"))),
            available_at=lineup_stamp,
            uses=["confidence", "player_props", "lineup_impact_candidate", "display"],
            gate="historical_pre_kickoff_snapshots + xi_strength_walk_forward_pending",
            leakage_risk="high_until_snapshot_gate",
            status="candidate_gated",
            notes="Un XI probable exige evidencia de ambos equipos; el XI oficial se conserva con hora de captura para evitar leakage.",
        ),
        _row(
            feature="player_props",
            source="API-Football /players + XI probable/oficial; estimación trazable solo para huecos sin muestra",
            coverage=_coverage(
                matches,
                lambda m: bool((_nested(m, "alineacion", "clave_local") or []))
                and bool((_nested(m, "alineacion", "clave_visitante") or [])),
            ),
            available_at=lineup_stamp,
            uses=["player_props", "player_profile", "display"],
            gate="real_sample_preferred + explicit_estimate_label + lineup_integrity",
            leakage_risk="medium",
            status="production_with_provenance",
            notes="Las estimaciones nunca se presentan como estadística observada y conservan evidencia/tamaño de muestra.",
        ),
        _row(
            feature="tactical_matchup",
            source="Perfiles observados casa/fuera derivados de football-data.co.uk",
            coverage=_coverage(matches, lambda m: isinstance(m.get("tactical_matchup"), dict) and bool(m.get("tactical_matchup"))),
            available_at=generated_at,
            uses=["context", "explanation", "display"],
            gate="matchup_feature_walk_forward_pending",
            leakage_risk="low",
            status="context_only",
            notes="Se muestra como inteligencia contextual; no altera 1X2 hasta superar un challenger temporal.",
        ),
    ]

    return {
        "generated_at": generated_at,
        "principle": "candidate -> leakage-safe snapshot -> walk-forward -> compare vs accepted engine + no-vig market -> promote only on improvement",
        "eligible_matches": len(_eligible(matches)),
        "features": features,
    }


def refresh_payload(payload: dict) -> bool:
    table = build_feature_truth_table(payload)
    if payload.get("feature_truth_table") == table:
        return False
    payload["feature_truth_table"] = table
    return True


def run(path: Path = OUTPUT) -> tuple[bool, dict]:
    previous = load_feed(path)
    if not previous:
        return False, {"error": "feed_missing"}
    candidate = dict(previous)
    changed = refresh_payload(candidate)
    if not changed:
        return False, {"changed": False, "features": len((candidate.get("feature_truth_table") or {}).get("features") or [])}
    ok, report = write_feed_safely(path, candidate, previous=previous)
    return ok, {
        "changed": True,
        "features": len((candidate.get("feature_truth_table") or {}).get("features") or []),
        "feed_valid": bool(ok),
        "feed_issues": report.get("issues") or [],
    }


def main() -> int:
    import json

    ok, stats = run()
    print(json.dumps({"written": ok, **stats}, ensure_ascii=False, sort_keys=True))
    return 0 if not stats.get("feed_issues") else 1


if __name__ == "__main__":
    raise SystemExit(main())
