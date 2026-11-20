"""Notas de la Release a partir de CHANGELOG.md.

Uso: python packaging/release_notes.py v0.2.0 [ruta-al-sha256]
Imprime la sección "## [0.2.0]" del changelog más las instrucciones de descarga.
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

Comprobación SHA-256 de `ModUpdater.exe`:

```
{sha}
```

Proyecto no oficial: no está afiliado a Mojang Studios, Microsoft, CurseForge ni Modrinth.
"""


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
    sha = Path(argv[2]).read_text(encoding="ascii").strip() if len(argv) > 2 else "(no disponible)"
    sys.stdout.reconfigure(encoding="utf-8")
    print(body + "\n" + FOOTER.replace("{sha}", sha))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
