"""Normalización canónica de nombres de equipo entre fuentes.

Lección aprendida (prompt #29, #69-problema3): la normalización genérica
agresiva (bajar a minúsculas, quitar sufijos) produce colisiones y NaN al
cruzar fuentes. Aquí usamos un registro EXPLÍCITO de alias por equipo y solo
recurrimos a una heurística conservadora como último recurso, avisando.

Cada equipo tiene un ``canonical`` (nuestro identificador estable) y un
conjunto de alias tal como aparecen en football-data.org, football-data.co.uk,
API-Football, FBref, etc. Añadir una fuente = añadir alias, nunca reescribir.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TeamEntry:
    canonical: str
    aliases: tuple[str, ...] = field(default_factory=tuple)


# --- LaLiga 2025/26: mapeo explícito (de tu prompt, verificado) ------------
# canonical -> alias en distintas fuentes (org, co.uk, y variantes comunes).
_LALIGA: list[TeamEntry] = [
    TeamEntry("Girona", ("Girona FC",)),
    TeamEntry("Villarreal", ("Villarreal CF",)),
    TeamEntry("Mallorca", ("RCD Mallorca",)),
    TeamEntry("Alaves", ("Deportivo Alavés", "Alavés")),
    TeamEntry("Valencia", ("Valencia CF",)),
    TeamEntry("Celta", ("RC Celta de Vigo", "Celta Vigo", "Celta de Vigo")),
    TeamEntry("Ath Bilbao", ("Athletic Club", "Athletic Bilbao", "Athletic")),
    TeamEntry("Espanol", ("RCD Espanyol de Barcelona", "Espanyol")),
    TeamEntry("Elche", ("Elche CF",)),
    TeamEntry("Real Madrid", ("Real Madrid CF",)),
    TeamEntry("Betis", ("Real Betis Balompié", "Real Betis")),
    TeamEntry("Ath Madrid", ("Club Atlético de Madrid", "Atletico Madrid",
                             "Atlético Madrid", "Atlético de Madrid", "Atl. Madrid",
                             "Atl Madrid")),
    TeamEntry("Levante", ("Levante UD",)),
    TeamEntry("Osasuna", ("CA Osasuna",)),
    TeamEntry("Sociedad", ("Real Sociedad de Fútbol", "Real Sociedad")),
    TeamEntry("Oviedo", ("Real Oviedo",)),
    TeamEntry("Sevilla", ("Sevilla FC",)),
    TeamEntry("Vallecano", ("Rayo Vallecano de Madrid", "Rayo Vallecano")),
    TeamEntry("Getafe", ("Getafe CF",)),
    TeamEntry("Barcelona", ("FC Barcelona", "Barcelona FC")),
]

# --- Segunda y equipos españoles recientes (canónico = forma co.uk) --------
_SPAIN_EXTRA: list[TeamEntry] = [
    TeamEntry("Cadiz", ("Cádiz CF", "Cadiz CF")),
    TeamEntry("Almeria", ("UD Almería", "Almería")),
    TeamEntry("Granada", ("Granada CF",)),
    TeamEntry("Las Palmas", ("UD Las Palmas",)),
    TeamEntry("Leganes", ("CD Leganés", "Leganés")),
    TeamEntry("Valladolid", ("Real Valladolid CF", "Real Valladolid")),
    TeamEntry("Eibar", ("SD Eibar",)),
    TeamEntry("Malaga", ("Málaga CF", "Málaga")),
    TeamEntry("Zaragoza", ("Real Zaragoza",)),
    TeamEntry("Santander", ("Racing Santander", "Real Racing Club",
                            "Real Racing Club de Santander", "Racing de Santander")),
    TeamEntry("Sp Gijon", ("Sporting Gijón", "Real Sporting de Gijón",
                           "Sporting de Gijón", "Sporting Gijon")),
    TeamEntry("Tenerife", ("CD Tenerife",)),
    # Filiales: el nombre corto (co.uk) es el canónico; la quiniela usa el largo.
    TeamEntry("Sociedad B", ("Real Sociedad B", "Real Sociedad II")),
    TeamEntry("Celta B", ("RC Celta B", "Celta de Vigo B", "Celta Fortuna")),
    TeamEntry("Albacete", ("Albacete BP", "Albacete Balompié")),
    TeamEntry("Huesca", ("SD Huesca",)),
    TeamEntry("Mirandes", ("CD Mirandés", "Mirandés")),
    TeamEntry("Burgos", ("Burgos CF",)),
    TeamEntry("Cartagena", ("FC Cartagena",)),
    TeamEntry("Ferrol", ("Racing Ferrol", "Racing de Ferrol")),
    TeamEntry("Eldense", ("CD Eldense",)),
    TeamEntry("Amorebieta", ("SD Amorebieta",)),
    TeamEntry("Andorra", ("FC Andorra",)),
    TeamEntry("Alcorcon", ("AD Alcorcón", "Alcorcón")),
    TeamEntry("Castellon", ("CD Castellón", "Castellón")),
    TeamEntry("Cordoba", ("Córdoba CF", "Córdoba")),
    TeamEntry("Deportivo", ("Deportivo La Coruña", "RC Deportivo", "RC Deportivo de La Coruña",
                            "RC Deportivo La Coruña", "Dep. A Coruna", "Dep A Coruna", "La Coruna")),
]

# --- Grandes de Champions (para cruzar ligas; se irá ampliando) ------------
_EUROPE: list[TeamEntry] = [
    TeamEntry("Man City", ("Manchester City", "Manchester City FC")),
    TeamEntry("Arsenal", ("Arsenal FC",)),
    TeamEntry("Liverpool", ("Liverpool FC",)),
    TeamEntry("Bayern Munich", ("FC Bayern München", "Bayern", "Bayern München")),
    TeamEntry("Dortmund", ("Borussia Dortmund", "BVB")),
    TeamEntry("PSG", ("Paris Saint-Germain", "Paris Saint Germain", "Paris SG")),
    TeamEntry("Inter", ("Inter Milan", "FC Internazionale Milano", "Internazionale")),
    TeamEntry("Juventus", ("Juventus FC",)),
    TeamEntry("Milan", ("AC Milan", "Associazione Calcio Milan")),
    TeamEntry("Porto", ("FC Porto",)),
    TeamEntry("Benfica", ("SL Benfica", "Sport Lisboa e Benfica")),
]

_REGISTRY: list[TeamEntry] = _LALIGA + _SPAIN_EXTRA + _EUROPE

# Índice alias(normalizado) -> canonical, construido una vez.
_ALIAS_INDEX: dict[str, str] = {}


def _key(name: str) -> str:
    """Clave de comparación: sin acentos, sin puntuación, minúsculas."""
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = re.sub(r"[^a-z0-9 ]", " ", n.lower())
    return re.sub(r"\s+", " ", n).strip()


def _build_index() -> None:
    for entry in _REGISTRY:
        for name in (entry.canonical, *entry.aliases):
            _ALIAS_INDEX[_key(name)] = entry.canonical


_build_index()


class UnknownTeamWarning(UserWarning):
    pass


def canonical_team(name: str, strict: bool = False) -> str:
    """Devuelve el nombre canónico de un equipo desde cualquier fuente.

    Si no está en el registro:
      * strict=True  -> lanza KeyError (útil en tests/validación de datos).
      * strict=False -> devuelve el nombre original y emite un warning
        (nunca inventa un cruce silencioso: esa fue la causa de los NaN).
    """
    if name is None:
        raise ValueError("El nombre de equipo no puede ser None")
    k = _key(name)
    if k in _ALIAS_INDEX:
        return _ALIAS_INDEX[k]
    if strict:
        raise KeyError(f"Equipo no registrado: {name!r}")
    import warnings

    warnings.warn(
        f"Equipo no registrado, se usa el nombre original: {name!r}",
        UnknownTeamWarning,
        stacklevel=2,
    )
    return name


def register_team(canonical: str, aliases: list[str]) -> None:
    """Añade un equipo o alias en tiempo de ejecución (p. ej. nueva fuente)."""
    entry = TeamEntry(canonical, tuple(aliases))
    _REGISTRY.append(entry)
    for n in (canonical, *aliases):
        _ALIAS_INDEX[_key(n)] = canonical


def known_teams() -> list[str]:
    return sorted({e.canonical for e in _REGISTRY})
