"""Quiniela oficial de Loterías y Apuestas del Estado (LAE).

Descarga la combinación oficial de la jornada (los 14 partidos + Pleno al 15)
desde el servicio JSON de loteriasyapuestas.es. Así la pestaña Quiniela usa la
quiniela REAL de la semana en vez de los 15 primeros partidos con predicción.

Uso como diagnóstico:  python -m futbol_pred.ingest.quiniela_lae
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

# Cabecera de navegador: LAE rechaza el user-agent por defecto de requests.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.loteriasyapuestas.es/es/la-quiniela",
}

# Candidatas de endpoint (el servicio de LAE ha cambiado de ruta con el tiempo).
CANDIDATES = [
    "https://www.loteriasyapuestas.es/servicios/proximosv3?game_id=LAQU&num=1",
    "https://www.loteriasyapuestas.es/servicios/proximos?game_id=LAQU&num=1",
    "https://www.loteriasyapuestas.es/servicios/fechasjuegos?game_id=LAQU&celebrados=false&fechaInicioInclusiva=20260801&fechaFinInclusiva=20270601",
]


@dataclass
class QuinielaMatch:
    orden: int          # 1..15 (15 = Pleno al 15)
    local: str
    visitante: str


@dataclass
class Quiniela:
    jornada: str
    fecha: str | None
    partidos: list[QuinielaMatch]


def _extract_partidos(draw: dict) -> list[QuinielaMatch]:
    partidos = draw.get("partidos") or draw.get("Partidos") or []
    out: list[QuinielaMatch] = []
    for i, p in enumerate(partidos, start=1):
        local = p.get("local") or p.get("equipoLocal") or p.get("nombreLocal") or ""
        visit = p.get("visitante") or p.get("equipoVisitante") or p.get("nombreVisitante") or ""
        if local and visit:
            out.append(QuinielaMatch(orden=i, local=local, visitante=visit))
    return out


def get_current_quiniela(timeout: int = 20) -> Quiniela | None:
    for url in CANDIDATES:
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if not r.ok:
                continue
            data = r.json()
        except (requests.RequestException, ValueError):
            continue
        draws = data if isinstance(data, list) else data.get("draws") or [data]
        for draw in draws:
            if not isinstance(draw, dict):
                continue
            partidos = _extract_partidos(draw)
            if len(partidos) >= 14:
                return Quiniela(
                    jornada=str(draw.get("jornada") or draw.get("num_jornada")
                                or draw.get("id_sorteo") or ""),
                    fecha=draw.get("fecha_sorteo") or draw.get("fecha") or None,
                    partidos=partidos,
                )
    return None


def _diagnose() -> None:
    import json

    for url in CANDIDATES:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            ct = r.headers.get("content-type", "")
            print(f"[LAE] {url}\n  status={r.status_code} type={ct} len={len(r.text)}")
            if r.ok and "json" in ct:
                data = r.json()
                sample = data[0] if isinstance(data, list) and data else data
                if isinstance(sample, dict):
                    print(f"  keys={list(sample.keys())[:20]}")
                    partidos = sample.get("partidos") or sample.get("Partidos")
                    if partidos:
                        print(f"  partidos={len(partidos)} primero={json.dumps(partidos[0], ensure_ascii=False)[:200]}")
            else:
                print(f"  head={r.text[:200]!r}")
        except Exception as exc:  # noqa: BLE001 - diagnóstico
            print(f"[LAE] {url}\n  ERROR {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    _diagnose()
