# 🏆 El sistema de la Champions — visión y arquitectura

Este documento traduce tus dos **prompts maestros** (motor predictivo LaLiga/
Champions + Quiniela 1ª/2ª) a la arquitectura del paquete `futbol_pred`. La
idea rectora: **conservar cada decisión que aprendiste a base de errores**, pero
sacarla del notebook de Colab y meterla en código modular, testeado y
automatizable por cron. Nada de lo tuyo se pierde; todo se endurece.

## Por qué la Champions es un problema distinto (y cómo lo resolvemos)

| Reto Champions (tus prompts) | Solución en el paquete |
|---|---|
| **La forma no puede salir solo de la Champions**: si Arsenal juega, su forma de Premier informa (#48). | `form.rolling_form(..., competition_filter=None)` mezcla TODAS las competiciones del equipo. |
| **Equipos de ligas distintas** sin rating común. | `elo.EloRatings`: un rating único para todos, cruzable entre ligas. |
| **`max(matchday)` no sirve**: fase de liga (1..8) + eliminatorias (#47). | `scheduling.next_fixtures` detecta la próxima ronda por fase+fecha, no por número. |
| **Nombres inconsistentes** entre fuentes al cruzar ligas (#29). | `normalize.canonical_team` con alias explícitos, avisa en vez de inventar cruces. |
| **Fuentes que fallan** (API-Football 403 en Champions, #69-P5). | `ingest/` degrada con elegancia; el pipeline nunca se cae por una fuente. |
| **FBref como capa avanzada de xG** para Champions (#79). | Módulo `ingest/fbref.py` previsto (roadmap), features vía `soccerdata`. |

## Pipeline end-to-end (lo que ejecutará el cron)

```
RAW  ─────────────▶  CLEAN  ─────▶  FEATURES  ─────▶  MODELS  ─────▶  PREDICT  ─────▶  REPORT
football-data.org   normalize     form (rolling      Dixon-Coles     score_matrix    storytelling
The Odds API        (equipos,      shift(1),          + Elo +         → mercados       + HTML + email
FBref (xG)           fechas)        multi-comp)        boosting        paramétricos
                    validación     Elo pre-match      por mercado     + value bets
```

Cada etapa es una carpeta/módulo; nunca se mezclan (tu principio #19/#84).

## Mapa completo: tus celdas → módulos

| Bloque de tu prompt | Celdas | Módulo `futbol_pred` | Estado |
|---|---|---|---|
| Config, logging, persistencia | C01–C05 | `config.py`, `db/` | ✅ |
| Ingesta multi-fuente + fallback | C06–C15 | `ingest/` | ✅ (base) |
| UPSERT incremental (SCHEDULED→FINISHED) | C18B | `db/` upsert | 🔜 |
| Normalización de equipos | C21, #29 | `normalize.py` | ✅ |
| Normalización fechas/temporadas | C22 | `clean.py` | 🔜 |
| Validación de calidad | C23, #67 | `validate.py` | 🔜 |
| Pivot stats API-Football | C24 | `ingest/` | 🔜 |
| Rolling features sin leakage | C26–C34, #33 | `form.py` | ✅ |
| Fuerza ofensiva/defensiva | #45 | `strength.py` | 🔜 |
| Elo cronológico | #46 | `elo.py` | ✅ |
| Detección jornada/fase | #30, #47 | `scheduling.py` | ✅ |
| Poisson / Dixon-Coles + score matrix | #35, #36 | `model/` | ✅ |
| Modelos por mercado (boosting) | #40, #41 | `model/markets_ml.py` | 🔜 |
| 1X2 + doble oportunidad | #37, #42 | `score_matrix.py` + `picks.py` | ✅ / 🔜 |
| Value betting (edge, Kelly) | #44 | `value/` | ✅ |
| Storytelling determinista | #52, #17 | `storytelling.py` | 🔜 |
| HTML + Gmail | #55–57 | `report/` | 🔜 |
| Backtesting walk-forward | #58–60 | `backtest/` | ✅ |

✅ construido y testeado · 🔜 siguiente iteración

## Reglas innegociables (heredadas de tus prompts)

1. **Cero data leakage** (#33): rolling con `shift(1)` por equipo; Elo solo se
   actualiza tras el partido. Está garantizado por diseño y cubierto por tests.
2. **Validación temporal** (#59): nunca `train_test_split(shuffle=True)`;
   walk-forward. Un modelo complejo solo entra si bate a los baselines (#61).
3. **Multi-fuente tolerante a nulls** (#25, #68): un `NaN` (desconocido) no es
   un `0` (ocurrió cero veces). Se imputa en la capa de modelo, no en RAW.
4. **Nada de lenguaje de certeza** (#74): probabilidades y edge, nunca "apuesta
   segura". El objetivo es ventaja estadística a largo plazo, no adivinar.

## Configuración de ligas

`config.LEAGUES` ya incluye `laliga` (140), `segunda` (141) y `champions` (2),
con `teams_per_round` para la detección de jornada (10 en LaLiga, 18 en la fase
de liga de la Champions de 36 equipos).

## Próximos pasos recomendados (en orden de valor)

1. ~~**Backtesting walk-forward**~~ — ✅ hecho (`backtest/`).
2. **UPSERT + refresco inteligente de temporada actual** (C07B/C18B) — sin esto,
   `Run all`/cron reusa datos viejos.
3. **xG real vía FBref** — cliente listo (`ingest/fbref.py`, correr en local con
   `soccerdata` y volcar a Parquet). Pendiente: mezclar xG en el modelo híbrido.
4. **Storytelling + informe HTML + email** — la capa de presentación que ya
   tenías, portada a `report/`.
