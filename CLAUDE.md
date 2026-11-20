# Reglas del proyecto mod_updater_Minecraft

Actualizador de mods de Minecraft (NeoForge 1.21.1) en Python. Planes: `docs/PLAN.md` (v1, CLI) y `docs/PLAN_v2.md` (interfaz gráfica). Repo privado: github.com/racsoga/mod_updater_Minecraft.

## Seguridad (obligatorio)
- **Nunca** leer, imprimir, copiar ni commitear `.env`, la API key de CurseForge ni ninguna otra credencial. Para saber si hay key, basta con que el programa la use; no mostrarla ni en parte.
- La key solo se envía en la cabecera `x-api-key` a dominios de CurseForge (`curseforge.com`, `forgecdn.net`). Nunca en logs, mensajes de error ni URLs.
- Antes de cada commit, comprobar que no entran `.env`, `.cache/`, `config.toml` ni `*.jar` (`git diff --cached --name-only`).

## La carpeta real de mods es de solo lectura en pruebas
- **Nunca** modificar `%APPDATA%\.minecraft\mods` ni `%APPDATA%\.minecraft\mods_backup` al probar. Revisar en modo lectura (`python -m mod_updater` sin `--apply`) está permitido.
- Para probar `--apply`, copiar la carpeta a un directorio temporal (el scratchpad) con estructura `<tmp>/.minecraft/mods` y usar `--mods-dir`. Borrar la copia al terminar.
- Hacer una instantánea (nombre, tamaño, fecha) de la carpeta real antes y después de cada prueba y confirmar que no ha cambiado.

## Tests
- Ejecutar `.venv\Scripts\python -m pytest` antes de cada commit. Si fallan, no se hace commit.
- Los tests no usan red: clientes HTTP y sesiones falsos (ver `tests/`).

## Idioma
- **Ningún texto visible escrito directamente en el código.** Todo texto para el usuario (interfaz, mensajes de Python, CLI, `cambios.txt`) va en `mod_updater/locales/es.json`, `en.json` y `ca.json`, y se usa con `t("clave")` (Python: `mod_updater.i18n`; JS: `t()` en `app.js`; HTML: atributos `data-i18n*`).
- Al añadir o cambiar un texto, hacerlo en los **tres** archivos con las mismas claves y los mismos `{parámetros}`. Plurales: `clave_one` / `clave_other` con `count`. `tests/test_i18n.py` lo comprueba.
- Idioma por defecto: el de la **interfaz** de Windows (no la región); si no es es/en/ca, inglés. Ajustes → Idioma (app) o `--lang` / `language` en `config.toml` (CLI).
- La lógica nunca depende del texto traducido (p. ej. duplicados usan `Resolution.duplicate`, no buscar "duplicado" en la nota).
- Estados visibles: claves `status.up|ok|manual|missing|dep` (es: *Actualizable*, *Al día*, *Descarga manual*, *No encontrado*, *Nueva dependencia*).
- Commits, comentarios del código y documentación del repo: en **español**.

## Estructura
- `mod_updater/scanner.py` hashes + metadatos (con caché en `.cache/`), `murmur2.py` fingerprint CurseForge.
- `curseforge.py`, `modrinth.py` clientes; `net.py` reintentos.
- `resolver.py` estado de cada jar (CurseForge principal, Modrinth respaldo).
- `deps.py` plan de dependencias requeridas (recursivo, bloquea si una dependencia no es descargable).
- `downloader.py` descarga verificada, backup en `.minecraft\mods_backup\<fecha>\` con `cambios.json`, poda de backups.
- `procs.py` detecta Minecraft abierto; `main.py` CLI; `report.py` tabla.
- `gui/` app pywebview: `api.py` (puente JS↔Python, la key nunca sale de Python), `web/` (HTML/CSS/JS, fuentes incluidas). `settings.py` ajustes en `%APPDATA%\mod_updater`, `credentials.py` key en keyring.
- Probar la interfaz en navegador con el simulador: servir `mod_updater/gui/web` y abrir `index.html?mock` (`dev-mock.js`, no va en el .exe).

## Diseño (interfaz v2)
- Estilo base: `apple.com-DESIGN.md` (raíz, **solo local**: no está en el repo; tampoco `design/references/`). Las referencias de `design/references/` son solo inspiración: usar únicamente lo que diga su sección "Préstamos".
- Tema oscuro, un único color de acento, sin degradados morados, emojis decorativos ni tarjetas con brillo.
- Validar el mockup con el usuario antes de programar pantallas.

## Entorno
- Windows 11, Python en `.venv`. En el shell Bash de Claude Code los heredocs pierden las barras invertidas: para escribir código con `\` usar las herramientas Write/Edit.
