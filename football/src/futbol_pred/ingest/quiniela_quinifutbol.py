"""Quiniela de la próxima jornada desde quinielafutbol.info.

Alternativa gratuita y scrapeable a LAE (que bloquea a los scripts con 403).
La web publica un bloque JSON-LD (schema.org ItemList de SportsEvent) con los
15 partidos del boleto de la próxima jornada, incluido el Pleno al 15. Leerlo
es mucho más estable que parsear el HTML.

Diagnóstico:  python -m futbol_pred.ingest.quiniela_quinifutbol
"""

from __future__ import annotations

import json
import re

import requests

from .quiniela_lae import Quiniela, QuinielaMatch

URL = "https://www.quinielafutbol.info/proximas-jornadas-de-la-quiniela.html"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}
_LD_RE = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S)


def _item_lists(obj):
    """Devuelve todos los ItemList anidados en un JSON-LD."""
    out = []
    if isinstance(obj, dict):
        if obj.get("@type") == "ItemList" and obj.get("itemListElement"):
            out.append(obj)
        for v in obj.values():
            out += _item_lists(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _item_lists(v)
    return out


def _jornada_num(name: str | None) -> str:
    m = re.search(r"jornada\s+(\d+)", name or "", re.I)
    return m.group(1) if m else ""


def get_current_quiniela(timeout: int = 20) -> Quiniela | None:
    """Boleto de la próxima jornada (15 partidos) o None si no se pudo leer."""
    try:
        r = requests.get(URL, headers=HEADERS, timeout=timeout)
        if not r.ok:
            return None
        html = r.text
    except requests.RequestException:
        return None

    lists = []
    for block in _LD_RE.findall(html):
        try:
            lists += _item_lists(json.loads(block))
        except (ValueError, TypeError):
            continue

    for lst in lists:
        events = [
            el for el in lst.get("itemListElement", [])
            if isinstance(el, dict) and (el.get("item") or {}).get("@type") == "SportsEvent"
        ]
        if len(events) < 14:
            continue
        events.sort(key=lambda el: el.get("position") or 0)
        partidos: list[QuinielaMatch] = []
        fecha = None
        for orden, el in enumerate(events[:15], start=1):
            item = el["item"]
            local = (item.get("homeTeam") or {}).get("name") or ""
            visit = (item.get("awayTeam") or {}).get("name") or ""
            if not (local and visit):  # respaldo: "Local vs Visitante"
                parts = re.split(r"\s+vs\.?\s+", item.get("name") or "", maxsplit=1)
                if len(parts) == 2:
                    local, visit = parts[0].strip(), parts[1].strip()
            if local and visit:
                partidos.append(QuinielaMatch(orden=orden, local=local, visitante=visit))
            if orden == 1:
                fecha = (item.get("startDate") or "")[:10] or None
        if len(partidos) >= 14:
            return Quiniela(jornada=_jornada_num(lst.get("name")), fecha=fecha, partidos=partidos)
    return None


def _diagnose() -> None:
    q = get_current_quiniela()
    if not q:
        print("[quinifutbol] no se pudo obtener la quiniela")
        return
    print(f"[quinifutbol] Jornada {q.jornada} · fecha {q.fecha} · {len(q.partidos)} partidos")
    for m in q.partidos:
        etiqueta = "P15" if m.orden == 15 else f"{m.orden:>2}"
        print(f"  {etiqueta}  {m.local} - {m.visitante}")


if __name__ == "__main__":
    _diagnose()
