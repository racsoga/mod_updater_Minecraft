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

## Uso

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
| `actualizable` | hay una versión más nueva y compatible (1.21.1 + NeoForge) |
| `al día` | ya tienes la última versión compatible |
| `solo manual` | hay versión nueva pero ni CurseForge ni Modrinth permiten descargarla por API (se muestra el enlace) |
| `desconocido` | no se ha identificado el archivo (no se toca) |

**Regla de canal:** si tu archivo es *release* solo se proponen releases; si es *beta* se permiten betas; si es *alpha*, alphas. `--allow-beta` permite betas siempre.

Los hashes se guardan en `.cache/scan_cache.json` (dentro del proyecto, no en la carpeta de mods), así que la primera ejecución tarda unos segundos más.

## Cómo actualiza (`--apply`)

También puedes hacer doble clic en `actualizar.bat`. **Cierra Minecraft antes.**

1. Descarga cada jar nuevo a un `.part` en `.minecraft\mods_backup\AAAA-MM-DD_HHMM\` y verifica su hash (sha512 o sha1).
2. Solo si coincide, mueve el jar viejo a esa carpeta de backup y coloca el nuevo en `mods`.
3. Si algo falla, el jar viejo sigue (o vuelve) a su sitio. **Nunca se borra nada.**
4. `cambios.txt` en la carpeta de backup lista lo que cambió, para revertir a mano.

Los mods duplicados en la carpeta se saltan. La API key de CurseForge solo se envía a dominios de CurseForge, incluso si la descarga redirige a otro sitio.

## Estado

- [x] Hito 1: esqueleto del repo
- [x] Hito 2: escaneo + fingerprint CurseForge (MurmurHash2) con tests, validado contra la API (125/125)
- [x] Hito 3: Modrinth, tabla en modo revisión
- [x] Hito 4: CurseForge como fuente principal, Modrinth como respaldo
- [x] Hito 5: descarga + backup (`--apply`)
- [ ] Hito 6: dependencias

## Tests

```bat
.venv\Scripts\python -m pytest
```
