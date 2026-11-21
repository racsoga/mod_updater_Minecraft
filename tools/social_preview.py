"""Genera docs/images/social-preview.png (1280x640), la imagen que GitHub muestra al compartir
el enlace del repositorio. Uso: python tools/social_preview.py  (necesita Pillow)."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images" / "social-preview.png"
LOGO = ROOT / "assets" / "logo-256.png"

BG, TEXT, MUTED, ACCENT = "#111214", "#f2f2f2", "#a7a9ad", "#7ccf5a"
W, H = 1280, 640


def font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    logo = Image.open(LOGO).convert("RGBA").resize((288, 288), Image.NEAREST)  # pixel art: sin suavizar
    img.paste(logo, (120, (H - 288) // 2), logo)

    x = 470
    bold = font(["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"], 84)
    regular = font(["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"], 34)
    draw.text((x, 196), "Mod Updater", font=bold, fill=TEXT)
    draw.text((x, 312), "Actualiza tus mods de Minecraft", font=regular, fill=TEXT)
    draw.text((x, 358), "CurseForge y Modrinth · dependencias · deshacer", font=regular, fill=MUTED)
    draw.rectangle((x, 430, x + 96, 436), fill=ACCENT)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    print(OUT)


if __name__ == "__main__":
    main()
