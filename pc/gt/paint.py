"""Turkish painted the game's way: on the PC, into a picture that looks like the game's own text (the colour of the
bubble or card behind it, its letters' colour, about its size), sent to the TV as a picture that covers the English.

The colours are measured on the Remote Play picture, so the patch blends with what the TV shows. A patch stays inside
the plain background around the English text (a message bubble, a map card): it is found by walking out from the text
until the colour changes (the bubble's edge, an icon, a picture). A longer Turkish text gets smaller letters first
(down to MIN_SHARE of the English size), then the patch grows down over the gap below it.
"""
import base64
import os
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SUPER = 2               # drawn this many times larger, then shrunk: smooth letters
MIN_SHARE = 0.78        # the smallest Turkish letters, as a share of the English letters' size
LINE_EM = 1.5           # a game's line of text is this many font sizes high (GTA 6's phone: like Segoe UI at 1/1.5)
_FONT_FILES = {"regular": ("segoeui.ttf", "arial.ttf", "tahoma.ttf"),
               "semibold": ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf")}
_WEIGHTS = {"regular": 480, "semibold": 640}     # Segoe UI Variable (Windows 11): a little heavier than Regular
_FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


CAP_EM = 0.7            # Bahnschrift: a capital letter is this many font sizes high


@lru_cache(maxsize=64)
def font(px, weight="regular"):
    """regular / semibold: Segoe UI (Variable on Windows 11); condensed: Bahnschrift Bold Condensed, like GTA's
    capitals ("STYLE", "SET DESTINATION")."""
    size = max(6, int(round(px)))
    if weight == "condensed":
        for name, axes in (("bahnschrift.ttf", [700, 75]), ("arialbd.ttf", None)):
            path = os.path.join(_FONT_DIR, name)
            if os.path.exists(path):
                fnt = ImageFont.truetype(path, size)
                if axes:
                    try:
                        fnt.set_variation_by_axes(axes)
                    except (OSError, ValueError):
                        pass
                return fnt
    var = os.path.join(_FONT_DIR, "SegUIVar.ttf")
    if os.path.exists(var):
        try:
            fnt = ImageFont.truetype(var, size)
            fnt.set_variation_by_axes([_WEIGHTS.get(weight, 480), 10])
            return fnt
        except (OSError, ValueError):
            pass
    for name in _FONT_FILES.get(weight, _FONT_FILES["regular"]):
        path = os.path.join(_FONT_DIR, name)
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def hex_colour(bgr):
    b, g, r = (int(max(0, min(255, round(float(v))))) for v in bgr)
    return f"#{r:02X}{g:02X}{b:02X}"


def ring(img, rect, pad):
    """The pixels in a band `pad` px wide just outside rect (x0, y0, x1, y1), inside the picture."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in rect)
    a0, b0, a1, b1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
    if a1 <= a0 or b1 <= b0:
        return np.zeros((0, 3), np.uint8)
    mask = np.ones((b1 - b0, a1 - a0), bool)
    mask[max(0, y0 - b0):max(0, y1 - b0), max(0, x0 - a0):max(0, x1 - a0)] = False
    return img[b0:b1, a0:a1][mask]


def background(img, rect, pad=4):
    """The plain colour around a text (BGR floats): the median of the band around it, the letters' outliers left out."""
    px = ring(img, rect, pad).astype(np.float32)
    if len(px) < 8:
        x0, y0, x1, y1 = (int(round(v)) for v in rect)
        px = img[max(0, y0):y1, max(0, x0):x1].reshape(-1, 3).astype(np.float32)
    if len(px) == 0:
        return np.array([255.0, 255.0, 255.0])
    lum = px.mean(axis=1)
    mid = np.median(lum)
    keep = px[np.abs(lum - mid) <= 25]
    return np.median(keep if len(keep) else px, axis=0)


def ink(img, rect, bg):
    """The letters' colour (BGR floats): the pixels in the text furthest from the background's brightness."""
    x0, y0, x1, y1 = (int(round(v)) for v in rect)
    px = img[max(0, y0):max(0, y1), max(0, x0):max(0, x1)].reshape(-1, 3).astype(np.float32)
    if len(px) < 10:
        return np.array([30.0, 30.0, 30.0]) if bg.mean() > 128 else np.array([250.0, 250.0, 250.0])
    lum = px.mean(axis=1)
    # the letters are the few pixels far from the background: darker or lighter, whichever reaches further (a dim
    # screen in a dark room has darker letters on a background darker than mid grey)
    lo, hi = np.percentile(lum, (5, 95))
    dark = float(bg.mean()) - lo >= hi - float(bg.mean())
    cut = np.percentile(lum, 8 if dark else 92)
    pick = px[lum <= cut] if dark else px[lum >= cut]
    return np.median(pick, axis=0)


def tight(img, rect, bg):
    """The letters' own box inside a text's box (a reader's boxes reach a little past the letters)."""
    x0, y0, x1, y1 = rect
    diff = np.abs(img[y0:y1, x0:x1].astype(np.float32).mean(axis=2) - float(bg.mean()))
    ys, xs = np.nonzero(diff > 45)
    if len(xs) < 10:
        return rect
    return x0 + int(xs.min()), y0 + int(ys.min()), x0 + int(xs.max()) + 1, y0 + int(ys.max()) + 1


def room(img, rect, bg, limit=None, tol=16.0, stop=2, lab=None):
    """How far the plain background around a text reaches (x0, y0, x1, y1): walked out from the text's middle in each
    direction until the colour differs from bg by more than tol (LAB) for `stop` px in a row, or `limit` is reached.
    lab: the picture in LAB (float32), when the caller has it already."""
    h, w = img.shape[:2]
    lx0, ly0, lx1, ly1 = limit if limit is not None else (0, 0, w, h)
    x0, y0, x1, y1 = (int(round(v)) for v in rect)
    if lab is None:
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    ref = cv2.cvtColor(np.uint8([[np.clip(bg, 0, 255)]]), cv2.COLOR_BGR2LAB)[0, 0].astype(np.float32)
    # a strip through the middle half of the text, so a rounded corner or a letter's tail does not stop the walk
    ym0, ym1 = y0 + (y1 - y0) // 4, max(y0 + (y1 - y0) // 4 + 1, y1 - (y1 - y0) // 4)
    xm0, xm1 = x0 + (x1 - x0) // 4, max(x0 + (x1 - x0) // 4 + 1, x1 - (x1 - x0) // 4)

    def far(strip):
        # an edge, an icon or a row of letters: enough of the strip is not the background (letters are thin, a
        # median would walk through them)
        d = np.linalg.norm(strip.reshape(-1, 3) - ref, axis=1)
        return float(np.mean(d > tol)) > 0.12

    def walk(start, end, step, strip_of):
        last, run = start, 0
        for p in range(start, end, step):
            if far(strip_of(p)):
                run += 1
                if run >= stop:
                    return last
            else:
                run, last = 0, p
        return last

    right = walk(x1, min(w, lx1), 1, lambda x: lab[ym0:ym1, x])
    left = walk(x0 - 1, max(-1, lx0 - 1), -1, lambda x: lab[ym0:ym1, x])
    down = walk(y1, min(h, ly1), 1, lambda y: lab[y, xm0:xm1])
    up = walk(y0 - 1, max(-1, ly0 - 1), -1, lambda y: lab[y, xm0:xm1])
    return min(left, x0), min(up, y0), max(right + 1, x1), max(down + 1, y1)


def erase(img, rect, bg, feather=3):
    """The text in rect taken out of the picture: its letters filled in from around them (the card's colour and
    whatever shows through it stay) -> BGRA of rect, opaque, its border fading out over `feather` px."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in rect)
    m = feather + 6
    a0, b0, a1, b1 = max(0, x0 - m), max(0, y0 - m), min(w, x1 + m), min(h, y1 + m)
    crop = img[b0:b1, a0:a1]
    letters = (np.abs(crop.astype(np.float32).mean(axis=2) - float(bg.mean())) > 35).astype(np.uint8)
    letters[:max(0, y0 - b0), :] = 0
    letters[y1 - b0:, :] = 0
    letters[:, :max(0, x0 - a0)] = 0
    letters[:, x1 - a0:] = 0
    letters = cv2.dilate(letters, np.ones((5, 5), np.uint8))
    clean = cv2.inpaint(crop, letters * 255, 5, cv2.INPAINT_TELEA)
    out = np.zeros((y1 - y0, x1 - x0, 4), np.uint8)
    out[..., :3] = clean[y0 - b0:y1 - b0, x0 - a0:x1 - a0]
    alpha = np.ones((y1 - y0, x1 - x0), np.float32)
    for i in range(min(feather, (y1 - y0) // 2, (x1 - x0) // 2)):
        f = (i + 1) / (feather + 1)
        alpha[i, :] = np.minimum(alpha[i, :], f)
        alpha[-1 - i, :] = np.minimum(alpha[-1 - i, :], f)
        alpha[:, i] = np.minimum(alpha[:, i], f)
        alpha[:, -1 - i] = np.minimum(alpha[:, -1 - i], f)
    out[..., 3] = (alpha * 255).astype(np.uint8)
    return out


def wrap(text, fnt, width):
    """Greedy word wrap to `width` px -> lines (a word longer than a line is cut)."""
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}" if cur else word
        if fnt.getlength(trial) <= width:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        cur = ""
        # on a new line; a word longer than a line (a link, "@thiccmeditator") is cut where it reaches the edge
        for ch in word:
            if cur and fnt.getlength(cur + ch) > width:
                lines.append(cur)
                cur = ""
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def layout(text, width, height, pitch, weight="regular", min_share=MIN_SHARE):
    """The Turkish in a box `width` x `height` px with lines `pitch` px apart (the English text's) -> (font, lines,
    line pitch, fits). The English size first, smaller down to min_share of it; at the smallest size it may not fit."""
    share = 1.0
    while True:
        p = pitch * share
        fnt = font(p / LINE_EM, weight)
        lines = wrap(text, fnt, width)
        fits = len(lines) * p <= height + 0.35 * p
        if fits or share * 0.94 < min_share:
            return fnt, lines, p, fits
        share *= 0.94


def draw_text(draw, x, y, lines, fnt, pitch, fill, align="left", width=0):
    """Lines of text from (x, y) (the top of the first line), `pitch` px apart, each line's letters centred in it."""
    asc, desc = fnt.getmetrics()
    for i, line in enumerate(lines):
        top = y + i * pitch + (pitch - (asc + desc)) / 2
        lx = x + (width - fnt.getlength(line)) / 2 if align == "center" else x
        draw.text((lx, top), line, font=fnt, fill=fill)


def canvas(w, h):
    """A transparent picture SUPER times the size, and its drawing pen."""
    img = Image.new("RGBA", (int(w * SUPER), int(h * SUPER)), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def shrink(img):
    """The SUPER-sized picture -> BGRA uint8 at the real size (premultiplied while shrinking: no dark fringes)."""
    rgba = np.asarray(img, dtype=np.float32)
    a = rgba[..., 3:4] / 255.0
    pm = np.concatenate([rgba[..., :3] * a, a * 255.0], axis=2)
    w, h = img.size[0] // SUPER, img.size[1] // SUPER
    small = cv2.resize(pm, (w, h), interpolation=cv2.INTER_AREA)
    return _unpremultiply(small, rgb_order=True)


def _unpremultiply(pm, rgb_order=False):
    a = pm[..., 3:4]
    rgb = np.where(a > 0.5, pm[..., :3] * 255.0 / np.maximum(a, 1e-3), 0)
    if rgb_order:
        rgb = rgb[..., ::-1]            # RGB -> BGR
    return np.concatenate([np.clip(rgb, 0, 255), np.clip(a, 0, 255)], axis=2).astype(np.uint8)


def warp(bgra, corners, frame_w, frame_h):
    """A picture of the upright phone screen, bent onto the screen's corners in the frame (tl, tr, br, bl) -> (x, y,
    BGRA cut to its painted part) in frame pixels, or None when nothing is painted."""
    sh, sw = bgra.shape[:2]
    c = np.float32(corners)
    x0, y0 = max(0, int(np.floor(c[:, 0].min()))), max(0, int(np.floor(c[:, 1].min())))
    x1, y1 = min(frame_w, int(np.ceil(c[:, 0].max()))), min(frame_h, int(np.ceil(c[:, 1].max())))
    if x1 <= x0 or y1 <= y0:
        return None
    m = cv2.getPerspectiveTransform(np.float32([[0, 0], [sw, 0], [sw, sh], [0, sh]]), c - np.float32([x0, y0]))
    a = bgra[..., 3:4].astype(np.float32)
    pm = np.concatenate([bgra[..., :3].astype(np.float32) * a / 255.0, a], axis=2)
    out = cv2.warpPerspective(pm, m, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR, borderValue=0)
    return cut(x0, y0, _unpremultiply(out))


def cut(x, y, bgra):
    """A picture cut to its painted part -> (x, y, picture) or None when it is all transparent."""
    ys, xs = np.nonzero(bgra[..., 3] > 0)
    if len(xs) == 0:
        return None
    a0, a1, b0, b1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    return x + int(a0), y + int(b0), bgra[b0:b1, a0:a1]


def tv_box(box_id, x, y, bgra, frame_w, frame_h):
    """A TV "regions" box that is a picture (older TV apps draw nothing for it: no text, no background)."""
    ok, png = cv2.imencode(".png", bgra, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    h, w = bgra.shape[:2]
    return {"id": box_id, "x": x / frame_w, "y": y / frame_h, "w": w / frame_w, "h": h / frame_h,
            "mw": w / frame_w, "mh": h / frame_h, "lines": 1, "tr": "", "icons": {}, "fg": "#FFFFFF",
            "bg": "#000000", "alpha": 0.0, "scale": 1.0, "shadow": False, "align": "left",
            "img": base64.b64encode(png.tobytes()).decode("ascii") if ok else ""}
