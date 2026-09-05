# Fútbol Edge · auditoría y mejora profesional

Fecha: 5 de septiembre de 2026. Base revisada: `598ada967ccd96f92892e5f472317907a5104825`. Rama de trabajo: `codex/professional-audit-20260905`.

## Resultado ejecutivo

Se han implementado cambios en la interfaz, en el contrato de datos y en la validación estadística. La prioridad ha sido que la aplicación explique qué sabe, de dónde procede y qué incertidumbre conserva. Las correcciones están preparadas localmente; no están publicadas ni desplegadas.

La inspección inicial encontró una aplicación con numerosas fuentes y modelos, pero con mensajes que confundían disponibilidad, probabilidad, confianza y rendimiento histórico. También había una divergencia matemática entre la corrección Dixon-Coles usada al entrenar y la distribución usada al predecir. La corrección elimina esa divergencia; el experimento realizado **no demuestra una mejora predictiva consistente**.

## Hallazgos y cambios aplicados

| Prioridad | Hallazgo | Cambio realizado |
|---|---|---|
| Alta | La verosimilitud Dixon-Coles utilizaba intensidades medias de liga para corregir cada resultado bajo. | La corrección usa las intensidades específicas de cada partido. Se rechazan ajustes sin convergencia o parámetros no finitos. |
| Alta | El orden de jornadas podía introducir resultados de partidos aplazados todavía desconocidos. | Corte por disponibilidad temporal antes de entrenar; temporada incluida en la identidad de jornada; exclusión de resultados parciales y partidos en directo. |
| Alta | La calibración podía separar partidos del mismo día entre entrenamiento y validación. | Cortes por bloques temporales para ensemble, residual y mezclas de mercado. Sin un corte válido se descarta el ajuste. |
| Alta | Los pesos antiguos podían sobrevivir a una modificación del modelo base. | Versión `edge-2.1`; bloqueo de ensemble/residual de otra versión, filtrado de snapshots por versión y regeneración de semillas antiguas. |
| Alta | La falta de credenciales de un proveedor impedía consultar otros y podía llevar a ejemplos sintéticos. | Adaptadores independientes, validación de liga/temporada/identidad y eliminación de duplicados. Demostración solo mediante opción explícita en el pipeline. |
| Alta | Arrays vacíos de bajas, onces incompletos y cuotas parciales podían contar como cobertura. | Bajas requieren comprobación; XI requiere 11+11 y calidad de fuente; cuotas requieren tres precios decimales finitos superiores a 1. |
| Alta | Interfaz y servidor discrepaban en estados y ventanas de cobertura. | Contrato de cobertura versión 2, fuente del servidor como referencia y evaluación conservadora para feeds antiguos. El panel de explicación utiliza la misma función que el resto de la interfaz. |
| Alta | Una nueva fecha del feed podía ocultar la antigüedad de una fuente. | Fechas específicas de observación y caducidad por fuente; intentos de actualización no rejuvenecen un once antiguo. |
| Alta | El navegador reconstruía marcadores con Poisson independiente a partir de medias redondeadas. | Publicación y congelación de la matriz exacta del servidor; la interfaz la consume directamente. Sin matriz no se inventa una distribución. |
| Alta | Aciertos sin comprobar la fecha del snapshot podían contaminar la lectura del rendimiento. | El resumen solo cuenta probabilidades válidas publicadas antes del inicio, con resultado final válido. |
| Media | Selecciones de otras fechas, marcador previsto parecido a resultado real y ROI llamativo con muestra mínima. | Calendario y partidos primero, selecciones del día elegido, etiqueta «Más probable», muestra e intervalo junto al acierto; se retira el reclamo de ROI del resumen. |
| Media | La pantalla abierta podía conservar un partido antiguo tras actualizar datos. | Suscripción con limpieza al desmontar, protección ante respuestas antiguas y copia de respaldo, y resolución del detalle desde el feed vigente. |
| Media | Cada consulta creaba una URL diferente para un feed muy grande. | URL estable y revalidación HTTP, con tiempo máximo de espera. La reducción efectiva de bytes dependerá de la caché del proveedor. |
| Media | Tipografía pequeña, contraste discreto y demasiada información con igual peso. | Superficies y tipografía más legibles, espaciado consistente, detalle progresivo de fuentes, estados semánticos y adaptación móvil/claro/oscuro. |

Se han añadido navegación accesible, enlace para saltar al contenido y respeto a la preferencia de movimiento reducido. Estos cambios son de implementación; la conformidad WCAG y la validación visual final no se dan por certificadas.

## Cómo se conectan e interpretan las fuentes

| Información | Fuentes/recorrido existente | Uso real | Regla aplicada y límite |
|---|---|---|---|
| Calendario y resultados | football-data.org → API-Football → OpenFootball → football-data.co.uk | Identificación, horario e histórico del modelo | Cada proveedor se consulta de forma independiente. Se selecciona el primer calendario válido; no se fusionan calendarios por semejanza aproximada de nombres. |
| Histórico de goles | Resultados completos de temporadas disponibles | Dixon-Coles, fuerza relativa y evaluación | Solo resultados finalizados. En el backtest se usa inicio + 3 h como disponibilidad conservadora cuando no existe la fecha real de publicación del resultado. |
| Estadísticas de equipos | CSV football-data.co.uk y estadísticas finales disponibles | Modelos de estadísticas y proxy de goles | Un proxy no equivale a xG observado de eventos. La interfaz identifica las medias como estimaciones del modelo. |
| Cuotas | The Odds API y cierres históricos compatibles | Referencia de mercado, mezcla 1X2, EV y evaluación histórica | Tres cuotas válidas; caducidad operativa de 6 h. Mezclar con mercado no demuestra por sí mismo calibración estadística. |
| Clima | Open-Meteo | Escenarios de goles/estadísticas mediante heurística acotada | Caducidad de 12 h. El código declara que no modifica el 1X2; la interfaz explica esa separación. |
| Bajas | API-Football y comprobaciones operativas | Disponibilidad y solidez de evidencia | Caducidad de 12 h. Cero incidencias solo cuenta cuando hubo comprobación; ausencia de respuesta no equivale a cero bajas. |
| Once probable | Fuentes de alineación y plantillas vigentes | Escenario de titulares y minutos | Requiere 11+11 y respaldo; una reconstrucción de plantilla sigue siendo estimada. Caducidad de 24 h. |
| Once oficial | Publicación oficial recibida por el adaptador | Confirmación final y revisión del partido | Exige 11+11. «Aún no publicado», «parcial» y «confirmado» se mantienen separados. |
| Árbitros, jugadores y noticias | Directorio RFEF, API-Football, plantillas y RSS existentes | Contexto y estadísticas específicas | La auditoría no convierte estas fuentes en variables predictivas validadas ni acredita cobertura completa por disponer de un texto o una plantilla. |

Las ventanas de exigencia quedan alineadas: clima T−8 h, bajas T−6 h, probable T−3 h, oficial T−45 min y cuotas T−24 h. Son reglas operativas, **no porcentajes de acierto**. La caducidad también se comprueba en la interfaz mientras el usuario consulta el feed.

Una matriz de marcadores y un 1X2 mezclado con Elo/mercado pueden tener distribuciones marginales distintas. El nuevo detalle identifica expresamente el alcance de la matriz base y los ajustes que no incorpora. La coherencia actual consiste en conservar el origen matemático y explicarlo; una distribución conjunta única para todos los escenarios sigue siendo un trabajo pendiente de validación.

## Evaluación de la corrección matemática

Datos: 380 resultados de LaLiga 2025/26 del [CSV de football-data.co.uk](https://www.football-data.co.uk/mmz4281/2526/SP1.csv). Comparación entre la implementación de la base Git y la corregida, con los mismos parámetros por defecto. Tres bloques cronológicos con ventana de entrenamiento creciente; 57 partidos de evaluación por bloque, **171 en total**. Se excluyen del entrenamiento los encuentros del día de corte.

| Métrica | Versión anterior | Corregida | Cambio |
|---|---:|---:|---:|
| Log loss — menor es mejor | 1,013327 | 1,015311 | +0,001985 |
| Brier multiclase — menor es mejor | 0,600984 | 0,600914 | −0,000071 |
| RPS — menor es mejor | 0,211626 | 0,211693 | +0,000067 |
| Acierto 1X2 | 52,63 % | 52,63 % | 0 puntos |

El resultado es mixto y pequeño: Brier mejora ligeramente, log loss y RPS empeoran ligeramente y el acierto no cambia. **No se afirma superioridad estadística, rentabilidad ni mejora del producto completo.** La prueba aísla la verosimilitud Dixon-Coles: no evalúa conjuntamente Elo, proxy de goles, mezcla de mercado, escenarios meteorológicos o selección de apuestas. No se ajustaron hiperparámetros buscando mejorar estos 171 resultados.

La interfaz incorpora un intervalo de Wilson aproximado al 95 % junto a la tasa de acierto, siempre con numerador y denominador. Este intervalo resume incertidumbre binomial y no elimina la dependencia entre partidos/equipos ni valida el sistema de apuestas.

Resultados por bloque y huella SHA-256 del fichero: `audit-20260905-model-evaluation.json`. Reproducción desde la raíz del repositorio, con las dependencias de `football` instaladas y el CSV descargado:

```bash
python scripts/audit_model_evaluation.py --csv SP1-2526.csv --output model-evaluation.json
```

Fundamentos: [Dixon y Coles, artículo original](https://research.lancaster-university.uk/en/publications/modelling-association-football-scores-and-inefficiencies-in-the-f/), [documentación de calibración de scikit-learn](https://scikit-learn.org/stable/modules/calibration.html) y [prevención de fuga de información](https://scikit-learn.org/stable/common_pitfalls.html).

## Verificación y entrega

- Backend: **474 pruebas aprobadas**; 318 avisos ya presentes en la suite, principalmente por equipos sintéticos de pruebas sin registrar.
- Frontend: 81 pruebas aprobadas; lint y compilación de producción correctos.
- Regresiones cubiertas: intensidades por partido, aplazamientos, bloques temporales, versiones de parámetros, fallback entre proveedores, zonas horarias, resultados parciales, matrices inválidas, fuentes caducadas, porcentajes, abstención, fecha de snapshot y limpieza de suscripciones.
- Los interceptores de las pruebas E2E existentes se han adaptado a las URL estables del feed.
- Se inspeccionó la interfaz original de producción. **La nueva vista previa no pudo abrirse: el navegador del entorno devuelve `ERR_BLOCKED_BY_CLIENT`. No se declara superada la validación visual ni la suite E2E de la versión modificada.**
- No se regeneró ni publicó un feed real completo con las credenciales de producción. Las conexiones externas y cuotas deben comprobarse en el entorno de despliegue.
- La revisión automática rechazó incluso el ensayo de publicación de GitHub por considerar que faltaba autorización explícita para compartir metadatos con el servicio externo. No se ha intentado eludir el bloqueo mediante otro conector.

## Trabajo pendiente antes de considerar el producto plenamente validado

1. **Entrega verificable:** publicar la rama y PR con autorización; ejecutar CI y revisión visual móvil/escritorio en preview accesible; regenerar feed y comparar calidad antes de promover a producción. Conservar el despliegue anterior como rollback.
2. **Identidades persistentes:** registro de equipos, jugadores, competiciones y encuentros con identificadores canónicos y correspondencias de proveedor. La selección coherente de un calendario evita mezclas ambiguas, pero no resuelve todos los cambios de identidad entre proveedores.
3. **Datos disponibles en cada instante:** conservar por observación `provider`, `source_id`, `observed_at`, `ingested_at`, versión y estado de validación. Sustituir la aproximación inicio + 3 h por disponibilidad real. Los snapshots actuales son una base, no una garantía completa de reconstrucción histórica de cada fuente.
4. **Validación integral:** evaluar la cadena exacta publicada por liga y temporada, con iguales encuentros para todos los modelos, reserva temporal nueva y análisis por horizonte. Evitar comparar directamente métricas de muestras distintas o métricas reajustadas sobre el mismo conjunto de aprendizaje.
5. **Mercado y escenarios:** separar pesos heurísticos de pesos aprendidos, comparar también contra mercado sin margen y validar el efecto incremental de clima/once/bajas. Las heurísticas actuales no deben presentarse como mejoras empíricas demostradas.
6. **Carga y operación:** el feed inicial rondaba 21,5 MB. Separar índice, datos por jornada y detalle de partido; introducir validación de esquema antes de publicar, publicación atómica y métricas de latencia/caducidad/error. La URL estable reduce desperdicio potencial, pero no resuelve el tamaño inicial.
7. **Cobertura real:** resolver los huecos de cuotas, árbitros y estadísticas individuales con disponibilidad efectiva de los proveedores. No comprar planes ni prometer cobertura sin verificar licencias, presupuesto y cuota de consulta.

Criterio de aceptación: ninguna fuente ausente se convierte en evidencia, ninguna evaluación usa información futura y ninguna mejora predictiva se anuncia sin comparación temporal adecuada. La publicación debe mostrar claramente lo observado, lo estimado y lo todavía desconocido.
