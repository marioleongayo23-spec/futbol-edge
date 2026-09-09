# Resumen de ejecución — quant-edge

> ⚠️ DATOS SINTÉTICOS — no son mercado real, no son evidencia de ventaja.

**Decisión: NO DEMOSTRADO**

## Cartera fuera de muestra (neta, tras costes e impuestos)
- Media diaria geométrica mensual (media): `-0.0973%` (objetivo 0,40%)
- Mediana mensual: `-0.0066%`
- Media geométrica diaria global: `0.0073%`
- Drawdown máximo: `15.26%`
- Sharpe anualizado: `0.28`
- Meses cumpliendo objetivo: `0%`
- Benchmark (buy&hold) media diaria: `0.0204%`

## Robustez estadística
- Nº de configuraciones probadas (pruebas): `39`
- Sharpe Desinflado (DSR): `0.000` (umbral 0,95)
- PBO: `30.16%` (umbral 50%)
- IC95 media diaria (bootstrap): `[-0.0360%, 0.0535%]`
- Monte Carlo P(alcanzar objetivo): `0.0%`

## Condiciones de la puerta
- ❌ **media_diaria_geometrica_mensual>=objetivo** — Media OOS -0.0973% vs objetivo 0.40%
- ❌ **supera_benchmark** — OOS 0.0073%/día vs benchmark 0.0204%/día
- ❌ **mediana_mensual_no_negativa** — Mediana mensual -0.0066%
- ❌ **drawdown_bajo_limite** — Drawdown máx 15.26% vs límite 15.00%
- ✅ **escenarios_costes_latencia_positivos** — Media diaria geométrica > 0 en todos los escenarios de estrés de costes/latencia
- ❌ **aparece_en_varios_mercados** — 0/6 mercados cumplen objetivo
- ❌ **no_depende_de_mes_extremo** — Robusto a quitar el mejor mes y ningún mes concentra el resultado
- ✅ **supera_60_sesiones_futuras** — 250 sesiones simuladas
- ✅ **todas_SHADOW_ONLY** — Todas las operaciones registradas en modo SHADOW_ONLY
- ❌ **sharpe_desinflado_significativo** — DSR 0.000 (corrige nº de pruebas)
- ✅ **pbo_bajo** — Probabilidad de sobreajuste 30.16%
- ❌ **ic_bootstrap_media_diaria_positivo** — Límite inferior IC95 media diaria -0.0360%
- ❌ **datos_reales_dos_fuentes** — Datos intradía reales de >=2 fuentes independientes, point-in-time
- ❌ **sesiones_futuras_en_vivo** — Las 60+ sesiones son paper trading hacia delante en vivo, no backtest histórico

## Evidencia que falta
- media_diaria_geometrica_mensual>=objetivo: Media OOS -0.0973% vs objetivo 0.40%
- supera_benchmark: OOS 0.0073%/día vs benchmark 0.0204%/día
- mediana_mensual_no_negativa: Mediana mensual -0.0066%
- drawdown_bajo_limite: Drawdown máx 15.26% vs límite 15.00%
- aparece_en_varios_mercados: 0/6 mercados cumplen objetivo
- no_depende_de_mes_extremo: Robusto a quitar el mejor mes y ningún mes concentra el resultado
- sharpe_desinflado_significativo: DSR 0.000 (corrige nº de pruebas)
- ic_bootstrap_media_diaria_positivo: Límite inferior IC95 media diaria -0.0360%
- datos_reales_dos_fuentes: Datos intradía reales de >=2 fuentes independientes, point-in-time
- sesiones_futuras_en_vivo: Las 60+ sesiones son paper trading hacia delante en vivo, no backtest histórico
