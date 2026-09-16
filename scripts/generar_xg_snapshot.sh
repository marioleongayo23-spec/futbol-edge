#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Fútbol Edge — genera el snapshot de xG por partido y lo sube a producción.
#
# FBref bloquea las IPs de la nube, así que esto se ejecuta EN TU ORDENADOR
# (una vez, y luego cuando quieras refrescarlo). Descarga el xG de LaLiga y
# Segunda, escribe football/data/xg_match_snapshot.json y lo sube a GitHub.
# En cuanto llega a main, el modelo activa el retador xG y lo valida solo.
#
# Uso:   bash scripts/generar_xg_snapshot.sh
#        SEASON=2026 bash scripts/generar_xg_snapshot.sh   # otra temporada
# ---------------------------------------------------------------------------
set -euo pipefail

SEASON="${SEASON:-2026}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/football"
export PYTHONPATH=src

echo "⚽ Fútbol Edge — generador de xG (temporada $SEASON)"
echo "→ (1/4) Instalando 'soccerdata' (solo la primera vez)…"
pip install -q soccerdata

echo "→ (2/4) Descargando xG de LaLiga…"
python -m futbol_pred.build_xg_snapshot --league laliga --season "$SEASON"

echo "→ (3/4) Descargando xG de Segunda…"
python -m futbol_pred.build_xg_snapshot --league segunda --season "$SEASON" --merge || \
  echo "  (Segunda sin xG en FBref para esta temporada; sigo con LaLiga)"

echo "→ (4/4) Subiendo el fichero a GitHub…"
cd "$ROOT"
git add football/data/xg_match_snapshot.json
if git diff --cached --quiet; then
  echo "  (No hay cambios nuevos que subir.)"
else
  git commit -m "Actualizar snapshot de xG por partido"
  git push
fi

echo ""
echo "✅ Listo. En unos minutos el modelo empezará a usar el xG (el gate lo valida solo)."
