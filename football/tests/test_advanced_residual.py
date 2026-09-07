from datetime import datetime, timedelta, timezone

from futbol_pred.advanced_stats import latest_snapshot_as_of
from futbol_pred.backtest.advanced_residual import (
    MIN_RECORDS,
    advanced_residual_probabilities,
    fit_walk_forward_advanced_residual,
)


def _base_record(i: int, actual: str) -> dict:
    kickoff = datetime(2026, 1, 1, 18, tzinfo=timezone.utc) + timedelta(days=i)
    return {
        "round": ("league", "REGULAR", 2026, i + 1),
        "kickoff": kickoff.timestamp(),
        "home": "Barcelona",
        "away": "RCD Espanyol",
        "actual": actual,
        "probs": {"1": 0.34, "X": 0.33, "2": 0.33},
    }


def _elo_record(i: int, actual: str) -> dict:
    row = _base_record(i, actual)
    row["probs"] = {"1": 0.33, "X": 0.34, "2": 0.33}
    return row


def _snapshot(i: int, actual: str) -> dict:
    kickoff = datetime(2026, 1, 1, 18, tzinfo=timezone.utc) + timedelta(days=i)
    if actual == "1":
        home = (3.0, 0.6, 2.7, 0.5, 0.35)
        away = (0.6, 2.5, 0.5, 2.2, -0.25)
    elif actual == "2":
        home = (0.6, 2.5, 0.5, 2.2, -0.25)
        away = (3.0, 0.6, 2.7, 0.5, 0.35)
    else:
        home = (1.25, 1.25, 1.10, 1.10, 0.0)
        away = (1.25, 1.25, 1.10, 1.10, 0.0)

    def side(values):
        xgf, xga, npxgf, npxga, keeper = values
        return {
            "matches": 12 + i,
            "xg_for90": xgf,
            "xg_against90": xga,
            "npxg_for90": npxgf,
            "npxg_against90": npxga,
            "goalkeepers": [
                {
                    "player": "GK",
                    "minutes": 1000 + i * 90,
                    "psxg90": 1.0,
                    "psxg_plus_minus90": keeper,
                }
            ],
        }

    return {
        "schema": "advanced-stats-snapshot-v1",
        "source": "synthetic-test-only",
        "source_version": "1",
        "generated_at": (kickoff - timedelta(hours=2)).isoformat(),
        "available_at": (kickoff - timedelta(hours=1)).isoformat(),
        "league": "laliga",
        "season": 2026,
        "league_keeper_psxg_plus_minus90": 0.0,
        "teams": {
            "Barcelona": side(home),
            "RCD Espanyol": side(away),
        },
    }


def _dataset(n: int = 120):
    actuals = ["1", "X", "2"]
    base, elo, snapshots = [], [], []
    for i in range(n):
        actual = actuals[i % 3]
        base.append(_base_record(i, actual))
        elo.append(_elo_record(i, actual))
        snapshots.append(_snapshot(i, actual))
    archive = {"schema": "advanced-stats-archive-v1", "snapshots": snapshots}
    return base, elo, archive


def test_sin_snapshots_el_challenger_queda_bloqueado_y_no_afecta_1x2():
    base, elo, _archive = _dataset(MIN_RECORDS)
    result = fit_walk_forward_advanced_residual(
        base,
        elo,
        {"schema": "advanced-stats-archive-v1", "snapshots": []},
        league="laliga",
        season=2026,
    )
    assert result["accepted"] is False
    assert result["status"] == "blocked_insufficient_advanced_snapshots"
    assert result["n"] == 0
    assert result["affects_1x2"] is False


def test_snapshot_posterior_al_kickoff_no_entra_pero_historico_previo_si():
    base, elo, archive = _dataset(MIN_RECORDS)
    original_available = []
    for snapshot, record in zip(archive["snapshots"], base):
        kickoff = datetime.fromtimestamp(record["kickoff"], tz=timezone.utc)
        snapshot["available_at"] = (kickoff + timedelta(seconds=1)).isoformat()
        original_available.append(snapshot["available_at"])

    first_kickoff = datetime.fromtimestamp(base[0]["kickoff"], tz=timezone.utc)
    assert latest_snapshot_as_of(archive, "laliga", 2026, first_kickoff) is None

    second_kickoff = datetime.fromtimestamp(base[1]["kickoff"], tz=timezone.utc)
    selected = latest_snapshot_as_of(archive, "laliga", 2026, second_kickoff)
    assert selected is not None
    assert selected["available_at"] == original_available[0]
    assert selected["available_at"] != original_available[1]

    result = fit_walk_forward_advanced_residual(
        base, elo, archive, league="laliga", season=2026
    )
    # El snapshot del propio partido nunca entra; desde el segundo partido sí
    # existe un snapshot histórico anterior y causalmente válido.
    assert result["n"] == MIN_RECORDS - 1
    assert result["coverage"]["snapshot_available"] == MIN_RECORDS - 1
    assert result["status"] == "blocked_insufficient_advanced_snapshots"


def test_senal_avanzada_fuerte_puede_superar_residual_estandar_en_misma_muestra():
    base, elo, archive = _dataset(120)
    result = fit_walk_forward_advanced_residual(
        base, elo, archive, league="laliga", season=2026
    )
    assert result["n"] == 120
    assert result["n_validation"] >= 25
    assert result["validation"]["log_loss"] < result["validation_baselines"]["residual_same_sample"]["log_loss"]
    assert result["validation"]["rps"] < result["validation_baselines"]["residual_same_sample"]["rps"]
    assert result["accepted"] is True
    assert result["status"] == "accepted_offline_not_promoted"
    assert result["affects_1x2"] is False
    assert result["promotion_status"] == "manual_future_pr_required"


def test_baseline_extra_incompleto_bloquea_aunque_el_modelo_avanzado_gane():
    base, elo, archive = _dataset(120)
    market = [{**row, "probs": {"1": 0.34, "X": 0.33, "2": 0.33}} for row in base[:-1]]
    result = fit_walk_forward_advanced_residual(
        base,
        elo,
        archive,
        league="laliga",
        season=2026,
        extra_baseline_records={"market_no_vig": market},
    )
    assert result["accepted"] is False
    assert result["status"] == "blocked_incomplete_baseline_coverage"
    assert result["baseline_coverage"]["market_no_vig"]["complete"] is False


def test_aplicacion_con_parametros_rotos_cae_exactamente_al_base():
    base = {"1": 0.5, "X": 0.3, "2": 0.2}
    elo = {"1": 0.4, "X": 0.3, "2": 0.3}
    context = {
        "home": {"xg_for90": 2.0, "xg_against90": 1.0, "matches": 10},
        "away": {"xg_for90": 1.0, "xg_against90": 2.0, "matches": 10},
    }
    out = advanced_residual_probabilities(base, elo, context, {"weights": "broken"})
    assert out == base
