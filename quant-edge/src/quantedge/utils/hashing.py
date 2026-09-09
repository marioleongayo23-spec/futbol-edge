"""Reproducibilidad: hashes deterministas de datos, configuración y artefactos.

Todo resultado que se afirme debe poder reproducirse bit a bit. Guardamos el
sha256 de: el DataFrame de datos (tras normalizar orden y tipos), la config, y
cada artefacto generado. Esto permite a un revisor (Astra) verificar que las
métricas provienen exactamente de los datos y parámetros declarados.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_dataframe(df: pd.DataFrame) -> str:
    """Hash estable de un DataFrame.

    Ordena columnas, convierte a un buffer binario canónico (valores + índice +
    nombres de columna) para que el hash no dependa de detalles de memoria.
    """
    cols = sorted(map(str, df.columns))
    ordered = df.reindex(columns=cols)
    parts = [",".join(cols).encode("utf-8")]
    # Índice (fechas como int64 ns cuando sea datetime).
    idx = ordered.index
    if isinstance(idx, pd.DatetimeIndex):
        parts.append(idx.asi8.tobytes())
    else:
        parts.append(np.asarray(idx).astype("U").tobytes())
    # Valores en float64 con NaN normalizado; columnas no numéricas como texto.
    for c in cols:
        s = ordered[c]
        if pd.api.types.is_numeric_dtype(s):
            parts.append(np.ascontiguousarray(s.to_numpy(dtype="float64")).tobytes())
        else:
            parts.append(s.astype("U").to_numpy().tobytes())
    h = hashlib.sha256()
    for p in parts:
        h.update(hashlib.sha256(p).digest())
    return h.hexdigest()


def hash_obj(obj: Any) -> str:
    """Hash de un objeto serializable a JSON (config, parámetros, resultados)."""
    payload = json.dumps(obj, sort_keys=True, default=_default, separators=(",", ":"))
    return sha256_bytes(payload.encode("utf-8"))


def _default(o: Any):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.ndarray,)):
        return o.tolist()
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    raise TypeError(f"No serializable: {type(o)}")
