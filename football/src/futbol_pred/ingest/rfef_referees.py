"""Designaciones arbitrales (árbitro **pre-partido**) desde fuentes públicas.

Las APIs gratis (football-data.org, API-Football en su plan free) no exponen el
árbitro antes del pitido inicial, así que el efecto del árbitro del Bloque 2
quedaba invisible en los partidos apostables. Las designaciones se publican
**~1 día antes** de cada partido.

Fuentes por orden de preferencia:
  0. **Prensa vía Google News RSS** (``collect_from_media``) — PRIMARIA: las
     cabeceras (AS, Marca, Soccerway…) publican la ronda de designaciones el día
     del partido y Google News las indexa. Reusa la misma tubería sin muro que ya
     alimenta las alineaciones probables, así que es la que de verdad funciona.
  1. **BeSoccer** (``es.besoccer.com``) — respaldo: su WAF devuelve HTTP 406
     incluso con cabeceras de navegador (bloqueo por huella), así que rinde 0; se
     mantiene por si cambia.
  2. **RFEF** (``rfef.es``) — respaldo: su web devuelve un muro anti-bot (Drupal
     ``antibot``) que no expone el contenido a un cliente sin JavaScript, así que
     normalmente rinde 0; se mantiene por si cambia.

Este módulo descarga esas noticias, extrae ``(local, visitante) -> árbitro`` y
lo cachea en ``data/referee_designations.json`` (con la ``source``). El build del
feed lee ese fichero (sin red en el camino caliente) y rellena ``fixture.referee``
cuando la API no lo trae, encendiendo el perfil del árbitro y el ajuste de
faltas/tarjetas ya existentes.

Diseño **defensivo**: cualquier fallo de red o de parseo deja el fichero como
estaba (o vacío) y el feed sigue exactamente igual. El árbitro es siempre
opcional; nunca puede tumbar la generación del feed.

Parser **auto-observable**: si descarga una noticia pero no extrae designaciones,
registra una muestra amplia del texto para afinar el parseo desde los logs del
cron (la estructura HTML real no es accesible desde el entorno de desarrollo por
egress).
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import urlencode

from ..config import DATA_DIR
from ..normalize import canonical_team

log = logging.getLogger(__name__)

CACHE_NAME = "referee_designations.json"
# Cabecera de navegador COMPLETA. El WAF de BeSoccer devuelve HTTP 406 ("Not
# Acceptable") ante el `Accept: */*` que `requests` manda por defecto, así que
# nunca llegábamos a ver el HTML. Emular Chrome —sobre todo un `Accept:
# text/html` real y las cabeceras `Sec-Fetch-*`— hace pasar la petición. El
# contenido es público (designaciones arbitrales); esto solo evita el bloqueo
# por bot, no accede a nada privado.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}
# Cuántas noticias de designación leer (cubre jornada en curso + la siguiente si
# ya se publicó a mitad de semana).
_MAX_ARTICLES = 6

# --- Fuentes de designaciones, por orden de preferencia ---------------------
# BeSoccer sirve el contenido ESTÁTICO (Google lo indexa con los árbitros
# reales), así que es la fuente primaria. RFEF queda como respaldo aunque su
# web devuelva un muro anti-bot (contenido vacío -> 0, sin romper nada).
BESOCCER_BASE = "https://es.besoccer.com"
RFEF_BASE = "https://rfef.es"
# Índice/listado del que sacar los enlaces a las noticias de designaciones.
_SOURCES = (
    ("BeSoccer", BESOCCER_BASE,
     ("https://es.besoccer.com/competicion/noticias/primera",
      "https://es.besoccer.com/competicion/noticias/segunda_division",
      "https://es.besoccer.com/noticias"),
     re.compile(r"/noticia/[^\"'#?]*designaciones[^\"'#?]*", re.I)),
    ("RFEF", RFEF_BASE,
     ("https://rfef.es/es/noticias/arbitros/designaciones",),
     re.compile(r"/es/noticias/[^\"'#?]*designaciones[^\"'#?]*", re.I)),
)
# "Local - Visitante": admite guion (normal/medio/largo) o "vs" con espacios.
_PAIR = re.compile(r"(.+?)\s+(?:vs\.?|[-‐-―])\s+(.+)", re.I)
# Etiqueta explícita del árbitro principal en el texto de la noticia.
_REF_LABEL = re.compile(
    r"(?:árbitro|arbitro)(?:\s+principal)?\s*:?\s*([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ.'\- ]{3,60})",
    re.I,
)


@dataclass
class Designation:
    home: str          # nombre canónico del local
    away: str          # nombre canónico del visitante
    referee: str       # árbitro principal (tal cual lo publica la fuente)
    raw_home: str = ""  # nombre tal cual aparecía (diagnóstico)
    raw_away: str = ""
    source: str = ""    # fuente de la que salió (prensa, BeSoccer, RFEF…)
    fetched_at: str = ""  # ISO UTC de cuándo se recogió (para expirar el cache)


def _known(name: str) -> str | None:
    """Nombre canónico si el equipo está en nuestro registro; None si no."""
    try:
        return canonical_team(name.strip(), strict=True)
    except Exception:  # noqa: BLE001 - nombre desconocido o basura
        return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _team_suffix(text: str) -> str | None:
    """Equipo conocido MÁS LARGO al final del texto (el local suele venir tras
    hora/fecha: '18:30 FC Barcelona')."""
    words = _clean(text).split()
    best = None
    for k in range(1, min(len(words), 5) + 1):
        cand = " ".join(words[len(words) - k:]).strip(":.-–— ")
        c = _known(cand)
        if c:
            best = c
    return best


def _team_prefix(text: str) -> tuple[str | None, str]:
    """Equipo conocido MÁS LARGO al principio del texto y el resto (que puede
    llevar '': árbitro (comité)''). Devuelve (canónico|None, resto)."""
    words = _clean(text).split()
    best = None
    best_k = 0
    for k in range(1, min(len(words), 5) + 1):
        cand = " ".join(words[:k]).strip(":.-–— ")
        c = _known(cand)
        if c:
            best, best_k = c, k
    if best is None:
        return None, ""
    return best, " ".join(words[best_k:])


# Palabras de cabeceras/medios: un nombre de árbitro que las contenga es basura
# (p.ej. 'Mundo Deportivo' colado como árbitro).
_OUTLET_WORDS = {
    "mundo", "deportivo", "deportiva", "marca", "sport", "relevo", "estadio",
    "superdeporte", "desmarque", "soccerway", "cadena", "ser", "cope", "diario",
    "radio", "onda", "prensa", "besoccer", "futbolfantasy", "eurosport", "dazn",
    "goal", "gol", "espanol", "confidencial", "vozpopuli", "okdiario",
}


def _referee_from(text: str) -> str | None:
    """Nombre del árbitro a partir de un fragmento (etiqueta 'Árbitro:' o el
    resto tras el visitante). Corta en comité/asistentes/VAR."""
    if not text:
        return None
    label = _REF_LABEL.search(text)
    raw = label.group(1) if label else text
    raw = raw.lstrip(":-–—. ")
    # Corta en comité/asistentes/VAR, en un nuevo enfrentamiento (' - ') o en una
    # nueva etiqueta de árbitro (evita arrastrar la línea del siguiente partido).
    raw = re.split(r"[,(/|]|\bVAR\b|\bAsisten|\bComité|\bComite|\bNº|\bN\.º"
                   r"|\s[-‐-―]\s|(?:á|a)rbitro", raw, flags=re.I)[0]
    raw = _clean(raw)
    # Descarta cabeceras genéricas (no son nombres de árbitro).
    if not raw or not any(c.isalpha() for c in raw) or len(raw) < 3:
        return None
    # Nunca termina en partícula suelta ('… y', '… de'): recórtala.
    raw = re.sub(r"\s+(?:de|del|la|los|las|y|da|di|dos|van|von)$", "", raw, flags=re.I).strip()
    low = raw.casefold()
    if not raw or low.startswith(("jornada", "laliga", "primera", "segunda", "viernes",
                                  "sábado", "sabado", "domingo", "lunes", "martes",
                                  "miércoles", "miercoles", "jueves")):
        return None
    # Descarta nombres de medios ('Mundo Deportivo', 'Cadena SER'…).
    if set(re.findall(r"[a-z0-9]+", _norm_key(raw))) & _OUTLET_WORDS:
        return None
    return raw


def parse_designations(text: str) -> list[Designation]:
    """Extrae designaciones del texto plano de una noticia.

    Heurística tolerante al formato exacto (que puede cambiar): busca líneas con
    un enfrentamiento cuyos DOS equipos reconozcamos y, cerca, el árbitro
    principal. Validar ambos equipos contra el registro descarta ruido; solo se
    emite una designación con árbitro localizado.
    """
    designations: list[Designation] = []
    seen: set[tuple[str, str]] = set()
    # Normaliza saltos y separa en líneas con contenido.
    lines = [_clean(ln) for ln in re.split(r"[\n\r]+|(?<=\.)\s{2,}", text) if _clean(ln)]

    def _parsed_pair(ln: str) -> tuple[str, str] | None:
        mm = _PAIR.search(ln)
        if not mm:
            return None
        h = _team_suffix(mm.group(1))
        a, _ = _team_prefix(mm.group(2))
        return (h, a) if h and a and h != a else None

    for i, line in enumerate(lines):
        m = _PAIR.search(line)
        if not m:
            continue
        home = _team_suffix(m.group(1))
        away, remainder = _team_prefix(m.group(2))
        if not home or not away or home == away:
            continue
        key = (home, away)
        if key in seen:
            continue
        # Árbitro: primero el resto de la MISMA línea (formato inline
        # 'A - B: Árbitro'), luego la etiqueta en las líneas siguientes HASTA el
        # próximo enfrentamiento (no arrastrar la línea del siguiente partido).
        follow: list[str] = []
        for j in range(i + 1, min(i + 4, len(lines))):
            if _parsed_pair(lines[j]):
                break
            follow.append(lines[j])
        ref = _referee_from(remainder) or _referee_from(" ".join(follow))
        if ref:
            seen.add(key)
            designations.append(Designation(
                home=home, away=away, referee=ref,
                raw_home=_clean(m.group(1)), raw_away=_clean(m.group(2)),
            ))
    return designations


# --- Prensa deportiva: formato de ronda "<árbitro> para el <local>-<visitante>"
# Las cabeceras (AS, Marca, Soccerway…) publican la ronda de designaciones ~1 día
# antes y el día del partido con titulares del tipo: "Los árbitros de la jornada
# 3: Gil Manzano para el Barça-Valencia; Sánchez Martínez para el Betis-Madrid".
# parse_designations ya cubre "Local - Visitante: Árbitro"; esto añade la forma
# "Árbitro para el Local-Visitante" (y dirigirá/arbitrará), que es la dominante en
# prensa.
#
# Apodos de prensa que canonical_team(strict) no resuelve (claves normalizadas:
# minúsculas, sin acentos). Solo los inequívocos; el cruce se valida luego contra
# el partido REAL del feed, así que un apodo mal mapeado como mucho PIERDE una
# designación, nunca la aplica al partido equivocado.
_NICKNAMES = {
    "barca": "Barcelona", "barsa": "Barcelona",
    "atleti": "Atlético de Madrid", "atletico": "Atlético de Madrid",
    "colchoneros": "Atlético de Madrid",
    "rayo": "Rayo Vallecano",
    "la real": "Real Sociedad", "txuri urdin": "Real Sociedad",
    "madrid": "Real Madrid",
    "leones": "Athletic Club",
}
# Nombre de árbitro: palabra Mayúscula inicial + continuaciones que pueden ser
# partículas en minúscula ('de', 'del', 'la'…) o más palabras Mayúsculas, para no
# truncar 'Díaz de Mera Escuderos' ni 'De Burgos Bengoetxea' (review Codex P2).
# Sin '.' en la clase de caracteres: un punto es fin de frase, no parte del
# nombre. Incluirlo hacía que 'Mundo Deportivo. El colegiado…' se capturara como
# un solo nombre cruzando la frase (falso positivo con el nombre del medio).
_NAME = (
    r"[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ'’\-]+"
    r"(?:\s+(?:de|del|la|los|las|di|da|dos|van|von|y|"
    r"[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ'’\-]+)){0,4}"
)
_ROUNDUP_REF_FIRST = re.compile(
    r"(" + _NAME + r")"
    r"\s+(?:para|dirigir[áa]|arbitrar[áa]|pit[ae]r[áa]?)\s+(?:el|la)\s+"
    r"([^;,.:]+?[-‐-―][^;,.:]+?)(?=\s*[;,.:]|\s+[-‐-―]\s|\s+[ye]\s|$)",
)
# Extracción del árbitro cuando YA conocemos el partido (consulta por partido):
# basta hallar el nombre junto a una etiqueta ('árbitro', 'colegiado') o un verbo
# ('dirigirá', 'arbitrará'). Flags de caso acotadas para no romper la Mayúscula
# inicial del nombre.
_REF_PATTERNS = [
    # nombre ANTES de la etiqueta: 'Munuera Montero, árbitro del Betis-Madrid'
    re.compile(r"(?P<ref>" + _NAME + r")\s*,?\s+(?i:árbitro|arbitro|colegiado)\b"),
    # etiqueta ANTES: 'árbitro del partido (será|:) Díaz de Mera'
    re.compile(r"(?i:árbitro|arbitro|colegiado)"
               r"(?:\s+(?i:principal|del partido|del encuentro|del choque|designado))?"
               r"(?:\s*[:\-–—]|\s+(?i:ser[áa]|es|fue)(?:\s+el)?)?\s+(?P<ref>" + _NAME + r")"),
    # verbo tras el nombre: 'X será el árbitro | dirigirá | arbitrará | pitará'
    re.compile(r"(?P<ref>" + _NAME + r")\s*,?\s+(?i:ser[áa] el árbitro|dirigir[áa]|arbitrar[áa]|pitar[áa]|pita)\b"),
    # verbo antes del nombre: 'dirigirá (el encuentro) X'
    re.compile(r"(?i:dirigir[áa]|arbitrar[áa]|pitar[áa])\s+(?:(?i:el|la|este|el partido|el encuentro|el choque)\s+)?"
               r"(?P<ref>" + _NAME + r")"),
    re.compile(r"(?i:designad[oa])\s+(?:(?i:a|al)\s+)?(?P<ref>" + _NAME + r")"),
]
# Descarta piezas de otra competición para el mismo par de clubes (Copa, Liga F,
# juvenil, europeas): su árbitro ≠ el de LaLiga/Segunda (review Codex P2).
_EXCLUDE_COMP = re.compile(
    r"(?i:copa del rey|\bcopa\b|supercopa|femenin|liga f\b|juvenil|cadete|"
    r"champions|europa league|conference|mundial|amistoso|selecci)")


def _norm_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _resolve_side(text: str) -> str | None:
    """Un lado de un enfrentamiento de prensa -> equipo canónico, tolerando apodos
    ('Barça', 'Atleti') y sufijos/prefijos ('Rayo Vallecano')."""
    raw = _clean(text).strip(" .:;-‐-― ")
    if not raw:
        return None
    nick = _NICKNAMES.get(_norm_key(raw))
    if nick:
        return _known(nick)
    return _known(raw) or _team_suffix(raw) or _team_prefix(raw)[0]


def parse_media_text(text: str) -> list[Designation]:
    """Designaciones de un texto de prensa (titular + entradilla).

    Une dos gramáticas: la de ronda '<árbitro> para el <local>-<visitante>' y la
    de parse_designations ('<local> - <visitante>: <árbitro>'). Valida ambos
    equipos contra el registro y descarta lo que no cuadre."""
    out: list[Designation] = []
    seen: set[tuple[str, str]] = set()
    for m in _ROUNDUP_REF_FIRST.finditer(text or ""):
        parts = re.split(r"\s*[-‐-―]\s*", m.group(2), maxsplit=1)
        if len(parts) != 2:
            continue
        home, away = _resolve_side(parts[0]), _resolve_side(parts[1])
        ref = _referee_from(m.group(1))
        if home and away and home != away and ref and (home, away) not in seen:
            seen.add((home, away))
            out.append(Designation(home=home, away=away, referee=ref,
                                    raw_home=_clean(parts[0]), raw_away=_clean(parts[1])))
    for d in parse_designations(text or ""):
        if (d.home, d.away) not in seen:
            seen.add((d.home, d.away))
            out.append(d)
    return out


def referee_in_text(text: str) -> str | None:
    """Nombre del árbitro suelto en un texto cuando el partido YA se conoce.

    A diferencia de parse_media_text (que deriva el partido del texto), aquí solo
    hace falta el nombre: lo localiza junto a una etiqueta ('árbitro', 'colegiado')
    o un verbo ('dirigirá', 'arbitrará'). Descarta lo que sea un equipo conocido."""
    text = text or ""
    for pat in _REF_PATTERNS:
        for m in pat.finditer(text):
            # 'colegiado X … en el VAR' designa al VAR, no al árbitro principal.
            if re.search(r"\bVAR\b", text[m.end():m.end() + 18]):
                continue
            ref = _referee_from(m.group("ref"))
            # un nombre de equipo no es un árbitro (evita 'dirigirá el Betis…')
            if ref and not _known(ref) and not _team_suffix(ref):
                return ref
    return None


_PRESS_STOP = {
    "cf", "fc", "cd", "ud", "sd", "rc", "rcd", "sad", "club", "de", "del",
    "balompie", "balompié", "futbol", "fútbol", "deportivo", "deportiva",
}


def _press_core(name: str) -> str:
    """Núcleo periodístico del nombre para la consulta ('Real Betis Balompié' ->
    'Real Betis'). Conserva el orden; descarta sufijos jurídicos/genéricos."""
    toks = [t for t in re.findall(r"[0-9A-Za-zÁÉÍÓÚÑáéíóúñ]+", name or "")
            if _norm_key(t) not in _PRESS_STOP]
    return " ".join(toks) or _clean(name)


def _fixture_pairs(data_dir: Path, now: datetime, horizon_days: int = 6) -> list[tuple[str, str, str, str]]:
    """(local_raw, visitante_raw, local_canon, visitante_canon) de los próximos
    partidos SIN árbitro en el feed publicado. Lee el dashboard.json del build
    anterior (sin red); ausente/ilegible -> []."""
    try:
        payload = json.loads((Path(data_dir) / "dashboard.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    lo = now.date().isoformat()
    hi = (now + timedelta(days=horizon_days)).date().isoformat()
    out: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for m in payload.get("matches") or []:
        oc = m.get("official_context") or {}
        if oc.get("referee"):
            continue  # ya tiene árbitro (API); no hace falta la prensa
        kickoff = (oc.get("kickoff") or m.get("kickoff") or "")[:10]
        if not (lo <= kickoff <= hi):
            continue
        home, away = m.get("home") or "", m.get("away") or ""
        ch, ca = _known(home), _known(away)
        if ch and ca and ch != ca and (ch, ca) not in seen:
            seen.add((ch, ca))
            out.append((home, away, ch, ca))
    return out


_session = None


def _get_session():
    """Sesión `requests` cacheada por ejecución: reutiliza las cookies entre el
    índice y las noticias (algunos WAF sirven una cookie en la primera respuesta
    y la exigen en la siguiente). Devuelve None si `requests` no está instalado
    (entorno ligero del hot-refresh)."""
    global _session
    if _session is not None:
        return _session
    try:
        import requests
    except Exception:  # noqa: BLE001 - entorno ligero sin requests
        return None
    session = requests.Session()
    session.headers.update(_HEADERS)
    _session = session
    return _session


def _fetch(url: str, timeout: int = 20) -> str | None:
    """Descarga defensiva; None ante cualquier problema (incl. egress bloqueado)."""
    session = _get_session()
    if session is None:
        return None
    # Google News RSS es un endpoint pensado para clientes, no un WAF: reproduce
    # las cabeceras simples que ya usa el colector de alineaciones (evita que un
    # Accept: text/html + Sec-Fetch de "navegador" devuelva un interstitial en vez
    # del XML).
    headers = None
    if "news.google.com" in url:
        headers = {
            "User-Agent": "FutbolEdge/1.0 referee-research",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
    try:
        resp = session.get(url, timeout=timeout, headers=headers)
        if resp.status_code != 200 or not resp.text:
            snippet = _clean(getattr(resp, "text", "") or "")[:200]
            log.warning("designaciones %s -> HTTP %s %s", url, resp.status_code, snippet)
            return None
        # Preserva los acentos de los nombres de árbitro cuando la cabecera no
        # declara charset (requests asumiría latin-1 y rompería 'González').
        if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "latin-1"):
            resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text
    except Exception as exc:  # noqa: BLE001 - red no disponible / bloqueada
        log.warning("designaciones: fetch falló para %s: %s", url, exc)
        return None


def _to_text(html: str) -> str:
    """HTML -> texto plano PRESERVANDO los límites de fila.

    RFEF separa cada partido/árbitro con ``<br>``/``<p>``/``<td>``…, no con
    saltos literales; ``text_content()`` los perdería y dejaría todo en una línea
    (una sola designación parseada, el resto absorbido o descartado). Por eso
    inyectamos ``\\n`` en esos límites ANTES de extraer el texto."""
    html = html or ""
    html = re.sub(r"(?i)<\s*br\s*/?>", "\n", html)
    html = re.sub(
        r"(?i)</\s*(?:p|div|tr|li|ul|ol|h[1-6]|td|th|section|article|table)\s*>",
        "\n", html,
    )
    try:
        from lxml import html as lxml_html
        return lxml_html.fromstring(html).text_content()
    except Exception:  # noqa: BLE001
        return re.sub(r"<[^>]+>", " ", html)


def discover_articles(index_html: str, base: str, slug_re: "re.Pattern[str]",
                      index_url: str = "") -> list[str]:
    """URLs absolutas de las noticias de designación halladas en un índice."""
    urls: list[str] = []
    seen: set[str] = set()
    for href in slug_re.findall(index_html or ""):
        url = href if href.startswith("http") else base + href
        # el propio índice puede casar el patrón (RFEF): descártalo.
        if index_url and url.rstrip("/") == index_url.rstrip("/"):
            continue
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls[:_MAX_ARTICLES]


# --- Prensa vía Google News RSS (fuente PRIMARIA, sin muro anti-bot) ----------
# Reusa la misma tubería que ya alimenta las alineaciones probables: Google News
# como índice, filtrando a cabeceras de confianza. No amurallada (a diferencia de
# RFEF/BeSoccer), así que es la fuente principal; RFEF/BeSoccer quedan de respaldo.
NEWS_RSS = "https://news.google.com/rss/search"
_MEDIA_QUERIES = (
    "designaciones arbitrales jornada",
    "árbitros de la jornada LaLiga",
    "árbitros de la jornada Segunda",
)
# Ventana amplia: la ronda se publica ~1 día antes y se re-publica el día del
# partido; el cruce exacto con el fixture del feed evita arrastrar jornadas viejas.
_MEDIA_MAX_AGE_H = 120
# Cabeceras fiables para un hecho oficial (claves normalizadas: minúsculas, sin
# acentos). Un blog cualquiera no basta; el equipo+árbitro se validan estructural-
# mente, pero restringir la fuente descarta ruido.
_TRUSTED_SOURCES = {
    "as": "AS", "diario as": "AS", "marca": "MARCA",
    "mundo deportivo": "Mundo Deportivo", "sport": "SPORT", "relevo": "Relevo",
    "estadio deportivo": "Estadio Deportivo", "superdeporte": "Superdeporte",
    "el desmarque": "ElDesmarque", "eldesmarque": "ElDesmarque",
    "soccerway": "Soccerway", "es.soccerway.com": "Soccerway",
    "cadena ser": "Cadena SER", "cadena cope": "COPE", "cope": "COPE",
    "el espanol": "El Español", "besoccer": "BeSoccer", "futbolfantasy": "FutbolFantasy",
}


def _news_url(query: str) -> str:
    return NEWS_RSS + "?" + urlencode(
        {"q": query, "hl": "es", "gl": "ES", "ceid": "ES:es"})


def _rss_items(xml_text: str) -> list:
    try:
        root = ET.fromstring((xml_text or "").encode("utf-8"))
        return list(root.findall("./channel/item"))
    except (ET.ParseError, ValueError, TypeError):
        return []


def _clean_tags(value: str | None) -> str:
    return _clean(re.sub(r"<[^>]+>", " ", unescape(str(value or ""))))


def _fresh_media(pub_date: str | None, now: datetime) -> bool:
    if not pub_date:
        return True  # sin fecha: no descartamos; el cruce con el fixture ya filtra
    try:
        stamp = parsedate_to_datetime(pub_date)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (now.astimezone(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds() / 3600
        return -2 <= age <= _MEDIA_MAX_AGE_H
    except (TypeError, ValueError, OverflowError):
        return True


def _src(item) -> str:
    el = item.find("source")
    return (el.text or "").strip() if el is not None else ""


def _mentions(text: str, core: str) -> bool:
    """El texto menciona a un equipo: exige su token MÁS DISTINTIVO (apellido/ciudad,
    no 'Real'/'Club'), para no atribuir una pieza de un solo equipo a un partido."""
    toks = [t for t in _norm_key(core).split() if len(t) >= 4] or _norm_key(core).split()
    longest = max(toks, key=len, default="")
    return bool(longest) and re.search(rf"\b{re.escape(longest)}", _norm_key(text)) is not None


def collect_from_media(fetch=_fetch, now: datetime | None = None,
                       fixtures: list[tuple[str, str, str, str]] | None = None) -> list[Designation]:
    """Designaciones desde la prensa deportiva vía Google News RSS.

    Dos pasadas: (1) POR PARTIDO —conocido el fixture, basta hallar el nombre del
    árbitro junto a ambos equipos (lo más fiable); (2) RONDA global —titulares tipo
    'X para el A-B; Y para el C-D'. Solo cabeceras de confianza y frescas, y descarta
    otras competiciones. Nunca lanza; auto-observable: registra hasta 5 titulares de
    muestra si no extrae nada."""
    now = now or datetime.now(timezone.utc)
    out: list[Designation] = []
    seen: set[tuple[str, str]] = set()
    sources: set[str] = set()
    samples: list[str] = []

    def _accept(d: Designation, outlet: str) -> bool:
        if (d.home, d.away) in seen:
            return False
        seen.add((d.home, d.away))
        d.source = "prensa"  # categoría (para provenance/contador); el medio va al log
        out.append(d)
        sources.add(outlet)
        return True

    # 1) POR PARTIDO: consulta dirigida; conocemos el fixture, solo falta el nombre.
    for home, away, ch, ca in (fixtures or []):
        hc, ac = _press_core(home), _press_core(away)
        xml = fetch(_news_url(f"{hc} {ac} árbitro designado"))
        if not xml:
            continue
        for item in _rss_items(xml):
            outlet = _TRUSTED_SOURCES.get(_norm_key(_src(item)))
            if not outlet or not _fresh_media(item.findtext("pubDate"), now):
                continue
            text = f"{_clean_tags(item.findtext('title'))}. {_clean_tags(item.findtext('description'))}"
            if _EXCLUDE_COMP.search(text) or not (_mentions(text, hc) and _mentions(text, ac)):
                continue
            ref = referee_in_text(text)
            if ref and _accept(Designation(home=ch, away=ca, referee=ref, raw_home=home, raw_away=away), outlet):
                break
            if not ref and len(samples) < 5:
                samples.append(text[:160])

    # 2) RONDA GLOBAL: recoge los partidos que la prensa lista juntos.
    for query in _MEDIA_QUERIES:
        xml = fetch(_news_url(query))
        if not xml:
            continue
        for item in _rss_items(xml):
            outlet = _TRUSTED_SOURCES.get(_norm_key(_src(item)))
            if not outlet or not _fresh_media(item.findtext("pubDate"), now):
                continue
            title = _clean_tags(item.findtext("title"))
            desc = _clean_tags(item.findtext("description"))
            if _EXCLUDE_COMP.search(f"{title}. {desc}"):
                continue
            if len(samples) < 5:
                samples.append(title[:160])
            # Google News añade ' - <Cabecera>' al título; parsea también sin sufijo.
            title_stripped = re.sub(r"\s+[-‐-―]\s+[^-‐-―]+$", "", title)
            for chunk in (title, title_stripped, desc):
                for d in parse_media_text(chunk):
                    _accept(d, outlet)
    if out:
        log.info("prensa: %d designaciones vía Google News (%s)",
                 len(out), ", ".join(sorted(sources)))
    else:
        log.info("prensa: 0 designaciones vía Google News (%d fixtures, %d consultas). Muestras: %s",
                 len(fixtures or []), len(_MEDIA_QUERIES),
                 " || ".join(samples) or "(sin ítems de confianza)")
    return out


def collect_designations(fetch=_fetch, now: datetime | None = None,
                         fixtures: list[tuple[str, str, str, str]] | None = None
                         ) -> tuple[list[Designation], str | None]:
    """Reúne designaciones de la primera fuente que dé datos.

    Orden: (1) PRENSA vía Google News RSS —sin muro, la que funciona—; de respaldo
    (2) BeSoccer y (3) RFEF, que suelen rendir 0 por WAF pero se conservan por si
    cambian. Nunca lanza; registra muestras amplias para afinar el parser desde los
    logs del cron cuando una fuente devuelve contenido pero no se extrae nada."""
    media = collect_from_media(fetch=fetch, now=now, fixtures=fixtures)
    if media:
        return media, "prensa"
    for source, base, index_urls, slug_re in _SOURCES:
        for index_url in index_urls:
            index = fetch(index_url)
            if not index:
                continue
            articles = discover_articles(index, base, slug_re, index_url)
            if not articles:
                log.info("%s: %s sin enlaces de designación", source, index_url)
                continue
            out: list[Designation] = []
            keys: set[tuple[str, str]] = set()
            for url in articles:
                html = fetch(url)
                if not html:
                    continue
                text = _to_text(html)
                parsed = parse_designations(text)
                if not parsed:
                    log.warning("%s: 0 designaciones en %s. Muestra(1200): %s",
                                source, url, _clean(text)[:1200])
                    continue
                for d in parsed:
                    if (d.home, d.away) not in keys:
                        keys.add((d.home, d.away))
                        d.source = source
                        out.append(d)
            if out:
                log.info("%s: %d designaciones de %d noticias (%s)",
                         source, len(out), len(articles), index_url)
                return out, source
    log.warning("Designaciones: ninguna fuente devolvió datos")
    return [], None


_CACHE_TTL_DAYS = 10


def _load_cache(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def fetch_and_store(data_dir: Path | None = None, fetch=_fetch,
                    now: datetime | None = None) -> int:
    """Descarga y cachea designaciones. Devuelve cuántas designaciones nuevas trajo.

    MERGE con el cache previo (no pisa designaciones válidas de la jornada con un
    resultado PARCIAL de prensa, que suele cubrir solo unos partidos; review Codex).
    Si no trae ninguna, NO reescribe: el cache previo sigue sirviendo tal cual."""
    data_dir = Path(data_dir or DATA_DIR)
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat()
    fixtures = _fixture_pairs(data_dir, now)
    designations, source = collect_designations(fetch=fetch, now=now, fixtures=fixtures)
    if not designations:
        return 0  # nada nuevo -> no toques el cache
    path = data_dir / CACHE_NAME
    cutoff = (now - timedelta(days=_CACHE_TTL_DAYS)).isoformat()
    prev = _load_cache(path)
    # Filas del cache antiguo sin 'fetched_at' se migran con el sello top-level del
    # payload (no con 'ahora'): así caducan de verdad y no arrastran un árbitro de
    # una temporada pasada si el par se repite (Codex).
    legacy = prev.get("fetched_at") or stamp
    merged: dict[tuple[str, str], dict] = {}
    for row in prev.get("designations") or []:  # conserva lo previo aún vigente
        h, a, r = row.get("home"), row.get("away"), row.get("referee")
        if not (h and a and r):
            continue
        row_ts = row.get("fetched_at") or legacy
        if row_ts < cutoff:
            continue
        row["fetched_at"] = row_ts  # re-sella para que porte fecha y caduque en el futuro
        merged[(h, a)] = row
    for d in designations:  # lo nuevo gana
        row = asdict(d)
        row["fetched_at"] = stamp
        merged[(d.home, d.away)] = row
    payload = {"fetched_at": stamp, "source": source or "", "designations": list(merged.values())}
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        log.warning("Designaciones: no pude escribir %s: %s", path, exc)
        return 0
    return len(designations)


class RefereeDirectory:
    """Búsqueda ``(local, visitante) -> árbitro`` por nombre canónico."""

    def __init__(self, designations: list[Designation], fetched_at: str | None = None,
                 source: str | None = None):
        self.fetched_at = fetched_at
        self.source = source or ""
        # Guarda (árbitro, fuente) POR PARTIDO: el cache puede mezclar filas de
        # distinta procedencia (prensa/BeSoccer/RFEF) y cada una conserva la suya;
        # usar la fuente top-level para todas etiquetaría mal las retenidas (Codex).
        self._by_pair: dict[tuple[str, str], tuple[str, str]] = {}
        for d in designations:
            self._by_pair[(d.home, d.away)] = (d.referee, d.source or self.source)

    def __len__(self) -> int:
        return len(self._by_pair)

    def _row(self, home: str, away: str) -> tuple[str, str] | None:
        ch, ca = _known(home), _known(away)
        if not ch or not ca:
            return None
        return self._by_pair.get((ch, ca))

    def lookup(self, home: str, away: str) -> str | None:
        """Árbitro designado para ese local-visitante EXACTO, o None.

        Respeta la dirección local/visitante: NO cae al orden inverso. El partido
        de vuelta (B-A) tiene su propia designación, distinta y normalmente aún sin
        publicar; cruzar el par como no ordenado aplicaría el árbitro equivocado
        (y su ajuste de faltas/tarjetas) al partido de vuelta meses antes. La fuente
        publica el local/visitante correctos, así que el cruce exacto basta."""
        row = self._row(home, away)
        return row[0] if row else None

    def source_for(self, home: str, away: str) -> str | None:
        """Fuente (prensa/BeSoccer/RFEF) de ESA designación en concreto, o None."""
        row = self._row(home, away)
        return row[1] if row else None


def load_directory(data_dir: Path | None = None) -> RefereeDirectory:
    """Lee el cache. Defensivo: fichero ausente/corrupto -> directorio vacío."""
    path = Path(data_dir or DATA_DIR) / CACHE_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("designations") or []
        des = [Designation(**{k: r.get(k, "") for k in ("home", "away", "referee", "raw_home", "raw_away", "source")})
               for r in rows if r.get("home") and r.get("away") and r.get("referee")]
        return RefereeDirectory(des, payload.get("fetched_at"), payload.get("source"))
    except FileNotFoundError:
        return RefereeDirectory([])
    except Exception as exc:  # noqa: BLE001 - json corrupto, etc.
        log.warning("Designaciones: cache ilegible %s: %s", path, exc)
        return RefereeDirectory([])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    n = fetch_and_store()
    print(f"Designaciones arbitrales guardadas: {n}")


if __name__ == "__main__":
    main()
