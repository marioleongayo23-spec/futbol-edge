from futbol_pred.ingest.probable_lineup_media import EVIDENCE_HIERARCHY, covered_sides


def test_noticia_de_un_equipo_solo_cubre_ese_lado():
    sides = covered_sides(
        "Real Madrid CF",
        "Real Sociedad de Fútbol",
        "El once probable del Real Madrid para esta noche",
        "Ancelotti prepara cambios en la alineación titular.",
    )
    assert sides == ["local"]


def test_noticia_que_menciona_ambos_equipos_puede_cubrir_ambos_lados():
    sides = covered_sides(
        "Real Madrid CF",
        "Real Sociedad de Fútbol",
        "Posibles onces de Real Madrid y Real Sociedad",
        "Estas son las alineaciones probables de los dos equipos.",
    )
    assert sides == ["local", "visitante"]


def test_jerarquia_de_evidencia_es_explicita_y_no_rankea_cabeceras():
    assert EVIDENCE_HIERARCHY["official_lineup"] < EVIDENCE_HIERARCHY["trusted_media_recent"]
    assert EVIDENCE_HIERARCHY["trusted_media_recent"] < EVIDENCE_HIERARCHY["model_estimate"]
