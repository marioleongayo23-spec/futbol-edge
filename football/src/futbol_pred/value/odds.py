"""Utilidades de cuotas: conversión, margen (vig) y probabilidad implícita."""

from __future__ import annotations


def decimal_to_implied(odds: float) -> float:
    """Probabilidad implícita bruta (incluye margen de la casa)."""
    if odds <= 1.0:
        raise ValueError("Una cuota decimal debe ser > 1.0")
    return 1.0 / odds


def implied_to_decimal(prob: float) -> float:
    if not 0 < prob < 1:
        raise ValueError("La probabilidad debe estar en (0, 1)")
    return 1.0 / prob


def remove_vig(odds: list[float], method: str = "proportional") -> list[float]:
    """Devuelve probabilidades 'justas' (suman 1) quitando el margen.

    ``proportional``: reparto proporcional (simple y robusto).
    ``power``: método de potencias (Shin-like), mejor para favoritos fuertes.
    """
    raw = [decimal_to_implied(o) for o in odds]
    booksum = sum(raw)
    if method == "proportional":
        return [p / booksum for p in raw]
    if method == "power":
        # Resuelve k tal que sum(p_i^k) = 1 por bisección.
        lo, hi = 0.5, 2.0
        for _ in range(60):
            k = (lo + hi) / 2
            s = sum(p**k for p in raw)
            if s > 1:
                lo = k
            else:
                hi = k
        k = (lo + hi) / 2
        adj = [p**k for p in raw]
        tot = sum(adj)
        return [p / tot for p in adj]
    raise ValueError(f"Método de vig desconocido: {method!r}")


def booksum_margin(odds: list[float]) -> float:
    """Margen del mercado (overround). 0.05 = 5% de comisión implícita."""
    return sum(decimal_to_implied(o) for o in odds) - 1.0
