# Plan: actualizador de mods de Minecraft (NeoForge 1.21.1)

## Objetivo
Un programa en Python que:
1. Lee los `.jar` de una carpeta de mods (por defecto `%APPDATA%\.minecraft\mods`), **sin moverla ni copiarla**.
2. Identifica cada mod por su huella (hash) en **CurseForge** (principal) y **Modrinth** (respaldo).
3. Muestra una tabla: mod | versión actual → versión nueva | fuente.
4. Tras confirmación, descarga las nuevas versiones y mueve las viejas a `mods_backup\AAAA-MM-DD_HHMM\` (nunca borra).
5. Se guarda en un repo de GitHub del usuario.

Entorno: Windows 11, Minecraft 1.21.1, NeoForge 21.1.x, ~130 mods.

---

## Stack
- Python 3.12+
- `requests` (HTTP), `rich` (tablas y colores en consola), `python-dotenv` (leer la API key de `.env`), `pytest` (tests).
- Sin GUI en la v1. Ejecutable por línea de comandos.

## Estructura del repo
```
mod-updater/
├─ mod_updater/
│  ├─ __init__.py
│  ├─ main.py          # CLI: argumentos, flujo principal
│  ├─ config.py        # carga .env y config.toml (carpeta, versión MC, loader)
│  ├─ scanner.py       # lista .jar, calcula sha1 y fingerprint CurseForge
│  ├─ murmur2.py       # implementación MurmurHash2 estilo CurseForge
│  ├─ curseforge.py    # cliente API CurseForge
│  ├─ modrinth.py      # cliente API Modrinth
│  ├─ resolver.py      # decide la versión nueva por mod (CF > Modrinth)
│  ├─ downloader.py    # descarga, verificación de hash, backup del viejo
│  └─ report.py        # tabla de resultados con rich
├─ tests/
│  ├─ test_murmur2.py
│  └─ test_resolver.py
├─ config.example.toml
├─ .env.example        # CF_API_KEY=
├─ .gitignore          # .env, __pycache__, .venv, mods_backup/, *.jar
├─ requirements.txt
└─ README.md
```

**Importante:** la API key de CurseForge va SOLO en `.env`, que está en `.gitignore`. Nunca se sube a GitHub.

---

## Detalles técnicos

### 1. Escaneo (`scanner.py`)
- Por cada `.jar`: nombre de archivo, tamaño, `sha1` (para Modrinth), `sha512` opcional, y **fingerprint CurseForge**.
- Fingerprint CurseForge = MurmurHash2 de 32 bits, **seed = 1**, calculado sobre los bytes del archivo **quitando los bytes de espacio en blanco** 9 (tab), 10 (LF), 13 (CR) y 32 (espacio). Implementarlo a mano en `murmur2.py` (la librería `mmh3` es Murmur3, NO sirve).
- Opcional: leer `META-INF/neoforge.mods.toml` dentro del jar para sacar `modId` y versión legible (útil para la tabla y para mods no encontrados).

### 2. CurseForge (`curseforge.py`)
- Base URL: `https://api.curseforge.com`. Cabecera: `x-api-key: <CF_API_KEY>`.
- Minecraft `gameId = 432`. NeoForge `modLoaderType = 6`.
- **Identificar todos los mods de una vez:** `POST /v1/fingerprints/432` con body `{"fingerprints": [int, ...]}` → `exactMatches[]` con `id` (modId) y `file` (el archivo actual).
- **Nombres:** `POST /v1/mods` con `{"modIds": [...]}`.
- **Versiones disponibles:** `GET /v1/mods/{modId}/files?gameVersion=1.21.1&modLoaderType=6&pageSize=50`. Ordenar por `fileDate` descendente.
- Campos útiles del archivo: `id`, `displayName`, `fileName`, `fileDate`, `releaseType` (1=release, 2=beta, 3=alpha), `downloadUrl`, `hashes`, `dependencies` (`relationType` 3 = requerida).
- **`downloadUrl` puede venir `null`** si el autor no permite descargas de terceros. En ese caso, intentar Modrinth; si tampoco, mostrar el enlace de la web para descargarlo a mano.
- Las descargas del CDN (`edge.forgecdn.net`) también llevan la cabecera `x-api-key`.
- Respetar límites: pausas cortas entre peticiones, reintentos con backoff ante 429/5xx.

### 3. Modrinth (`modrinth.py`) — respaldo
- Base URL: `https://api.modrinth.com`. No requiere key, pero SÍ un `User-Agent` descriptivo (ej. `oscar/mod-updater/0.1 (github.com/<usuario>/mod-updater)`).
- **Identificar y obtener la última versión en una sola llamada:** `POST /v2/version_files/update` con
  `{"hashes": [sha1...], "algorithm": "sha1", "loaders": ["neoforge"], "game_versions": ["1.21.1"]}`.
- Para mods no encontrados en CurseForge o con `downloadUrl` nulo.

### 4. Resolución (`resolver.py`)
Para cada jar:
- Si CurseForge lo identifica → última versión compatible (1.21.1 + NeoForge).
- Si no, o si no se puede descargar → Modrinth.
- Si ninguno → estado "desconocido" (se lista, no se toca).
- **Regla de canal:** si el archivo actual es release, solo proponer releases. Si es beta/alpha, permitir beta. Configurable con `--allow-beta`.
- Estado final por mod: `al_dia`, `actualizable`, `desconocido`, `solo_manual` (no descargable por API).
- Avisar si la versión nueva tiene dependencias requeridas que no están en la carpeta.

### 5. Descarga (`downloader.py`)
- Descargar a un `.part` temporal, verificar hash, y solo entonces:
  1. mover el jar viejo a `mods_backup\<fecha>\`
  2. renombrar el nuevo a su nombre final en `mods`
- Si algo falla, el jar viejo sigue en su sitio.
- Generar `mods_backup\<fecha>\cambios.txt` con lo que se cambió (para revertir a mano).

### 6. CLI (`main.py`)
```
python -m mod_updater                 # solo revisa y muestra la tabla (dry-run, por defecto)
python -m mod_updater --apply         # revisa, pide confirmación y actualiza
python -m mod_updater --apply --yes   # sin confirmación
python -m mod_updater --mods-dir "D:\otra\carpeta\mods"
python -m mod_updater --allow-beta
python -m mod_updater --only create,jei   # filtrar
```
- Por defecto NUNCA modifica nada: hay que pasar `--apply`.
- Añadir un `actualizar.bat` en la raíz que haga `python -m mod_updater --apply` para usarlo con doble clic.

---

## Hitos (orden de trabajo)
1. **Esqueleto del repo**: estructura, `requirements.txt`, `.gitignore`, `.env.example`, `README.md`. `git init` + primer commit.
2. **Escaneo + murmur2** con tests. Verificar contra un jar real: el fingerprint calculado debe coincidir con el que devuelve CurseForge para ese archivo.
3. **Modrinth** (funciona sin key): identificar y mostrar tabla en dry-run. Primer resultado útil.
4. **CurseForge** en cuanto llegue la API key: identificar por fingerprint y combinar con Modrinth.
5. **Descarga + backup** con `--apply`.
6. **Dependencias** y avisos.
7. Subir a GitHub (`gh repo create mod-updater --private --source . --push`).
8. Extras futuros: GUI sencilla, exportar lista de mods, recomendar mods, perfil para el servidor.

## Criterios de "hecho" para la v1
- `python -m mod_updater` sobre la carpeta real muestra todos los mods con su estado, sin tocar nada.
- `--apply` actualiza, deja backup, y el juego arranca con los mods nuevos.
- La key nunca aparece en el repo ni en los logs.
