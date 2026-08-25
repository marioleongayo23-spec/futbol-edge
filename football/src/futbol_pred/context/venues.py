"""Registro versionado de estadios para geolocalizar previsiones meteorológicas."""

from __future__ import annotations

import re
import unicodedata


def _key(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).casefold()
    text = re.sub(r"\b(fc|cf|ca|rc|ud|cd|sd|club|de|la|el|b)\b", " ", text)
    return re.sub(r"[^a-z0-9]", "", text)


# Coordenadas del recinto, no del centro de la ciudad. Es un registro local
# auditable: si una sede cambia, se corrige aquí sin gastar llamadas a otra API.
_VENUES = {
    "Albacete": ("Carlos Belmonte", "Albacete", 38.981, -1.852),
    "Almeria": ("UD Almería Stadium", "Almería", 36.840, -2.435),
    "Andorra": ("Estadi Nacional", "Andorra la Vella", 42.505, 1.517),
    "Athletic Club": ("San Mamés", "Bilbao", 43.264, -2.950),
    "Ath Bilbao": ("San Mamés", "Bilbao", 43.264, -2.950),
    "Atletico Madrid": ("Riyadh Air Metropolitano", "Madrid", 40.436, -3.600),
    "Ath Madrid": ("Riyadh Air Metropolitano", "Madrid", 40.436, -3.600),
    "Barcelona": ("Spotify Camp Nou", "Barcelona", 41.381, 2.123),
    "Betis": ("Benito Villamarín", "Sevilla", 37.356, -5.982),
    "Real Betis": ("Benito Villamarín", "Sevilla", 37.356, -5.982),
    "Real Betis Balompié": ("Benito Villamarín", "Sevilla", 37.356, -5.982),
    "Burgos": ("El Plantío", "Burgos", 42.344, -3.680),
    "Cadiz": ("Nuevo Mirandilla", "Cádiz", 36.502, -6.273),
    "Castellon": ("Castalia", "Castellón", 39.994, -0.037),
    "Celta Vigo": ("Abanca Balaídos", "Vigo", 42.212, -8.739),
    "Celta": ("Abanca Balaídos", "Vigo", 42.212, -8.739),
    "Ceuta": ("Alfonso Murube", "Ceuta", 35.893, -5.307),
    "Cordoba": ("Nuevo Arcángel", "Córdoba", 37.872, -4.765),
    "Alaves": ("Mendizorrotza", "Vitoria-Gasteiz", 42.837, -2.688),
    "Deportivo Alavés": ("Mendizorrotza", "Vitoria-Gasteiz", 42.837, -2.688),
    "Eibar": ("Ipurua", "Eibar", 43.181, -2.475),
    "Elche": ("Martínez Valero", "Elche", 38.267, -0.663),
    "Eldense": ("Nuevo Pepico Amat", "Elda", 38.484, -0.793),
    "Getafe": ("Coliseum", "Getafe", 40.326, -3.715),
    "Girona": ("Montilivi", "Girona", 41.961, 2.828),
    "Granada": ("Nuevo Los Cármenes", "Granada", 37.153, -3.596),
    "Las Palmas": ("Estadio de Gran Canaria", "Las Palmas", 28.100, -15.456),
    "Leganes": ("Butarque", "Leganés", 40.340, -3.760),
    "Levante": ("Ciutat de València", "València", 39.495, -0.364),
    "Mallorca": ("Son Moix", "Palma", 39.590, 2.630),
    "Malaga": ("La Rosaleda", "Málaga", 36.734, -4.426),
    "Oviedo": ("Carlos Tartiere", "Oviedo", 43.361, -5.870),
    "Osasuna": ("El Sadar", "Pamplona", 42.796, -1.637),
    "Real Oviedo": ("Carlos Tartiere", "Oviedo", 43.361, -5.870),
    "Deportivo La Coruna": ("Abanca-Riazor", "A Coruña", 43.369, -8.417),
    "Dep La Coruna": ("Abanca-Riazor", "A Coruña", 43.369, -8.417),
    "Espanyol": ("RCDE Stadium", "Cornellà", 41.347, 2.076),
    "RCD Espanyol de Barcelona": ("RCDE Stadium", "Cornellà", 41.347, 2.076),
    "Rayo Vallecano": ("Vallecas", "Madrid", 40.392, -3.658),
    "Rayo Vallecano de Madrid": ("Vallecas", "Madrid", 40.392, -3.658),
    "Real Madrid": ("Santiago Bernabéu", "Madrid", 40.453, -3.688),
    "Racing Santander": ("El Sardinero", "Santander", 43.476, -3.793),
    "Real Racing Club de Santander": ("El Sardinero", "Santander", 43.476, -3.793),
    "Real Sociedad": ("Reale Arena", "San Sebastián", 43.301, -1.973),
    "Real Sociedad de Fútbol": ("Reale Arena", "San Sebastián", 43.301, -1.973),
    "Sociedad": ("Reale Arena", "San Sebastián", 43.301, -1.973),
    "Sabadell": ("Nova Creu Alta", "Sabadell", 41.557, 2.091),
    "Sevilla": ("Ramón Sánchez-Pizjuán", "Sevilla", 37.384, -5.970),
    "Sporting Gijon": ("El Molinón", "Gijón", 43.536, -5.637),
    "Sp Gijon": ("El Molinón", "Gijón", 43.536, -5.637),
    "Tenerife": ("Heliodoro Rodríguez López", "Santa Cruz de Tenerife", 28.463, -16.260),
    "Valencia": ("Mestalla", "València", 39.475, -0.358),
    "Valladolid": ("José Zorrilla", "Valladolid", 41.644, -4.762),
    "Villarreal": ("Estadio de la Cerámica", "Vila-real", 39.944, -0.104),
}
_BY_KEY = {_key(team): values for team, values in _VENUES.items()}


def venue_for(team: str) -> dict | None:
    values = _BY_KEY.get(_key(team))
    if not values:
        return None
    name, city, latitude, longitude = values
    return {
        "name": name,
        "city": city,
        "latitude": latitude,
        "longitude": longitude,
        "source": "registro Fútbol Edge v1",
    }
