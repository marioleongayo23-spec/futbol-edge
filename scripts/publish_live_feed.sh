#!/usr/bin/env bash
set -euo pipefail

feed_file="${1:-football/data/dashboard.json}"
tag="${LIVE_FEED_TAG:-live-feed}"
repo="${GITHUB_REPOSITORY:-marioleongayo23-spec/futbol-edge}"

if [ ! -f "$feed_file" ]; then
  echo "[live-feed] No existe $feed_file" >&2
  exit 1
fi

python - "$feed_file" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, encoding='utf-8') as fh:
    data = json.load(fh)
assert data.get('feed_quality', {}).get('valid') is True, 'feed_quality.valid != true'
assert len(data.get('matches', [])) >= 20, 'feed sin partidos suficientes'
print('[live-feed] validado:', data.get('generated_at'), '| partidos:', len(data.get('matches', [])))
PY

if ! gh release view "$tag" --repo "$repo" >/dev/null 2>&1; then
  echo "[live-feed] Creando release estable $tag"
  gh release create "$tag" \
    --repo "$repo" \
    --target main \
    --title "Fútbol Edge · live feed" \
    --notes "Canal automático de datos en vivo. El asset dashboard.json se reemplaza en cada refresco sin crear commits de datos."
fi

echo "[live-feed] Publicando dashboard.json en release/$tag"
gh release upload "$tag" "$feed_file#dashboard.json" --clobber --repo "$repo"
