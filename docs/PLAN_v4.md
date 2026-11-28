# Plan v4 — Mod Updater 0.4.0

Continuación de `docs/PLAN_v3.md`. La v0.3.0 está publicada (28/11/2026). El tema de esta versión es **que la partida no se rompa**: saber qué falla, aislarlo, no actualizar lo que no toca y poder cambiar de versión de Minecraft o preparar el servidor sin sustos.

Todo lo de `CLAUDE.md` sigue vigente: carpeta real de mods en solo lectura durante las pruebas, key nunca visible, tests antes de cada commit, textos en `es.json` y `en.json`, estilo de `apple.com-DESIGN.md` (local) y paleta actual de la app.

---

## 0. Forma de trabajar

Igual que en la v3:
- **Una rama por hito** y un **pull request** a `main` que se fusiona solo con el check "Tests" en verde. Nada de commits directos a `main`.
- En cada hito: implementar → tests (unitarios + de interfaz con el simulador) → capturas con Playwright → auditoría con Impeccable → `CHANGELOG.md` (sección `[0.4.0] - sin publicar`) y README si cambia algo visible → PR → fusionar.
- Usar las skills de superpowers (writing-plans para cada hito; subagentes para tareas independientes).
- **Puntos de control (🛑):** parar, enseñar capturas y esperar el OK de Oscar. Fuera de ellos, seguir sin preguntar.
- Decisión no prevista: si no es reversible, preguntar; si lo es, elegir lo más sencillo y apuntarlo en el resumen del hito.
- Al terminar cada hito, resumen corto: qué se hizo, qué se probó, qué queda raro.
- Nada se envía fuera del PC salvo las consultas a CurseForge/Modrinth/Mojang que ya hace la app. Los logs y crash reports **nunca** se suben a ningún sitio.

## Orden de los hitos
1. S3: dependencias al combinar Añadir y Quitar (issue #12)
2. Activar y desactivar mods
3. Fijar versión y volver a una versión anterior
4. Diagnóstico de crasheos
5. Búsqueda por mitades (encontrar el mod que rompe la partida)
6. ¿Puedo pasar a otra versión de Minecraft?
7. Preparar el servidor
8. Copia y exportación de la configuración
9. Shaders y resource packs
10. Recomendación de memoria (RAM)
11. Firma del `.exe` con SignPath (en paralelo, no bloquea la Release)
12. Pulido, QA y Release 0.4.0

El orden importa: la búsqueda por mitades (5) usa activar/desactivar (2); el diagnóstico (4) propone acciones de 2 y 3; preparar el servidor (7) reutiliza los perfiles y el lado cliente/servidor de la 0.3.0.

---

## 1. S3: dependencias al combinar Añadir y Quitar

- Reproducir primero con un test: en Sugerencias, marcar Añadir un mod que depende de X y Quitar X a la vez.
- Al construir el plan, recalcular dependencias con el estado final (lo instalado − lo que se quita + lo que se añade). Si algo que se quita es necesario para algo que queda o se añade: no quitarlo y explicarlo en una frase ("No se quita Balm: lo necesita Waystones, que vas a añadir").
- Lo mismo al quitar a mano desde Mis mods.
- Cerrar el issue #12 desde el PR.

**Tests:** el caso de S3, dependencia indirecta (A → B → C), quitar dos mods que se necesitan entre sí, que no cambie nada si no hay conflicto.

---

## 2. Activar y desactivar mods

- Desactivar = renombrar `mod.jar` a `mod.jar.disabled` (convención que respetan launchers como Prism, CurseForge y Modrinth App). Activar = quitar el sufijo. Nunca se borra nada.
- El escáner lista también los `.jar.disabled`, con estado **Desactivado**. Siguen identificándose (el hash no cambia con el nombre) para poder actualizarlos.
- Al actualizar un mod desactivado, el nuevo también queda desactivado.
- Interruptor en cada fila de Mis mods y acción en bloque ("Desactivar seleccionados").
- Avisar antes de desactivar una librería que usan mods activos ("Si desactivas Balm, dejarán de cargar Waystones y 3 más"), con opción de desactivar también los que dependen de ella.
- Bloquear con mensaje claro si Minecraft está abierto (`procs.py`).
- Análisis y exportar: los desactivados se cuentan aparte y no van en el `.mrpack` (sí en `.modlist.json`, con `"activo": false`).
- Deshacer: cada cambio queda en el historial del perfil como el resto.

**Tests:** renombrado ida y vuelta, escaneo con desactivados, actualizar un desactivado, aviso de librería, Minecraft abierto, nombres raros (`.JAR`, dobles extensiones).

---

## 3. Fijar versión y volver a una versión anterior

- **Fijar** ("No actualizar este"): el mod sale como *Fijado* y no entra en "Actualizar todo". Se guarda por perfil con el motivo opcional que escriba el usuario.
- **Volver a una versión anterior:** en el panel "Ver cambios", lista de versiones disponibles para la versión de Minecraft y el cargador del perfil; elegir una instala esa (con copia y Deshacer) y la deja fijada.
- Si un mod fijado bloquea una dependencia nueva que pide otro mod, avisarlo.
- Exportar e importar respetan las fijaciones (`"fijado": true` en `.modlist.json`).

**Tests:** fijado no se actualiza, volver atrás instala la versión exacta, fijación por perfil, exportar/importar con fijados.

---

## 4. Diagnóstico de crasheos

Pantalla nueva **Diagnóstico** (o sección en Mis mods) que lee, de la carpeta de la partida del perfil (la que contiene `mods`):
- `crash-reports/*.txt` (el más reciente por defecto, con selector).
- `logs/latest.log` y, si existe, `logs/debug.log`.

**Motor por reglas, local, sin IA externa:**
- Errores de carga de NeoForge: dependencias obligatorias que faltan o con versión incorrecta, mod duplicado, mod para otro cargador o para otra versión de Minecraft.
- Excepciones de Mixin que nombran el mod o su archivo de configuración de mixins.
- Trazas de pila: mapear los paquetes Java de los frames al mod que los contiene (el escáner ya lee los `.jar`; guardar los paquetes de cada uno en la caché) y señalar el más probable.
- Falta de memoria (`OutOfMemoryError`) → enlazar con el hito 10.
- Base de patrones en `mod_updater/knowledge/crasheos.json`, versionada y con tests, para añadir casos sin tocar código.

**Resultado:** "Sospechoso: X" con el **motivo en una frase** y la línea del log que lo demuestra, y acciones de un clic: instalar la dependencia que falta, actualizar X, volver a una versión anterior (hito 3), desactivar X (hito 2) o, si no está claro, empezar la búsqueda por mitades (hito 5).
- Botón "Copiar resumen" para pegarlo en un issue del mod, **quitando el nombre de usuario de Windows y de Minecraft** de las rutas y del texto.
- Texto honesto: es una ayuda, no siempre acierta.

**🛑 Punto de control A:** mockup de la pantalla de Diagnóstico con un crash report real de Oscar (si tiene alguno) o uno de ejemplo.

**Tests:** un crash de ejemplo por cada regla (en `tests/fixtures/`, inventados o anonimizados), log sin errores, log enorme (no congelar la ventana), codificación rara, anonimización del resumen.

---

## 5. Búsqueda por mitades

Asistente para encontrar el mod que rompe la partida cuando el diagnóstico no basta:
1. Hace una copia del estado actual (qué está activo).
2. Desactiva la mitad de los mods sospechosos, **manteniendo juntas las dependencias** (nunca deja un mod activo sin su librería).
3. "Abre Minecraft y dime: ¿falla?" → Sí / No. Según la respuesta, sigue con la mitad que corresponde.
4. Al final: "El problema está en X" (o en el grupo X + Y) y **restaura todo como estaba**, con la acción sugerida.
- Permite marcar mods como "seguro que no es este" para descartarlos desde el principio.
- Muestra cuántas vueltas faltan como máximo (con 150 mods, unas 7–8).
- Si se cierra la app a mitad, al volver ofrece continuar o restaurar.

**🛑 Punto de control B:** capturas del asistente antes de fusionar.

**Tests:** con 1, 2, 7 y 150 mods ficticios, dependencias que obligan a mover grupos, restaurar al cancelar, retomar tras cerrar.

---

## 6. ¿Puedo pasar a otra versión de Minecraft?

- Selector de versión de destino. La lista sale del manifiesto oficial de versiones de Mojang (comprobar la URL actual antes de usarla; caché de un día), solo versiones *release*.
- **Privacidad:** si se consulta el manifiesto de Mojang, añadirlo a la sección *Privacidad* del README (es/en) y a la de `CODE_SIGNING_POLICY.md` (nota de Oscar, 28/11).
- Para cada mod del perfil, consultar en CurseForge y Modrinth si hay versión para el destino y el cargador del perfil.
- Resultado: "142 de 150 listos" con tres grupos: **Listos**, **Faltan** (con fecha de su última versión, para ver si está vivo) y **Con alternativa** (existe en la otra web o hay un mod del mismo grupo de solapamiento que sí está).
- Las librerías se agrupan aparte: lo que importa es si los mods que las usan están listos.
- Botón **Crear perfil nuevo para esa versión**: nueva carpeta (la elige el usuario), descarga lo que está listo y **no toca el perfil actual**.
- Guardar el resultado para comparar más adelante ("desde la última vez, 5 mods más listos").

**🛑 Punto de control C:** captura con la carpeta real de Oscar y el destino que él elija.

**Tests:** recuento, mods solo en una web, alternativa por solapamiento, sin red, crear perfil nuevo sin tocar el original.

---

## 7. Preparar el servidor

- Un perfil puede marcarse como **Servidor** (carpeta `mods` del servidor, p. ej. la de `NEW_NEO_SERVER`).
- **Copiar del perfil de cliente al de servidor** solo lo necesario: mods de ambos lados y de servidor; los de solo cliente se quedan fuera (dato de la 0.3.0, S5). Los de lado desconocido se preguntan.
- Comparar cliente y servidor: qué falta, qué sobra y qué versiones no coinciden ("el servidor tiene Create 6.0.1 y tú 6.0.4").
- Antes de tocar la carpeta del servidor: copia de seguridad y Deshacer, como en cualquier perfil. Bloquear si el servidor está en marcha (proceso `java` con esa carpeta).
- Reutilizar exportar/importar donde se pueda.

**Tests:** filtrado por lado, lado desconocido, comparación de versiones, servidor en marcha, Deshacer.

---

## 8. Copia y exportación de la configuración

- Las copias de seguridad incluyen también la carpeta `config` del perfil (opcional, activado por defecto). Solo se guarda si ha cambiado desde la última copia.
- **Exportar con configuración:** un `.zip` con el `.modlist.json` y la carpeta `config` (y `defaultconfigs` si existe), sin rutas absolutas, sin la key y sin archivos de más de 5 MB (avisar de los que se quedan fuera).
- **Importar con configuración:** muestra qué archivos de config se sobrescribirían; copia de seguridad antes.
- Caso de uso: que la pareja de Oscar tenga los mismos mods **y** los mismos ajustes.

**Tests:** ida y vuelta, archivo grande excluido, que no se cuelen rutas ni datos personales, importar sobre config existente.

---

## 9. Shaders y resource packs

- Además de `mods`, gestionar `resourcepacks` y `shaderpacks` de la carpeta de la partida.
- CurseForge: clases propias de resource packs y shaders (comprobar los `classId` con `GET /v1/categories?gameId=432&classesOnly=true`). Modrinth: `project_type` `resourcepack` y `shader`.
- Identificación por hash igual que los mods (también son `.zip`).
- En Mis mods y Explorar: selector de **Tipo** (Mods · Resource packs · Shaders). Actualizar, copia y Deshacer funcionan igual.
- Los shaders necesitan un mod cargador (Iris, Oculus…): si no está instalado, avisarlo al instalar un shader.

**Tests:** escaneo de las dos carpetas, identificación, filtro por tipo, aviso de cargador de shaders.

---

## 10. Recomendación de memoria (RAM)

- Leer la RAM total del PC y contar los mods activos del perfil.
- Recomendar cuánta memoria asignar a Minecraft con una regla sencilla y explicada (por número de mods y RAM total, dejando margen para Windows). **Basar los tramos en fuentes reconocidas y citarlas en el código**; no inventar cifras.
- Mostrar el argumento listo para copiar (`-Xmx…G`) y dónde pegarlo en el launcher oficial (Instalaciones → Editar → Más opciones → Argumentos de JVM).
- **Solo lectura:** la app no modifica `launcher_profiles.json`.
- Si el diagnóstico (hito 4) detecta `OutOfMemoryError`, enlazar aquí.
- Aviso si se asigna más de lo razonable (más memoria no siempre es mejor).

**Tests:** tramos de la regla, PC con poca RAM, perfil sin mods.

---

## 11. Firma del `.exe` con SignPath (en paralelo)

Objetivo: acabar con los falsos positivos y el aviso de SmartScreen. SignPath Foundation firma gratis proyectos de código abierto si el `.exe` se compila de forma automática desde el repo público (ya lo hace `.github/workflows/release.yml`).
1. Revisar las condiciones actuales en signpath.org y comprobar que el proyecto las cumple (licencia OSI, sin componentes propietarios, compilación en GitHub Actions, MFA en GitHub).
2. Añadir `CODE_SIGNING_POLICY.md` y la frase de atribución que pida SignPath en el README.
3. Preparar el texto de la solicitud y **dárselo a Oscar** para que la envíe él (requiere su cuenta).
4. Cuando la aprueben: integrar el paso de firma en `release.yml`.

No bloquea la Release 0.4.0: si no está aprobada a tiempo, se publica sin firmar como hasta ahora.

---

## 12. Pulido, QA y Release 0.4.0

0. **Búsqueda por mitades: "Buscar con qué otro mod choca"** (decisión de Oscar en el punto de control B, 28/11). Cuando el fallo viene de dos mods juntos (A con B), la búsqueda señala a uno (A). Botón en el resultado que repite la búsqueda dejando A siempre activo para encontrar B. Mientras tanto, el resultado ya avisa de que puede ser una combinación.
0. **Pasar a otra versión** (notas de Oscar en el punto de control C, 28/11): en *Faltan*, junto a "última versión publicada", decir para qué versión es (p. ej. "nov 2026 (para 26.1)"), que si no parece que el mod esté al día; y quitar del nombre mostrado las etiquetas entre corchetes que ponen los autores (p. ej. "[Fabric | Forge | Quilt]").
1. Pasada completa con **qa-bug-hunter** e **Impeccable** sobre todas las pantallas nuevas. Corregir críticos e importantes sin preguntar; preguntar por los menores dudosos.
2. Accesibilidad: teclado, contraste, `prefers-reduced-motion`, textos alternativos.
3. Rendimiento: abrir con 150 mods en menos de 3 s con caché; leer logs grandes y consultar versiones sin congelar la ventana.
4. README (es/en): capturas nuevas, funciones, preguntas frecuentes (desactivar, fijar, diagnóstico, migrar, servidor).
5. `CHANGELOG.md` con fecha y versión `0.4.0` en `mod_updater/__init__.py`.
6. **🛑 Punto de control D:** etiqueta `v0.4.0` → Release en **borrador**. Dar a Oscar el enlace y los SHA-256 para que lo pruebe y lo pase por VirusTotal. Publicar solo con su OK, con el enlace de VirusTotal en las notas y en el README. No se reportan los falsos positivos a los antivirus (decisión del 28/11).
