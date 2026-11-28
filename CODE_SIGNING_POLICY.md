# Code signing policy · Política de firma de código

*English below.*

## Español

**Estado:** solicitud a SignPath Foundation en curso. Hasta que la aprueben, los `.exe` de las Releases **no están firmados**; compruébalos con el SHA-256 y el informe de VirusTotal de las notas de cada Release.

Cuando esté aprobada: firma de código gratuita proporcionada por [SignPath.io](https://about.signpath.io), certificado de [SignPath Foundation](https://signpath.org).

### Qué se firma
- Solo los ejecutables de Mod Updater (`ModUpdater.exe` y el de la versión en carpeta) compilados por GitHub Actions (`.github/workflows/release.yml`) a partir del código de este repositorio, al crear la etiqueta `vX.Y.Z`.
- Nunca binarios compilados a mano ni de otros proyectos. Las librerías de terceros se incluyen tal como las publican sus autores.

### Equipo y funciones
| Función | Quién |
|---|---|
| Autor (puede cambiar el código sin revisión adicional) | [Oscar Gonzalez (@racsoga)](https://github.com/racsoga) |
| Revisor (todo cambio de alguien de fuera del equipo pasa por un pull request revisado) | [Oscar Gonzalez (@racsoga)](https://github.com/racsoga) |
| Aprobador (aprueba a mano cada firma) | [Oscar Gonzalez (@racsoga)](https://github.com/racsoga) |

La rama `main` está protegida: todo cambio entra por pull request y con los tests en verde. Es obligatorio que todo el equipo use autenticación en dos pasos en GitHub y en SignPath.

### Privacidad
Este programa solo se conecta a CurseForge y Modrinth para hacer lo que pide el usuario (enviando solo la huella de cada `.jar`, nunca archivos ni datos personales) y, una vez al día como mucho, a `api.github.com` para avisar de versiones nuevas; este aviso viene activado y se desactiva en *Ajustes*. Sin telemetría. Detalle en la sección [Privacidad del README](README.md#privacidad). Políticas de terceros: [CurseForge (Overwolf)](https://www.overwolf.com/legal/privacy/), [Modrinth](https://modrinth.com/legal/privacy), [GitHub](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement).

## English

**Status:** application to SignPath Foundation in progress. Until it is approved, release `.exe` files are **not signed**; verify them with the SHA-256 and the VirusTotal report in each release's notes.

Once approved: free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org).

### What is signed
- Only Mod Updater's own executables (`ModUpdater.exe` and the one in the folder build), built by GitHub Actions (`.github/workflows/release.yml`) from this repository's source when a `vX.Y.Z` tag is created.
- Never hand-built binaries or binaries from other projects. Third-party libraries are included as their authors publish them.

### Team and roles
| Role | Who |
|---|---|
| Author (may change the code without extra review) | [Oscar Gonzalez (@racsoga)](https://github.com/racsoga) |
| Reviewer (every change from outside the team goes through a reviewed pull request) | [Oscar Gonzalez (@racsoga)](https://github.com/racsoga) |
| Approver (manually approves every signing request) | [Oscar Gonzalez (@racsoga)](https://github.com/racsoga) |

The `main` branch is protected: every change goes through a pull request with passing tests. Multi-factor authentication on GitHub and SignPath is required for every team member.

### Privacy
This program only connects to CurseForge and Modrinth to do what the user asks (sending only each `.jar`'s fingerprint, never files or personal data) and, at most once a day, to `api.github.com` to announce new versions; this check is on by default and can be turned off in *Settings*. No telemetry. Details in the README's [Privacy section](README.en.md#privacy). Third-party policies: [CurseForge (Overwolf)](https://www.overwolf.com/legal/privacy/), [Modrinth](https://modrinth.com/legal/privacy), [GitHub](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement).
