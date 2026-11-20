# mod-updater

Actualizador de mods de Minecraft para **NeoForge 1.21.1**. Identifica cada `.jar` de la carpeta de mods por su hash en **CurseForge** (fuente principal) y **Modrinth** (respaldo) y muestra qué mods tienen versión nueva.

> Por defecto **no modifica nada**: solo revisa y muestra una tabla.

## Instalación

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Opcional:
- `copy .env.example .env` y pon tu `CF_API_KEY`. Sin ella solo se consulta Modrinth.
- `copy config.example.toml config.toml` para cambiar la carpeta, la versión de Minecraft o el loader.

`.env` y `config.toml` están en `.gitignore`: **la API key nunca se sube al repo**.

## App de escritorio

Doble clic en **`ModUpdater.pyw`** (o `.venv\Scripts\python -m mod_updater.gui`). La primera vez pide la carpeta de mods (la deduce sola), la versión de Minecraft y el loader (también los deduce de tus mods) y la key de CurseForge, que se guarda en el **Administrador de credenciales de Windows**. Después revisa tus mods con una barra de progreso y muestra los resultados con filtros, búsqueda y casillas.

La app está en **español, inglés y catalán**: por defecto usa el idioma de la interfaz de Windows (si no es ninguno de esos, inglés) y se cambia en Ajustes → Idioma. En la CLI: `--lang es|en|ca`.

Los ajustes de la app se guardan en `%APPDATA%\mod_updater\settings.json`. Actualizar desde la ventana llega en la siguiente versión; mientras, usa `actualizar.bat`.

## Uso (línea de comandos)

```bat
.venv\Scripts\python -m mod_updater                       :: revisa y muestra la tabla (no toca nada)
.venv\Scripts\python -m mod_updater --apply               :: revisa, pide confirmación y actualiza
.venv\Scripts\python -m mod_updater --apply --yes         :: sin confirmación
.venv\Scripts\python -m mod_updater --apply --only balm   :: actualiza solo algunos
.venv\Scripts\python -m mod_updater --hide-up-to-date     :: oculta los mods al día
.venv\Scripts\python -m mod_updater --only create,jei     :: filtra por nombre
.venv\Scripts\python -m mod_updater --allow-beta          :: propone betas aunque tengas la release
.venv\Scripts\python -m mod_updater --mods-dir "D:\otra\carpeta\mods"
```

Estados:

| Estado | Significado |
|---|---|
| **Actualizable** | hay una versión nueva compatible (1.21.1 + NeoForge) |
| **Al día** | ya tienes la última versión |
| **Descarga manual** | hay versión nueva, pero no se puede descargar automáticamente (se muestra el enlace); también si le falta una dependencia no descargable |
| **No encontrado** | no está en CurseForge ni en Modrinth; se deja como está |
| **Nueva dependencia** | no está en tu carpeta, pero otro mod la necesita; se instalará |

**Regla de canal:** si tu archivo es *release* solo se proponen releases; si es *beta* se permiten betas; si es *alpha*, alphas. `--allow-beta` permite betas siempre.

Los hashes se guardan en `.cache/scan_cache.json` (dentro del proyecto, no en la carpeta de mods), así que la primera ejecución tarda unos segundos más.

## Cómo actualiza (`--apply`)

También puedes hacer doble clic en `actualizar.bat`. **Cierra Minecraft antes.**

1. Descarga cada jar nuevo a un `.part` en `.minecraft\mods_backup\AAAA-MM-DD_HHMM\` y verifica su hash (sha512 o sha1).
2. Solo si coincide, mueve el jar viejo a esa carpeta de backup y coloca el nuevo en `mods`.
3. Si algo falla, el jar viejo sigue (o vuelve) a su sitio. **Nunca se borra nada.**
4. `cambios.txt` en la carpeta de backup lista lo que cambió, para revertir a mano.

Antes de tocar nada comprueba que Minecraft no esté abierto con esa carpeta. Se guarda solo el último backup (`backups_to_keep` en `config.toml` o `--keep-backups N`). Los mods duplicados en la carpeta se saltan.

## Dependencias

Antes de actualizar se leen las dependencias **requeridas** de cada versión nueva y también las de los mods ya instalados (detecta carpetas rotas). Si falta alguna, se añade al plan automáticamente y se avisa: *"Se instalará MezzConfig 0.7.1 (requerida por JEI)"*. Si una dependencia no se puede descargar, el mod que la necesita no se actualiza. Las dependencias sin ninguna versión para este Minecraft/loader (p. ej. "Create Fabric" declarada por un mod multi-loader) solo generan un aviso. La API key de CurseForge solo se envía a dominios de CurseForge, incluso si la descarga redirige a otro sitio.

## Estado

- [x] Hito 1: esqueleto del repo
- [x] Hito 2: escaneo + fingerprint CurseForge (MurmurHash2) con tests, validado contra la API (125/125)
- [x] Hito 3: Modrinth, tabla en modo revisión
- [x] Hito 4: CurseForge como fuente principal, Modrinth como respaldo
- [x] Hito 5: descarga + backup (`--apply`)
- [x] Hito 6: dependencias automáticas
- [x] Plan v2 pasos 1-3: CLI mejorada, dependencias y mockup validado (`design/mockup/resultados.html`)
- [x] Plan v2 paso 4: app pywebview (Bienvenida/Ajustes, Escaneo, Resultados)
- [ ] Plan v2 paso 5: actualizar desde la app, pantalla final y Deshacer

## Tests

```bat
.venv\Scripts\python -m pytest
```
