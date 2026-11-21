# Seguridad

*[English below](#security-policy)*

## Cómo informar de un problema de seguridad

**No abras un issue público** para un problema de seguridad: cualquiera podría leerlo antes de que esté arreglado.

Infórmalo en privado desde GitHub:

1. Ve a la pestaña [**Security**](https://github.com/racsoga/mod_updater_Minecraft/security) del repositorio.
2. Pulsa **Report a vulnerability**.
3. Describe el problema, cómo reproducirlo y qué versión usas.

Solo lo verá el mantenedor. Intentaré responder en un plazo de 7 días. Te avisaré cuando esté arreglado y, si quieres, te mencionaré en las notas de la versión.

**No incluyas tu key de CurseForge** ni otros datos privados en el informe. Si el problema tiene que ver con la key, descríbelo sin pegarla.

## Qué cuenta como problema de seguridad

Por ejemplo:
- Que la key de CurseForge salga del equipo hacia cualquier sitio que no sea CurseForge, o que aparezca en un archivo, registro o mensaje.
- Que la app escriba o borre archivos fuera de la carpeta de mods elegida y de sus copias de seguridad.
- Que se instale un archivo sin comprobar su hash, o desde un origen que no sea CurseForge o Modrinth.
- Que el ejecutable publicado no coincida con el código de este repositorio.

Los fallos normales (un mod que sale mal clasificado, un error al actualizar…) van en un [issue](https://github.com/racsoga/mod_updater_Minecraft/issues/new/choose).

## Versiones con soporte

Solo la última versión publicada en *Releases*.

---

## Security policy

**Please don't open a public issue** for a security problem. Report it privately: go to the repository's [**Security**](https://github.com/racsoga/mod_updater_Minecraft/security) tab and press **Report a vulnerability**. Describe the problem, how to reproduce it and the version you use. Only the maintainer will see it; I'll try to reply within 7 days.

Don't include your CurseForge key or other private data in the report.

Examples of security problems: the CurseForge key being sent anywhere other than CurseForge or showing up in a file, log or message; the app writing or deleting files outside the chosen mods folder and its backups; installing a file without checking its hash or from a source other than CurseForge or Modrinth; the published executable not matching this repository's code.

Only the latest version published under *Releases* is supported.
