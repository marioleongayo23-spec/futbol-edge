#!/usr/bin/env bash
set -euo pipefail

mkdir -p app/public
printf '{"commit":"%s","ref":"%s","built_at":"%s"}\n' \
  "${VERCEL_GIT_COMMIT_SHA:-unknown}" \
  "${VERCEL_GIT_COMMIT_REF:-unknown}" \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > app/public/build-version.json

# El feed completo (~45 MB) se lee directamente desde GitHub. No copiarlo
# al bundle de Vercel: duplicaba decenas de MB en cada despliegue y en la
# instalación PWA. app/public/dashboard.json es una copia ligera de emergencia.
# La interfaz la etiqueta explícitamente como respaldo si la utiliza.

cd app
npm run build
