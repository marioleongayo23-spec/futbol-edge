# Fútbol Edge · Diseño de alineaciones y fotografías 3.1

## Qué está realmente implementado

- El campo nuevo muestra las posiciones **solo si los 11 jugadores del
  equipo tienen posiciones reconocidas y hay exactamente un portero**.
  En cualquier otro caso se muestra una lista verificable, nunca un 4-3-3
  supuesto visualmente.
- Los duplicados de un mismo nombre en el XI invalidan la etiqueta
  «oficial» y generan advertencia. Un XI parcial no se muestra como completo.
- Las fichas desde el campo preservan la pantalla del partido al volver.
- Jugadores en campo, ranking, plantilla de equipo y perfil comparten
  avatar; la fotografía necesita coincidencia única de nombre completo
  y equipo. Dos personas con el mismo apellido no se mezclan.
- Los fallos de red de la foto o la falta de un campo ofrecen un avatar de
  iniciales, no una imagen ajena ni un error visual.
- `npm run audit:media` calcula cobertura real de escudos, fotografías
  existentes y alineaciones de la muestra pública sin realizar llamadas
  externas.

## Fuentes de imágenes: análisis de coste y derechos

| Fuente | Uso potencial | Restricciones |
|---|---|---|
| El `crest` ya suministrado por football-data.org | Escudos y equipos actuales | Revisar el uso permitido de imágenes; no atribuir derechos de autor por la mera respuesta de la API |
| Feed actual de jugadores (perfil existente) | Foto en ficha, campo, ranking y plantilla | Se muestra el recurso remoto ya suministrado; **no replicar, descargar ni redistribuir** sin confirmar permiso del proveedor y titular |
| Wikidata P18 para fotos, P154 para logos | Identificación de recursos en Commons | Wikidata no determina por sí solo las condiciones de licencia del archivo |
| Wikimedia Commons `imageinfo` / `extmetadata` | Archivo con autor, licencia, atribución y thumbnails | Revisar cada licencia y conservar atribución/licencia/URL de origen; no asumir que todas son CC0 |
| TheSportsDB v1 | Posible relleno con cuentas gratuitas | Cuotas y cobertura variables, fan art no garantiza derechos del equipo o fotógrafo; no integrarlo como importador por defecto |
| Transfermarkt, SofaScore, Flashscore, etc. | Ninguno en el pipeline | No implementar extracción que eluda términos/licencias |

Fuentes consultadas:
- https://www.football-data.org/documentation/quickstart
- https://www.thesportsdb.com/docs_api_guide
- https://www.wikidata.org/wiki/Property:P18
- https://www.wikidata.org/wiki/Property:P154
- https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia
- https://www.mediawiki.org/wiki/API:Imageinfo

## Próxima fase gratuita: catálogo autorizado

El próximo trabajo **no consiste en intentar una foto por similitud de nombre**.
Construir un catálogo revisable, con ID inequívoco de jugador y equipo,
identificadores externos y metadatos independientes:

```json
{
  "player_uid": "id-interno-estable",
  "club_uid": "club-id-interno",
  "wikidata_qid": "Qxxxxx",
  "image_source": "Wikimedia Commons",
  "file_title": "File:...",
  "image_url": "https://upload.wikimedia.org/...",
  "creator": "Autor comprobado",
  "license": "CC BY-SA 4.0",
  "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
  "attribution_url": "https://commons.wikimedia.org/wiki/File:...",
  "checked_at": "ISO-8601"
}
```

No consumir imágenes de Wikidata P18/P154 sin verificar la ficha real de
Commons. Reducir consultas mediante caché duradera en GitHub y no hacer peticiones
de búsqueda en cada render. Un registro ambiguo debe producir placeholder.

## QA / condiciones para publicar

- Pruebas unitarias: 11 únicos, cero duplicados, 1 portero, orientación
  izquierda/derecha, homónimos, URLs HTTPS y valores ausentes.
- Playwright en 1365 px y 390 px: campo, foto lazy-load y fallback,
  clic en jugador y retorno a partido, estado de XI incompleto.
- Inspeccionar los screenshots y el informe `npm run audit:media`;
  ningún umbral de cobertura baja debe convertir un dato desconocido en
  una identidad inventada.
- La versión 3.1 no afecta pesos, cuotas, recomendaciones ni backtests.
