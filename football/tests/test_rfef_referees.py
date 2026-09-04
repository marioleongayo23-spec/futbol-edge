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


# --- Prensa vía Google News RSS (fuente primaria, sin muro) ------------------
from datetime import datetime, timezone
from email.utils import format_datetime

from futbol_pred.ingest.rfef_referees import parse_media_text, collect_from_media

_NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def test_parse_media_ronda_para_el_con_apodos_y_separadores():
    # Formato dominante en prensa: "<árbitro> para el <local>-<visitante>", con
    # apodos (Barça, Atleti, Rayo, Madrid), separador ';' y ' y ', y sufijo de
    # cabecera ' - AS' que añade Google News al final del titular.
    txt = ("Los árbitros de la jornada 3: Gil Manzano para el Barça-Valencia; "
           "Alberola Rojas para el Atleti-Rayo y Soto Grado para el Betis-Madrid - AS")
    got = {(d.home, d.away): d.referee for d in parse_media_text(txt)}
    assert got[("Barcelona", "Valencia")] == "Gil Manzano"
    assert got[("Ath Madrid", "Vallecano")] == "Alberola Rojas"
    assert got[("Betis", "Real Madrid")] == "Soto Grado"


def test_parse_media_dirigira_y_arbitrara():
    assert parse_media_text("De Burgos Bengoetxea dirigirá el Real Madrid-Real Sociedad")[0] == \
        Designation(home="Real Madrid", away="Sociedad", referee="De Burgos Bengoetxea",
                    raw_home="Real Madrid", raw_away="Real Sociedad")
    d = parse_media_text("Hernández Hernández arbitrará el Villarreal-Osasuna")
    assert d and (d[0].home, d[0].away, d[0].referee) == ("Villarreal", "Osasuna", "Hernández Hernández")


def test_parse_media_tambien_admite_formato_local_visitante_arbitro():
    # parse_designations sigue cubriendo "Local - Visitante: Árbitro".
    d = parse_media_text("Real Betis - Real Madrid: González Fuertes (Comité Asturiano)")
    assert d and (d[0].home, d[0].away, d[0].referee) == ("Betis", "Real Madrid", "González Fuertes")


def _rss(items_xml: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
            + items_xml + "</channel></rss>")


def _item(title, source, when=_NOW, desc="x"):
    return (f"<item><title>{title}</title><description>{desc}</description>"
            f'<source url="https://x">{source}</source>'
            f"<pubDate>{format_datetime(when)}</pubDate><link>https://x/a</link></item>")


def _news_fetch(rss_xml):
    def fetch(url, timeout=20):
        return rss_xml if "news.google.com" in url else None
    return fetch


def test_collect_from_media_extrae_de_cabecera_confiable():
    rss = _rss(_item("Gil Manzano para el Barça-Valencia; Soto Grado para el Betis-Madrid - AS", "AS"))
    des = collect_from_media(fetch=_news_fetch(rss), now=_NOW)
    got = {(d.home, d.away): (d.referee, d.source) for d in des}
    assert got[("Barcelona", "Valencia")] == ("Gil Manzano", "AS")
    assert got[("Betis", "Real Madrid")] == ("Soto Grado", "AS")


def test_collect_from_media_ignora_fuente_no_confiable():
    rss = _rss(_item("Gil Manzano para el Barça-Valencia", "Blog Random"))
    assert collect_from_media(fetch=_news_fetch(rss), now=_NOW) == []


def test_collect_from_media_ignora_noticia_vieja():
    old = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)  # >120h antes de _NOW
    rss = _rss(_item("Gil Manzano para el Barça-Valencia", "AS", when=old))
    assert collect_from_media(fetch=_news_fetch(rss), now=_NOW) == []


def test_collect_designations_usa_prensa_como_primaria():
    rss = _rss(_item("Mateu Lahoz para el Sevilla-Getafe", "MARCA"))
    des, source = collect_designations(fetch=_news_fetch(rss), now=_NOW)
    assert source == "prensa"
    assert des and (des[0].home, des[0].away, des[0].referee) == ("Sevilla", "Getafe", "Mateu Lahoz")


def test_collect_from_media_defensivo_sin_red():
    assert collect_from_media(fetch=lambda u, timeout=20: None, now=_NOW) == []


# --- Consulta POR PARTIDO + fixes de review (Codex P2) ----------------------
from futbol_pred.ingest.rfef_referees import referee_in_text, _fixture_pairs

_FIXTURE = [("Real Betis Balompié", "Real Madrid CF", "Betis", "Real Madrid")]


def test_referee_in_text_formatos_frecuentes():
    assert referee_in_text("Munuera Montero, árbitro del Betis-Real Madrid") == "Munuera Montero"
    assert referee_in_text("El árbitro del partido será Díaz de Mera Escuderos") == "Díaz de Mera Escuderos"
    assert referee_in_text("Hernández Hernández pitará el choque") == "Hernández Hernández"
    # 'colegiado X … en el VAR' es el VAR, no el árbitro principal.
    assert referee_in_text("El colegiado Gil Manzano estará en el VAR") is None
    # un equipo no es un árbitro.
    assert referee_in_text("Real Madrid, árbitro del derbi") is None


def test_parse_media_preserva_particulas_en_el_nombre():
    # Codex P2: no truncar 'Díaz de Mera Escuderos' a 'Mera Escuderos'.
    des = parse_media_text("Díaz de Mera Escuderos para el Sevilla-Getafe")
    assert des and des[0].referee == "Díaz de Mera Escuderos"


def test_collect_from_media_por_partido_extrae_el_nombre():
    rss = _rss(_item("Munuera Montero será el árbitro del Betis - Real Madrid de este sábado - AS", "AS"))
    des = collect_from_media(fetch=_news_fetch(rss), now=_NOW, fixtures=_FIXTURE)
    assert [(d.home, d.away, d.referee, d.source) for d in des] == [("Betis", "Real Madrid", "Munuera Montero", "AS")]


def test_collect_from_media_descarta_otra_competicion():
    # Codex P2: una pieza de Copa del Rey de los mismos clubes NO fija el árbitro de Liga.
    rss = _rss(_item("Munuera Montero, árbitro del Betis-Real Madrid de Copa del Rey - AS", "AS"))
    assert collect_from_media(fetch=_news_fetch(rss), now=_NOW, fixtures=_FIXTURE) == []


def test_fetch_and_store_merge_no_borra_designaciones_previas(tmp_path):
    # Codex P2: un resultado PARCIAL de prensa no debe borrar el resto de la jornada.
    (tmp_path / "referee_designations.json").write_text(json.dumps({
        "fetched_at": _NOW.isoformat(), "source": "prensa",
        "designations": [{"home": "Sevilla", "away": "Getafe", "referee": "Gil Manzano",
                          "fetched_at": _NOW.isoformat()}]}), encoding="utf-8")
    (tmp_path / "dashboard.json").write_text(json.dumps({"matches": [
        {"home": "Real Betis Balompié", "away": "Real Madrid CF",
         "kickoff": "2026-09-06T20:00:00+02:00"}]}), encoding="utf-8")
    rss = _rss(_item("Munuera Montero será el árbitro del Betis - Real Madrid - AS", "AS"))
    n = fetch_and_store(data_dir=tmp_path, fetch=_news_fetch(rss), now=_NOW)
    d = load_directory(tmp_path)
    assert n == 1
    assert d.lookup("Sevilla", "Getafe") == "Gil Manzano"          # NO borrado
    assert d.lookup("Real Betis Balompié", "Real Madrid CF") == "Munuera Montero"  # añadido


def test_fixture_pairs_salta_los_que_ya_tienen_arbitro(tmp_path):
    (tmp_path / "dashboard.json").write_text(json.dumps({"matches": [
        {"home": "Sevilla FC", "away": "Getafe CF", "kickoff": "2026-09-05T20:00:00+02:00",
         "official_context": {"referee": "Ya asignado"}},
        {"home": "Real Betis Balompié", "away": "Real Madrid CF",
         "kickoff": "2026-09-06T20:00:00+02:00"}]}), encoding="utf-8")
    canon = {(p[2], p[3]) for p in _fixture_pairs(tmp_path, _NOW)}
    assert ("Betis", "Real Madrid") in canon
    assert ("Sevilla", "Getafe") not in canon  # ya tiene árbitro de la API
