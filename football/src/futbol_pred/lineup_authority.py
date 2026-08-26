"""Reglas compartidas para distinguir XI oficial real de etiquetas heredadas.

Nunca tratamos ``status=confirmado`` como prueba suficiente. La autoridad exige
22 titulares y trazabilidad explícita a un fixture de un proveedor oficial.
"""
from __future__ import annotations


def is_authoritative_official_lineup(lineup: dict | None) -> bool:
    if not isinstance(lineup, dict) or lineup.get("status") != "confirmado":
        return False
    if len(lineup.get("local") or []) != 11 or len(lineup.get("visitante") or []) != 11:
        return False

    provider = str(lineup.get("provider") or "").strip().casefold()
    fixture_id = lineup.get("official_fixture_id")
    try:
        fixture_ok = int(fixture_id) > 0
    except (TypeError, ValueError):
        fixture_ok = False
    if provider != "api-football" or not fixture_ok:
        return False

    quality = lineup.get("quality") if isinstance(lineup.get("quality"), dict) else {}
    kind = str(lineup.get("lineup_kind") or "").strip().casefold()
    model = str(lineup.get("model") or "").strip().casefold()
    phase = str(lineup.get("phase") or "").strip().casefold()
    source = str(lineup.get("fuente") or "").strip().casefold()
    explicit_official = (
        quality.get("official") is True
        or kind == "official"
        or "alineación oficial" in model
        or (phase == "final" and "lineup" in source)
    )
    return bool(explicit_official)


def mark_official_provenance(lineup: dict) -> dict:
    """Canoniza metadatos tras recibir un 11+11 oficial de API-Football."""
    lineup["status"] = "confirmado"
    lineup["phase"] = "final"
    lineup["lineup_kind"] = "official"
    lineup["source_quality"] = "official"
    lineup["evidence_scope"] = "official_api"
    lineup["display_warning"] = None
    quality = dict(lineup.get("quality") or {})
    quality["official"] = True
    quality["complete"] = True
    quality["lineup_players"] = 22
    lineup["quality"] = quality
    return lineup
