"""Operaciones batch de API-Football orientadas a planes con cuota baja.

El plan Free permite pocas peticiones diarias. Este módulo concentra datos que
el proveedor acepta por varios fixture ids en una sola llamada y conserva la
diferencia entre "sin bajas" (lista vacía) y "no se pudo comprobar" (None).
"""
from __future__ import annotations

from .api_football import ApiFootballClient


def _unique_ids(fixture_ids) -> list[int]:
    out = []
    seen = set()
    for value in fixture_ids or []:
        try:
            fixture_id = int(value)
        except (TypeError, ValueError):
            continue
        if fixture_id <= 0 or fixture_id in seen:
            continue
        seen.add(fixture_id)
        out.append(fixture_id)
    return out


def _normalise_absence(item: dict) -> dict | None:
    player = item.get("player") or {}
    team = item.get("team") or {}
    name = str(player.get("name") or "").strip()
    if not name:
        return None
    return {
        "jugador": name,
        "team": str(team.get("name") or ""),
        "estado": str(player.get("type") or "baja").casefold(),
        "detalle": str(player.get("reason") or player.get("type") or "Baja comunicada"),
        "source": "API-Football",
        "official": True,
    }


def get_absences_batch(
    client: ApiFootballClient,
    fixture_ids,
    *,
    chunk_size: int = 20,
) -> dict[int, list[dict] | None]:
    """Obtiene bajas para varios fixtures con ``/injuries?ids=...``.

    Devuelve una clave por fixture solicitado. Una lista vacía significa que la
    petición respondió correctamente y no reportó bajas; ``None`` significa que
    ese lote no pudo comprobarse. Los lotes se limitan a 20 ids para mantener la
    misma cota conservadora usada por ``/fixtures?ids``.
    """
    ids = _unique_ids(fixture_ids)
    if getattr(client, "offline", True) or not ids:
        return {}

    size = max(1, min(int(chunk_size or 20), 20))
    out: dict[int, list[dict] | None] = {}
    for start in range(0, len(ids), size):
        chunk = ids[start:start + size]
        try:
            response = client._get(
                "injuries", {"ids": "-".join(map(str, chunk))}
            ).get("response") or []
        except Exception:
            for fixture_id in chunk:
                out[fixture_id] = None
            continue

        for fixture_id in chunk:
            out[fixture_id] = []
        for item in response:
            try:
                fixture_id = int(((item.get("fixture") or {}).get("id")))
            except (TypeError, ValueError):
                continue
            if fixture_id not in out or fixture_id not in chunk:
                continue
            row = _normalise_absence(item)
            if row is not None:
                out[fixture_id].append(row)
    return out
