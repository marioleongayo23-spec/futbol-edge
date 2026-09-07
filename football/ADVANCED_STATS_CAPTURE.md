# Captura avanzada xG/npxG/PSxG — P2.5

FBref puede bloquear IPs de datacenter, por lo que esta captura **no se ejecuta en GitHub Actions**. Se hace desde Colab o una conexión residencial y después el repositorio valida el archivo en CI.

## Opción recomendada: Colab/local

Desde la carpeta `football/`:

```bash
pip install -e '.[xg]'
python scripts/capture_advanced_stats.py --season 2026
```

Por defecto captura **LaLiga + Segunda**. Champions es opcional:

```bash
python scripts/capture_advanced_stats.py --season 2026 --leagues laliga,segunda,champions
```

## Qué hace el comando

1. Captura cada liga en un temporal independiente usando `fetch_fbref.py`.
2. Pasa cada temporal por el intake estricto P2.4.
3. Rechaza scope incorrecto, archivo vacío, identidad ambigua, manifest/hash inválido o conflicto semántico.
4. Si falla cualquier liga, **no modifica** `data/advanced_stats_snapshots.json`.
5. Si todas pasan, fusiona en memoria y reemplaza el archivo oficial de forma atómica.
6. Genera `data/advanced_stats_capture_report.json`.
7. Ejecuta P2.3 local y genera `data/advanced_outcome_challenger.local.json` salvo que se use `--skip-challenger`.

El comando **no hace commit ni push** y nunca activa el challenger en producción.

## Comprobación final

Una captura correcta debe dejar:

```text
data/advanced_stats_snapshots.json
data/advanced_stats_capture_report.json
data/advanced_outcome_challenger.local.json
```

El informe de captura debe mantener:

```json
{
  "affects_1x2": false,
  "production_wiring": false
}
```

Aunque P2.3 llegase a superar el gate offline, su promoción a producción requiere un PR separado y explícito.

## Repeticiones

Volver a ejecutar el comando es seguro:

- mismo contenido con distinto `generated_at` → `no_change`;
- nuevos snapshots → fusión aditiva;
- misma clave con estadísticas distintas → rechazo `semantic_key_conflict`;
- una liga falla → ninguna publicación parcial.
