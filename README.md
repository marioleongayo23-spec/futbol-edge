# Fútbol Edge

App de predicciones de fútbol (LaLiga / Segunda / Champions): probabilidades 1X2,
mercados (over/under, hándicap, value), quiniela y detalle por partido.

- **Frontend** (`app/`): React + Vite. Lee el feed de `football/data/dashboard.json`.
- **Backend / cron** (`football/`): genera el feed con datos reales.
- **Automatización** (`.github/workflows/`): el cron regenera el feed cada 12 h.

## Funciones de la app

- **📅 Jornada** — tarjetas por partido con 1X2, marcador previsto y acceso al
  análisis completo (mapa de marcadores, over/under, hándicap asiático, stats
  esperadas y calculadora de value). Salta por defecto a la próxima jornada.
- **🏆 Clasificación proyectada** — tabla a final de temporada combinando los
  puntos reales ya jugados con los puntos esperados del modelo
  (3·P(gana) + 1·P(empata)) partido a partido. Marca zonas de Champions,
  Europa y descenso.
- **🎫 Quiniela** — 14 partidos (1X2) + **Pleno al 15** (marcador exacto),
  reparto automático de dobles/triples por incertidumbre y **copiar** la
  columna al portapapeles.
- **💰 Value bets** — introduces las 3 cuotas, se **quita el margen** de la casa
  (vig), se muestra la probabilidad justa vs. la del modelo, el *edge* por
  selección y el *stake* con Kelly fraccionado (¼, máx. 5% del bankroll).
- **Extras UX** — modo claro/oscuro, *skeletons* de carga, aviso de feed
  desactualizado, copia local de respaldo del feed y **PWA instalable** con
  soporte offline.

## Deploy

- **Vercel**: Root Directory = `app`. Build Command = `npm run build`. Output = `dist`.
  - El feed en producción se lee de
    `https://raw.githubusercontent.com/<owner>/futbol-edge/main/football/data/dashboard.json`.
    Para que funcione, `football/data/dashboard.json` debe estar en `main`.
  - Opcional: `VITE_FEED_URL` para apuntar a otro feed; `VITE_SUPABASE_URL` /
    `VITE_SUPABASE_ANON_KEY` / `VITE_ALLOWED_EMAIL` para activar login privado
    (si no se definen, la app corre en modo abierto).
- **Secrets del repo** (Settings → Secrets) para el cron:
  `FOOTBALL_DATA_API_KEY`, `API_FOOTBALL_KEY`, `ODDS_API_KEY`,
  `AI_API_KEY`/`GEMINI_API_KEY` y `GROQ_API_KEY`. Gemini es el proveedor
  primario y Groq el fallback. La IA solo se intenta de 06:00–10:00 y
  20:00–23:00 (Madrid), con caché/LKG; el refresco de resultados sigue cada
  15 minutos sin consumir IA. Desde **Run workflow** se puede marcar
  `force_ai` para una regeneración manual.

## Desarrollo local

```bash
# Frontend
cd app && npm install && npm run dev      # http://localhost:5173

# Backend / feed
cd football && pip install -r requirements.txt && pytest
python -m futbol_pred.cli run --league laliga
```

## Actualización local sin bloqueos de IP

Algunas fuentes (FBref para **jugadores** y Loterías y Apuestas para la
**quiniela** oficial) devuelven `403` desde los runners de GitHub, pero sí
responden desde una IP residencial española. Para eso hay un modo local que baja
esos datos, regenera el feed y lo publica en `main` (de donde leen Vercel y la
app). El cron de GitHub sigue actualizando cada 12 h todo lo accesible desde CI;
esto añade lo que CI no puede.

```bash
bash scripts/setup_local.sh        # 1) instala backend (.venv) y frontend
bash scripts/refresh_and_push.sh   # 2) baja jugadores + quiniela + feed y hace push
bash scripts/schedule_12h.sh       # 3) (opcional) lo repite solo cada 12 h (08:00 y 20:00)
#   scripts/schedule_12h.sh --remove   para quitar la programación
```

- Claves de API opcionales (para partidos de pago): exporta
  `FOOTBALL_DATA_API_KEY` / `API_FOOTBALL_KEY`, o ponlas en un fichero `.env`
  en la raíz (lo carga `refresh_and_push.sh`).
- Solo un paso concreto:
  `cd football && python -m futbol_pred.refresh_local --no-quiniela` (o
  `--no-players`, `--no-feed`, `--season 2026`).
- Si una fuente no responde, **conserva el override anterior** y sigue; nunca
  deja el feed vacío.

## Modo 100% local (sin depender de GitHub)

Para tener **toda la app en tu PC**, sin Vercel ni GitHub, pero **actualizándose
sola cada 12 h** con un programador de tu propio ordenador:

```bash
git clone https://github.com/marioleongayo23-spec/futbol-edge.git
cd futbol-edge
bash scripts/setup_local.sh          # instala backend (.venv) + frontend (una vez)

bash scripts/run_local.sh            # refresca datos + compila + abre http://localhost:8080
LOCAL=1 bash scripts/schedule_12h.sh # actualiza SOLO en tu disco cada 12 h (sin push)
```

- `run_local.sh` compila la app apuntando al feed **local** (`/dashboard.json`) y
  la sirve con `scripts/serve_local.py`, que siempre entrega el
  `football/data/dashboard.json` más reciente de tu disco. No se consulta internet
  para los datos (sí, opcionalmente, para escudos de equipos).
- `LOCAL=1 scripts/schedule_12h.sh` programa `refresh_local.sh` (sin GitHub) a las
  08:00 y 20:00. Sin `LOCAL=1`, publica en GitHub (`refresh_and_push.sh`).
- Para que el servidor esté siempre encendido, deja `run_local.sh` corriendo o
  añádelo al arranque de tu sistema.

> Nota: las claves de API (`FOOTBALL_DATA_API_KEY`, `API_FOOTBALL_KEY`) siguen
> siendo opcionales y se leen de tu shell o de un `.env` en la raíz. Los datos
> gratuitos (calendario, resultados, Segunda, modelo) funcionan sin claves.

### Overrides manuales

Si prefieres rellenar los datos a mano en vez de con los scrapers, copia y edita:

- `football/data/players.json.example` → `players.json`
- `football/data/quiniela.json.example` → `quiniela.json`

El feed usa el override si existe; el resto lo calcula el modelo.
