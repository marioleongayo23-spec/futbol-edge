#!/usr/bin/env bash
set -euo pipefail

mkdir -p app/public
printf '{"commit":"%s","ref":"%s","built_at":"%s"}\n' \
  "${VERCEL_GIT_COMMIT_SHA:-unknown}" \
  "${VERCEL_GIT_COMMIT_REF:-unknown}" \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > app/public/build-version.json

cp football/data/dashboard.json app/public/dashboard.json

cd app
npm run build
