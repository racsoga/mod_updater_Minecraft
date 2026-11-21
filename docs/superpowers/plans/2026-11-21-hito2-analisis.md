# Hito 2 — Análisis de la colección: plan de implementación

> **Para agentes:** sub-skill: superpowers:executing-plans (ejecución nativa y autónoma). Pasos con casillas (`- [ ]`).

**Objetivo:** pestaña *Análisis* con el gráfico de bloques por categoría, cifras y listas útiles, a partir de la última revisión.

**Arquitectura:** los datos salen de la revisión (sin peticiones nuevas salvo una por lotes a Modrinth para el lado cliente/servidor). `mod_updater/analysis.py` es una función pura `analyze(results, include_libraries, now)`; la API la expone; el gráfico se dibuja con SVG propio en `gui/web/chart.js`.

**Spec:** `docs/PLAN_v3.md`, sección 2. 🛑 Punto de control A antes de terminar.

## Restricciones globales
- Sin librerías de gráficos. Animación corta que respeta `prefers-reduced-motion`.
- Tabla accesible con los mismos datos (oculta visualmente, botón "Ver como tabla").
- Textos en `es.json`/`en.json`.

## Foco de revisión
1. Carpeta vacía o revisión sin terminar → la pestaña muestra un estado vacío, no un gráfico roto.
2. Mods sin categoría (no encontrados) → cuentan en "Otras", no desaparecen.
3. Mods sin fecha de proyecto → no se cuentan como abandonados.
4. Librería requerida solo según el `mods.toml` del jar (no según la API) → no es huérfana.
5. 150 mods en una categoría → la columna no se sale del gráfico (escala).

### Tarea 1: datos nuevos
- `scanner.py`: `ModFile.requires: list[str]` (modIds obligatorios del jar, sin `minecraft`, `neoforge`, `forge`, `java`, `fabricloader`) y `ModFile.side` (`fabric.mod.json` `environment`); `CACHE_VERSION = 3`.
- `resolver.py`: `Resolution.project_updated` (CF `dateReleased`, MR `updated`) y `Resolution.side` (`client`/`server`/`both`/None, de Modrinth `client_side`/`server_side`; para mods resueltos por CurseForge, con los proyectos de Modrinth en lote).
- Tests en `tests/test_analysis.py`.

### Tarea 2: `analysis.py`
`analyze(results, *, include_libraries=False, now=None) -> dict` con `by_category`, `totals`, `heaviest` (5), `stale` (>365 días), `orphans`, `sides`. Tests: recuento, librerías excluidas/incluidas, huérfanas (por API y por jar), sin fecha, vacío.

### Tarea 3: API e interfaz
`Api.analysis(include_libraries)`; pestaña *Análisis*; `chart.js` (bloques isométricos, número, icono, foco/hover con lista); tarjetas; listas; interruptor; tabla accesible. Mock con datos de ejemplo.

### Tarea 4: 🛑 A, cierre
Capturas con los datos reales (solo lectura) a 1200×840 y 760×560 → esperar OK. Luego Impeccable, CHANGELOG, PR.
