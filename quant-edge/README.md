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
  fills parciales, paper trading `SHADOW_ONLY`, y una **puerta de aplicación** de
  14 condiciones que decide `SUPERADO` / `NO DEMOSTRADO`.
- **No:** no promete ausencia de pérdidas, no elige el "mejor" resultado a
  posteriori, no toca capital/beta real (todo es sombra), y no da por buena una
  conclusión basada solo en backtest.

## Estructura

```
quant-edge/
├── ESTUDIO.md              # ← documento de estudio (léelo primero)
├── config/                 # umbrales de la puerta y costes por activo
├── src/quantedge/
│   ├── data/               # contrato de datos, reconciliación 2 fuentes, sintético
│   ├── costs/              # comisión, diferencial, deslizamiento, impacto, impuestos
│   ├── strategies/         # momentum, tendencia, reversión, ruptura, vol
│   ├── backtest/           # motor largo/plano con latencia y fills parciales
│   ├── validation/         # métricas, splitters, MTC, bootstrap, walk-forward
│   ├── paper/              # bucle SHADOW_ONLY
│   ├── gate/               # puerta de aplicación (criterios ejecutables)
│   └── report/             # orquestador + artefactos con hashes
├── tests/                  # 22 pruebas (incluye "sin look-ahead")
└── reports/                # salidas generadas
```

## Uso

```bash
python -m pip install -r requirements.txt
PYTHONPATH=src python -m pytest tests -q
PYTHONPATH=src python -m quantedge.cli demo
```

Genera `reports/metrics.json`, `decision.json`, `manifest.json` (hashes
deterministas de datos y parámetros), `RESUMEN.md`, `oos_portfolio.csv` y
`shadow_ledger.csv`.

## Para pasar de `NO DEMOSTRADO` a una evaluación real

Enchufar datos reales point-in-time de ≥2 fuentes (`data/loader.RealVendorAdapter`),
medir costes reales por instrumento, y ejecutar ≥60 sesiones de paper trading
**hacia delante en vivo** (`SHADOW_ONLY`). Detalle en `ESTUDIO.md` §9.
