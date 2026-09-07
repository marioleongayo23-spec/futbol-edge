import json
from datetime import datetime, timedelta, timezone

import pytest

from futbol_pred.advanced_stats import ARCHIVE_SCHEMA
from futbol_pred.advanced_stats_export import (
    archive_manifest,
    build_historical_archive,
    write_archive,
)
from futbol_pred.advanced_stats_intake import (
    IntakeError,
    intake_file,
    parse_archive_strict,
    plan_intake,
)

NOW = datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc)


def _records(xg=2.0):
    return [
        {
            "match_at": "2026-08-20T19:00:00Z",
            "team": "FC Barcelona",
            "opponent": "RCD Espanyol",
            "xg_for": xg,
            "npxg_for": 1.8,
            "xg_against": 0.7,
            "npxg_against": 0.6,
            "keeper_psxg90": 0.8,
            "keeper_psxg_plus_minus90": 0.2,
            "keeper_minutes": 90,
        },
        {
            "match_at": "2026-08-20T19:00:00Z",
            "team": "RCD Espanyol",
            "opponent": "FC Barcelona",
            "xg_for": 0.7,
            "npxg_for": 0.6,
            "xg_against": xg,
            "npxg_against": 1.8,
            "keeper_psxg90": 1.9,
            "keeper_psxg_plus_minus90": -0.3,
            "keeper_minutes": 90,
        },
    ]


def _payload(xg=2.0):
    archive = build_historical_archive(
        _records(xg),
        league="laliga",
        season=2026,
        source="FBref residential",
        source_version="1.9.1",
        generated_at="2026-09-07T06:00:00Z",
    )
    return {**archive, "manifest": archive_manifest(archive)}


def test_archivo_exportado_valido_pasa_intake_estricto():
    payload = parse_archive_strict(_payload(), now=NOW)
    assert payload["schema"] == ARCHIVE_SCHEMA
    assert payload["manifest"]["snapshot_count"] == 1
    assert set(payload["snapshots"][0]["teams"]) == {"Barcelona", "Espanol"}


def test_manifest_manipulado_rechaza_archivo_completo():
    payload = _payload()
    payload["manifest"]["sha256"] = "0" * 64
    with pytest.raises(IntakeError, match="manifest_mismatch"):
        parse_archive_strict(payload, now=NOW)


def test_snapshot_invalido_no_se_descarta_silenciosamente():
    payload = _payload()
    payload["snapshots"].append({"schema": "broken"})
    payload["manifest"] = archive_manifest({
        "schema": ARCHIVE_SCHEMA,
        "snapshots": payload["snapshots"][:-1],
    })
    with pytest.raises(IntakeError, match=r"snapshot\[1\]:schema_invalid"):
        parse_archive_strict(payload, now=NOW)


def test_colision_de_alias_canonico_barcelona_se_rechaza_antes_del_manifest():
    payload = _payload()
    snapshot = payload["snapshots"][0]
    snapshot["teams"]["FC Barcelona"] = dict(snapshot["teams"]["Barcelona"])
    # No se recalcula el manifest: archive_manifest también normaliza y podría
    # detectar la colisión antes de ejercitar la puerta de entrada que probamos.
    with pytest.raises(IntakeError, match="team_duplicate:Barcelona"):
        parse_archive_strict(payload, now=NOW)


def test_clave_existente_con_datos_distintos_es_conflicto():
    existing = parse_archive_strict(_payload(2.0), now=NOW)
    incoming = parse_archive_strict(_payload(2.2), now=NOW)
    with pytest.raises(IntakeError, match="semantic_key_conflict"):
        plan_intake(existing, incoming)


def test_clave_existente_identica_es_no_change():
    existing = parse_archive_strict(_payload(), now=NOW)
    incoming = parse_archive_strict(_payload(), now=NOW)
    plan = plan_intake(existing, incoming)
    assert plan["status"] == "no_change"
    assert plan["added"] == 0
    assert plan["unchanged"] == 1
    assert plan["before_sha256"] == plan["after_sha256"]
    assert plan["affects_1x2"] is False


def test_fusion_aditiva_no_pierde_historico():
    existing = parse_archive_strict(_payload(), now=NOW)
    rows = _records()
    for row in rows:
        row["match_at"] = "2026-08-27T19:00:00Z"
    archive = build_historical_archive(
        rows,
        league="laliga",
        season=2026,
        source="FBref residential",
        source_version="1.9.1",
        generated_at="2026-09-07T06:00:00Z",
    )
    incoming = parse_archive_strict({**archive, "manifest": archive_manifest(archive)}, now=NOW)
    plan = plan_intake(existing, incoming)
    assert plan["status"] == "ready"
    assert plan["added"] == 1
    assert plan["total"] == 2
    assert plan["manifest"]["snapshot_count"] == 2


def test_timestamp_futuro_se_rechaza():
    payload = _payload()
    future = (NOW + timedelta(hours=2)).isoformat()
    payload["snapshots"][0]["available_at"] = future
    payload["manifest"] = archive_manifest({
        "schema": ARCHIVE_SCHEMA,
        "snapshots": payload["snapshots"],
    })
    with pytest.raises(IntakeError, match="available_at_in_future"):
        parse_archive_strict(payload, now=NOW)


def test_generated_at_futuro_se_rechaza():
    payload = _payload()
    payload["snapshots"][0]["generated_at"] = (NOW + timedelta(hours=2)).isoformat()
    # generated_at es metadato de ejecución y no cambia el digest semántico.
    with pytest.raises(IntakeError, match="generated_at_in_future"):
        parse_archive_strict(payload, now=NOW)


def test_valores_absurdos_de_xg_y_portero_se_rechazan():
    payload = _payload()
    team = payload["snapshots"][0]["teams"]["Barcelona"]
    team["xg_for90"] = 99
    team["goalkeepers"][0]["psxg_plus_minus90"] = 50
    payload["manifest"] = archive_manifest({
        "schema": ARCHIVE_SCHEMA,
        "snapshots": payload["snapshots"],
    })
    with pytest.raises(IntakeError) as exc:
        parse_archive_strict(payload, now=NOW)
    assert "xg_for90_out_of_range:Barcelona" in str(exc.value)
    assert "keeper_psxg_plus_minus90_out_of_range:Barcelona" in str(exc.value)


def test_intake_file_aplica_solo_si_se_pide(tmp_path):
    incoming = tmp_path / "incoming.json"
    output = tmp_path / "archive.json"
    write_archive(incoming, _payload())

    dry = intake_file(incoming, existing_path=output, output_path=output, apply=False, now=NOW)
    assert dry["status"] == "ready"
    assert dry["applied"] is False
    assert output.exists() is False

    applied = intake_file(incoming, existing_path=output, output_path=output, apply=True, now=NOW)
    assert applied["status"] == "ready"
    assert applied["applied"] is True
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["manifest"]["snapshot_count"] == 1