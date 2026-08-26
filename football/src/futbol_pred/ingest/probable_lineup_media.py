"""Señales periodísticas frescas para la alineación pre-final.

No convierte titulares de prensa en hechos. Solo recopila evidencia pública y
fechada que después usa el estimador de once probable. La alineación oficial
siempre procede de API-Football en las ventanas T-60/T-30.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import re
import unicodedata
import xml.etree.ElementTree as ET

import requests

NEWS_RSS = "https://news.google.com/rss/search"
TRUSTED_MEDIA = {
    "as": "AS",
    "marca": "MARCA",
    "mundo deportivo": "Mundo Deportivo",
    "relevo": "Relevo",
    "estadio deportivo": "Estadio Deportivo",
    "superdeporte": "Superdeporte",
    "el desmarque": "ElDesmarque",
}

# Jerarquía de evidencia, no ranking editorial entre cabeceras. Un XI oficial
# siempre está por encima de una propuesta de prensa; una propuesta de prensa
# reciente está por encima de una estimación de modelo/fallback.
EVIDENCE_HIERARCHY = {
    "official_lineup": 1,
    "trusted_media_recent": 2,
    "model_estimate": 3,
}


def _clean_html(value: str | None) -> str:
    text = re.sub(r"<[^>]+>", " ", unescape(str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def _norm(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _team_mentioned(team: str, haystack: str) -> bool:
    team_norm = _norm(team)
    text = _norm(haystack)
    if not team_norm or not text:
        return False
    if team_norm in text:
        return True
    # Los proveedores suelen traer sufijos jurídicos/deportivos que la prensa
    # omite (CF, FC, de Fútbol...). Aceptamos el núcleo largo, evitando tokens
    # genéricos que provocarían atribuciones falsas.
    stop = {"cf", "fc", "cd", "ud", "sd", "rcd", "real", "club", "de", "del", "la", "el", "futbol", "balompie"}
    tokens = [token for token in re.findall(r"[a-z0-9]+", team_norm) if token not in stop and len(token) >= 4]
    return bool(tokens) and any(re.search(rf"\b{re.escape(token)}\b", text) for token in tokens)


def covered_sides(home: str, away: str, title: str, snippet: str | None = None) -> list[str]:
    """Atribuye una pieza de evidencia únicamente al equipo que menciona."""
    haystack = f"{title} {snippet or ''}"
    sides = []
    if _team_mentioned(home, haystack):
        sides.append("local")
    if _team_mentioned(away, haystack):
        sides.append("visitante")
    return sides


def _fresh(pub_date: str | None, now: datetime, max_age_hours: int) -> tuple[bool, str | None]:
    if not pub_date:
        return False, None
    try:
        stamp = parsedate_to_datetime(pub_date)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (now.astimezone(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds() / 3600
        return 0 <= age <= max_age_hours, stamp.isoformat()
    except (TypeError, ValueError, OverflowError):
        return False, None


def collect_probable_lineup_media(
    home: str,
    away: str,
    now: datetime,
    *,
    max_items: int = 6,
    max_age_hours: int = 72,
    session=requests,
) -> list[dict]:
    """Busca noticias recientes sobre posibles onces de un partido.

    Google News RSS se usa solo como índice. Se conserva título, medio, fecha,
    snippet, enlace y, crucialmente, qué lado del partido respalda la pieza.
    Una noticia sobre un solo equipo nunca debe fundamentar automáticamente el
    XI del rival.
    """
    query = f'"{home}" "{away}" ("alineación posible" OR "alineación probable" OR "once probable")'
    try:
        response = session.get(
            NEWS_RSS,
            params={"q": query, "hl": "es", "gl": "ES", "ceid": "ES:es"},
            headers={"User-Agent": "FutbolEdge/1.0 lineup-research"},
            timeout=12,
        )
        if not response.ok:
            return []
        root = ET.fromstring(response.content)
    except (requests.RequestException, ET.ParseError, AttributeError, TypeError, ValueError):
        return []

    out = []
    seen = set()
    for item in root.findall("./channel/item"):
        source_el = item.find("source")
        source_raw = (source_el.text or "").strip() if source_el is not None else ""
        source = TRUSTED_MEDIA.get(source_raw.casefold())
        if not source:
            continue
        is_fresh, published_at = _fresh(item.findtext("pubDate"), now, max_age_hours)
        if not is_fresh:
            continue
        title = _clean_html(item.findtext("title"))
        snippet = _clean_html(item.findtext("description"))
        link = (item.findtext("link") or "").strip()
        haystack = f"{title} {snippet}".casefold()
        sides = covered_sides(home, away, title, snippet)
        if not sides:
            continue
        if not any(token in haystack for token in ("alineaci", "once", "titular")):
            continue
        key = (source, title.casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "source": source,
            "title": title,
            "published_at": published_at,
            "snippet": snippet[:700] or None,
            "url": link or None,
            "role": "probable_lineup_evidence",
            "covered_sides": sides,
            "evidence_level": "trusted_media_recent",
            "evidence_rank": EVIDENCE_HIERARCHY["trusted_media_recent"],
        })
        if len(out) >= max_items:
            break
    return out
