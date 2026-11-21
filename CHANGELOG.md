# Registro de cambios

Todos los cambios importantes de Mod Updater. Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/); versiones según [SemVer](https://semver.org/lang/es/).

La sección de cada versión es la que se publica como notas de la Release al crear la etiqueta `vX.Y.Z`.

## [0.3.0] - sin publicar

### Añadido
- **Categorías** propias para todos los mods (Tecnología, Magia, Aventura y exploración, Mundo y biomas, Mobs y combate, Construcción y decoración, Almacenamiento, Comida y granjas, Mapas e información, Calidad de vida, Rendimiento y Librerías), a partir de las de CurseForge y Modrinth.
- **Secciones** en pestañas: *Mis mods*, *Análisis* y *Ajustes*, con navegación por teclado (flechas, Inicio y Fin).
- **Análisis** de la colección:
  - Gráfico de mods por categoría con bloques isométricos, con opción de incluir las librerías y vista de tabla accesible.
  - Total de archivos (mods + librerías), tamaño, estado y fuente.
  - Los que más ocupan y el reparto entre cliente y servidor.
  - Mods sin actualizar en más de un año, separando los posiblemente abandonados de los que no tienen versión nueva para tu versión de Minecraft.
  - Librerías que ningún mod pide, según CurseForge y el `mods.toml` de cada jar, indicando si alguien las usa de forma opcional.
- **Ver cambios** antes de actualizar: panel con las notas de todas las versiones entre la instalada y la nueva (CurseForge y Modrinth), limpiadas antes de mostrarse (sin scripts ni iframes, enlaces en el navegador, imágenes solo de los CDN de CurseForge y Modrinth) y con las palabras *breaking*, *incompatible*, *requires* y *world* resaltadas.
- Tabla de correcciones de categoría (`mod_updater/knowledge/categorias.json`); al clasificar gana la categoría más específica, no la principal de CurseForge a ciegas.

## [0.2.0] - 2026-11-21

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

- Avisa si dos mods declaran que son **incompatibles** entre sí.
- Además del `.exe`, cada Release trae una **versión en carpeta (zip)** por si un antivirus bloquea el `.exe`, y las notas incluyen el SHA-256 y el enlace a VirusTotal.

### Cambiado
- Solo se guarda la última copia de seguridad (configurable) y cada una incluye `cambios.json`.
- Línea de comandos: confirmación `[S/n]`, estados con nombres claros y opción `--lang`.
- `cambios.json` se escribe desde el principio y se actualiza tras cada mod: si se cierra la ventana a mitad, **Deshacer** sabe qué quedó a medias. Al cerrar durante una actualización, la app pide confirmación.
- **Deshacer** busca la última actualización que se puede deshacer, aunque después haya habido un intento fallido.
- Si CurseForge o Modrinth no responde, se muestran los resultados de la otra fuente con un aviso.
- Un mod retirado de CurseForge se busca en Modrinth.
- La ventana se adapta al tamaño de la pantalla y la barra inferior se compacta en ventanas bajas.
- Mensajes de error traducidos y sin rutas técnicas; progreso visible al esperar sin conexión o por límite de peticiones; mensaje propio para una carpeta vacía y si falta WebView2.
- Ejecutable con información de versión, sin UPX y con el cargador de PyInstaller compilado desde el código fuente. Dependencias y acciones de GitHub fijadas a versiones exactas.

### Corregido
- Al abrir, la app avisa si la última actualización se quedó a medias y ofrece **restaurar** la carpeta. La línea de comandos también lo avisa.
- La limpieza de copias nunca borra una copia de una actualización interrumpida ni una que guarde el único ejemplar de un mod que ya no está en la carpeta.
- Deshacer una actualización interrumpida no toca los mods que no llegaron a cambiar.
- Los errores de la línea de comandos salen completamente traducidos.
- Un jar que no se puede leer ya no detiene la revisión: aparece en *Requieren atención*.
- Errores del Administrador de credenciales de Windows al guardar u olvidar la key se muestran en lugar de fallar.
- La key de CurseForge no se reenvía si la API responde con una redirección.
- El foco del teclado ya no queda oculto bajo la barra inferior; los nombres largos muestran el nombre completo al pasar el ratón.

## [0.1.0] - 2026-11-20

Primera versión, solo línea de comandos.

### Añadido
- Identificación de mods por huella en CurseForge (principal) y Modrinth (respaldo).
- Tabla de revisión sin modificar nada y actualización con `--apply`: descarga verificada por hash y copia de seguridad del archivo viejo.
