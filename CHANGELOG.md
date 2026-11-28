# Registro de cambios

Todos los cambios importantes de Mod Updater. Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/); versiones según [SemVer](https://semver.org/lang/es/).

La sección de cada versión es la que se publica como notas de la Release al crear la etiqueta `vX.Y.Z`.

## [0.4.0] - sin publicar

### Añadido
- **Activar y desactivar mods** desde *Mis mods*: interruptor en cada fila y modo *Activar o desactivar varios*. Desactivar renombra `mod.jar` a `mod.jar.disabled` (la convención de Prism, CurseForge y Modrinth App); nunca se borra nada. Filtro *Desactivados*.
  - Antes de desactivar una librería que usan mods activos, avisa ("Si desactivas Balm, dejarán de cargar Waystones…") y deja desactivar también esos o solo la librería. Al activar un mod se activan también las librerías desactivadas que necesita.
  - Los desactivados se siguen identificando y actualizando; al actualizarse siguen desactivados.
  - Solo se renombra: no crea copia de seguridad ni cuenta para el límite de copias; para deshacerlo, se vuelve a activar. No se hace con Minecraft abierto.
  - *Análisis* no los cuenta (lo indica), el `.mrpack` los deja fuera y el `.modlist.json` los marca con `"activo": false`. Al importar una lista, los mods nuevos marcados así se instalan desactivados.

- **Fijar versión** ("No actualizar este"): desde *Ver cambios* o *Versiones* en cada fila, con un motivo opcional. El mod sale como *Fijado*, en su propio grupo y filtro, y no entra en "Actualizar todo" (tampoco en la CLI, que lee las fijaciones del perfil con esa carpeta). Se guarda por perfil.
  - Si otro mod necesita una versión más nueva de uno fijado, ese otro no se actualiza y se explica por qué.
  - **Volver a una versión anterior**: el mismo panel lista las versiones publicadas para tu Minecraft y cargador; elegir una la instala (con copia de seguridad y Deshacer) y la deja fijada.
  - Exportar e importar listas respeta las fijaciones (`"fijado": true` en `.modlist.json`).

- **Diagnóstico** (pestaña nueva): lee los crash reports y los logs de la partida del perfil, en tu PC y sin IA, y dice qué mod sospechar con la línea del informe que lo demuestra. Reconoce dependencias que faltan o son viejas, mods para otra versión, incompatibilidades, mixins que fallan (y con qué otro mod chocan), mods repetidos o de otro cargador, Java y falta de memoria; los patrones están en `knowledge/crasheos.json`.
  - Acciones de un clic que no crean problemas nuevos: instalar lo que falta, cambiar un mod por otro cuando chocan ("Cambiar Embeddium por Sodium" arregla a la vez la dependencia y la incompatibilidad), activar, desactivar (nombrando también a los que dependen), actualizar o volver a una versión anterior. "Actualizar" solo se propone si hay versión más nueva.
  - Aviso en la pestaña y en *Mis mods* cuando hay un crash report nuevo. *Copiar resumen* para pegarlo en el issue del mod, sin tu usuario de Windows ni de Minecraft.

- **Buscar el mod culpable por mitades** (desde *Diagnóstico*): desactiva la mitad de los sospechosos, abres Minecraft y dices si sigue fallando; repite hasta dar con él y al terminar lo deja todo como estaba. Nunca deja un mod activo sin su librería, permite descartar mods de antemano, dice cuántas vueltas quedan, más o menos, y, si se cierra la app a medias, ofrece continuar o restaurar. Si una vuelta no se puede preparar, cancela y lo deja todo como estaba. Mientras dura, no se pueden cambiar mods desde otro sitio (ni desde la CLI).

- **Pasar a otra versión de Minecraft** (en *Análisis*): elige la versión de destino y mira cuántos de tus mods existen ya para ella con tu cargador ("142 de 150 listos"), en tres grupos: *Listos*, *Faltan* (con la fecha de su última versión) y *Con alternativa* (solo en la otra web, o un mod que hace lo mismo y sí está). Las librerías aparte. Recuerda el resultado para decirte cuántos más están listos desde la última vez. *Crear perfil para esa versión* lo prepara en una carpeta nueva y descarga lo que está listo, sin tocar tu perfil actual. Usa la lista oficial de versiones que ya se consultaba en Modrinth: no se conecta a ningún sitio nuevo.

### Cambiado
- Las notas de cada Release enlazan la **política de firma de código** (*Code signing policy*, SignPath Foundation).

### Corregido
- **Sugerencias** ya no quita un mod que necesita otro que vas a añadir o que se queda (p. ej. Balm si añades Waystones), ni sus dependencias indirectas. Lo explica en una frase en la revisión del plan. Lo mismo al importar una lista y quitar lo que sobra ([#12](https://github.com/racsoga/mod_updater_Minecraft/issues/12)).

## [0.3.0] - 2026-11-21

### Añadido
- **Categorías** propias para todos los mods (Tecnología, Magia, Aventura y exploración, Mundo y biomas, Mobs y combate, Construcción y decoración, Almacenamiento, Comida y granjas, Mapas e información, Calidad de vida, Rendimiento y Librerías), a partir de las de CurseForge y Modrinth.
- **Secciones** en pestañas: *Mis mods*, *Análisis*, *Explorar*, *Sugerencias* y *Ajustes*, con navegación por teclado (flechas, Inicio y Fin).
- **Análisis** de la colección:
  - Gráfico de mods por categoría con bloques isométricos, con opción de incluir las librerías y vista de tabla accesible.
  - Total de archivos (mods + librerías), tamaño, estado y fuente.
  - Los que más ocupan y el reparto entre cliente y servidor.
  - Mods sin actualizar en más de un año, separando los posiblemente abandonados de los que no tienen versión nueva para tu versión de Minecraft.
  - Librerías que ningún mod pide, según CurseForge y el `mods.toml` de cada jar, indicando si alguien las usa de forma opcional.
- **Ver cambios** antes de actualizar: panel con las notas de todas las versiones entre la instalada y la nueva (CurseForge y Modrinth), limpiadas antes de mostrarse (sin scripts ni iframes, enlaces en el navegador, imágenes solo de los CDN de CurseForge y Modrinth) y con las palabras *breaking*, *incompatible*, *requires* y *world* resaltadas.
- **Explorar**: busca mods en CurseForge y Modrinth a la vez, siempre para tu versión de Minecraft y cargador, sin duplicados entre fuentes. Filtros por categoría y orden, opción de ocultar los que ya tienes, ficha de cada mod (descripción, capturas, enlaces, versión que se instalaría y dependencias) y **cesta** para instalar varios a la vez con sus dependencias, copia de seguridad y Deshacer. Los mods que el autor no deja descargar desde otras apps aparecen como *Descarga manual*.
- **Perfiles**: varias carpetas de mods o instancias, cada una con su versión de Minecraft, cargador y ajustes. Se detectan solas las del launcher oficial, CurseForge, Prism Launcher, MultiMC y Modrinth App, y se puede añadir cualquier carpeta. Selector en la cabecera; la revisión, el análisis y Explorar usan el perfil activo; las copias y Deshacer van con la carpeta de cada perfil. Los ajustes anteriores pasan a un perfil *Principal* sin perder nada, y se avisa si dos perfiles usan la misma carpeta.
- **Compartir la lista de mods**: exportar el perfil a un archivo `.modlist.json` (sin rutas, key ni datos personales) o a un `.mrpack` de Modrinth para otros launchers; importar una lista e instalar las versiones **exactas**, con la comparación previa (qué se añade, qué cambia de versión, qué no está disponible y, si se quiere, quitar lo que sobra) y aviso si es de otra versión de Minecraft; comparar dos perfiles sin instalar nada; copiar la lista legible para pegarla en un chat.
- **Quitar mods** de forma segura: se mueven a la copia de seguridad y Deshacer los devuelve.
- **Sugerencias según el tipo de partida**: cuestionario (solo o con gente, estilos, dificultad, PC y número de mods) y resultado en *Quitar · Revisar · Mantener · Añadir* con el motivo de cada sugerencia, a partir de una base de conocimiento propia (mods que hacen lo mismo, incompatibilidades, recomendados por estilo y mods que suben mucho la dificultad). Por reglas, sin IA externa; nada se aplica sin marcarlo. Un mod posiblemente abandonado solo se propone quitar si tienes otro activo que hace lo mismo, y las librerías de configuración (Cloth Config, YACL…) solo llevan un aviso, porque muchos mods las usan de forma opcional para su menú de ajustes.
- **Aviso de versiones nuevas** de Mod Updater (como mucho una vez al día, desactivable en Ajustes): enlaza a la página de la Release, sin actualizarse sola.
- Tabla de correcciones de categoría (`mod_updater/knowledge/categorias.json`); al clasificar gana la categoría más específica, no la principal de CurseForge a ciegas.

### Cambiado
- **Revisión más rápida**: las consultas a CurseForge y Modrinth van en lotes en paralelo, y Modrinth se consulta a la vez que CurseForge (con unos 140 mods y la caché llena, de unos 4 s a unos 2 s).

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
