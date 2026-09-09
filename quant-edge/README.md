# quant-edge — arnés de investigación y validación de estrategias

Marco **reproducible** para decidir, con honestidad estadística, si una estrategia
de inversión alcanza el objetivo de **≥0,4% de media diaria geométrica mensual**
(aspirando a 0,6%) **neto** de costes, latencia e impuestos — o para declarar que
**no está demostrado** y explicar exactamente qué evidencia falta.

> ⚠️ **Estado actual: `NO DEMOSTRADO`.** Ver **[`ESTUDIO.md`](ESTUDIO.md)** (el
> documento para revisión con Astra 6). Este entorno no tiene acceso a feeds de
> mercado reales, así que el arnés se demuestra sobre **datos sintéticos
> etiquetados** que **no son evidencia de ventaja**.

Vive junto a la app de fútbol de este repositorio pero es **independiente**;
comparte su filosofía —*promover un modelo solo si gana en validación temporal
fuera de muestra*—, aplicada a mercados financieros.

## Qué hace (y qué no)

- **Sí:** implementa purga+embargo, walk-forward anidado, holdout oculto, DSR/PSR,
  PBO (CSCV), bootstrap dependiente, Monte Carlo, modelo de costes con impacto y
  fills parciales, **adaptadores de datos reales con dual-source y caché**,
  **congelado del modelo**, **bucle forward `SHADOW_ONLY`** (en vivo o ensayo en
  seco), y una **puerta de aplicación** de 14 condiciones que decide `SUPERADO` /
  `NO DEMOSTRADO`.
- **No:** no promete ausencia de pérdidas, no elige el "mejor" resultado a
  posteriori, no toca capital/beta real (todo es sombra), y no da por buena una
  conclusión basada solo en backtest.

## Estructura

```
quant-edge/
├── ESTUDIO.md              # ← documento de estudio (léelo primero)
├── config/                 # umbrales de la puerta y costes por activo
├── src/quantedge/
│   ├── data/
│   │   ├── providers/      # binance, coinbase, polygon, csv (+ base HTTP/caché)
│   │   ├── loader.py       # contrato, registro de proveedores, load_dual_source
│   │   ├── dual_source.py  # reconciliación de 2 fuentes
│   │   └── synthetic.py    # generador sintético etiquetado
│   ├── costs/              # comisión, diferencial, deslizamiento, impacto, impuestos
│   ├── strategies/         # momentum, tendencia, reversión, ruptura, vol
│   ├── backtest/           # motor largo/plano con latencia y fills parciales
│   ├── validation/         # métricas, splitters, MTC, bootstrap, walk-forward, resample
│   ├── model/              # congelado del modelo (frozen.py)
│   ├── paper/              # SHADOW_ONLY: shadow.py y forward.py (libro + puerta combinada)
│   ├── gate/               # puerta de aplicación (criterios ejecutables)
│   └── report/             # orquestador + artefactos con hashes
├── tests/                  # 31 pruebas (incluye "sin look-ahead")
└── reports/                # salidas generadas
```

## Uso

```bash
python -m pip install -r requirements.txt
PYTHONPATH=src python -m pytest tests -q
PYTHONPATH=src python -m quantedge.cli demo --use-config   # estudio + congelado + ensayo forward
PYTHONPATH=src python -m quantedge.cli providers-check     # acceso a datos reales (aquí: 403)
```

Genera en `reports/`: `metrics.json`, `decision.json`, `forward_decision.json`,
`manifest.json` (hashes deterministas), `RESUMEN.md`, `frozen_model.json`,
`dev_robustness.json`, `oos_portfolio.csv`, `shadow_ledger.csv` y
`forward_ledger.jsonl`.

## Para pasar de `NO DEMOSTRADO` a una evaluación real

Ya no falta código, falta acceso a datos y tiempo real: levantar el bloqueo de
red (o ejecutar fuera del sandbox), `POLYGON_API_KEY` para acciones/ETF/FX
(cripto ya tiene Binance+Coinbase sin clave), cargar y reconciliar con
`load_dual_source`, medir costes reales, y correr `ForwardRunner.step(is_live=True)`
durante ≥60 sesiones. Detalle en `ESTUDIO.md` §9 y §11.
