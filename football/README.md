# ⚽ futbol-pred — Predicción de fútbol y apuestas

Sistema automatizado de predicción para **LaLiga, Segunda División y Champions
League**: probabilidades de mercados (1X2, over/under, hándicaps asiáticos,
BTTS, resultado exacto...), detección de **value bets** frente a las cuotas y
generación de la **quiniela española** (14 + Pleno al 15).

> ⚠️ **Aviso honesto.** Ningún modelo acierta siempre: el fútbol tiene azar
> irreducible. El objetivo de este sistema es tener **ventaja medible (edge)
> sobre las cuotas** a largo plazo, con gestión de bankroll — no "adivinar"
> cada partido. Úsalo con responsabilidad.

## Arquitectura

```
Ingesta (API-Football, The Odds API, FBref/xG) ──▶ BBDD (SQLite → Postgres)
        │                                               │
   Cron (GitHub Actions)                                ▼
        │                                    Motor de predicción
        │                              (Dixon-Coles + corrección + xG)
        ▼                                               │
   Value bets · Submercados · Quiniela ◀────────────────┘
```

## Componentes

| Módulo | Qué hace |
|--------|----------|
| `model/score_matrix.py` | Matriz conjunta de goles → **cualquier mercado paramétrico** (líneas ±). |
| `model/dixon_coles.py`  | Modelo Dixon-Coles con ponderación temporal y corrección de resultados bajos. |
| `value/odds.py`         | Cuotas: quitar margen (vig), probabilidad justa. |
| `value/detector.py`     | Detección de value bets (edge = prob·cuota − 1). |
| `value/bankroll.py`     | Staking con criterio de Kelly fraccionado. |
| `quiniela/generator.py` | Quiniela 14 + Pleno al 15, con dobles/triples en los partidos inciertos. |
| `ingest/`               | Clientes API-Football y The Odds API (degradan a datos de ejemplo sin claves). |
| `db/`                   | Modelos SQLAlchemy y sesiones (SQLite/Postgres). |
| `pipeline.py`           | Orquestación end-to-end (lo que ejecuta el cron). |

## Uso rápido

```bash
cd football
pip install -r requirements.txt

# Pipeline completo (offline con datos de ejemplo si no hay claves):
python -m futbol_pred.cli run --league laliga

# Detección de value dado tus probs y cuotas:
python -m futbol_pred.cli value --probs 0.55,0.25,0.20 --odds 2.1,3.6,3.4

# Backtesting walk-forward (baseline vs Elo vs Dixon-Coles):
python -m futbol_pred.cli backtest --league laliga

# Tests:
pytest
```

## Backtesting — la prueba de fuego

El paquete `backtest/` valida el edge SIN engañarse (tu principio de validación
temporal): entrena solo con el pasado y predice el futuro, ronda a ronda.

```python
from futbol_pred.backtest import walk_forward, DixonColesPredictor, simulate_bets
res = walk_forward(matches, DixonColesPredictor())
res.metrics()        # log loss, Brier, RPS, accuracy
res.calibration("1") # ¿el 60% predicho ocurre el 60% de las veces?

# Con cuotas reales: ROI, yield, hit rate, max drawdown.
sim = simulate_bets(res.records)
sim.summary()
```

Incluye **baselines obligatorios** (tasas base, Elo): un modelo complejo solo se
acepta si los bate consistentemente. El backtest está diseñado para **revelar
cuándo Dixon-Coles se sobreajusta** con pocos datos, no para esconderlo.

## Configuración

Copia `.env.example` a `.env` y añade tus claves (`API_FOOTBALL_KEY`,
`ODDS_API_KEY`). Sin claves, todo funciona en **modo offline** con datos de
ejemplo para desarrollo y tests.

## Jugar con líneas y submercados

El corazón es la `ScoreMatrix`: una vez calculada, cualquier mercado es un
sumatorio. Ejemplos:

```python
from futbol_pred.model import DixonColesModel
sm = DixonColesModel.matrix_from_lambdas(1.6, 1.1, rho=-0.03)

sm.over(3.5)                      # P(más de 3.5 goles)
sm.asian_handicap(-1.0, "home")  # hándicap asiático local -1
sm.asian_handicap(-0.25, "home") # línea de cuarto
sm.btts()                        # ambos marcan
sm.correct_score(2, 1)           # resultado exacto 2-1
```

## Roadmap (próximos pasos)

- [ ] Integrar tus prompts/lógica previa.
- [ ] xG real vía FBref/Understat (`soccerdata`) para modelo híbrido.
- [ ] Ingesta de cuotas a BBDD + snapshot histórico (line movement).
- [ ] **Backtesting** con ROI/edge por mercado y liga.
- [ ] Calibración (Platt/isotónica) y CLV (closing line value).
- [ ] Notificaciones (Telegram) y/o dashboard.
```
