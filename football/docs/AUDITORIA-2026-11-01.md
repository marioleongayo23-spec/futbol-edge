# Fútbol Edge · auditoría incremental (2026-11-01)

## Alcance y garantías

Código de `marioleongayo23-spec/futbol-edge`, rama `main`, inspección del
proyecto de Vercel `futbol-edge` y del informe estadístico versionado
`football/docs/audit-20260905-model-evaluation.json`. Cambios en rama
`chatgpt/audit-performance-ui-20261101`. **No se cambian los pesos de los
modelos ni se anuncia una mejora de precisión sin backtest independiente**.
Ninguna mejora requiere contratar servicios, modelos de pago, bibliotecas
comerciales o API nuevas.

## Hallazgos observables

| Prioridad | Hallazgo | Evidencia | Actuación |
| --- | --- | --- | --- |
| P0 · rendimiento | `football/data/dashboard.json` ocupa unos 45,4 MiB en el árbol revisado. `scripts/vercel-build.sh` lo copiaba en el PWA, pese a existir una copia de emergencia de unos 0,65 MiB. | Tamaños del árbol de GitHub y script de build. | Eliminar copia pesada en cada build; mantener fallback empaquetado. |
| P1 · modelo / mercados | El detector podía aceptar probabilidades o cuotas no finitas; el indicador de value del navegador daba por válido el primer elemento sin comprobar cuota/edge ni inicio de partido. | `value/detector.py`, `app/src/insights.js`. | Dominios finitos, descarte de mercados inválidos, selección del mayor edge válido y abstención cuando el partido ha comenzado. |
| P1 · cartera | El ROI del navegador incluía stakes de apuestas nulas en el denominador y mostraba 0% sin muestra. | Componente `Cartera` de `App.jsx`. | Separación de apuestas liquidadas, nulas y abiertas; ROI sin muestra = «—». |
| P1 · UX | Calendario dependiente del huso del dispositivo e índice de fecha que podía cambiar cuando se insertan o eliminan partidos en actualizaciones. | `App.jsx`. | Día anclado a Madrid y selección persistida por fecha. |
| P1 · privacidad | El estado de invitado mostraba un nombre personal escrito en el código. | `App.jsx`. | Sustitución por «Invitado». |
| P1 · seguridad CI | El token de Vercel se pasaba en argumentos CLI, expuestos potencialmente en la lista de procesos. | `deploy-vercel.yml`. | Entorno de cada paso en vez de argumentos. |
| P2 · claridad | El sistema de estilos tiene varias capas y prevalencias (styles, premium, professional); la jerarquía y los tratamientos no eran consistentes. | Archivos CSS y componentes. | Capa final `edge-refresh.css`, variables coherentes, navegación, spotlight, tarjetas, contraste y responsive. |

## Publicación: distinción importante

El último deployment de producción consultado estaba READY el **16 de
septiembre de 2026**, pero `main` tiene actualizaciones de datos del **1 de
noviembre de 2026**. Es intencionado que `vercel.json` use
`git.deploymentEnabled=false` y que se desplegue código solo desde un
workflow específico: el feed dinámico se consulta desde GitHub. Por tanto,
**la diferencia de fechas no demuestra por sí sola que el frontend esté
desactualizado**. Hay que comparar el commit del último cambio en
`app/` con el deploy, y comprobar el contrato `build-version.json`.

## Evidencia estadística disponible

El informe de septiembre separa 171 observaciones de LaLiga 2025/26
en tres bloques cronológicos, para aislar una corrección Dixon-Coles:

- Acierto 1X2 anterior y corregido: 52,63% en ambos casos.
- Brier multiclase: 0,600984 → 0,600914 (ligera mejora).
- Log loss: 1,013327 → 1,015311 (ligero empeoramiento).
- RPS: 0,211626 → 0,211693 (ligero empeoramiento).

Estos resultados son mixtos y **no son una prueba end-to-end de todo el sistema
actual**, ni justifican afirmar que es rentable. Las nuevas validaciones de
mercado reducen salidas engañosas, pero tampoco demuestran mayor acierto.

## Siguientes cambios por impacto (sin gasto nuevo)

1. **Serving ligero y verificable:** inspeccionar el peso por campo con
   `python scripts/audit_feed_payload.py`; diseñar un `dashboard-serving.json`
   separado del histórico/diagnóstico, con equivalencia comprobada por contratos
   y E2E antes de cambiar la URL. Evitar las publicaciones de blobs de 45 MiB
   cada cinco minutos; conservar historial detallado fuera del serving.
2. **Calibración auditada:** evaluación walk-forward por fecha de publicación,
   contra baseline de mercado sin margen, Elo y Dixon-Coles; registrar Brier,
   log loss, RPS, cobertura, curvas de calibración e intervalos, desglosados
   por liga y horizonte. Decidir cambios de pesos con holdout temporal real.
3. **Disponibilidad real de fuentes:** exigir `observed_at` e `ingested_at`
   para bajas, onces, cuotas, clima y estadísticas; no reconstruir conocimiento
   futuro en backtests. Evitar props con muestras mínimas o jugadores de otra
   plantilla, e introducir abstención explícita.
4. **Experiencia visual completa:** validación E2E escritorio/móvil, capturas
   comparadas, accesibilidad contrastes y teclado; luego vistas de comparación
   de equipos y explicación de cada probabilidad sin falsa precisión.
5. **Monetización / datos públicos:** la SPA y el feed público no bastan para
   imponer derechos de acceso a datos premium; separar datos públicos y privados
   en un backend seguro si se activan planes de pago. No basta ocultar componentes.

## Comprobaciones de esta rama

- `cd app && npm test && npm run lint && npm run build`
- `cd app && npm run test:e2e`
- `cd football && pytest -q`
- `python scripts/audit_feed_payload.py football/data/dashboard.json`

Las tres suites principales están configuradas en GitHub Actions; ejecutar
en pull request y revisar sus resultados antes de fusionar. La auditoría
visual completa y el despliegue de producción no se deben declarar
superados sin un preview verificable.

## Coste

- Nuevas dependencias: **cero**.
- Nuevos servicios externos: **cero**.
- Nuevas llamadas a proveedores de IA o deporte: **cero**.
- Deploys de producción iniciados durante esta rama: **cero**.
- Se reutilizan GitHub Actions/Vercel existentes; verificar sus límites Hobby
  antes de publicar y no habilitar automáticamente builds por cada commit de feed.
