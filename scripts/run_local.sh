#!/usr/bin/env bash
# Arranca Fútbol Edge ENTERO en tu PC, sin depender de GitHub:
#   1) refresca los datos (si puede),
#   2) compila la app apuntando al feed LOCAL (/dashboard.json),
#   3) la sirve en http://localhost:8080 y la abre en el navegador.
#
#   bash scripts/run_local.sh
#   PORT=9000 bash scripts/run_local.sh
#
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8080}"

if [ -f .env ]; then set -a; . ./.env; set +a; fi
if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# 1) Datos frescos (si una fuente falla, conserva lo anterior).
echo "== 1/3 Refrescando datos =="
( cd football && python -m futbol_pred.refresh_local ) || echo "AVISO: refresco parcial; sigo con lo que haya."

# 2) Build apuntando al feed local (independiente de GitHub).
echo "== 2/3 Compilando la app (feed local) =="
( cd app && VITE_FEED_URL=/dashboard.json npm run build )

# 3) Servir y abrir el navegador.
echo "== 3/3 Sirviendo en http://localhost:$PORT =="
URL="http://localhost:$PORT"
( sleep 1
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  fi ) >/dev/null 2>&1 &
PORT="$PORT" python scripts/serve_local.py
