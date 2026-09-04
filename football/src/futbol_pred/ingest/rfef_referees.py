"""Designaciones arbitrales (árbitro **pre-partido**) desde fuentes públicas.

Las APIs gratis (football-data.org, API-Football en su plan free) no exponen el
árbitro antes del pitido inicial, así que el efecto del árbitro del Bloque 2
quedaba invisible en los partidos apostables. Las designaciones se publican
**~1 día antes** de cada partido.

Fuentes por orden de preferencia (``_SOURCES``):
  1. **BeSoccer** (``es.besoccer.com``) — primaria: sirve el contenido de las
     noticias con los árbitros reales (Google las indexa), así que es scrapeable
     SIN JavaScript. Su WAF sí rechaza el ``Accept: */*`` de ``requests`` con un
     HTTP 406, por eso emulamos las cabeceras de un navegador (ver ``_HEADERS``).
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
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

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
    source: str = ""    # fuente de la que salió (BeSoccer, RFEF…)


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
    low = raw.casefold()
    if low.startswith(("jornada", "laliga", "primera", "segunda", "viernes",
                       "sábado", "sabado", "domingo", "lunes", "martes",
                       "miércoles", "miercoles", "jueves")):
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
    try:
        resp = session.get(url, timeout=timeout)
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


def collect_designations(fetch=_fetch) -> tuple[list[Designation], str | None]:
    """Prueba las fuentes en orden de preferencia (BeSoccer primero, RFEF de
    respaldo) y devuelve (designaciones, fuente) de la primera que dé datos.
    Nunca lanza; registra muestras amplias para poder afinar el parser desde los
    logs del cron cuando una fuente devuelve HTML pero no se extrae nada."""
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


def fetch_and_store(data_dir: Path | None = None, fetch=_fetch) -> int:
    """Descarga y cachea designaciones. Devuelve cuántas guardó.

    Si no consigue ninguna, NO borra un cache previo válido (una jornada ya
    descargada sigue sirviendo aunque una descarga puntual falle)."""
    data_dir = Path(data_dir or DATA_DIR)
    designations, source = collect_designations(fetch=fetch)
    if not designations:
        return 0
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": source or "",
        "designations": [asdict(d) for d in designations],
    }
    path = data_dir / CACHE_NAME
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
        self._by_pair: dict[tuple[str, str], str] = {}
        for d in designations:
            self._by_pair[(d.home, d.away)] = d.referee

    def __len__(self) -> int:
        return len(self._by_pair)

    def lookup(self, home: str, away: str) -> str | None:
        """Árbitro designado para ese local-visitante EXACTO, o None.

        Respeta la dirección local/visitante: NO cae al orden inverso. El partido
        de vuelta (B-A) tiene su propia designación, distinta y normalmente aún sin
        publicar; cruzar el par como no ordenado aplicaría el árbitro equivocado
        (y su ajuste de faltas/tarjetas) al partido de vuelta meses antes. RFEF
        publica el local/visitante correctos, así que el cruce exacto basta."""
        ch, ca = _known(home), _known(away)
        if not ch or not ca:
            return None
        return self._by_pair.get((ch, ca))


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
