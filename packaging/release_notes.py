"""Notas de la Release a partir de CHANGELOG.md.

Uso: python packaging/release_notes.py v0.2.0 [archivo.sha256 ...]
Imprime la sección "## [0.2.0]" del changelog más las instrucciones de descarga, los SHA-256
de cada archivo y el enlace a su informe de VirusTotal.
Falla si la versión no está en el changelog (para no publicar sin notas).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FOOTER = """
---

### Descarga

1. Descarga **ModUpdater.exe** (abajo, en *Assets*) y ábrelo. No hace falta instalar nada.
2. Si Windows muestra "Windows protegió tu PC", pulsa **Más información → Ejecutar de todas formas** (el ejecutable no está firmado con un certificado de pago).
3. Haz una copia de tu carpeta `mods` la primera vez.

Si tu antivirus bloquea el `.exe` (falso positivo habitual en programas hechos con PyInstaller), prueba **ModUpdater-…-carpeta.zip**: descomprímelo y abre `ModUpdater.exe` de dentro.

### Comprobación

{hashes}

Para comprobar tu descarga, en PowerShell: `Get-FileHash .\\ModUpdater.exe -Algorithm SHA256`. El resultado debe coincidir con el de arriba.

**Firma de código:** [Code signing policy](https://github.com/racsoga/mod_updater_Minecraft/blob/main/CODE_SIGNING_POLICY.md). Firma gratuita de [SignPath.io](https://about.signpath.io) con certificado de [SignPath Foundation](https://signpath.org) (solicitud en curso: hasta que la aprueben, el `.exe` no está firmado).

Proyecto no oficial: no está afiliado a Mojang Studios, Microsoft, CurseForge ni Modrinth.
"""

VIRUSTOTAL = "https://www.virustotal.com/gui/file/{sha}"


def hash_lines(sha_files: list[str]) -> str:
    """Una línea por archivo: nombre, SHA-256 y enlace a VirusTotal."""
    if not sha_files:
        return "SHA-256: (no disponible)"
    out = []
    for f in sha_files:
        sha, _, name = Path(f).read_text(encoding="ascii").strip().partition("  ")
        out.append(f"- `{name}` · SHA-256 `{sha}` · [informe de VirusTotal]({VIRUSTOTAL.format(sha=sha)})")
    return "\n".join(out)


def section(changelog: str, version: str) -> str | None:
    pattern = rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)"
    m = re.search(pattern, changelog, flags=re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else None


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    version = argv[1].lstrip("v")
    body = section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), version)
    if not body:
        print(f"CHANGELOG.md no tiene la sección [{version}]", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(body + "\n" + FOOTER.replace("{hashes}", hash_lines(argv[2:])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
