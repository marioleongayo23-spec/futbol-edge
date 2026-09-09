"""Carga de configuración YAML con hash de reproducibilidad."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .hashing import hash_obj


@dataclass(frozen=True)
class LoadedConfig:
    data: dict[str, Any]
    sha256: str
    path: str


def load_config(path: str | Path) -> LoadedConfig:
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return LoadedConfig(data=raw, sha256=hash_obj(raw), path=str(p))
