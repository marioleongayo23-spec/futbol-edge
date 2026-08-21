#!/usr/bin/env bash
# Refresco COMPLETO desde tu IP (sin bloqueos) y publicación en GitHub.
# Baja jugadores (FBref) + quiniela (LAE) + regenera el feed y hace push a main,
# de donde Vercel y la app leen los datos. El cron de GitHub sigue actualizando
# cada 12h lo que sí es accesible desde CI; esto añade lo que CI no puede.
#
#   bash scripts/refresh_and_push.sh
#
# Variables opcionales:
#   BRANCH=main            rama a la que publicar (por defecto main)
#   NO_PUSH=1              solo genera los ficheros, no hace push
set -euo pipefail
cd "$(dirname "$0")/.."
BRANCH="${BRANCH:-main}"

# Carga .env si existe (para las claves de API).
if [ -f .env ]; then set -a; . ./.env; set +a; fi

# Activa el entorno virtual si está.
if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "== Refrescando datos (jugadores + quiniela + feed) =="
( cd football && python -m futbol_pred.refresh_local )

echo "== Publicando en origin/$BRANCH =="
git add football/data/players.json football/data/quiniela.json football/data/dashboard.json 2>/dev/null || true
if git diff --cached --quiet; then
  echo "Sin cambios en los datos."
  exit 0
fi
git commit -m "Datos locales: jugadores + quiniela + feed [refresh local]"

if [ "${NO_PUSH:-0}" = "1" ]; then
  echo "NO_PUSH=1: hecho el commit, sin push."
  exit 0
fi

# Publica de forma robusta (rebase + reintentos ante pushes concurrentes).
for i in 1 2 3 4 5; do
  git pull --rebase --autostash origin "$BRANCH" || true
  if git push origin "HEAD:$BRANCH"; then
    echo "Publicado en $BRANCH."
    exit 0
  fi
  echo "push rechazado, reintento $i…"; sleep $((i * 3))
done
echo "No se pudo publicar tras varios intentos." >&2
exit 1
