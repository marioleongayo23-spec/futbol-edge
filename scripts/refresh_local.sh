#!/usr/bin/env bash
# Refresco LOCAL sin GitHub: baja jugadores + quiniela + regenera el feed en tu
# disco (football/data/dashboard.json). No hace ningún push. Es lo que programa
# schedule_12h.sh en modo local.
#
#   bash scripts/refresh_local.sh
#
set -euo pipefail
cd "$(dirname "$0")/.."

# Carga .env si existe (claves de API opcionales).
if [ -f .env ]; then set -a; . ./.env; set +a; fi
# Activa el entorno virtual si está.
if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "== Refresco local (sin GitHub) =="
( cd football && python -m futbol_pred.refresh_local )
echo "Feed actualizado en football/data/dashboard.json"
