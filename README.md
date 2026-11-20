# mod-updater

Actualizador de mods de Minecraft para **NeoForge 1.21.1**. Identifica cada `.jar` de la carpeta de mods por su hash en **Modrinth** (y, próximamente, en **CurseForge**) y muestra qué mods tienen versión nueva.

> Por defecto **no modifica nada**: solo revisa y muestra una tabla.

## Instalación

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Opcional:
- `copy .env.example .env` y pon tu `CF_API_KEY` (necesaria para CurseForge; aún no se usa).
- `copy config.example.toml config.toml` para cambiar la carpeta, la versión de Minecraft o el loader.

`.env` y `config.toml` están en `.gitignore`: **la API key nunca se sube al repo**.

## Uso

```bat
.venv\Scripts\python -m mod_updater                       :: revisa y muestra la tabla (no toca nada)
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
| `solo manual` | hay versión nueva pero no se puede descargar por API |
| `desconocido` | no se ha identificado el archivo (no se toca) |

**Regla de canal:** si tu archivo es *release* solo se proponen releases; si es *beta* se permiten betas; si es *alpha*, alphas. `--allow-beta` permite betas siempre.

Los hashes se guardan en `.cache/scan_cache.json` (dentro del proyecto, no en la carpeta de mods), así que la primera ejecución tarda unos segundos más.

## Estado

- [x] Hito 1: esqueleto del repo
- [x] Hito 2: escaneo + fingerprint CurseForge (MurmurHash2) con tests — falta validar contra la API de CurseForge
- [x] Hito 3: Modrinth, tabla en modo revisión
- [ ] Hito 4: CurseForge
- [ ] Hito 5: descarga + backup (`--apply`)
- [ ] Hito 6: dependencias

## Tests

```bat
.venv\Scripts\python -m pytest
```
