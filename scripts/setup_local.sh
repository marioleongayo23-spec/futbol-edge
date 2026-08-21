#!/usr/bin/env bash
# Instalación local de Fútbol Edge (backend Python + frontend).
# Ejecútalo UNA vez en tu máquina (IP española). Después usa refresh_and_push.sh.
#
#   bash scripts/setup_local.sh
#
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
echo "== Fútbol Edge · instalación local en $ROOT =="

# --- Backend Python (predicciones + ingesta) ---
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: necesitas python3 (3.11+). Instálalo y reintenta." >&2
  exit 1
fi
echo "-- creando entorno virtual en .venv"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
echo "-- instalando dependencias del backend"
pip install -r football/requirements.txt
pip install -e football
echo "-- tests rápidos del backend"
( cd football && pytest -q ) || echo "AVISO: algún test falló; revisa arriba."

# --- Frontend (opcional, para verlo en local) ---
if command -v npm >/dev/null 2>&1; then
  echo "-- instalando dependencias del frontend"
  ( cd app && npm install )
  echo "   (para verlo en local: cd app && npm run dev)"
else
  echo "AVISO: no hay npm; me salto el frontend (el backend/datos funcionan igual)."
fi

cat <<'EOF'

== Listo ==
Claves de API (opcionales para partidos de pago; los datos gratis funcionan sin ellas):
  export FOOTBALL_DATA_API_KEY=xxxx
  export API_FOOTBALL_KEY=xxxx
Ponlas en tu shell o en un fichero .env que cargues antes de refrescar.

Ahora, para actualizar TODO (jugadores + quiniela + feed) y publicarlo:
  bash scripts/refresh_and_push.sh

Para que se actualice solo cada 12 horas:
  bash scripts/schedule_12h.sh
EOF
