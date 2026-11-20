# Plan v2: interfaz gráfica y experiencia de uso

Continuación de PLAN.md. La lógica actual (scanner, murmur2, curseforge, modrinth, resolver, downloader) se mantiene; la v2 le pone una cara y la hace usable por cualquiera que la descargue de GitHub.

## Objetivos
1. Ventana propia en lugar de terminal. Nada de `.bat` con consola negra.
2. Barra de progreso real mientras escanea, consulta y descarga.
3. Asistente de primer uso para la API key de CurseForge.
4. Confirmaciones con botones, no con "y/n".
5. Backups que no se acumulan, con botón "Deshacer última actualización".
6. Distribuible como `.exe` para quien no tenga Python.

---

## 1. Tecnología de la interfaz
- **pywebview** + HTML/CSS/JS propio dentro de la app. Motivo: control total del diseño (se puede hacer algo con personalidad, no el típico "look de IA") y el backend sigue siendo el Python que ya existe.
- Comunicación: el JS llama a funciones Python expuestas con `js_api`; Python envía el progreso al JS con `window.evaluate_js`.
- El trabajo pesado (hashes, peticiones, descargas) va en un hilo aparte para que la ventana no se congele.
- La CLI actual se mantiene (`python -m mod_updater`) para uso avanzado y para los tests.

## 2. Pantallas
1. **Bienvenida / configuración** (solo la primera vez, o desde Ajustes):
   - Detecta la carpeta de mods automáticamente (`%APPDATA%\.minecraft\mods`) con botón "Cambiar carpeta".
   - Versión de Minecraft y loader: se intenta deducir de los mods; si no, selector (por defecto 1.21.1 / NeoForge).
   - API key de CurseForge: campo para pegarla, enlace "¿Cómo consigo una?" que abre console.curseforge.com, y botón **Probar** que hace una petición de prueba y muestra ✓ o el error en lenguaje claro.
   - Botón "Continuar sin key (solo Modrinth)": la app funciona igual pero con menos cobertura, y lo dice.
2. **Escaneo**: barra de progreso con fases ("Leyendo mods 34/125", "Consultando CurseForge", "Consultando Modrinth").
3. **Resultados**: lista de mods con:
   - Icono del mod (CurseForge y Modrinth devuelven la URL del logo), nombre, versión actual → nueva, fuente.
   - Filtros: Todos / Actualizables / Al día / Requieren atención.
   - Casilla por mod para elegir cuáles actualizar (todos marcados por defecto).
   - Resumen arriba: "55 actualizaciones disponibles · 70 al día".
   - Estados en lenguaje claro, con tooltip:
     - **Al día**: ya tienes la última versión.
     - **Actualizable**: hay una versión nueva compatible.
     - **Descarga manual**: hay versión nueva, pero el autor no permite descargarla automáticamente. Botón "Abrir página".
     - **No encontrado**: no está en CurseForge ni en Modrinth (mod propio, o bajado de otro sitio). Se deja como está.
4. **Actualizando**: barra de progreso global + estado por mod (descargando / verificado / listo / error).
5. **Final**: "55 mods actualizados" + botones **Deshacer** y **Abrir carpeta de mods**. Si hubo errores, se listan con su motivo.
6. **Ajustes**: carpeta, key (cambiar/probar/borrar), permitir betas, política de backups.

## 3. API key: seguridad
- Se guarda en el **Administrador de credenciales de Windows** con la librería `keyring`, no en texto plano. El `.env` se mantiene solo para desarrollo.
- Cada usuario usa **su propia key** (las condiciones de CurseForge no permiten compartirla). Nunca se incluye una key en el repo ni en el `.exe`.
- La key nunca se muestra entera en pantalla (solo los últimos 4 caracteres) ni se escribe en logs.

## 4. Backups
- Por defecto se guarda **solo el último backup**. Al hacer una actualización nueva, el backup anterior se borra.
- Ajuste: "Guardar los últimos N backups" (1 por defecto) y botón "Borrar backups ahora".
- **Deshacer última actualización**: restaura los jars del último backup y quita los nuevos, usando `cambios.txt` (que pasa a ser `cambios.json` para leerlo bien).

## 5. Confirmaciones
- En la GUI, todo con botones ("Actualizar 55 mods" / "Cancelar").
- En la CLI, aceptar `s`, `si`, `sí`, `y`, `yes` (sin distinguir mayúsculas) y mostrar `[S/n]` en el texto de la pregunta.
- Avisar si Minecraft está abierto (proceso `javaw.exe` con la carpeta del juego) antes de tocar archivos.

## 6. Dependencias (hito 6 pendiente): resolución automática
- Antes de actualizar, leer las dependencias **requeridas** de cada versión nueva (CurseForge `dependencies` con `relationType == 3`; Modrinth `dependency_type == "required"`).
- Comprobar si cada dependencia ya está en la carpeta (por modId/projectId de los mods identificados, no por nombre de archivo).
- Si falta: buscar la última versión compatible (1.21.1 + NeoForge), **añadirla al plan de actualización automáticamente** y marcarla en la tabla como "Nueva dependencia de X".
- Si la versión instalada de una dependencia es más vieja que la que exige el mod, actualizarla también.
- Resolver de forma recursiva (la dependencia puede tener sus propias dependencias), con protección contra ciclos.
- Siempre se avisa antes de aplicar: "Se instalará MezzConfig 0.7.1 (requerida por JEI 19.71)". Nada se instala sin que aparezca en el resumen que el usuario confirma.
- Si una dependencia no se puede descargar por API, la actualización del mod que la necesita se **bloquea** y se muestra como "Descarga manual", para no dejar el juego roto.
- Además, revisar las dependencias de los mods **ya instalados** aunque no se actualicen (detecta carpetas que ya están rotas).
- Caso de prueba real: **JEI 19.71.0.470 requiere MezzConfig** (Modrinth project `mezzconfig`, CurseForge buscar "MezzConfig"). El test debe reproducir: JEI actualizado + MezzConfig ausente → el plan incluye MezzConfig automáticamente.

## 7. Diseño visual
- **Seguir `apple.com-DESIGN.md` de la raíz** (estilo base sacado de Refero). Los archivos de `design/references/` son solo inspiración; usar únicamente lo que indique la sección "Préstamos" de `apple.com-DESIGN.md`.
- Usar el plugin frontend-design. Si está instalado el plugin playwright, abrir el mockup, hacer captura y revisarlo antes de enseñarlo.
- Tema oscuro, sobrio. Un único color de acento.
- Tipografía legible para el texto (Inter o similar). Si se quiere un guiño a Minecraft, usar una fuente pixelada SOLO en el título.
- Nada de degradados morados, emojis decorativos ni tarjetas con brillo: que no parezca una plantilla generada.
- Animaciones mínimas: barra de progreso y transición entre pantallas.
- Antes de programar las pantallas, hacer un mockup HTML estático de la pantalla de Resultados para validar el estilo.

## 8. Distribución
- Empaquetar con **PyInstaller** en un único `ModUpdater.exe` con icono propio.
- Publicar el `.exe` en **GitHub Releases**, no dentro del repo.
- README con capturas, cómo conseguir la key de CurseForge y una advertencia: "haz copia de tu carpeta de mods la primera vez".
- Opcional más adelante: hacer el repo público.

## 9. CLAUDE.md
Crear `CLAUDE.md` en la raíz con las reglas del proyecto, para que Claude Code las siga en cada sesión:
- Nunca leer, imprimir ni commitear `.env` ni keys.
- Nunca modificar la carpeta real de mods en pruebas: usar siempre una copia temporal.
- Ejecutar los tests antes de cada commit.
- Textos de la interfaz en español.

## Orden de trabajo
1. CLAUDE.md + mejoras de la CLI (confirmación s/y, backups con límite, estados renombrados, aviso de Minecraft abierto).
2. Hito 6: dependencias.
3. Mockup HTML de la pantalla de Resultados → validación del usuario.
4. App pywebview: Configuración + Escaneo + Resultados.
5. Actualización con progreso + Final + Deshacer.
6. keyring para la key.
7. PyInstaller + Release en GitHub + README con capturas.
