"""Designaciones arbitrales de la RFEF (árbitro **pre-partido**).

Las APIs gratis (football-data.org, API-Football en su plan free) no exponen el
árbitro antes del pitido inicial, así que el efecto del árbitro del Bloque 2
quedaba invisible en los partidos apostables. La RFEF/CTA publica las
designaciones **~1 día antes** de cada partido (antes de las 16:00) en
``rfef.es/es/noticias/arbitros/designaciones``: cada jornada es una noticia con
el árbitro principal de cada encuentro.

Este módulo descarga esas noticias, extrae ``(local, visitante) -> árbitro`` y
lo cachea en ``data/referee_designations.json``. El build del feed lee ese
fichero (sin red en el camino caliente) y rellena ``fixture.referee`` cuando la
API no lo trae, encendiendo el perfil del árbitro y el ajuste de faltas/tarjetas
ya existentes.

Diseño **defensivo**: cualquier fallo de red o de parseo deja el fichero como
estaba (o vacío) y el feed sigue exactamente igual. El árbitro es siempre
opcional; nunca puede tumbar la generación del feed.

Parser **auto-observable**: si descarga una noticia pero no consigue extraer
designaciones, registra una muestra del texto para poder afinar el parseo desde
los logs del cron (la estructura HTML real de RFEF no es accesible desde el
entorno de desarrollo por egress).
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

INDEX_URL = "https://rfef.es/es/noticias/arbitros/designaciones"
BASE_URL = "https://rfef.es"
CACHE_NAME = "referee_designations.json"
# Cabecera de navegador: RFEF suele rechazar el User-Agent por defecto de requests.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
}
# Cuántas noticias de designación leer (cubre jornada en curso + la siguiente si
# ya se publicó a mitad de semana).
_MAX_ARTICLES = 4
_ARTICLE_SLUG = re.compile(r"/es/noticias/[^\"'#?]*designaciones[^\"'#?]*", re.I)
# "Local - Visitante": admite guion normal, medio o largo, con espacios.
_PAIR = re.compile(r"(.+?)\s+[-‐-―]\s+(.+)")
# Etiqueta explícita del árbitro principal en el texto de la noticia.
_REF_LABEL = re.compile(
    r"(?:árbitro|arbitro)(?:\s+principal)?\s*:?\s*([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ.'\- ]{3,60})",
    re.I,
)


@dataclass
class Designation:
    home: str          # nombre canónico del local
    away: str          # nombre canónico del visitante
    referee: str       # árbitro principal (tal cual lo publica RFEF)
    raw_home: str = ""  # nombre tal cual aparecía (diagnóstico)
    raw_away: str = ""


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


def _fetch(url: str, timeout: int = 20) -> str | None:
    """Descarga defensiva; None ante cualquier problema (incl. egress bloqueado)."""
    try:
        import requests
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        if resp.status_code != 200 or not resp.text:
            log.warning("RFEF %s -> HTTP %s", url, resp.status_code)
            return None
        return resp.text
    except Exception as exc:  # noqa: BLE001 - red no disponible / bloqueada
        log.warning("RFEF fetch falló para %s: %s", url, exc)
        return None


def _to_text(html: str) -> str:
    """HTML -> texto plano con lxml si está; si no, un desnudado básico."""
    try:
        from lxml import html as lxml_html
        return lxml_html.fromstring(html).text_content()
    except Exception:  # noqa: BLE001
        return re.sub(r"<[^>]+>", " ", html)


def discover_articles(index_html: str) -> list[str]:
    """URLs absolutas de las noticias de designación, más recientes primero."""
    urls: list[str] = []
    seen: set[str] = set()
    for href in _ARTICLE_SLUG.findall(index_html or ""):
        url = href if href.startswith("http") else BASE_URL + href
        # el propio índice también casa el slug: descártalo.
        if url.rstrip("/") == INDEX_URL.rstrip("/"):
            continue
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls[:_MAX_ARTICLES]


def collect_designations(fetch=_fetch) -> list[Designation]:
    """Orquesta índice -> noticias -> designaciones. Nunca lanza."""
    index = fetch(INDEX_URL)
    if not index:
        return []
    articles = discover_articles(index)
    if not articles:
        log.warning("RFEF: índice sin enlaces de designación (¿cambió el HTML?)")
        return []
    out: list[Designation] = []
    keys: set[tuple[str, str]] = set()
    for url in articles:
        html = fetch(url)
        if not html:
            continue
        text = _to_text(html)
        parsed = parse_designations(text)
        if not parsed:
            # Auto-observable: deja una muestra para afinar el parser desde logs.
            log.warning("RFEF: 0 designaciones en %s. Muestra: %s", url, _clean(text)[:600])
            continue
        for d in parsed:
            if (d.home, d.away) not in keys:
                keys.add((d.home, d.away))
                out.append(d)
    log.info("RFEF: %d designaciones de %d noticias", len(out), len(articles))
    return out


def fetch_and_store(data_dir: Path | None = None, fetch=_fetch) -> int:
    """Descarga y cachea designaciones. Devuelve cuántas guardó.

    Si no consigue ninguna, NO borra un cache previo válido (una jornada ya
    descargada sigue sirviendo aunque una descarga puntual falle)."""
    data_dir = Path(data_dir or DATA_DIR)
    designations = collect_designations(fetch=fetch)
    if not designations:
        return 0
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "rfef.es/es/noticias/arbitros/designaciones",
        "designations": [asdict(d) for d in designations],
    }
    path = data_dir / CACHE_NAME
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        log.warning("RFEF: no pude escribir %s: %s", path, exc)
        return 0
    return len(designations)


class RefereeDirectory:
    """Búsqueda ``(local, visitante) -> árbitro`` por nombre canónico."""

    def __init__(self, designations: list[Designation], fetched_at: str | None = None):
        self.fetched_at = fetched_at
        self._by_pair: dict[tuple[str, str], str] = {}
        for d in designations:
            self._by_pair[(d.home, d.away)] = d.referee

    def __len__(self) -> int:
        return len(self._by_pair)

    def lookup(self, home: str, away: str) -> str | None:
        """Árbitro designado para ese local-visitante, o None.

        Casa por nombre canónico y, como respaldo, en cualquier orden (por si la
        fuente invierte local/visitante)."""
        ch, ca = _known(home), _known(away)
        if not ch or not ca:
            return None
        return self._by_pair.get((ch, ca)) or self._by_pair.get((ca, ch))


def load_directory(data_dir: Path | None = None) -> RefereeDirectory:
    """Lee el cache. Defensivo: fichero ausente/corrupto -> directorio vacío."""
    path = Path(data_dir or DATA_DIR) / CACHE_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("designations") or []
        des = [Designation(**{k: r.get(k, "") for k in ("home", "away", "referee", "raw_home", "raw_away")})
               for r in rows if r.get("home") and r.get("away") and r.get("referee")]
        return RefereeDirectory(des, payload.get("fetched_at"))
    except FileNotFoundError:
        return RefereeDirectory([])
    except Exception as exc:  # noqa: BLE001 - json corrupto, etc.
        log.warning("RFEF: cache ilegible %s: %s", path, exc)
        return RefereeDirectory([])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    n = fetch_and_store()
    print(f"RFEF designaciones guardadas: {n}")


if __name__ == "__main__":
    main()
