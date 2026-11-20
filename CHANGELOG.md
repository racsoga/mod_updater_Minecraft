# Registro de cambios

Todos los cambios importantes de Mod Updater. Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/); versiones según [SemVer](https://semver.org/lang/es/).

La sección de cada versión es la que se publica como notas de la Release al crear la etiqueta `vX.Y.Z`.

## [0.2.0] - sin publicar

Primera versión con ventana propia.

### Añadido
- **App de escritorio** (`ModUpdater.exe`): pantallas de bienvenida, revisión con progreso, resultados, actualización con estado por mod y pantalla final.
- **Deshacer** la última actualización: los archivos viejos vuelven y los nuevos se apartan en la copia, sin borrarse.
- **Dependencias automáticas**: si a un mod le falta otro que necesita, se instala con él. Si no se puede descargar, el mod no se actualiza para no romper el juego.
- Avisa si un mod al día tiene una **beta más reciente**.
- No toca nada si **Minecraft está abierto** con esa carpeta.
- **Idiomas**: español e inglés. Usa el idioma de Windows (español si es español, catalán, gallego o euskera; inglés en el resto) y se cambia en Ajustes.
- Pensado para NeoForge, Forge, Fabric y Quilt; **probado con NeoForge 1.21.1**.
- Versión de Minecraft y cargador de mods **deducidos de tus mods**, con desplegable de versiones reales.
- La key de CurseForge se guarda en el **Administrador de credenciales de Windows**.
- Ajustes: carpeta, key, betas, número de copias que se guardan, borrar copias e idioma.
- Logo propio (yunque en pixel art) e icono en la ventana y el ejecutable.

### Cambiado
- Solo se guarda la última copia de seguridad (configurable) y cada una incluye `cambios.json`.
- Línea de comandos: confirmación `[S/n]`, estados con nombres claros y opción `--lang`.

## [0.1.0] - 2026-11-20

Primera versión, solo línea de comandos.

### Añadido
- Identificación de mods por huella en CurseForge (principal) y Modrinth (respaldo).
- Tabla de revisión sin modificar nada y actualización con `--apply`: descarga verificada por hash y copia de seguridad del archivo viejo.
