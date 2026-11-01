# Fútbol Edge 3.0: base propia de datos abiertos (sin coste)

## Estado y límites

**Implementación experimental, sin modificar las probabilidades de producción.**
Esta fase prepara un repositorio propio de observaciones históricas con permiso
de reutilización verificable. Los resultados de otros proveedores siguen sin
tener licencia automática porque se guarden en Google Sheets.

La aplicación ya tiene `OpenFootballClient`, `HistoricalFeatureStore` y
un motor Dixon-Coles/Elo/pi-ratings; esta integración los reutiliza. El modelo
`DynamicStrengthPredictor` es un *challenger* que solo se importará para
backtests, no para recomendaciones de apuestas hasta demostrar calidad en
datos temporalmente separados.

## Origen y licencias (consultado en noviembre de 2026)

| Fuente | Permiso/cobertura | Uso en esta fase |
| --- | --- | --- |
| [OpenFootball football.json](https://github.com/openfootball/football.json) | Public domain / CC0; Primera y Segunda histórica; las contribuciones de resultados pueden demorarse | **Habilitado**: resultados cerrados, 1 vez al día, con referencia exacta |
| [Wyscout/Pappalardo](https://www.nature.com/articles/s41597-019-0247-7) | Eventos históricos 2017/18 CC BY 4.0 (con atribución) | Pendiente de adaptador y validación de cobertura para entrenar un xG de investigación |
| [StatsBomb Open Data](https://github.com/statsbomb/open-data) | Algunas competiciones; su README exige atribución y logo en trabajos publicados | Investigación separada, verificar permisos de redistribución antes de servirlos |
| [football-data.org](https://www.football-data.org/) | Nivel gratuito registrado, cobertura limitada y condiciones de API | Ya existe en el pipeline, optimizar caché y cuota |
| [football-data.co.uk](https://www.football-data.co.uk/contact.php) | Su política restringe CSV gratuitos a uso individual/académico y 2 descargas automáticas/semana como máximo | **No crear un nuevo scraper ni ampliar la dependencia**. Revisar y reemplazar el uso heredado |
| [Open-Meteo](https://open-meteo.com/) | Llamadas públicas gratuitas solo para uso no comercial, atribución CC BY 4.0 | Mantener uso no comercial bajo condiciones; no representa odds ni eventos premium |

**Prohibido en esta vía**: eludir un paywall, reutilizar tokens/cookies ajenas,
recoger cuotas detrás de inicios de sesión, redistribuir tablas premium a través
de una hoja pública o vender como datos actuales un dataset histórico.

## Instalación del prototipo Apps Script

1. Crear una **hoja privada** de Google Sheets (nombre libre).
2. Abrir `Extensiones → Apps Script`. Copiar `scripts/edge-data-bridge/Code.gs`.
3. Ejecutar `setupEdgeBridge` y aprobar la autorización de tu cuenta. Crea
   `Observaciones` con columnas para procedencia, licencia, fecha y valor.
4. Ejecutar `pullOpenFootball` una vez. Descarga únicamente JSON públicos de
   OpenFootball de la temporada actual y la anterior (Primera/Segunda).
5. Opcional: ejecutar `installDailyTrigger`, que configura una comprobación
   diaria. No es una API de partido en directo y su ejecución no está
   garantizada en un minuto exacto.
6. Exportar solo la pestaña `Observaciones` como **CSV UTF-8**, manteniéndola
   privada en Google Drive.

### Integración en la base SQLite

Desde la raíz `football/`, con las dependencias actuales:

```bash
python -m futbol_pred.open_data_bridge /ruta/observaciones.csv /ruta/edge-shadow.sqlite
```

El importador rechaza cualquier fuente/licencia no autorizada, campos
incompatibles, goles imposibles, resultados marcados como prepartido y marcas
temporales futuras. **Valida el lote entero antes de insertar**. Reimportar el
mismo CSV es idempotente. No ejecuta consultas de red ni modifica `dashboard.json`.

**Cuidado con las fechas de OpenFootball**: para muchos partidos solo hay
fecha, no hora exacta. `kickoff_precision=date_only` usa 00:00 UTC solo como
índice administrativo del día, nunca como un saque inicial verificado.
Los resultados se guardan con `phase=postmatch` y `available_at` igual a
la primera observación del script, no a una hora de resultado inventada.
El modelo rechaza explícitamente históricos sin hora de kickoff verificable.

## Modelo de fuerza dinámica

`football/src/futbol_pred/backtest/dynamic_strength.py` añade un modelo
Poisson secuencial con parámetros de ataque y vulnerabilidad defensiva
individuales, regularización y olvido temporal. Está diseñado para ejecutarse
después en el motor `walk_forward`; hoy no altera el campeón en producción.

Antes de habilitarlo deben completarse:
- Unir los partidos históricos de distintas fuentes por identidad fiable,
  sin confundir temporadas, homónimos ni encuentros aplazados.
- Obtener kickoff real de la fuente ya integrada antes de permitir resultados
  solo-fecha en el backtest temporal.
- Comparar en períodos no usados para ajuste contra Dixon-Coles, Elo, pi
  y el mercado de cierre cuando las cuotas sean válidas.
- Atribución y licencias verificadas, cobertura mínima por liga y
  detección de cambios de formato de fuentes.
- Mejoras sólidas de Log Loss / RPS / Brier en validación y sin degradación
  operativa antes de su eventual promoción.

## Escala y operaciones

- Apps Script no convierte fuentes cerradas en abiertas. El consumidor dispone
  aproximadamente de 20.000 UrlFetch/día, 90 min de triggers/día y límite de
  6 minutos por ejecución; Google puede cambiar estas cifras.
- Google Sheets anunció en septiembre de 2026 20 millones de celdas por libro,
  pero la capa analítica debe ser SQLite (y después Parquet si crece).
- Reducir el número de fuentes/peticiones y almacenar hechos por cambios
  semánticos, no una nueva fila cada vez que un cron mira lo mismo.
- Google Sheets se usa como **bandeja de entrada revisable** y jamás como
  fuente autoritativa de cuotas o señales financieras.

Referencias:
- https://developers.google.com/apps-script/guides/services/quotas
- https://workspaceupdates.googleblog.com/2026/09/doubled-cell-limits-in-google-sheets-now-generally-available.html
- https://github.com/openfootball/football.json
- https://www.football-data.co.uk/contact.php
