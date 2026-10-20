"""Génère l'icône de NetShift (assets/netshift.ico + PNG) — nécessite Pillow.

Carré arrondi en dégradé bleu → violet, deux flèches opposées (la « bascule » entre réseaux),
chacune partant d'un point de connexion.
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
S = 1024  # dessin en haute résolution puis réduction

TOP_LEFT = (59, 130, 246)      # #3B82F6
BOTTOM_RIGHT = (124, 58, 237)  # #7C3AED


def rounded_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return m


def gradient(size: int) -> Image.Image:
    g = Image.new("RGB", (size, size))
    px = g.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(TOP_LEFT, BOTTOM_RIGHT))
    return g


def symbol(size: int) -> Image.Image:
    """Les deux flèches en blanc sur fond transparent."""
    sym = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(sym)
    w = int(size * 0.072)          # épaisseur du trait
    r = w // 2
    dot = int(size * 0.062)        # rayon des points de connexion
    head = int(size * 0.115)       # taille des pointes

    def line(a, b):
        d.line([a, b], fill=255, width=w)
        for x, y in (a, b):
            d.ellipse((x - r, y - r, x + r, y + r), fill=255)

    def arrow(y, x_from, x_to):
        sign = 1 if x_to > x_from else -1
        d.ellipse((x_from - dot, y - dot, x_from + dot, y + dot), fill=255)
        line((x_from, y), (x_to, y))
        line((x_to, y), (x_to - sign * head, y - head))
        line((x_to, y), (x_to - sign * head, y + head))

    arrow(int(size * 0.385), int(size * 0.27), int(size * 0.74))
    arrow(int(size * 0.615), int(size * 0.73), int(size * 0.26))
    return sym


def build() -> Image.Image:
    radius = int(S * 0.23)
    base = gradient(S).convert("RGBA")

    # léger reflet en haut
    shine = Image.new("L", (S, S), 0)
    sd = ImageDraw.Draw(shine)
    for y in range(S // 2):
        sd.line([(0, y), (S, y)], fill=int(38 * (1 - y / (S / 2))))
    base = Image.composite(Image.new("RGBA", (S, S), (255, 255, 255, 255)), base, shine)

    sym = symbol(S)
    # ombre douce sous le symbole
    shadow = sym.filter(ImageFilter.GaussianBlur(S * 0.02)).point(lambda v: v * 0.35)
    shadow = ImageChops.offset(shadow, 0, int(S * 0.014))
    base = Image.composite(Image.new("RGBA", (S, S), (20, 20, 60, 255)), base, shadow)
    base = Image.composite(Image.new("RGBA", (S, S), (255, 255, 255, 255)), base, sym)

    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(base, (0, 0), rounded_mask(S, radius))
    return out


def main():
    icon = build()
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    icon.resize((256, 256), Image.LANCZOS).save(assets / "netshift.png")
    icon.resize((512, 512), Image.LANCZOS).save(assets / "netshift-512.png")
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    icon.resize((256, 256), Image.LANCZOS).save(assets / "netshift.ico", sizes=[(s, s) for s in sizes])
    # logos de la barre latérale (choisis selon la mise à l'échelle de l'écran)
    for s in (38, 48, 57, 76):
        icon.resize((s, s), Image.LANCZOS).save(assets / f"logo-{s}.png")
    print("Icône générée dans", assets)


if __name__ == "__main__":
    main()
