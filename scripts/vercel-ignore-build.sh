#!/usr/bin/env bash
set -euo pipefail

# Vercel ejecuta este script como Ignored Build Step.
# Exit 0 => ignorar el deployment. Exit 1 => construir/deployar.
#
# El feed vivo se sirve directamente desde GitHub y cambia cada pocos minutos,
# por lo que un commit puramente de datos NO necesita reconstruir la SPA.
# Cualquier cambio de código/configuración de la app sí debe llegar a producción.

if ! git rev-parse HEAD^ >/dev/null 2>&1; then
  echo "[vercel] Sin commit anterior disponible: construir por seguridad"
  exit 1
fi

changed="$(git diff --name-only HEAD^ HEAD)"
printf '%s\n' "$changed" | sed 's/^/[vercel] changed: /'

if printf '%s\n' "$changed" | grep -Eq '^(app/|vercel\.json$|scripts/vercel-ignore-build\.sh$|\.nvmrc$)'; then
  echo "[vercel] Cambio relevante para producción: construir"
  exit 1
fi

echo "[vercel] Solo datos/backend/workflows sin cambio de SPA: ignorar rebuild"
exit 0
