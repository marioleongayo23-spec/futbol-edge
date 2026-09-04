"""Scraper de designaciones RFEF: parseo tolerante, cruce por equipo y defensa.

No toca la red: usa `fetch` inyectado y HTML/txt de muestra. Valida que el
árbitro pre-partido se extrae en los formatos plausibles de RFEF y que
cualquier fallo deja el sistema en vacío (feed intacto).
"""
from __future__ import annotations

import json

from futbol_pred.ingest.rfef_referees import (
    parse_designations, discover_articles, collect_designations,
    fetch_and_store, load_directory, RefereeDirectory, INDEX_URL,
)

_ARTICLE = """LALIGA EA SPORTS - JORNADA 6
Viernes 5 de septiembre de 2026
18:30 FC Barcelona - Valencia CF
Árbitro: Gil Manzano (Comité Extremeño)
VAR: Hernández Hernández
Real Madrid CF - Athletic Club
Árbitro principal: Sánchez Martínez
Sevilla FC - Getafe CF: González Fuertes (Comité Asturiano)
"""


def test_parse_formato_etiquetado_e_inline():
    des = parse_designations(_ARTICLE)
    got = {(d.home, d.away): d.referee for d in des}
    assert got[("Barcelona", "Valencia")] == "Gil Manzano"          # etiquetado + hora delante
    assert got[("Real Madrid", "Ath Bilbao")] == "Sánchez Martínez"  # etiquetado línea siguiente
    assert got[("Sevilla", "Getafe")] == "González Fuertes"          # inline con dos puntos


def test_parse_ignora_ruido_y_equipos_desconocidos():
    ruido = "Comité Técnico - Nota de prensa. VAR - sistema. Jornada 2025-2026"
    assert parse_designations(ruido) == []
    # un enfrentamiento con un equipo que no reconocemos no se emite
    assert parse_designations("FC Barcelona - Equipo Inventado FC\nÁrbitro: Fulano") == []


def test_parse_requiere_arbitro():
    # sin árbitro localizable no hay designación (no inventamos)
    assert parse_designations("FC Barcelona - Valencia CF\nAsistentes varios") == []


def test_discover_articles_filtra_indice():
    html = ('<a href="/es/noticias/designaciones-arbitros-sexta-jornada">a</a>'
            '<a href="/es/noticias/arbitros/designaciones">indice</a>'
            '<a href="https://rfef.es/es/noticias/designaciones-septima-jornada">b</a>')
    urls = discover_articles(html)
    assert "https://rfef.es/es/noticias/designaciones-arbitros-sexta-jornada" in urls
    assert "https://rfef.es/es/noticias/designaciones-septima-jornada" in urls
    assert all("arbitros/designaciones" not in u.rsplit("/", 1)[-1] for u in urls)


def test_directory_lookup_canonico_y_orden_invertido():
    des = parse_designations(_ARTICLE)
    d = RefereeDirectory(des)
    assert d.lookup("FC Barcelona", "Valencia CF") == "Gil Manzano"
    assert d.lookup("Valencia CF", "FC Barcelona") == "Gil Manzano"   # invierte local/visitante
    assert d.lookup("Barcelona", "Valencia") == "Gil Manzano"          # alias -> canónico
    assert d.lookup("Equipo Raro", "Otro") is None


def _fake_fetch(index_html, article_html):
    def fetch(url, timeout=20):
        return index_html if url == INDEX_URL else article_html
    return fetch


def test_collect_defensivo_sin_red():
    assert collect_designations(fetch=lambda u, timeout=20: None) == []


def test_fetch_and_store_y_load_roundtrip(tmp_path):
    idx = '<a href="/es/noticias/designaciones-sexta-jornada">x</a>'
    n = fetch_and_store(data_dir=tmp_path, fetch=_fake_fetch(idx, _ARTICLE))
    assert n == 3
    cache = json.loads((tmp_path / "referee_designations.json").read_text(encoding="utf-8"))
    assert len(cache["designations"]) == 3 and cache["source"].startswith("rfef.es")
    d = load_directory(tmp_path)
    assert len(d) == 3
    assert d.lookup("Real Madrid CF", "Athletic Club") == "Sánchez Martínez"


def test_fetch_and_store_no_borra_cache_si_falla(tmp_path):
    # cache previo válido
    fetch_and_store(data_dir=tmp_path, fetch=_fake_fetch('<a href="/es/noticias/designaciones-x">x</a>', _ARTICLE))
    before = (tmp_path / "referee_designations.json").read_text(encoding="utf-8")
    # descarga posterior falla del todo -> no toca el cache
    n = fetch_and_store(data_dir=tmp_path, fetch=lambda u, timeout=20: None)
    assert n == 0
    assert (tmp_path / "referee_designations.json").read_text(encoding="utf-8") == before


def test_load_directory_defensivo(tmp_path):
    assert len(load_directory(tmp_path)) == 0            # fichero ausente
    (tmp_path / "referee_designations.json").write_text("{ roto", encoding="utf-8")
    assert len(load_directory(tmp_path)) == 0            # json corrupto
