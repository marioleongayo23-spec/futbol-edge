"""Modelo CONGELADO: la decisión que se llevará al paper trading forward.

Crítico para la honestidad del test: el modelo (estrategia + parámetros por
instrumento) se congela ANTES de ver las sesiones futuras. El fichero guarda
también los hashes de los datos de desarrollo y la config, para que Astra pueda
auditar que el forward no reutilizó nada del futuro.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..costs.model import InstrumentCosts
from ..strategies.base import Strategy
from ..strategies.library import make_strategy


@dataclass
class FrozenModel:
    created_utc: str
    instruments: dict[str, dict]          # instrumento -> {"strategy": name, "params": {...}}
    costs: dict                           # asdict(InstrumentCosts)
    thresholds: dict
    dev_data_sha256: dict                 # instrumento -> hash de datos de desarrollo
    params_sha256: str
    note: str = "SHADOW_ONLY. Congelado antes de las sesiones forward."
    version: str = "0.1.0"

    def strategy_for(self, instrument: str) -> Strategy:
        spec = self.instruments[instrument]
        return make_strategy(spec["strategy"], spec.get("params", {}))

    def instrument_costs(self) -> InstrumentCosts:
        return InstrumentCosts(**self.costs)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> "FrozenModel":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)


def freeze_from_selection(
    selected_by_instrument: dict[str, Strategy],
    costs: InstrumentCosts,
    thresholds: dict,
    dev_data_sha256: dict,
    params_sha256: str,
) -> FrozenModel:
    from dataclasses import asdict as _asdict

    instruments = {
        name: {"strategy": strat.name, "params": strat.params}
        for name, strat in selected_by_instrument.items()
    }
    return FrozenModel(
        created_utc=datetime.now(timezone.utc).isoformat(),
        instruments=instruments,
        costs=_asdict(costs),
        thresholds=thresholds,
        dev_data_sha256=dev_data_sha256,
        params_sha256=params_sha256,
    )
