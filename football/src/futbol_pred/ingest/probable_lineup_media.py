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


def _clean_html(value: str | None) -> str:
    text = re.sub(r"<[^>]+>", " ", unescape(str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


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
    snippet y enlace del resultado; nunca se afirma que un jugador sea titular
    porque aparezca en una noticia.
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
        # Exige que la noticia hable al menos de uno de los dos equipos y de XI.
        if not (home.casefold() in haystack or away.casefold() in haystack):
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
        })
        if len(out) >= max_items:
            break
    return out
