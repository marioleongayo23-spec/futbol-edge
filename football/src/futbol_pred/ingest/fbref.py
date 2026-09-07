"""Cliente FBref (capa avanzada de xG y stats) vía la librería `soccerdata`.

La ingesta avanzada NO forma parte del cron de producción: FBref puede bloquear
IPs cloud/datacenter o pedir CAPTCHA. Este adaptador se usa en local/Colab para
generar snapshots versionados que luego consume :mod:`futbol_pred.advanced_stats`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..config import DATA_DIR
from ..normalize import canonical_team

FBREF_LEAGUES = {
    "laliga": "ESP-La Liga",
    "segunda": "ESP-La Liga 2",
    "champions": "INT-Champions League",
}

# Tipos/columnas útiles según la API actual de soccerdata. El tipo de portero es
# ``keeper``; ``keeper_adv`` era una suposición antigua no documentada.
USEFUL_COLUMNS = {
    "standard": ["Gls", "Ast", "xG", "npxG", "xAG", "PrgP", "PrgC"],
    "shooting": ["Sh", "SoT", "SoT%", "G/Sh", "npxG/Sh", "Dist"],
    "passing": ["Cmp%", "PrgP", "KP", "1/3", "PPA", "xA"],
    "gca": ["SCA", "SCA90", "GCA", "GCA90"],
    "defense": ["Tkl", "TklW", "Int", "Blocks", "Clr"],
    "keeper": ["PSxG", "PSxG+/-", "/90"],
    "possession": ["Touches", "Att Pen", "Carries", "PrgC", "CPA"],
}


def soccerdata_available() -> bool:
    try:
        import soccerdata  # noqa: F401

        return True
    except Exception:
        return False


class FBrefClient:
    """Descarga stats FBref para producir artefactos offline, nunca para cron."""

    def __init__(self, cache_dir: str | Path | None = None):
        if not soccerdata_available():
            raise RuntimeError(
                "FBref requiere 'soccerdata'. Instálalo con: pip install soccerdata. "
                "Ejecuta esta ingesta en local/Colab y publica después el snapshot; "
                "producción no depende del scraping en vivo."
            )
        self.cache_dir = Path(cache_dir) if cache_dir else DATA_DIR / "fbref_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _reader(self, league: str, season: int):
        import soccerdata as sd

        if league not in FBREF_LEAGUES:
            raise ValueError(f"Liga FBref no soportada: {league}")
        return sd.FBref(
            leagues=FBREF_LEAGUES[league],
            seasons=season,
            data_dir=self.cache_dir,
        )

    def team_season_stats(
        self,
        league: str,
        season: int,
        stat_type: str = "standard",
        *,
        opponent_stats: bool = False,
    ) -> pd.DataFrame:
        """Stats agregadas; ``opponent_stats`` permite xG concedido real."""
        reader = self._reader(league, season)
        df = reader.read_team_season_stats(
            stat_type=stat_type,
            opponent_stats=opponent_stats,
        )
        return normalize_fbref_teams(df)

    def team_match_stats(
        self,
        league: str,
        season: int,
        stat_type: str = "schedule",
        *,
        opponent_stats: bool = False,
        team: str | None = None,
        force_cache: bool = False,
    ) -> pd.DataFrame:
        """Stats por partido para construir un histórico fechado/as-of."""
        reader = self._reader(league, season)
        df = reader.read_team_match_stats(
            stat_type=stat_type,
            opponent_stats=opponent_stats,
            team=team,
            force_cache=force_cache,
        )
        return normalize_fbref_teams(df)

    def player_season_stats(
        self, league: str, season: int, stat_type: str = "standard"
    ) -> pd.DataFrame:
        """Stats por jugador; usa ``stat_type='keeper'`` para porteros."""
        reader = self._reader(league, season)
        return reader.read_player_season_stats(stat_type=stat_type)

    def save_parquet(self, df: pd.DataFrame, name: str) -> Path:
        out = self.cache_dir / f"{name}.parquet"
        try:
            df.to_parquet(out)
        except Exception:
            out = out.with_suffix(".csv")
            df.to_csv(out)
        return out


def normalize_fbref_teams(df: pd.DataFrame) -> pd.DataFrame:
    """Añade ``team_canonical`` cuando la tabla contiene una identidad de equipo."""
    out = df.copy()
    if "team" in out.columns:
        names = out["team"]
    elif out.index.name == "team":
        names = out.index.to_series()
    elif isinstance(out.index, pd.MultiIndex) and "team" in out.index.names:
        names = out.index.get_level_values("team").to_series(index=out.index)
    else:
        return out
    out["team_canonical"] = [canonical_team(str(name)) for name in names]
    return out
