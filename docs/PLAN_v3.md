# Plan v3 — Mod Updater 0.3.0

Continuación de `docs/PLAN.md` (v1, CLI) y `docs/PLAN_v2.md` (v2, app). La v0.2.0 está publicada. Este plan añade siete funciones y está pensado para ejecutarse de forma autónoma, con **puntos de control** en los que hay que parar y esperar la validación de Oscar.

Todo lo de `CLAUDE.md` sigue vigente: carpeta real de mods en solo lectura durante las pruebas, key nunca visible, tests antes de cada commit, textos en `es.json` y `en.json`, estilo de `apple.com-DESIGN.md` (local) y paleta actual de la app.

---

## 0. Forma de trabajar

- **Una rama por hito** (`feat/analisis`, `feat/sugerencias`…), con un **pull request** a `main` que se fusiona solo cuando el check "Tests" está en verde. No se hacen commits directos a `main`.
- En cada hito: implementar → tests (unitarios + de interfaz con el simulador) → capturas con Playwright → auditoría con Impeccable → actualizar `CHANGELOG.md` (sección `[0.3.0] - sin publicar`) y los README si cambia algo visible → PR → fusionar.
- Usar las skills de superpowers para planificar cada hito (writing-plans) y, si conviene, subagentes para tareas independientes.
- **Puntos de control (🛑):** parar, enseñar capturas y esperar el OK de Oscar. Fuera de ellos, seguir sin preguntar.
- Si una decisión no está en este plan y no es reversible, preguntar. Si es reversible, elegir lo más sencillo y apuntarlo en el resumen del hito.
- Al terminar cada hito, un resumen corto: qué se hizo, qué se probó, qué queda raro.

## Orden de los hitos
1. Base común: categorías y navegación
2. Análisis de la colección
3. Ver el changelog antes de actualizar
4. Buscar e instalar mods
5. Perfiles (varias carpetas o instancias)
6. Exportar e importar la lista de mods
7. Sugerencias según el tipo de partida
8. Aviso de nuevas versiones de la app
9. Pulido, QA y Release 0.3.0

El orden importa: el análisis y las sugerencias necesitan las categorías (hito 1); las sugerencias reutilizan la búsqueda e instalación (hito 4).

---

## 1. Base común: categorías y navegación

**Categorías unificadas**
- CurseForge: `GET /v1/categories?gameId=432&classId=6` (clase Mods). Cada categoría trae `id`, `name`, `slug`, `iconUrl` y `parentCategoryId`. Cada mod trae `categories[]` y `primaryCategoryId`.
- Modrinth: `GET /v2/tag/category` (nombre, `project_type`, `header`, icono SVG). Cada proyecto trae `categories[]`.
- Crear `mod_updater/categories.py` con un **mapa propio de ~12 categorías** a las que se traducen las de ambas fuentes, con icono propio coherente con la app:
  Tecnología · Magia · Aventura y exploración · Mundo y biomas · Mobs y combate · Construcción y decoración · Almacenamiento · Comida y granjas · Mapas e información · Calidad de vida · Rendimiento · Librerías.
- Usar la **categoría principal** de cada mod para los gráficos (`primaryCategoryId` en CurseForge; en Modrinth, la primera que mapee). Guardar todas para los filtros.
- Las librerías (Balm, Architectury, Kotlin for Forge…) se marcan como tales y se pueden ocultar de los gráficos.
- Caché de categorías e iconos en `%APPDATA%\mod_updater\cache` (una semana).

**Navegación**
- Pasar de una sola pantalla a una barra lateral o pestañas: **Mis mods** (la pantalla actual) · **Análisis** · **Explorar** · **Sugerencias** · **Ajustes**. Arriba, el selector de **perfil** (hito 5).
- Mantener el atajo `/` para buscar y la navegación con teclado.

**Tests:** mapa de categorías (cada categoría de CurseForge y Modrinth cae en una de las nuestras o en "Otras"), caché, mods sin categoría.

---

## 2. Análisis de la colección

Una pantalla que enseña cómo es tu colección de un vistazo.

**Contenido**
- **Gráfico principal:** mods por categoría. Estilo **barras isométricas de bloques** (columnas apiladas de cubos tipo Minecraft, con el icono de la categoría encima): da el toque 3D sin perder legibilidad. Cada columna muestra el número. Hover/foco: lista de los mods de esa categoría.
  - Hacerlo con SVG o canvas propio, sin librerías pesadas. Animación de entrada corta (los bloques "caen"), que respete `prefers-reduced-motion`.
  - Alternativa accesible: tabla con los mismos datos, oculta visualmente pero disponible para lectores de pantalla y con un botón "Ver como tabla".
- **Tarjetas de cifras:** total de mods, librerías, tamaño total de la carpeta, mods al día / con actualización, fuente (CurseForge/Modrinth).
- **Otros datos útiles:**
  - Los 5 mods más pesados (MB).
  - Mods sin actualizar desde hace más de un año (posible abandono).
  - Mods que nadie necesita: librerías que ya no usa ningún mod instalado (candidatas a borrar).
  - Reparto de lado cliente/servidor si las fuentes lo dan (útil para el servidor).
- Interruptor "Incluir librerías".

**🛑 Punto de control A:** mockup del gráfico y de la pantalla con los datos reales de la carpeta de Oscar, en escritorio y ventana pequeña. Esperar OK antes de terminar el hito.

**Tests:** recuento por categoría, detección de librerías huérfanas, mods sin fecha, carpeta vacía.

---

## 3. Ver el changelog antes de actualizar

- En **Mis mods**, cada fila con actualización tiene un botón "Ver cambios" que abre un panel lateral con el changelog de **todas las versiones entre la instalada y la nueva**, no solo la última.
- CurseForge: `GET /v1/mods/{modId}/files/{fileId}/changelog` (HTML). Modrinth: campo `changelog` (Markdown) de cada versión.
- **Seguridad:** el HTML/Markdown se limpia antes de mostrarlo (lista blanca de etiquetas, sin scripts, sin iframes, enlaces abiertos en el navegador del sistema, imágenes solo de los CDN conocidos).
- Si el changelog está vacío: "El autor no ha publicado notas para esta versión" y un enlace a la página del mod.
- Marcar visualmente las palabras "breaking", "incompatible", "requires", "world" (posibles cambios que rompen partidas) para llamar la atención.

**Tests:** limpieza de HTML malicioso, rango de versiones, changelog vacío.

---

## 4. Buscar e instalar mods (Explorar)

- **Búsqueda** en CurseForge (`/v1/mods/search` con `gameId=432`, `classId=6`, `gameVersion`, `modLoaderType`, `sortField`) y Modrinth (`/v2/search` con facetas de versión, loader y categoría). Siempre filtrado por la versión y el cargador del perfil activo.
- Resultados **combinados y sin duplicados** (un mod que está en las dos fuentes aparece una vez; preferir CurseForge si hay key, igual que en las actualizaciones).
- Filtros: categoría (las del hito 1), orden (popularidad, descargas, actualizado recientemente, nombre), "ocultar los que ya tengo".
- **Tarjeta de resultado:** logo, nombre, autor, resumen, descargas, última actualización, categorías, insignia "Ya instalado".
- **Detalle:** descripción (limpia, como en el hito 3), capturas, enlaces a la página, dependencias requeridas, versión que se instalaría.
- **Instalar:** reutiliza el downloader y la resolución de dependencias existentes (copia de seguridad, hash, deshacer). Instalar varios a la vez desde una "cesta".
- Respetar `allowModDistribution == false`: mostrar "Descarga manual" con el enlace.
- Paginación o scroll infinito, con caché y sin saturar las APIs (máximo de peticiones por segundo).

**🛑 Punto de control B:** capturas de Explorar (búsqueda, detalle, cesta) antes de fusionar.

**Tests:** fusión de resultados de ambas fuentes, filtro por versión y cargador, instalación con dependencias, mod ya instalado.

---

## 5. Perfiles

- Un **perfil** = nombre + carpeta de mods + versión de Minecraft + cargador + ajustes propios (betas, copias).
- **Detección automática** de instancias al crear un perfil:
  - Launcher oficial: `%APPDATA%\.minecraft\launcher_profiles.json` (campo `gameDir` de cada instalación).
  - CurseForge: `%USERPROFILE%\curseforge\minecraft\Instances\*` (`minecraftinstance.json`).
  - Prism / MultiMC: `instances\*\` con `instance.cfg` y `mmc-pack.json`.
  - Modrinth App: su carpeta de perfiles (`profile.json`).
  - Siempre se puede añadir una carpeta a mano.
- Selector de perfil en la cabecera; la revisión, el análisis, Explorar y las sugerencias trabajan sobre el perfil activo.
- Migración: los ajustes actuales se convierten en un perfil "Principal" sin perder nada.
- Las copias de seguridad y Deshacer son **por perfil**.
- Avisar si dos perfiles apuntan a la misma carpeta.

**Tests:** migración de ajustes, lectura de cada formato de launcher con ejemplos ficticios, perfiles duplicados, carpeta borrada.

---

## 6. Exportar e importar la lista de mods

Caso de uso principal: que la pareja de Oscar tenga exactamente los mismos mods para jugar en el servidor.

- **Exportar** el perfil a un archivo `.modlist.json` propio y versionado:
  ```json
  {
    "formato": 1,
    "app": "Mod Updater 0.3.0",
    "minecraft": "1.21.1",
    "cargador": "neoforge",
    "mods": [
      {"nombre": "Create", "fuente": "curseforge", "proyecto": 328085, "archivo": 1234567, "sha1": "…", "categoria": "tecnologia"}
    ]
  }
  ```
  Sin rutas, sin key ni datos personales.
- Opción de exportar también como **`.mrpack`** (formato estándar de Modrinth) para que se pueda abrir en otros launchers. Solo con mods de Modrinth o con URLs de descarga permitidas; avisar de los que no se pueden incluir.
- **Importar:** elegir archivo → pantalla de comparación con el perfil destino: "Se añadirán 12, se actualizarán 3, se quitarán 2 (opcional), 1 no disponible". Instalar con copia y Deshacer, con las versiones **exactas** del archivo.
- **Comparar dos perfiles** (por ejemplo, el de Oscar y el del servidor) sin instalar nada.
- Copiar una **lista legible** al portapapeles (nombre + versión) para pegarla en un chat.

**Tests:** ida y vuelta exportar/importar, archivo de otra versión de Minecraft (avisar), archivo corrupto, mods no descargables, que el archivo nunca contenga rutas ni la key.

---

## 7. Sugerencias según el tipo de partida

**Cuestionario** (una pantalla, con tarjetas grandes y iconos):
1. ¿Solo o con más gente? (solo / con amigos / servidor)
2. ¿Qué te apetece? (varias): tecnología y automatización · magia · exploración y aventura · construir y decorar · granjas y comida · combate y jefes · tranquilo/creativo.
3. Dificultad: relajada / normal / reto.
4. ¿Cómo va tu PC? (justo / normal / potente) — para pesar los mods de rendimiento y los muy pesados.
5. ¿Cuántos mods quieres como máximo? (sin límite / unos 50 / unos 100 / unos 150).

Guardar las respuestas en el perfil.

**Motor de sugerencias (por reglas, sin IA externa ni datos personales enviados a nadie)**
- Base de conocimiento propia en `mod_updater/knowledge/*.json`, versionada y con tests:
  - **Grupos de solapamiento:** mods que hacen lo mismo (dos visores de recetas, dos minimapas, varios mods de mochilas…). Ej.: JEI / EMI / REI; Xaero's / JourneyMap; Sodium / Embeddium.
  - **Incompatibilidades conocidas** además de las que declaran las APIs.
  - **Esenciales por estilo:** para cada respuesta del cuestionario, una lista corta de mods recomendados con el motivo, identificados por proyecto de CurseForge/Modrinth.
  - **Mods "duros":** los que suben mucho la dificultad (Born in Chaos, Infernal Mobs…), para el filtro de dificultad.
- Señales de las APIs: categorías, descargas, fecha de la última versión, si existe para tu versión y cargador.
- **Resultado en tres columnas: Quitar · Mantener · Añadir**, cada sugerencia con **el motivo en una frase** ("Tienes dos minimapas: Xaero's y JourneyMap", "Sin actualizar desde 2024", "Muy popular en partidas de tecnología con Create"). Nada se aplica sin que el usuario lo marque.
- "Añadir" reutiliza la instalación del hito 4 y "Quitar" mueve los mods a la copia de seguridad (se puede deshacer), nunca borra.
- Las sugerencias de añadir solo incluyen mods que existen para la versión y el cargador del perfil.
- Texto honesto en la pantalla: son recomendaciones automáticas; revisa antes de aplicar.

**🛑 Punto de control C:** cuestionario y pantalla de resultados con la carpeta real de Oscar (partida en solitario). Oscar revisa si las sugerencias tienen sentido antes de dar por bueno el motor.

**Tests:** cada regla con casos ficticios, solapamientos, filtro por dificultad, límite de mods, que nunca sugiera un mod incompatible con la versión.

---

## 8. Aviso de nuevas versiones de la app

- Al abrir (como máximo una vez al día), consultar `GET https://api.github.com/repos/racsoga/mod_updater_Minecraft/releases/latest`.
- Si hay una versión mayor: aviso discreto en la cabecera "Mod Updater 0.4.0 disponible · Ver novedades", con las notas de la Release.
- Botón **Descargar**: abre la página de la Release en el navegador (no autoactualización automática: menos riesgo y menos falsos positivos de antivirus). Recordar la comprobación del SHA-256.
- Opción en Ajustes para desactivar el aviso. Sin red, no molestar.

**Tests:** comparación de versiones, sin red, respuesta inesperada de GitHub, aviso desactivado.

---

## 9. Pulido, QA y Release 0.3.0

1. Pasada completa con **qa-bug-hunter** (instalado) y con **Impeccable** sobre todas las pantallas nuevas. Informe por gravedad; corregir críticos e importantes sin preguntar, y preguntar por los menores dudosos.
2. Accesibilidad: teclado en todas las pantallas nuevas, contraste, `prefers-reduced-motion`, textos alternativos de gráficos.
3. Rendimiento: abrir la app con 150 mods en menos de 3 s con caché; la búsqueda no debe congelar la ventana.
4. README (es/en): nuevas capturas y GIF, sección de funciones actualizada, preguntas frecuentes nuevas (perfiles, importar, sugerencias).
5. `CHANGELOG.md` con la fecha y la versión `0.3.0` en `mod_updater/__init__.py`.
6. **🛑 Punto de control D:** crear la etiqueta `v0.3.0` → Release en **borrador**. Dar a Oscar el enlace y los SHA-256 para que pruebe el `.exe` en el otro ordenador y lo pase por VirusTotal. Publicar solo con su OK, añadiendo el enlace de VirusTotal a las notas.
