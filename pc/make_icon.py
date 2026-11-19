"""Draws assets/icon.png and assets/icon.ico (run once)."""
from PIL import Image, ImageDraw

from gt.config import ASSETS


def draw(size):
    s = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8 * s, 8 * s, 248 * s, 248 * s], radius=56 * s, fill=(30, 42, 58, 255))
    # screen
    d.rounded_rectangle([40 * s, 52 * s, 216 * s, 172 * s], radius=18 * s, fill=(76, 141, 255, 255))
    d.rectangle([108 * s, 172 * s, 148 * s, 192 * s], fill=(76, 141, 255, 255))
    d.rounded_rectangle([84 * s, 188 * s, 172 * s, 204 * s], radius=8 * s, fill=(76, 141, 255, 255))
    # subtitle bars
    d.rounded_rectangle([62 * s, 118 * s, 194 * s, 134 * s], radius=8 * s, fill=(255, 255, 255, 255))
    d.rounded_rectangle([86 * s, 142 * s, 170 * s, 156 * s], radius=7 * s, fill=(227, 10, 23, 255))
    return img


if __name__ == "__main__":
    ASSETS.mkdir(exist_ok=True)
    big = draw(256)
    big.save(ASSETS / "icon.png")
    big.save(ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("ok")
