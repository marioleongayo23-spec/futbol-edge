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
  `FOOTBALL_DATA_API_KEY`, `API_FOOTBALL_KEY`, `ODDS_API_KEY`.

## Desarrollo local

```bash
# Frontend
cd app && npm install && npm run dev      # http://localhost:5173

# Backend / feed
cd football && pip install -r requirements.txt && pytest
python -m futbol_pred.cli run --league laliga
```
