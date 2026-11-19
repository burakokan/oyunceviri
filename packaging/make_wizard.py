"""Draws the setup wizard's pictures (packaging/wizard/*.bmp) from assets/icon.png, in the app's colours.
Inno Setup picks the size that fits the screen scaling (100 / 150 / 200 %)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "wizard"
ICON = Image.open(ROOT / "assets" / "icon.png").convert("RGBA")
FONTS = Path("C:/Windows/Fonts")
TOP, BOTTOM = (22, 30, 44), (10, 13, 18)
ACCENT, TEXT, MUTED = (76, 141, 255), (232, 236, 241), (139, 151, 167)


def gradient(w, h):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        row = tuple(round(TOP[i] * (1 - t) + BOTTOM[i] * t) for i in range(3))
        for x in range(w):
            px[x, y] = row
    return img


def centered(draw, w, y, text, font, fill):
    x = (w - draw.textlength(text, font=font)) / 2
    draw.text((x, y), text, font=font, fill=fill)


def side(scale):
    """The tall picture on the welcome and finish pages (164 x 314 at 100 %)."""
    w, h = round(164 * scale), round(314 * scale)
    img = gradient(w, h)
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r = round(70 * scale)
    cx, cy = w // 2, round(118 * scale)
    for i in range(r, 0, -2):
        gd.ellipse((cx - i, cy - i, cx + i, cy + i), fill=ACCENT + (round(28 * (1 - i / r)),))
    img.paste(glow, (0, 0), glow)
    size = round(96 * scale)
    icon = ICON.resize((size, size), Image.LANCZOS)
    img.paste(icon, (cx - size // 2, cy - size // 2), icon)
    d = ImageDraw.Draw(img)
    centered(d, w, round(186 * scale), "Oyun Çeviri", ImageFont.truetype(str(FONTS / "seguisb.ttf"),
                                                                       round(19 * scale)), TEXT)
    small = ImageFont.truetype(str(FONTS / "segoeui.ttf"), round(10.5 * scale))
    centered(d, w, round(216 * scale), "PS5 altyazıları", small, MUTED)
    centered(d, w, round(232 * scale), "TV'de Türkçe", small, MUTED)
    bar_w, bar_h = round(64 * scale), max(2, round(4 * scale))
    d.rounded_rectangle((cx - bar_w // 2, round(262 * scale), cx + bar_w // 2, round(262 * scale) + bar_h),
                        radius=bar_h // 2, fill=ACCENT)
    return img


def small_icon(scale):
    """The small picture at the top right of the other pages (55 x 55 at 100 %)."""
    n = round(55 * scale)
    img = Image.new("RGB", (n, n), (255, 255, 255))
    icon = ICON.resize((n, n), Image.LANCZOS)
    img.paste(icon, (0, 0), icon)
    return img


def main():
    OUT.mkdir(exist_ok=True)
    for scale, tag in ((1, "100"), (1.5, "150"), (2, "200")):
        side(scale).save(OUT / f"side-{tag}.bmp")
        small_icon(scale).save(OUT / f"small-{tag}.bmp")
    print("ok", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
