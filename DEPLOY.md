# Despliegue de Fútbol Edge

La web se despliega **desde GitHub Actions** con la CLI de Vercel
(`.github/workflows/deploy-vercel.yml`), de forma independiente a la integración
Git de Vercel (que puede pausarse por cuota o desconectarse). Cada cambio de
**código** (`app/`, `vercel.json`, `scripts/`, `.nvmrc`) construye y publica en
producción automáticamente. Los commits de **datos** (el feed) NO redeployan: la
app lee el feed en vivo desde GitHub, así que no gastan cuota.

## Activación (una sola vez, ~2 min)

Añade 3 secrets en **GitHub → Settings → Secrets and variables → Actions → New repository secret**:

| Secret | De dónde sale |
|--------|---------------|
| `VERCEL_TOKEN` | https://vercel.com/account/settings/tokens → **Create Token** (scope: Full Account o el equipo del proyecto). |
| `VERCEL_ORG_ID` | Ejecuta `vercel link` en la raíz del repo (una vez) → se crea `.vercel/project.json`; copia el valor `orgId`. |
| `VERCEL_PROJECT_ID` | Del mismo `.vercel/project.json` → valor `projectId`. |

> Si no tienes la CLI: `npm i -g vercel && vercel login && vercel link`. Elige el
> proyecto `futbol-edge` existente cuando lo pregunte. No hace falta commitear
> `.vercel/` (está pensado para quedarse local).

## Tras añadir los secrets

- El workflow **deploy vercel (CLI)** se dispara solo en el siguiente push de
  código, o puedes lanzarlo a mano: **Actions → deploy vercel (CLI) → Run workflow**.
- Al terminar, producción sirve el commit exacto (se valida con
  `build-version.json`). A partir de ahí, cada cambio de código se publica solo.

## Verificación

- `https://futbol-edge-snowy.vercel.app/build-version.json` debe mostrar el
  `commit` actual de `main`.
- El workflow `vercel production contract` valida lo mismo automáticamente.
