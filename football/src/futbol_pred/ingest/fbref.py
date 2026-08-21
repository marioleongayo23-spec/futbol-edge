"""Cliente FBref (capa avanzada de xG y stats) vía la librería `soccerdata`.

Por qué `soccerdata` y no un scraper propio (tu prompt #26): habla con FBref de
forma EDUCADA — cachea a disco, respeta rate limits y normaliza tablas. Picar
HTML a mano es frágil y se rompe cada vez que FBref cambia el maquetado, además
de arriesgar baneos.

⚠️ IMPORTANTE — ejecución: FBref bloquea IPs de datacenter/cloud (los runners de
GitHub Actions suelen recibir 403). Por eso este cliente está pensado para
correr en TU máquina o Colab (IP residencial) y volcar los datos a Parquet, que
luego el modelo consume como capa `xg`. No lo llames desde el cron.

Instalación (opcional): pip install "futbol-pred[xg]"   (o: pip install soccerdata)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..config import DATA_DIR
from ..normalize import canonical_team

# Mapa de nuestras ligas a los identificadores de soccerdata/FBref.
FBREF_LEAGUES = {
    "laliga": "ESP-La Liga",
    "segunda": "ESP-La Liga 2",
    "champions": "INT-Champions League",
}

# Columnas de interés por tipo de tabla (subconjunto útil de tus #14-#22).
USEFUL_COLUMNS = {
    "standard": ["Gls", "Ast", "xG", "npxG", "xAG", "PrgP", "PrgC"],
    "shooting": ["Sh", "SoT", "SoT%", "G/Sh", "npxG/Sh", "Dist"],
    "passing": ["Cmp%", "PrgP", "KP", "1/3", "PPA", "xA"],
    "gca": ["SCA", "SCA90", "GCA", "GCA90"],
    "defense": ["Tkl", "TklW", "Int", "Blocks", "Clr"],
    "keeper_adv": ["PSxG", "PSxG+/-", "/90"],
    "possession": ["Touches", "Att Pen", "Carries", "PrgC", "CPA"],
}


def soccerdata_available() -> bool:
    try:
        import soccerdata  # noqa: F401

        return True
    except Exception:
        return False


class FBrefClient:
    """Descarga stats de FBref a nivel equipo/jugador vía soccerdata."""

    def __init__(self, cache_dir: str | Path | None = None):
        if not soccerdata_available():
            raise RuntimeError(
                "FBref requiere 'soccerdata'. Instálalo con: pip install soccerdata. "
                "Recuerda ejecutar la ingesta FBref en local/Colab, no en el cron "
                "(FBref bloquea IPs de datacenter)."
            )
        self.cache_dir = Path(cache_dir) if cache_dir else DATA_DIR / "fbref_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _reader(self, league: str, season: int):
        import soccerdata as sd

        return sd.FBref(
            leagues=FBREF_LEAGUES[league],
            seasons=season,
            data_dir=self.cache_dir,
        )

    def team_season_stats(
        self, league: str, season: int, stat_type: str = "standard"
    ) -> pd.DataFrame:
        """Stats de equipo por temporada, con nombres canónicos de equipo."""
        reader = self._reader(league, season)
        df = reader.read_team_season_stats(stat_type=stat_type)
        return normalize_fbref_teams(df)

    def player_season_stats(
        self, league: str, season: int, stat_type: str = "standard"
    ) -> pd.DataFrame:
        """Stats por jugador (para futuras features de alineación, tu #23-#24)."""
        reader = self._reader(league, season)
        return reader.read_player_season_stats(stat_type=stat_type)

    def save_parquet(self, df: pd.DataFrame, name: str) -> Path:
        out = self.cache_dir / f"{name}.parquet"
        try:
            df.to_parquet(out)
        except Exception:
            out = out.with_suffix(".csv")  # fallback CSV (tu #7)
            df.to_csv(out)
        return out


def normalize_fbref_teams(df: pd.DataFrame) -> pd.DataFrame:
    """Añade una columna 'team_canonical' resolviendo el nombre FBref.

    Trabaja sobre el índice ('team') o una columna 'team' si existe, sin
    inventar cruces (canonical_team avisa si no reconoce un equipo).
    """
    out = df.copy()
    if "team" in out.columns:
        names = out["team"]
    elif out.index.name == "team":
        names = out.index.to_series()
    elif isinstance(out.index, pd.MultiIndex) and "team" in out.index.names:
        names = out.index.get_level_values("team").to_series(index=out.index)
    else:
        return out  # sin equipo identificable, se devuelve tal cual
    out["team_canonical"] = [canonical_team(str(n)) for n in names]
    return out
