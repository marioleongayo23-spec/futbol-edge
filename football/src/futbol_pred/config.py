"""Configuración central. Lee de variables de entorno / .env.

Sin claves de API el sistema sigue funcionando en 'modo offline' con datos
de ejemplo, para que los tests y el desarrollo no dependan de la red.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Carga .env si existe (dependencia opcional).
try:  # pragma: no cover - conveniencia de entorno
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

# parents[2] = carpeta 'football' (raíz del proyecto). Antes apuntaba un nivel
# más arriba y el feed se escribía fuera de la carpeta versionada.
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"

# Ligas objetivo (IDs de API-Football).
LEAGUES = {
    "laliga": 140,
    "segunda": 141,
    "champions": 2,
}

# Metadatos por liga. ``teams_per_round`` = partidos por jornada, usado por
# scheduling.next_fixtures para detectar la jornada actual (nunca max()).
# Champions (formato 36 equipos): fase de liga con 18 partidos por jornada.
LEAGUE_META = {
    "laliga": {"api_id": 140, "fd_code": "PD", "teams_per_round": 10},
    "segunda": {"api_id": 141, "fd_code": "SD", "teams_per_round": 11},
    "champions": {"api_id": 2, "fd_code": "CL", "teams_per_round": 18},
}


@dataclass
class Settings:
    api_football_key: str | None = os.getenv("API_FOOTBALL_KEY")
    football_data_api_key: str | None = os.getenv("FOOTBALL_DATA_API_KEY")
    odds_api_key: str | None = os.getenv("ODDS_API_KEY")
    database_url: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{DATA_DIR / 'futbol.db'}"
    )
    season: int = int(os.getenv("SEASON", "2025"))
    bankroll: float = float(os.getenv("BANKROLL", "1000"))
    min_edge: float = float(os.getenv("MIN_EDGE", "0.03"))
    kelly_multiplier: float = float(os.getenv("KELLY_MULTIPLIER", "0.25"))

    @property
    def offline(self) -> bool:
        """True si faltan claves y hay que tirar de datos de ejemplo."""
        return not self.api_football_key


settings = Settings()
