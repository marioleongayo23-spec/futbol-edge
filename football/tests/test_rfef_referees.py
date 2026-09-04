"""Scraper de designaciones (BeSoccer primario, RFEF de respaldo): parseo
tolerante, cruce por equipo y defensa. No toca la red: usa `fetch` inyectado y
HTML/txt de muestra.
"""
from __future__ import annotations

import json

from futbol_pred.ingest.rfef_referees import (
    parse_designations, discover_articles, collect_designations,
    fetch_and_store, load_directory, RefereeDirectory, Designation, _to_text,
    BESOCCER_BASE,
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

_BES_INDEX_URL = "https://es.besoccer.com/competicion/noticias/primera"
_BES_ARTICLE_URL = "https://es.besoccer.com/noticia/designaciones-arbitrales-jornada-6-1400000"
_BES_INDEX_HTML = (
    '<a href="/noticia/designaciones-arbitrales-jornada-6-1400000">Designaciones J6</a>'
    '<a href="/noticia/otra-cosa">nada</a>'
)


def test_parse_formato_etiquetado_e_inline():
    des = parse_designations(_ARTICLE)
    got = {(d.home, d.away): d.referee for d in des}
    assert got[("Barcelona", "Valencia")] == "Gil Manzano"
    assert got[("Real Madrid", "Ath Bilbao")] == "Sánchez Martínez"
    assert got[("Sevilla", "Getafe")] == "González Fuertes"


def test_parse_admite_separador_vs():
    # BeSoccer/prensa a veces usan "vs" en vez de guion.
    des = parse_designations("FC Barcelona vs Valencia CF\nÁrbitro: Gil Manzano")
    assert des and des[0].home == "Barcelona" and des[0].referee == "Gil Manzano"


def test_parse_ignora_ruido_y_equipos_desconocidos():
    assert parse_designations("Comité Técnico - Nota de prensa. VAR - sistema. Jornada 2025-2026") == []
    assert parse_designations("FC Barcelona - Equipo Inventado FC\nÁrbitro: Fulano") == []


def test_parse_requiere_arbitro():
    assert parse_designations("FC Barcelona - Valencia CF\nAsistentes varios") == []


def test_discover_articles_filtra_indice():
    from futbol_pred.ingest.rfef_referees import _SOURCES
    _, _, _, bes_slug = _SOURCES[0]  # BeSoccer
    urls = discover_articles(_BES_INDEX_HTML, BESOCCER_BASE, bes_slug, _BES_INDEX_URL)
    assert _BES_ARTICLE_URL in urls
    assert all("designaciones" in u for u in urls)  # solo enlaces de designación


def test_directory_lookup_respeta_direccion():
    des = parse_designations(_ARTICLE)
    d = RefereeDirectory(des)
    assert d.lookup("FC Barcelona", "Valencia CF") == "Gil Manzano"
    assert d.lookup("Barcelona", "Valencia") == "Gil Manzano"
    assert d.lookup("Equipo Raro", "Otro") is None


def test_no_hereda_arbitro_en_el_partido_de_vuelta():
    d = RefereeDirectory([Designation(home="Barcelona", away="Valencia", referee="Gil Manzano")])
    assert d.lookup("FC Barcelona", "Valencia CF") == "Gil Manzano"
    assert d.lookup("Valencia CF", "FC Barcelona") is None


def test_to_text_preserva_limites_html_multiples_designaciones():
    html = ("<p>LALIGA EA SPORTS - JORNADA 6</p><table>"
            "<tr><td>FC Barcelona - Valencia CF</td><td>Árbitro: Gil Manzano</td></tr>"
            "<tr><td>Real Madrid CF - Athletic Club</td><td>Árbitro: Sánchez Martínez</td></tr>"
            "</table>Sevilla FC - Getafe CF<br>Árbitro: González Fuertes")
    got = {(d.home, d.away): d.referee for d in parse_designations(_to_text(html))}
    assert got.get(("Barcelona", "Valencia")) == "Gil Manzano"
    assert got.get(("Real Madrid", "Ath Bilbao")) == "Sánchez Martínez"
    assert got.get(("Sevilla", "Getafe")) == "González Fuertes"


def _fake_fetch(index_html, article_html):
    def fetch(url, timeout=20):
        if url == _BES_INDEX_URL:
            return index_html
        if url == _BES_ARTICLE_URL:
            return article_html
        return None  # resto de candidatas de BeSoccer y RFEF -> sin datos
    return fetch


def test_collect_usa_besoccer_como_primaria():
    des, source = collect_designations(fetch=_fake_fetch(_BES_INDEX_HTML, _ARTICLE))
    assert source == "BeSoccer"
    assert {(d.home, d.away) for d in des} >= {("Barcelona", "Valencia"), ("Sevilla", "Getafe")}
    assert all(d.source == "BeSoccer" for d in des)


def test_collect_defensivo_sin_red():
    des, source = collect_designations(fetch=lambda u, timeout=20: None)
    assert des == [] and source is None


def test_headers_emulan_navegador_para_evitar_406():
    # El WAF de BeSoccer devuelve HTTP 406 ante el `Accept: */*` de requests; la
    # cabecera debe declarar text/html y un User-Agent de navegador para pasar.
    from futbol_pred.ingest.rfef_referees import _HEADERS
    assert "text/html" in _HEADERS.get("Accept", "")
    assert "Mozilla/5.0" in _HEADERS.get("User-Agent", "")


def test_fetch_and_store_y_load_roundtrip(tmp_path):
    n = fetch_and_store(data_dir=tmp_path, fetch=_fake_fetch(_BES_INDEX_HTML, _ARTICLE))
    assert n == 3
    cache = json.loads((tmp_path / "referee_designations.json").read_text(encoding="utf-8"))
    assert cache["source"] == "BeSoccer" and len(cache["designations"]) == 3
    d = load_directory(tmp_path)
    assert len(d) == 3 and d.source == "BeSoccer"
    assert d.lookup("Real Madrid CF", "Athletic Club") == "Sánchez Martínez"


def test_fetch_and_store_no_borra_cache_si_falla(tmp_path):
    fetch_and_store(data_dir=tmp_path, fetch=_fake_fetch(_BES_INDEX_HTML, _ARTICLE))
    before = (tmp_path / "referee_designations.json").read_text(encoding="utf-8")
    n = fetch_and_store(data_dir=tmp_path, fetch=lambda u, timeout=20: None)
    assert n == 0
    assert (tmp_path / "referee_designations.json").read_text(encoding="utf-8") == before


def test_load_directory_defensivo(tmp_path):
    assert len(load_directory(tmp_path)) == 0
    (tmp_path / "referee_designations.json").write_text("{ roto", encoding="utf-8")
    assert len(load_directory(tmp_path)) == 0
