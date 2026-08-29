# Despliegue de Fútbol Edge

La web se despliega **desde GitHub Actions** con la CLI de Vercel
(`.github/workflows/deploy-vercel.yml`), de forma independiente a la integración
Git de Vercel. Esta integración permanece desactivada en `vercel.json` para que
los commits automáticos de datos no creen deployments y no consuman la cuota de
Vercel.

Cada cambio de **código/configuración** (`app/`, `vercel.json`, `scripts/`,
`.nvmrc`) construye y publica producción. Los commits de **datos** no redeployan:
la app lee `football/data/dashboard.json` en vivo desde GitHub.

## Configuración necesaria

Solo hace falta un secret del repositorio:

| Secret | De dónde sale |
|--------|---------------|
| `VERCEL_TOKEN` | Vercel → Account Settings → Tokens → Create Token, con acceso al equipo/proyecto `futbol-edge`. |

Los identificadores de equipo y proyecto no son credenciales y están fijados en
el workflow de despliegue:

- `VERCEL_ORG_ID=team_UezD7A1MDWJVnLCRCRh4bdOc`
- `VERCEL_PROJECT_ID=prj_x059Hz47Zb5f8g2ibGEwUVBpNtU2`

## Flujo de publicación

1. GitHub Actions hace checkout del commit de `main`.
2. Descarga la configuración de producción con `vercel pull`.
3. Construye la SPA con `vercel build --prod`.
4. Comprueba que `app/dist/build-version.json` contiene exactamente el SHA que se quiere publicar.
5. Ejecuta `vercel deploy --prebuilt --prod`.
6. Verifica el deployment con `vercel inspect` usando el token autenticado.

El workflow `vercel production contract` valida además tests, lint, build,
seguridad runtime y frescura del feed.

## Verificación

El alias canónico utilizado por las comprobaciones es:

`https://futbol-edge-porra1.vercel.app`

Si el proyecto mantiene **Vercel Authentication**, las peticiones anónimas pueden
recibir redirección/403. En ese caso la verificación fuerte se hace con la CLI
autenticada dentro de GitHub Actions.

## Contención por cuota Hobby

Si Vercel responde con `api-deployments-free-per-day`, el artefacto puede haber
compilado correctamente aunque Vercel no acepte crear un deployment nuevo. No se
debe reactivar el auto-deploy Git ni lanzar deployments repetidamente: hay que
mantener `git.deploymentEnabled=false` y volver a ejecutar el workflow cuando la
ventana móvil de cuota tenga capacidad.
