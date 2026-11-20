"""Genera el logo de Mod Updater en pixel art (16×16) a partir de mapas de caracteres.

Uso:
    python tools/logo.py preview          -> design/logo/variante-*.png + preview.html
    python tools/logo.py build <variante> -> SVG, PNG e .ico multi-tamaño del logo elegido

Cada carácter del mapa es un píxel; '.' es transparente. Se escala con vecino más
cercano para que los píxeles se vean nítidos a cualquier tamaño.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "design" / "logo"

PALETTE = {
    "o": "#14100c",  # contorno
    "G": "#5ea83a",  # hierba
    "L": "#7ccf5a",  # hierba clara (el verde de acento de la app)
    "g": "#3c7a24",  # hierba oscura
    "D": "#8a5a2c",  # tierra
    "d": "#66421f",  # tierra oscura
    "W": "#f5f5f7",  # flecha
    "w": "#c7c7cc",  # flecha en sombra
    "S": "#c4c6cc",  # hierro claro
    "M": "#8e9097",  # hierro
    "m": "#5d5f66",  # hierro oscuro
    "T": "#1a1b1e",  # fondo de la loseta
    "t": "#2a2b2f",  # borde de la loseta
}

# Flecha de actualizar (↻) de 9×8: sale por abajo a la derecha, rodea por la
# izquierda y termina arriba a la derecha con la punta hacia abajo.
ARROW = """
..XXXX....
.X....X...
X......X..
X....XXXXX
X.....XXX.
X......X..
.X........
..XXXX....
"""

# A · Bloque de hierba con la flecha grabada en la tierra.
BLOCK = """
................
.oooooooooooooo.
.oLGGLGGGLGGLGo.
.oGGLGGgGGLGGGo.
.oGgGGGLGGGgGLo.
.ogGGgGGGgGGGgo.
.oDgDDgDDDgDDgo.
.oDDdDDDDDdDDDo.
.oDdDDDDDDDDdDo.
.oDDDDdDDDDDDDo.
.oDDDDDDDDDDdDo.
.odDDDDdDDDDDDo.
.oDDDDDDDDDDDdo.
.oDdDDDDDDDDDDo.
.oooooooooooooo.
................
"""

# B · El bloque sobre una loseta oscura redondeada (icono de app al estilo Apple).
TILE = """
..tttttttttttt..
.tTTTTTTTTTTTTt.
tTToooooooooooTt
tToLGGLGGGLGGoTt
tToGgGGLGGgGLoTt
tTogGDgDDgDDgoTt
tToDDDDDDDdDDoTt
tToDDDDDDDDDdoTt
tToDDDdDDDDDDoTt
tToDDDDDDDDDDoTt
tTodDDDDDDDDDoTt
tToDDDDDDDDDdoTt
tToooooooooooTTt
tTTTTTTTTTTTTTTt
.tTTTTTTTTTTTTt.
..tttttttttttt..
"""

# C · Yunque de hierro con la flecha verde encima.
ANVIL = """
................
................
................
................
................
................
................
................
.ooooooooooooo..
oSSSSSSSSSSSSSo.
.ooMMMMMMMMMoo..
...ooMMMMMoo....
....oMMMMMo.....
...oMMMmMMMo....
..ommmmmmmmmo...
..ooooooooooo...
"""

# (mapa, color de la flecha, fila, columna)
VARIANTS = {
    "a-bloque": (BLOCK, "W", 6, 3),
    "b-loseta": (TILE, "W", 5, 3),
    "c-yunque": (ANVIL, "L", 0, 3),
}
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def parse(art: str) -> list[str]:
    rows = [r for r in art.strip("\n").splitlines()]
    assert len(rows) == 16 and all(len(r) == 16 for r in rows), "el mapa debe ser 16×16"
    return rows


def compose(variant: tuple) -> list[str]:
    """Base 16×16 con la flecha superpuesta en (fila, columna) y del color indicado."""
    art, color, top, left = variant
    rows = [list(r) for r in parse(art)]
    for dy, line in enumerate(ARROW.strip("\n").splitlines()):
        for dx, ch in enumerate(line):
            if ch == "X":
                rows[top + dy][left + dx] = color
    return ["".join(r) for r in rows]


def to_image(rows: list[str], size: int = 16) -> Image.Image:
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != ".":
                h = PALETTE[ch].lstrip("#")
                img.putpixel((x, y), (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255))
    return img.resize((size, size), Image.NEAREST) if size != 16 else img


def to_svg(rows: list[str]) -> str:
    rects = []
    for y, row in enumerate(rows):
        x = 0
        while x < 16:
            ch = row[x]
            if ch == ".":
                x += 1
                continue
            run = 1
            while x + run < 16 and row[x + run] == ch:
                run += 1
            rects.append(f'<rect x="{x}" y="{y}" width="{run}" height="1" fill="{PALETTE[ch]}"/>')
            x += run
    body = "".join(rects)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" shape-rendering="crispEdges">{body}</svg>\n'


def preview() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, variant in VARIANTS.items():
        rows = compose(variant)
        (OUT / f"variante-{name}.svg").write_text(to_svg(rows), encoding="utf-8")
        to_image(rows, 256).save(OUT / f"variante-{name}.png")
    print("ok:", ", ".join(VARIANTS))


def build(name: str) -> None:
    rows = compose(VARIANTS[name])
    web = ROOT / "mod_updater" / "gui" / "web"
    (web / "logo.svg").write_text(to_svg(rows), encoding="utf-8")
    to_image(rows, 256).save(web / "logo-256.png")
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    big = to_image(rows, 256)
    big.save(assets / "ModUpdater.ico", sizes=[(s, s) for s in ICO_SIZES])
    big.save(assets / "logo-256.png")
    print("ok:", name)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "preview":
        preview()
    elif len(sys.argv) == 3 and sys.argv[1] == "build":
        build(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(2)
