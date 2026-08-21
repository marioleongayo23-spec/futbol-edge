# Fútbol Edge

App de predicciones de fútbol (LaLiga / Segunda / Champions): probabilidades 1X2,
mercados (over/under, hándicap, value), quiniela y detalle por partido.

- **Frontend** (`app/`): React + Vite. Lee el feed de `football/data/dashboard.json`.
- **Backend / cron** (`football/`): genera el feed con datos reales.
- **Automatización** (`.github/workflows/`): el cron regenera el feed cada 12 h.

## Deploy
- **Vercel**: Root Directory = `app`. Build = `npm run build`. Output = `dist`.
- **Secrets** (Settings → Secrets del repo) para el cron: `FOOTBALL_DATA_API_KEY`, `API_FOOTBALL_KEY`.
