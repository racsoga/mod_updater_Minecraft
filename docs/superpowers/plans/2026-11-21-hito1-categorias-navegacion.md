# Hito 1 — Categorías y navegación: plan de implementación

> **Para agentes:** sub-skill: superpowers:executing-plans (ejecución nativa, el usuario pidió trabajo autónomo). Pasos con casillas (`- [ ]`).

**Objetivo:** cada mod resuelto lleva sus categorías traducidas a 12 propias (+ "otras") y si es librería; la app pasa a navegación por pestañas.

**Arquitectura:** `mod_updater/categories.py` traduce por *slug* (CurseForge y Modrinth) con un mapa explícito y, para categorías de CurseForge desconocidas, sube por `parentCategoryId` usando un catálogo descargado y cacheado una semana. `resolver.py` rellena `Resolution.categories`; `gui/api.py` las serializa. En la interfaz, una barra de pestañas bajo la cabecera.

**Tecnología:** Python 3.13+, requests, pywebview; HTML/CSS/JS sin librerías.

**Spec:** `docs/PLAN_v3.md`, sección 1.

## Restricciones globales
- Textos visibles solo en `locales/es.json` y `en.json` (mismas claves).
- Tests sin red (clientes falsos).
- Caché en `%APPDATA%\mod_updater\cache` (`Api._cache()`); validez 7 días.
- Las 12 categorías (id estable → usado luego en `.modlist.json`): `tecnologia, magia, aventura, mundo, mobs, construccion, almacenamiento, comida, mapas, calidad_vida, rendimiento, librerias` + `otras`.

## Foco de revisión
1. Mod sin datos de categorías (no encontrado, jar ilegible) → `categories == []`, nunca error.
2. Categoría nueva de CurseForge que no está en el mapa → se resuelve por su padre; si tampoco, "otras".
3. Sin red al descargar el catálogo → se usa la caché aunque esté caducada; sin caché, solo el mapa explícito.
4. Caché corrupta → se ignora y se vuelve a pedir.
5. Etiquetas de Modrinth que no son categorías (`neoforge`, `fabric`, `client`…) → se ignoran.

---

### Tarea 1: `categories.py`
**Archivos:** crear `mod_updater/categories.py`, `tests/test_categories.py`.

**Interfaces (produce):**
- `OURS: tuple[str, ...]` (las 12), `OTHER = "otras"`, `LIBRARY = "librerias"`.
- `CF_SLUGS: dict[str, str]` y `MR_SLUGS: dict[str, str]` (slug de la fuente → nuestra categoría), cubriendo las 52 de CurseForge (clase 6) y las 19 de Modrinth (`header == "categories"`).
- `class Catalog` con `cf_parent: dict[int, int]`, `cf_slug: dict[int, str]`; `Catalog.load(cache_path, curseforge=None, max_age=7 días, now=None) -> Catalog`.
- `from_curseforge(info: dict, catalog: Catalog | None = None) -> list[str]` — principal (`primaryCategoryId`) primero, sin repetidos.
- `from_modrinth(project: dict) -> list[str]` — `categories` y luego `additional_categories`; principal = la primera que no sea "otras".
- `is_library(cats: list[str]) -> bool`.

**Tests:** cada slug de las listas reales (fixture) cae en `OURS` u "otras"; `technology-farming` → comida (específica gana a padre); hijo desconocido de `technology` → tecnologia vía catálogo; desconocido sin catálogo → otras; primaria CF primero; Modrinth ignora `neoforge`; librería; caché: válida no pide red, caducada pide, sin red usa caducada, corrupta se ignora.

### Tarea 2: resolver y API
**Archivos:** `mod_updater/resolver.py` (`Resolution.categories: list[str]`, propiedad `is_library`), `resolve_all(..., catalog=None)`; `gui/api.py` (`_do_scan` carga el catálogo; `serialize` añade `cat` y `lib` a cada fila); tests en `tests/test_categories.py`.

**Tests:** resolve_all con FakeCf/FakeClient da categorías CF y MR; mod no encontrado sin categorías; fila serializada con `cat`/`lib`.

### Tarea 3: navegación por pestañas
**Archivos:** `gui/web/index.html`, `app.css`, `app.js`, `dev-mock.js`, locales.

- `<nav class="tabs" role="tablist">` bajo la cabecera: **Mis mods** · **Ajustes** ahora; **Análisis**, **Explorar** y **Sugerencias** se añaden en sus hitos (sin pantallas vacías provisionales). Hueco `#profile-slot` en la cabecera para el hito 5.
- `Ajustes` deja de ser un botón suelto: es la pestaña. Flechas izquierda/derecha entre pestañas, `aria-selected`, foco visible. Ocultas en la bienvenida y durante la actualización.
- Atajo `/` sigue funcionando en Mis mods.

**Tests:** i18n (claves nuevas en es/en); Playwright con el simulador: cambio de pestaña con ratón y teclado, capturas escritorio y ventana pequeña.

### Tarea 4: cierre
Iconos propios de categoría (pixel art, `gui/web/cat-icons.js`) para usarlos en el hito 2; CHANGELOG `[0.3.0] - sin publicar`; auditoría Impeccable; PR con `docs/PLAN_v3.md`; fusionar con "Tests" en verde.
