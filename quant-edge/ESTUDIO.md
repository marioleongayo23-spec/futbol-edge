# Estudio: ¿existe una ventaja de inversión que alcance ≥0,4% diario geométrico mensual?

**Entregable para revisión conjunta con Astra 6, previo a codificar la herramienta.**
Autor del arnés: sesión de investigación reproducible (`quant-edge/`).
Fecha: 2026-09-09.

> **Decisión final de esta fase: `NO DEMOSTRADO`.**
> No se propone aplicar ningún modelo ni cambiar ninguna beta. Abajo se detalla
> exactamente qué evidencia falta y cómo obtenerla. Todo lo ejecutado es
> `SHADOW_ONLY`.

Este documento acompaña a un framework **ejecutable y reproducible**
(`python -m quantedge.cli demo`) que implementa toda la maquinaria de validación
que exigiste. No sustituye a la evidencia empírica real; la hace posible y la
juzga con una puerta objetiva.

---

## 1. El objetivo y por qué la carga de la prueba es alta

El objetivo —media **diaria geométrica** de al menos **0,4%** por mes, aspirando a
0,6%, **neto** de comisiones, diferencial, deslizamiento, latencia e impuestos—
equivale, compuesto, a:

| Objetivo diario | ≈ mensual | ≈ anual (252 días compuestos) |
|---|---|---|
| 0,40% | **+8,74%** | **+173,5%** |
| 0,60% | **+13,39%** | **+351,5%** |

Como referencia de dominio público (neto, aproximado):

- Índice de bolsa a largo plazo: ~10%/año.
- Mejores fondos sistemáticos accesibles: ~15–25%/año.
- **Medallion (Renaissance), el mejor track record documentado de la historia:
  ~39%/año neto**, y cerrado a capital externo.

El objetivo solicitado es **4–9× el mejor track record conocido**, sostenido,
**sin apalancamiento, sin cortos, sin derivados**. Esto no lo hace imposible por
decreto, pero fija el **prior**: la probabilidad a priori de que una combinación
de señales sencillas y líquidas logre esto de forma robusta y fuera de muestra es
**muy baja**. En consecuencia, la exigencia de evidencia debe ser
proporcionalmente **muy alta**, y cualquier resultado bueno de un backtest debe
tratarse como sospechoso hasta que sobreviva a corrección por pruebas múltiples,
a costes realistas y a datos que el modelo nunca vio. Ese es exactamente el
diseño del arnés.

Nota adicional sobre la métrica: una **media diaria geométrica mensual** premia
la consistencia y penaliza la volatilidad y las rachas negativas (la media
geométrica ≤ aritmética). Es una métrica honesta —difícil de "maquillar" con un
mes extremo— y por eso se ha adoptado literalmente en la puerta.

---

## 2. Alcance (Fase 1)

Conforme a tu encargo:

- **Instrumentos:** acciones, ETF, divisas, materias primas y criptomonedas
  líquidas.
- **Prohibido en fase 1:** apalancamiento, martingala, CFDs, opciones, futuros,
  posiciones cortas. Peso por instrumento acotado a **[0, 1]** (largo/plano).
- **Hipótesis investigadas:** momentum, tendencia (cruce de medias), reversión a
  la media (z-score), rupturas (Donchian), volatilidad (escalado por vol),
  régimen y combinaciones sencillas. Familias implementadas en
  `strategies/library.py`; el estudio mide si **alguna** aporta ventaja **neta
  fuera de muestra**, no busca una señal exótica.
- **Descartado por diseño:** cualquier dependencia de fuga de información,
  sesgo de supervivencia, look-ahead o datos revisados a posteriori
  (ver §7, Amenazas a la validez, y las salvaguardas de código en §4).

---

## 3. Datos y ejecución

### 3.1 Requisitos (tu encargo)
- Intradía histórico con **bid/ask, volumen, calendario de mercado, latencia,
  fills parciales y costes por instrumento**.
- **Al menos dos fuentes independientes**, reconciliadas.
- Modelado de **impacto de mercado** y pruebas de **retraso de ejecución**.

### 3.2 Estado en este entorno (importante y honesto)
Este entorno de ejecución **no tiene acceso a feeds de mercado**: la política de
egress deniega los hosts de datos (p. ej. `stooq.com` devolvió `403`), y las
fuentes gratuitas diarias **no traen bid/ask**. Por tanto **no es posible
producir aquí la evidencia empírica real** (datos intradía reales de dos fuentes
+ sesiones futuras en vivo).

Lo que sí se ha construido (**todo el andamiaje, listo para datos reales**):

- **Contrato de datos** y validaciones (`data/loader.py`): columnas mínimas
  `mid, bid, ask, volume_value, sigma_bar, spread_bps`, índice temporal
  ascendente y sin duplicados, `ask ≥ bid`.
- **Adaptadores de proveedores reales** (`data/providers/`), con red real,
  **caché en disco** (reproducible y offline tras la primera descarga) y
  `check_connectivity()` honesto ante bloqueos:
  - `binance.py` y `coinbase.py`: cripto **sin clave** → par **dual-source**
    real e independiente.
  - `polygon.py`: acciones, ETF, FX y cripto (requiere `POLYGON_API_KEY`);
    aggregates con VWAP para `volume_value`.
  - `csv_provider.py`: datos offline o aportados por el usuario (respeta bid/ask
    reales si el CSV los trae).
  - En este entorno los cuatro hosts responden **403** (verificable con
    `python -m quantedge.cli providers-check`).
- **Reconciliación de dos fuentes** (`data/dual_source.py` + `loader.load_dual_source`):
  detección de discrepancias, árbitro por consenso (mediana móvil), informe de
  calidad. Emparejamiento por defecto por clase de activo en `DUAL_SOURCE_MAP`.
- **Generador sintético etiquetado** (`data/synthetic.py`) con volatilidad
  agrupada (GARCH(1,1)) y regímenes, **solo** para probar la maquinaria. Va
  marcado en cada artefacto: *"DATOS SINTÉTICOS — no son evidencia de ventaja"*.
- **Soporte intradía** (`validation/resample.py`): las barras pueden ser
  intradía; se componen a retorno diario para medir el objetivo (que es diario).
  bid/ask reales requieren datos L1/quotes del proveedor; con OHLCV se estiman y
  queda marcado (`bidask_estimated`).

---

## 4. Metodología de validación (sin fuga, anti-sobreajuste)

Implementada en `validation/` y `backtest/`.

1. **Sin look-ahead por construcción.** Las señales usan solo ventanas que
   terminan en `t`; el motor (`backtest/engine.py`) impone un retardo
   estructural de 1 barra más `latency_bars` de latencia. Test unitario
   `test_no_lookahead_shift` lo verifica.
2. **Purga + embargo** (`validation/splitters.py`, López de Prado): se eliminan
   del entrenamiento las muestras cuya etiqueta solapa con el test y una banda de
   embargo posterior. Test `test_purged_kfold_no_overlap_and_embargo`.
3. **Walk-forward anidado** (`validation/walkforward.py`): bucle externo
   train→OOS; dentro de cada train, **CV purgada** para elegir hiperparámetros.
   El test externo **nunca** interviene en la selección.
4. **Holdout final oculto** (`validation/splitters.holdout_split`): el último
   tramo se reserva, separado por purga+embargo, y se evalúa **una sola vez**.
5. **Corrección por pruebas múltiples:**
   - **Sharpe Desinflado (DSR)** y **Sharpe Probabilístico (PSR)**
     (`validation/metrics.py`): corrigen el Sharpe por longitud de muestra,
     no-normalidad y **número de configuraciones probadas**.
   - **PBO por CSCV** (`validation/multiple_testing.py`): probabilidad de que la
     mejor config en muestra quede bajo la mediana fuera de muestra.
   - **Bonferroni / Benjamini-Hochberg** para p-valores múltiples.
6. **Bootstrap dependiente** (`validation/bootstrap.py`): bootstrap estacionario
   (Politis-Romano) y por bloques → intervalos de confianza que respetan la
   autocorrelación. **Monte Carlo** de trayectorias para la distribución de
   drawdown, probabilidad de pérdida y probabilidad de alcanzar el objetivo.

**Regla dura:** el conjunto de test **no se usa para elegir parámetros**. Si algo
falla, **no** se busca otro parámetro sobre el test (eso lo convertiría en
entrenamiento). Se declara qué falta.

---

## 5. Modelo de costes y ejecución (`costs/model.py`)

Todo se juzga **neto**. Componentes por operación:

- **Comisión** (bps del nocional), **medio diferencial** (bps por lado),
  **deslizamiento** (∝ volatilidad del bar).
- **Impacto de mercado** por **ley de la raíz cuadrada**:
  `coste ≈ coef · σ · sqrt(Q/ADV)`.
- **Fills parciales:** la ejecución se limita a `max_participation · volumen`;
  el resto se arrastra a barras siguientes.
- **Latencia:** retardo de ejecución de `latency_bars`.
- **Impuestos:** tasa sobre la ganancia neta positiva anual (conservador: sin
  compensar pérdidas entre años).

**Escenarios de estrés:** la puerta re-evalúa las **mismas decisiones** con
costes ×1,5 y ×2 (`InstrumentCosts.scaled`). Si el resultado deja de ser positivo
bajo fricción peor, no es robusto.

---

## 6. La puerta de aplicación como código (`gate/evaluate.py`)

Cada condición de tu encargo es un criterio ejecutable. **Si falla una sola →
`NO DEMOSTRADO`.** Umbrales en `config/gate.yaml`.

| # | Condición | Criterio |
|---|---|---|
| 1 | Media diaria geométrica mensual ≥ objetivo | ≥ 0,40% |
| 2 | Supera al benchmark | media diaria OOS > buy&hold neto |
| 3 | Mediana mensual no negativa | ≥ 0 |
| 4 | Drawdown máximo bajo límite | ≤ 15% (configurable) |
| 5 | Escenarios de costes/latencia positivos | media diaria > 0 con costes ×1,5 y ×2 |
| 6 | Aparece en varios mercados/regímenes | ≥ 3 mercados cumplen objetivo |
| 7 | No depende de un mes extremo | ningún mes aporta >50% del log-retorno **y** sigue ≥0 sin el mejor mes |
| 8 | ≥ 60 sesiones futuras simuladas | nº sesiones ≥ 60 |
| 9 | Todas SHADOW_ONLY | 100% de operaciones en sombra |
| 10 | Sharpe Desinflado significativo | DSR ≥ 0,95 |
| 11 | PBO bajo | ≤ 50% |
| 12 | IC bootstrap de la media diaria | límite inferior IC95 > 0 |
| 13 | **Datos reales de ≥2 fuentes** | point-in-time, sin revisiones |
| 14 | **Sesiones futuras en vivo** | paper trading hacia delante, no backtest histórico |

Las condiciones 13 y 14 son **bloqueantes de honestidad**: garantizan que un
"aprobado" nunca provenga de datos simulados ni de un backtest disfrazado de
"futuro".

---

## 7. Amenazas a la validez (y cómo se neutralizan)

| Amenaza | Mitigación en el arnés |
|---|---|
| Look-ahead | Señales causales + retardo de ejecución; test unitario. |
| Fuga por solapamiento de etiquetas | Purga + embargo en toda CV/walk-forward. |
| Sesgo de selección / pruebas múltiples | DSR + PBO; se cuenta el nº real de configs. |
| Sobreajuste de hiperparámetros | Selección solo en train; holdout intocado. |
| Autocorrelación al medir significancia | Bootstrap por bloques/estacionario. |
| Costes/impacto subestimados | Modelo explícito + estrés ×1,5/×2. |
| Dependencia de un mes/operación | Condición 7 (concentración + leave-best-out). |
| Sesgo de supervivencia | Requisito de universo point-in-time con deslistados (pendiente de datos reales). |
| Datos revisados a posteriori | Requisito point-in-time en el adaptador real. |
| Cambio de régimen / capacidad | Multi-mercado (cond. 6) + impacto por ADV; capacidad a validar con datos reales. |
| Fiscalidad/jurisdicción | Tasa configurable; a ajustar por instrumento/país. |

---

## 8. Ejecución demostrativa (control sintético neutro)

`python -m quantedge.cli demo --n-days 1000` corre TODO el pipeline sobre el
universo sintético (6 instrumentos, 5 clases de activo), con 39 configuraciones
candidatas, walk-forward anidado, holdout, estrés de costes y 250 sesiones en
sombra. Resultado (reproducible; hashes en `reports/manifest.json`):

- Media diaria geométrica mensual OOS: **−0,10%** (objetivo 0,40%).
- Mediana mensual: **−0,01%**. Drawdown máx: **15,3%**.
- **No supera** al benchmark buy&hold. **DSR ≈ 0,000**. PBO 30%.
- IC95 de la media diaria: **[−0,036%, +0,054%]** (incluye el 0).
- Monte Carlo P(alcanzar objetivo) ≈ **0%**.
- **Decisión: `NO DEMOSTRADO`** (fallan 10 de 14 condiciones).

**Lectura correcta:** el control sintético **no** demuestra que "no exista
ventaja en mercados reales"; demuestra dos cosas útiles:
1. El arnés **no es una máquina de aprobar**: rechaza correctamente cuando no hay
   señal robusta (DSR≈0, IC que cruza 0, por debajo del benchmark).
2. Las familias de señales **sencillas**, tal cual, **no son un atajo**: sin
   estructura explotable, y con costes reales, no clarean la barra.

---

## 9. Flujo forward y congelado del modelo (ya implementado)

El andamiaje para la evaluación real está **construido y probado**:

1. **Congelado del modelo** (`model/frozen.py`): tras el estudio se serializa
   `frozen_model.json` con la estrategia+parámetros elegidos por instrumento, los
   costes, los umbrales y los **hashes de los datos de desarrollo**. Esto ancla
   que el forward no reutiliza nada del futuro.
2. **Libro forward `SHADOW_ONLY`** (`paper/forward.py`): `ForwardLedger`
   (JSONL append-only) acumula sesiones; `ForwardRunner.step()` es el gancho de
   uso **en vivo** (decide con datos hasta t-1, registra el retorno realizado);
   `replay_forward()` hace un **ensayo en seco** sobre el holdout (marcado
   `is_live=False`, por lo que jamás cuenta como sesión en vivo).
3. **Puerta combinada** (`combined_gate`): junta la robustez de desarrollo
   (DSR/PBO/multi-mercado, de `dev_robustness.json`) con el rendimiento forward
   acumulado y decide.

## 9-bis. Evidencia que falta para poder emitir `SUPERADO`

Ya no falta *código*; falta **acceso a datos y tiempo real**:

1. **Acceso a los feeds** (levantar el bloqueo 403 o ejecutar fuera del sandbox)
   y, para acciones/ETF/FX, una **`POLYGON_API_KEY`** (u otro vendor). Cripto ya
   tiene dos fuentes sin clave (Binance + Coinbase).
2. **Datos intradía reales, point-in-time**, incluyendo **instrumentos
   deslistados** (contra supervivencia), reconciliados con `load_dual_source`.
3. **Costes reales por instrumento** medidos (diferencial efectivo, impacto,
   comisiones, fiscalidad de la jurisdicción) en `config/costs.yaml`.
4. **≥60 sesiones de paper trading EN VIVO** (`ForwardRunner.step`, `is_live=True`),
   decididas en el momento con datos que el modelo congelado no vio.
5. Repetir la puerta combinada. Solo si **las 14** condiciones pasan a la vez →
   `SUPERADO`. Si falla una, se documenta cuál y por qué, **sin** re-elegir
   parámetros sobre el test.

---

## 10. Decisión final

**`NO DEMOSTRADO`.** Doble motivo, ambos honestos:

- **Estructural:** este entorno no permite obtener datos reales de dos fuentes ni
  ejecutar sesiones futuras en vivo → las condiciones 13 y 14 no pueden
  satisfacerse aquí. Solo eso ya obliga a `NO DEMOSTRADO`.
- **Empírico (control neutro):** con señales sencillas sobre datos sin ventaja
  explotable y costes realistas, el sistema no clarea la barra, confirmando que
  el arnés rechaza como debe.

No se cambia ninguna beta. No se promete ausencia de pérdidas. El siguiente paso
es la lista de §9, ejecutada sobre datos reales, con Astra revisando cada pieza.

---

## 11. Cómo reproducir

```bash
cd quant-edge
python -m pip install -r requirements.txt
PYTHONPATH=src python -m pytest tests -q             # 31 pruebas del arnés
PYTHONPATH=src python -m quantedge.cli demo --use-config   # estudio + congelado + ensayo forward
PYTHONPATH=src python -m quantedge.cli providers-check     # acceso a datos reales (aquí: 403)
PYTHONPATH=src python -m quantedge.cli forward-replay      # replay del holdout como forward (seco)
PYTHONPATH=src python -m quantedge.cli gate \
    --ledger reports/forward_ledger.jsonl \
    --robustness reports/dev_robustness.json --benchmark 0.0002
# Artefactos: reports/{metrics.json, decision.json, forward_decision.json,
#   manifest.json, RESUMEN.md, frozen_model.json, dev_robustness.json,
#   oos_portfolio.csv, shadow_ledger.csv, forward_ledger.jsonl}
```

### Ejecutar con datos reales (fuera de este sandbox)
```bash
export POLYGON_API_KEY=...            # solo para acciones/ETF/FX; cripto no necesita clave
# 1) comprobar acceso
PYTHONPATH=src python -m quantedge.cli providers-check
# 2) cargar y reconciliar dos fuentes (ejemplo cripto en código):
#    from quantedge.data.loader import build_default_providers, load_dual_source
#    prov = build_default_providers()
#    df, rep = load_dual_source(prov, "crypto",
#              {"binance": "BTCUSDT", "coinbase": "BTC-USD"}, interval="1d")
# 3) alimentar el estudio con esos df en lugar del universo sintético,
#    congelar el modelo y arrancar ForwardRunner.step() en vivo (is_live=True).
```

Los hashes de `manifest.json` (params y datos) son deterministas: dos ejecuciones
producen los mismos, lo que permite a Astra auditar que las métricas provienen
exactamente de los datos y parámetros declarados.
