"""Extra screen areas translated as a whole and shown in ONE box on the TV, button icons included.

- "hint":  the tutorial / objective box ("Press (L3) to swim faster, and press again…"): all its rows are one
           paragraph, translated together.
- "phone": the in-game phone's messages: every message (paragraph) is translated on its own, one under the other.
- "objective": the short mission objective under the subtitles ("Go to the bank."), translated as one line.

Every area has its own reading filter (cfg regions.<kind>.filter: only white text in a dark box - the hint box -, only
outlined white text like subtitles, only bright text, or everything), so a sign or a poster that drifts into the area
is not translated, and its own look on the TV (place, size, colours, box).

The user picks each area on the "Altyazı Alanı" page (fractions of the PS5 picture, built-in Remote Play only).
A few times a second the area is compared with how it looked; when it changed, its text is searched (RapidOCR
detection + the small recognizer, ~0.1 s for a box) and read row by row. A new text must read the same twice before
it is translated, so a box that is still fading in is not translated half.

Button icons (GTA: a white disc / rounded square with a dark "L3", "R2", ✕ …) are found in every text row: a
solid, convex shape clearly taller than the letters (see find_icons). The icon's picture is cut out (transparent
around it) and its place in the sentence becomes a tag for DeepL (<x id="1">L3</x>), which moves it to the right
word of the Turkish sentence ("L3'e bas" -> "⟦1⟧ tuşuna bas"). The TV draws the same picture there.
"""
import base64
import json
import queue
import re
import statistics
import threading
import time
from collections import deque

import cv2
import numpy as np
from rapidfuzz import fuzz

from . import phone
from .config import ROOT
from .screen import group
from .tracker import normalize

KINDS = {
    "hint": {"label": "Görev / ipucu kutusu",
             "context": "Tutorial, hint or objective text in a video game: how to play, what to do next. Natural, "
                        "short Turkish instructions to one player (\"sen\" form: \"bas\", \"tut\"). Keep button and "
                        "place names.",
             "paragraph": True},
    "phone": {"label": "Telefon mesajları",
              "context": "Text messages on a character's phone in a video game, written informally between friends. "
                         "Natural spoken Turkish (\"sen\"), slang and swearing as strong as the English. Keep names.",
              "paragraph": False},
    "objective": {"label": "Görev hedefi",
                  "context": "A short mission objective shown under the subtitles of a video game (\"Go to the bank.\", "
                             "\"Follow Jason.\"). A short Turkish imperative to one player (\"sen\" form: "
                             "\"Bankaya git.\"). Keep the names of people and places.",
                  "paragraph": True},
}
# Which text an area reads (the rest - signs, posters, the scene - is left out):
FILTERS = {
    "dark_box": "Koyu kutudaki beyaz yazı",        # the hint box: white letters on a dark, plain background
    "outlined": "Kenarlıklı beyaz yazı",           # like subtitles: white letters with a dark outline / shadow
    "bright": "Parlak (beyaz) yazı",
    # the phone: dark text on a light message bubble AND white text on a black call / notification card; text on
    # a busy or colourful background (the street, a sign) is left out
    "plain": "Düz zemindeki yazı (açık ya da koyu)",
    "any": "Alandaki her yazı",
}
PLACES = ("cover", "below", "above", "top", "bottom")
WATCH_EVERY = 0.7           # s between readings of an area that is only being looked at on the area page
CHECK_EVERY = 0.15          # s between looks at the areas
MIN_READ_GAP = 0.35         # s between two readings of the same area
REREAD_SECONDS = 2.5        # read again at least this often while a translation is shown
EMPTY_READS_TO_HIDE = 2
MIN_SCORE = 0.6
SMALL_ROW = 28              # px: rows lower than this are enlarged x2 before reading
CACHE_FILE = ROOT / "region_cache.json"
TOKEN = re.compile(r"⟦(\d+)(?:\|([^⟧]*))?⟧")   # an icon: ⟦1|L3⟧ in English, ⟦1⟧ in Turkish
_LETTER = re.compile(r"[A-Za-z]")
# The look of an area on the TV when nothing is set (config.DEFAULTS has the same per area).
LOOK = {"place": "cover", "offset": 8, "align": "left", "size": 100, "fg": "#FFFFFF", "bg": "#10151C",
        "opacity": 92}
# GTA 6's phone, found by itself (gt/phone.py): looked for this often; closed when not seen for PHONE_CLOSE s (a
# blurred picture while scrolling, the hand shaking); read when its screen has not changed for PHONE_SETTLE s (right
# after a scroll the stream's picture is still soft: misread letters).
PHONE_EVERY = 0.3
PHONE_CLOSE = 1.8
PHONE_SETTLE = 0.6
PHONE_SAME = 88         # % alike: a new reading of what is shown (letters read a little differently) changes nothing
# bubbles: every message beside its own place on the phone, in the phone's colours (off: one panel of text)
PHONE_LOOK = {"enabled": True, "size": 100, "fg": "#FFFFFF", "bg": "#10151C", "opacity": 61, "bubbles": True}
_GTA6 = re.compile(r"grand theft auto vi\b|\bgta\s*(6|vi)\b", re.I)


_MENU_SMALL = {"of", "and", "&", "the", "a", "an", "to", "in", "on", "for", "with", "or", "by"}


def menu_like(english):
    """Menu items / tab names, not a hint: every word starts with a capital ("Game Store Help Photo Studio",
    "Hair Color Facial Hair Style", "Load Game New Game") and there is no sentence punctuation. The game's pause
    menu sits where the hint box appears and looks the same (white text on a dark background)."""
    text = TOKEN.sub(" ", english)
    words = [w for w in re.findall(r"[^\W\d_][\w'’]*", text) if len(w) > 1]   # stray letters ("w Map …")
    letters = [c for c in text if c.isupper() or c.islower()]      # cased letters ("白" is neither)
    if letters and all(c.isupper() for c in letters) and len(words) <= 12:
        # all capitals: button bars and interaction menus, with or without punctuation ("CASH? / SHUT UP /
        # PARROT", "MIN/MAX R1 / AMOUNT / WITHDRAW ($2,480) / BACK"); hints and messages are mixed case
        return True
    if re.search(r"[.!?,:;]", text):
        return False
    return all(w[0].isupper() or w.lower() in _MENU_SMALL for w in words)


def skip_reason(a, english):
    """Why the area's reading is not translated ("" = it is): a menu, or one of the user's exceptions."""
    plain = " ".join(TOKEN.sub(" ", english).split()).casefold()
    for phrase in a.get("ignore") or []:
        if phrase.strip() and phrase.strip().casefold() in plain:
            return f"istisna: {phrase.strip()}"
    if a.get("skip_menus") and menu_like(english):
        return "menü"
    return ""


def keep_reading(a, english, paragraph):
    """-> (what is translated, why the rest was left out). A paragraph area (hint box) is kept or left out as a whole.
    In the phone area a reading of only menu text goes as a whole; next to a message, only a button bar in capitals
    ("RESTORE DEFAULT BACK") and the user's exceptions go - the sender's name ("Jason W") stays with the message."""
    if not english:
        return "", ""
    why = skip_reason(a, english.replace("\n", " "))
    if paragraph or why:
        return ("", why) if why else (english, "")
    kept = []
    for block in english.split("\n"):
        reason = skip_reason(a, block)
        letters = [c for c in TOKEN.sub(" ", block) if c.isalpha()]
        if reason and (reason != "menü" or (letters and all(c.isupper() for c in letters))):
            why = why or reason
        else:
            kept.append(block)
    return "\n".join(kept), why


def area_cfg(cfg, kind):
    """The settings of an area with every key present (older config files lack the newer ones)."""
    from .config import DEFAULTS
    base = dict(LOOK, enabled=False, roi=None, filter="any", text_min=170, bg_max=80, skip_menus=False, ignore=[],
                keep_lines=True)
    base.update(DEFAULTS.get("regions", {}).get(kind, {}))
    base.update(cfg.get("regions", {}).get(kind, {}))
    return base


# ---------------------------------------------------------------- which text is read

def row_look(crop, rect, text_min=170):
    """How a piece of text looks -> dict: "bright" (light letters at all; dark text on a light message bubble has
    none), the letters' brightness and colourfulness (0-255), the background's brightness and how plain it is, and
    how much of the letters has a dark outline next to it (GTA's subtitles and objectives: ~0.9; a sign: ~0)."""
    x0, y0, x1, y1 = rect
    rh = max(1, y1 - y0)
    pad = max(2, int(0.25 * rh))
    region = crop[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
    if region.size == 0:
        return None
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    v, s = hsv[..., 2], hsv[..., 1]
    light = (((v >= max(120, text_min - 30)) & (s <= 90)) * 255).astype(np.uint8)
    # Letter-sized pieces only: a sunlit wall or the sky behind the text is not "the letters".
    n, labels, stats, _ = cv2.connectedComponentsWithStats(light, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = ((stats[1:, cv2.CC_STAT_HEIGHT] <= 1.6 * rh) & (stats[1:, cv2.CC_STAT_WIDTH] <= 3 * rh)
                & (stats[1:, cv2.CC_STAT_AREA] >= 4))
    letters = keep[labels]
    count = int(letters.sum())
    if count < 20:
        return {"bright": False}
    around = cv2.dilate(letters.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    bg = ~around
    # The outline is judged on the letters' edge pixels (thick bold letters have a bright middle far from it).
    edge = letters & ~(cv2.erode(letters.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)
    near_dark = cv2.erode(v, np.ones((5, 5), np.uint8)) < 70
    return {"bright": True, "text_v": float(np.median(v[letters])), "text_s": float(np.median(s[letters])),
            "bg_v": float(np.median(v[bg])) if bg.any() else 0.0,
            "bg_hi": float(np.percentile(v[bg], 85)) if bg.any() else 0.0,
            "outline": float((edge & near_dark).sum() / max(1, int(edge.sum())))}


def plain_look(crop, rect):
    """A piece of text on a plain card, whichever is lighter (dark text on a white message bubble, white text on a
    black call card) -> {"plain": True, "contrast", "bg_spread", "bg_s"}: the letters / background difference, how much
    the background's brightness varies, how colourful it is."""
    x0, y0, x1, y1 = rect
    pad = max(2, int(0.25 * max(1, y1 - y0)))
    region = crop[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
    if region.size == 0:
        return None
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    high = bw > 0
    text = high if high.mean() < 0.5 else ~high       # the smaller part is the text
    # the background without the letters' soft edges
    bg = cv2.erode((~text).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    if text.sum() < 15 or bg.sum() < 15:
        return None
    s = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)[..., 1]
    return {"plain": True, "contrast": float(abs(np.median(gray[text]) - np.median(gray[bg]))),
            "bg_spread": float(np.percentile(gray[bg], 90) - np.percentile(gray[bg], 10)),
            "bg_s": float(np.median(s[bg]))}


def accepts(look, a):
    """-> (row is read, why not) for an area's filter settings `a`."""
    kind = a.get("filter", "any")
    if kind == "any":
        return True, ""
    if kind == "plain":
        if look is None:
            return False, "yazı ayrılamadı"
        if look["contrast"] < 60:
            return False, "yazı zemine karışıyor"
        if look["bg_spread"] > 70:
            return False, "zemin düz değil"
        if look["bg_s"] > 70:
            return False, "zemin renkli"      # a green road sign, a coloured poster
        return True, ""
    if look is None or not look["bright"]:
        return False, "açık renk yazı yok"
    if look["text_v"] < a.get("text_min", 170):
        return False, "yazı soluk"
    if kind == "dark_box":
        dark = a.get("bg_max", 80)
        if look["bg_v"] > dark:
            return False, "zemin açık"
        if look["bg_hi"] > dark + 60:
            return False, "zemin düz değil"     # a dark sign in a bright, busy scene
        if look["text_s"] > 70:
            return False, "yazı renkli"
    elif kind == "outlined":
        if look["outline"] < 0.6:
            return False, "kenarlık yok"
    elif kind == "bright" and look["text_s"] > 70:
        return False, "yazı renkli"
    return True, ""


# ---------------------------------------------------------------- icons

def bright_text(bgr):
    """Is the text brighter than its background? (the smaller Otsu class is the text)"""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return bw.mean() / 255 < 0.5


def find_icons(row_bgr):
    """Button icons in a bright-text row -> [(x0, y0, x1, y1, filled mask)] in its pixels, left to right.

    An icon (GTA: a white disc / rounded square with a dark "L3") is a bright shape clearly taller than the letters
    (~1.4x the capitals), about as wide as high, solid once its label is filled in, and with a convex outline. A "b"
    or "d" is as tall as the capitals and not convex; letters melted together in a blurry picture are not solid.
    Rows of dark text on a light background (a message bubble) are not searched (see bright_text)."""
    gray = cv2.cvtColor(row_bgr, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
    rh = bw.shape[0]
    # The letters' height: pieces of the rows above / below cut by the edges do not count.
    heights = [stats[i, 3] for i in range(1, n)
               if stats[i, 4] >= 12 and stats[i, 1] > 0 and stats[i, 1] + stats[i, 3] < rh]
    if len(heights) < 2:
        return []
    cap = float(np.percentile(heights, 90))     # capitals / ascenders
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if h < 1.22 * cap or h < 12 or not 0.7 <= w / h <= 2.4:
            continue
        comp = (lab[y:y + h, x:x + w] == i).astype(np.uint8)
        contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        filled = np.zeros_like(comp)
        cv2.drawContours(filled, contours, -1, 1, -1)
        hull = cv2.contourArea(cv2.convexHull(np.vstack(contours)))
        if filled.sum() / (w * h) >= 0.7 and hull > 0 and filled.sum() / hull >= 0.9:
            out.append((x, y, x + w, y + h, filled))
    return sorted(out, key=lambda c: c[0])


def icon_png(row_bgr, icon):
    """The icon's picture, transparent around the shape -> base64 PNG."""
    x0, y0, x1, y1, filled = icon
    pic = row_bgr[y0:y1, x0:x1]
    alpha = cv2.dilate(filled * 255, np.ones((3, 3), np.uint8))
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
    bgra = np.dstack([pic, alpha])
    pad = 1
    bgra = cv2.copyMakeBorder(bgra, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(0, 0, 0, 0))
    ok, data = cv2.imencode(".png", bgra)
    return base64.b64encode(data.tobytes()).decode("ascii") if ok else ""


# ---------------------------------------------------------------- reading

class AreaReader:
    """Detection + recognition of the text in an area, row by row, icons as tokens."""

    def __init__(self):
        from rapidocr import ModelType, RapidOCR
        base = {"Global.log_level": "error", "EngineConfig.onnxruntime.intra_op_num_threads": 2}
        self.det = RapidOCR(params={**base, "Det.limit_side_len": 1280, "Det.limit_type": "max"})
        self.rec = RapidOCR(params={**base, "Rec.model_type": ModelType.SMALL})

    def _rec(self, img):
        if img.shape[0] < SMALL_ROW:
            img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        r = self.rec(img, use_det=False, use_cls=False)
        if not r.txts or r.scores[0] < MIN_SCORE:
            return ""
        return r.txts[0].strip()

    def read(self, crop, area=None):
        """-> rows [{"rect": (x0, y0, x1, y1), "pieces": ["text" | {"icon": png}], "ok": True}], top to bottom.
        area: the area's settings; rows its filter leaves out come with "ok": False and "why" (not read)."""
        r = self.det(crop, use_det=True, use_cls=False, use_rec=False)
        h, w = crop.shape[:2]
        boxes = []
        for quad in (r.boxes if r.boxes is not None else []):
            x0, y0 = np.floor(quad.min(0)).astype(int)
            x1, y1 = np.ceil(quad.max(0)).astype(int)
            x0, y0, x1, y1 = max(0, x0 - 2), max(0, y0 - 2), min(w, x1 + 2), min(h, y1 + 2)
            if y1 - y0 >= 8 and x1 - x0 >= 8:
                boxes.append((x0, y0, x1, y1))
        out = []
        if area is not None and area.get("filter", "any") != "any":
            # Every piece of text on its own: a sign next to the objective on the same row is left out, the
            # objective is still read.
            kept = []
            for b in boxes:
                look = (plain_look(crop, b) if area.get("filter") == "plain"
                        else row_look(crop, b, area.get("text_min", 170)))
                ok, why = accepts(look, area)
                if ok:
                    kept.append(b)
                else:
                    out.append({"rect": b, "pieces": [], "ok": False, "why": why})
            boxes = kept
        rows = []
        for b in sorted(boxes, key=lambda b: (b[1] + b[3]) / 2):
            cy, bh = (b[1] + b[3]) / 2, b[3] - b[1]
            for row in rows:
                if abs(row["cy"] - cy) < 0.5 * min(bh, row["h"]):
                    row["boxes"].append(b)
                    break
            else:
                rows.append({"cy": cy, "h": bh, "boxes": [b]})
        for row in rows:
            bx = row["boxes"]
            rect = (min(b[0] for b in bx), min(b[1] for b in bx), max(b[2] for b in bx), max(b[3] for b in bx))
            items = self._read_row(crop, rect, bx)
            if not items:
                continue
            pieces = [p for _, p in sorted(items, key=lambda i: i[0])]
            letters = sum(len(_LETTER.findall(p)) for p in pieces if isinstance(p, str))
            if letters < 2 and not any(isinstance(p, dict) for p in pieces):
                continue
            out.append({"rect": rect, "pieces": pieces, "ok": True})
        return out

    def _read_row(self, crop, rect, boxes):
        """One text row -> [(x, "text" | {"icon": png})]. Icons are searched in the whole row, a bit taller than
        the found boxes (an icon is often higher than the letters, and the detector may cut it or box it alone);
        the text boxes are read around them."""
        x0, y0, x1, y1 = rect
        pad = int(0.3 * (y1 - y0))
        ry0, ry1 = max(0, y0 - pad), min(crop.shape[0], y1 + pad)
        row = crop[ry0:ry1, x0:x1]
        icons = []
        if bright_text(row):        # icons only in bright text (the hint box), not in light message bubbles
            for icon in find_icons(row):
                cy = ry0 + (icon[1] + icon[3]) / 2
                if y0 <= cy <= y1:
                    icons.append(icon)
        spans = [(x0 + i[0], x0 + i[2]) for i in icons]
        items = [(s0, {"icon": icon_png(row, i), "label": self._label(row, i)}) for (s0, _), i in zip(spans, icons)]
        for bx0, by0, bx1, by1 in boxes:
            bh = by1 - by0
            parts = [(bx0, bx1)]
            for s0, s1 in spans:            # the box without the icons in it
                parts = [p for a, b in parts for p in ((a, min(b, s0)), (max(a, s1), b)) if p[1] - p[0] > 0]
            for a, b in parts:
                if b - a >= 0.6 * bh:
                    text = self._rec(crop[by0:by1, a:b])
                    if text:
                        items.append((a, text))
        return [i for i in items if not (isinstance(i[1], dict) and not i[1]["icon"])]

    def _label(self, row, icon):
        """The button's name printed on the icon ("L3", "R2", "X"), read from the inverted icon. It only helps
        the translator see a button there (DeepL picks the right Turkish ending for it)."""
        x0, y0, x1, y1, _ = icon
        pic = cv2.bitwise_not(row[y0:y1, x0:x1])
        text = re.sub(r"[^A-Za-z0-9]", "", self._rec(pic)).upper()
        return text if 1 <= len(text) <= 4 else "X"


def compose(rows, paragraph):
    """Rows -> (english with ⟦n|label⟧ for every icon, {n: png}, blocks [(english, rows)])."""
    icons, lines = {}, []
    for row in rows:
        if not row.get("ok", True):
            continue
        words = []
        for p in row["pieces"]:
            if isinstance(p, dict):
                n = len(icons) + 1
                icons[str(n)] = p["icon"]
                words.append(f"⟦{n}|{p.get('label') or 'X'}⟧")
            else:
                words.append(p)
        lines.append({"rect": row["rect"], "text": " ".join(words)})
    if paragraph:
        blocks = [" ".join(l["text"] for l in lines)] if lines else []
    else:
        blocks = [g["text"] for g in group(lines)]
    return "\n".join(blocks), icons, blocks


def same_text(a, b):
    """Two readings of the same box (small OCR differences allowed, the icons must match)."""
    if a == b:
        return True
    if not a or not b or len(TOKEN.findall(a)) != len(TOKEN.findall(b)):
        return False
    na, nb = normalize(TOKEN.sub(" ", a)), normalize(TOKEN.sub(" ", b))
    return fuzz.ratio(na, nb) >= 92


def to_xml(english):
    """⟦1|L3⟧ -> <x id="1">L3</x> (sent with ignore_tags=x: DeepL keeps "L3" and treats it as a button's name;
    a bare <x id="1"/> often landed next to the wrong word)."""
    text = english.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return TOKEN.sub(lambda m: f'<x id="{m.group(1)}">{m.group(2) or "X"}</x>', text)


# DeepL writes the Turkish case ending after the button's name ("L3'e bas"); after a picture the ending would look
# odd, so the button gets the word "tuş" with that case: "⟦1⟧ tuşuna bas".
_ENDINGS = [(re.compile(r"^y?[ae]$"), "tuşuna"), (re.compile(r"^y?[ıiuü]$"), "tuşunu"),
            (re.compile(r"^[dt][ae]n$"), "tuşundan"), (re.compile(r"^[dt][ae]$"), "tuşunda"),
            (re.compile(r"^y?l[ae]$"), "tuşuyla"), (re.compile(r"^n?[ıiuü]n$"), "tuşunun")]
_TAG_OUT = re.compile(r"<x\s+id=\"(\d+)\"\s*>[^<]*</x>(?:['’]([a-zçğıöşü]+))?|<x\s+id=\"(\d+)\"\s*/>")
_TUS = re.compile(r"^\s*tuş", re.I)


def from_xml(turkish):
    def tag(m):
        n = m.group(1) or m.group(3)
        ending = m.group(2)
        if ending is None:
            return f"⟦{n}⟧"
        rest = turkish[m.end():]
        word = next((w for p, w in _ENDINGS if p.match(ending)), "")
        return f"⟦{n}⟧" + (f" {word}" if word and not _TUS.match(rest) else "")
    text = _TAG_OUT.sub(tag, turkish)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    # One space around every icon (the tags sometimes come glued to the next word or with two spaces).
    text = re.sub(r"\s*(⟦\d+⟧)\s*", r" \1 ", text)
    text = re.sub(r" ([.,!?;:])", r"\1", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def restore_tokens(english, turkish):
    """Icons the translator lost go to the end of the sentence they were in (better than no icon)."""
    missing = [m.group(1) for m in TOKEN.finditer(english) if f"⟦{m.group(1)}⟧" not in turkish]
    if missing:
        turkish = turkish.rstrip() + " " + " ".join(f"⟦{t}⟧" for t in missing)
    return turkish


# ---------------------------------------------------------------- the watcher

class Area:
    def __init__(self, kind):
        self.kind = kind
        self.sig = None
        self.changed_at = 0.0
        self.read_at = 0.0
        self.english = ""       # what is shown (translated or being translated)
        self.candidate = ""     # a new reading waiting for a second, matching one
        self.icons = {}
        self.rect = None        # the English text in frame pixels (x0, y0, x1, y1)
        self.rows = 0
        self.tr = None
        self.empty = 0
        # The distance between its text rows (px) in recent readings: the Turkish text's size is taken from their
        # median, so it no longer jumps when one reading boxed the text a little bigger or smaller.
        self.pitches = deque(maxlen=15)
        self.skipped = ""


class RegionTranslator:
    """Runs on its own threads next to the subtitle engine. engine: for packs, translators and fixes."""

    def __init__(self, server, rp, cfg, engine, on_status=lambda kind, text: None):
        self.server = server
        self.rp = rp
        self.cfg = cfg
        self.engine = engine
        self.on_status = on_status
        self._areas = {k: Area(k) for k in KINDS}
        self._reader = None
        self._deepl = None
        self._deepl_key = None
        self._cache = self._load_cache()
        self._todo = queue.Queue()
        self._lock = threading.Lock()
        self._sent = None
        self._size = (1920, 1080)
        self.last = {}          # kind -> {"en", "tr", "via"} for the UI
        # The area page shows what an area reads (also while it is off): kinds it looks at, and per kind the last
        # reading {"time", "size": (w, h) of the crop, "rows": [{"rect", "ok", "why", "text"}]}.
        self.watching = set()
        self.debug = {}
        self._phone = self._phone_state()
        self._phone_box = None
        self._phone_reader = None
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._translate_loop, daemon=True).start()
        threading.Thread(target=self._phone_loop, daemon=True).start()

    # ---- control ----

    def enabled(self, kind):
        a = self.cfg.get("regions", {}).get(kind, {})
        return bool(a.get("enabled") and a.get("roi"))

    def area(self, kind):
        return area_cfg(self.cfg, kind)

    def preview(self, kind, seconds=8):
        """A sample box on the TV at the chosen place (no game needed)."""
        roi = self.cfg.get("regions", {}).get(kind, {}).get("roi") or [0.03, 0.05, 0.3, 0.2]
        w, h = self._size
        rect = (int(roi[0] * w), int(roi[1] * h), int((roi[0] + roi[2] * 0.9) * w),
                int((roi[1] + roi[3] * 0.6) * h))
        if kind == "objective":
            # one row as high as a subtitle's
            rect = (int(roi[0] * w), int(roi[1] * h), int((roi[0] + roi[2]) * w), int(roi[1] * h + 0.035 * h))
        sample = {"hint": "Daha hızlı yüzmek için ⟦1⟧ tuşuna bas, daha da hızlanmak için tekrar bas. Suda yana "
                          "kaymak ya da geri yüzmek için ⟦2⟧ tuşunu basılı tut.",
                  "phone": "Lucia: Neredesin? Herkes seni bekliyor.\nJason: Geliyorum, 5 dakika.",
                  "objective": "Bankaya git."}[kind]
        icons = {"1": _sample_icon("L3", True), "2": _sample_icon("L2", False)} if kind == "hint" else {}
        box = self._box(kind, rect, {"hint": 3, "phone": 2}.get(kind, 1), sample, icons, w, h)
        self.server.send({"type": "regions", "boxes": [box]})

        def back():
            time.sleep(seconds)
            self._sent = None
            self._send()
        threading.Thread(target=back, daemon=True).start()

    def restyle(self):
        """The place setting changed: send the boxes again."""
        with self._lock:
            if self._phone_box is not None and self._phone["corners"] is not None:
                self._phone_box = self._phone_panel(self._phone["corners"], self._phone_box)
        self._sent = None
        self._send()

    # ---- watching ----

    def _loop(self):
        seq = 0
        while True:
            time.sleep(CHECK_EVERY)
            kinds = [k for k in KINDS if self.enabled(k)]
            watched = [k for k in KINDS if k in self.watching and k not in kinds and self.area(k).get("roi")]
            if watched and self.rp is not None and self.rp.seq:
                self._watch_only(watched)
            if not kinds or self.rp is None or not self.rp.seq:
                self._hide_all()
                continue
            if self._reader is None:
                try:
                    self._reader = AreaReader()     # ~1 s: before the first box appears, not when it does
                except Exception as e:  # noqa: BLE001 - shown in the UI; tried again on the next look
                    for kind in kinds:
                        self.on_status(kind, f"OCR açılamadı: {e}")
                    time.sleep(5)
                    continue
            if self.rp.seq == seq:
                continue
            seq = self.rp.seq
            _, frame = self.rp.frame()
            if frame is None:
                continue
            self._size = (frame.shape[1], frame.shape[0])
            for kind in KINDS:
                if kind not in kinds:
                    self._hide(kind)
                    continue
                try:
                    self._look(kind, frame)
                except Exception as e:  # noqa: BLE001 - shown in the UI, the loop goes on
                    self.on_status(kind, f"Hata: {e}")

    def _watch_only(self, kinds):
        """An area that is off but open on the area page: read now and then so the page shows what it would read
        (nothing is translated or sent)."""
        now = time.monotonic()
        due = [k for k in kinds if now - self.debug.get(k, {}).get("time", 0) >= WATCH_EVERY]
        if not due:
            return
        _, frame = self.rp.frame()
        if frame is None:
            return
        if self._reader is None:
            try:
                self._reader = AreaReader()
            except Exception:  # noqa: BLE001 - tried again on the next look
                return
        for kind in due:
            crop, _ = self._crop(kind, frame)
            if crop.size:
                rows = self._reader.read(crop, self.area(kind))
                english, _, _ = compose(rows, KINDS[kind]["paragraph"])
                kept, why = keep_reading(self.area(kind), english, KINDS[kind]["paragraph"])
                self._note(kind, crop, rows, "" if kept else why)

    def _note(self, kind, crop, rows, skipped=""):
        """What the area read, for the area page (skipped: the whole reading was left out, and why)."""
        out = []
        for r in rows:
            text = " ".join(p if isinstance(p, str) else f"[{p.get('label') or 'tuş'}]" for p in r["pieces"])
            ok = r.get("ok", True) and not skipped
            out.append({"rect": r["rect"], "ok": ok, "why": r.get("why", "") or (skipped if r.get("ok", True) else ""),
                        "text": text})
        self.debug[kind] = {"time": time.monotonic(), "size": (crop.shape[1], crop.shape[0]), "rows": out}

    def _crop(self, kind, frame):
        h, w = frame.shape[:2]
        x, y, rw, rh = self.cfg["regions"][kind]["roi"]
        x0, y0 = int(x * w), int(y * h)
        return frame[y0:int((y + rh) * h), x0:int((x + rw) * w)], (x0, y0)

    def _look(self, kind, frame):
        a = self._areas[kind]
        crop, origin = self._crop(kind, frame)
        if crop.size == 0:
            return
        small = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (64, max(8, int(64 * crop.shape[0] / crop.shape[1]))),
                           interpolation=cv2.INTER_AREA).astype(np.int16)
        now = time.monotonic()
        moved = a.sig is None or a.sig.shape != small.shape or (np.abs(small - a.sig) > 24).mean() > 0.015
        a.sig = small
        if moved:
            a.changed_at = now
        # A new reading waiting for confirmation, or a shown box that read empty once: read again right away.
        due = (moved or a.candidate or (a.english and a.empty)
               or (a.english and now - a.read_at >= REREAD_SECONDS)
               or (not a.english and now - a.read_at >= REREAD_SECONDS * 2))
        if not due or now - a.read_at < MIN_READ_GAP:
            return
        a.read_at = now
        if self._reader is None:
            self._reader = AreaReader()
        rows = self._reader.read(crop, self.area(kind))
        english, icons, _ = compose(rows, KINDS[kind]["paragraph"])
        kept, skipped = keep_reading(self.area(kind), english, KINDS[kind]["paragraph"])
        self._note(kind, crop, rows, "" if kept else skipped)
        if skipped and english != a.skipped:
            a.skipped = english
            self._log(kind, skip=skipped, en=english)
        english = kept              # the pause menu / an exception is not shown
        if not english:
            a.candidate = ""
            a.empty += 1
            if a.english and a.empty >= EMPTY_READS_TO_HIDE:
                self._hide(kind)
            return
        a.empty = 0
        if a.english and same_text(english, a.english):
            a.candidate = ""
            return
        if not same_text(english, a.candidate):
            a.candidate = english       # read it once more before translating (a box still fading in)
            return
        a.candidate = ""
        x0, y0 = origin
        rows = [r for r in rows if r.get("ok", True)]
        rect = (x0 + min(r["rect"][0] for r in rows), y0 + min(r["rect"][1] for r in rows),
                x0 + max(r["rect"][2] for r in rows), y0 + max(r["rect"][3] for r in rows))
        # From the rows' own height, not the whole box / rows: the gaps between the phone's message bubbles made
        # that "row distance" up to twice too big (63 px letters on the TV).
        a.pitches.append(1.3 * statistics.median(r["rect"][3] - r["rect"][1] for r in rows))
        with self._lock:
            a.english, a.icons, a.rect, a.rows, a.tr = english, icons, rect, len(rows), self._cache.get(english)
        if a.tr is None:
            self._send()                # the old translation is gone at once
            self._todo.put((kind, english))
        else:
            self.last[kind] = {"en": english, "tr": a.tr, "via": "önbellek"}
            self.on_status(kind, "Okundu (önbellekten)")
            self._send()

    def _hide(self, kind):
        a = self._areas[kind]
        if a.english:
            with self._lock:
                a.english, a.tr, a.icons, a.rect, a.candidate = "", None, {}, None, ""
            self._send()

    def _hide_all(self):
        for kind in KINDS:
            self._hide(kind)

    # ---- GTA 6's phone ----

    @staticmethod
    def _phone_state():
        return {"hits": 0, "open": False, "seen_at": 0.0, "corners": None, "sig": None, "changed_at": 0.0,
                "read_sig": None, "english": "", "title": None, "messages": [], "known": [], "moved": None}

    def phone_look(self):
        """The phone panel's settings (cfg regions.gta_phone, missing keys from PHONE_LOOK)."""
        return {**PHONE_LOOK, **(self.cfg.get("regions", {}).get("gta_phone") or {})}

    def phone_active(self):
        """On, and the game is GTA 6 (or not known yet): another game's light, upright panel full of text is not
        taken for the phone."""
        if not self.phone_look().get("enabled"):
            return False
        title = self.engine.game_title(self.cfg) if self.engine else ""
        return not title or bool(_GTA6.search(title))

    def _phone_loop(self):
        while True:
            time.sleep(PHONE_EVERY)
            try:
                if not self.phone_active() or self.rp is None or not self.rp.seq:
                    self._phone_close()
                    continue
                _, frame = self.rp.frame()
                if frame is None:
                    continue
                self._size = (frame.shape[1], frame.shape[0])
                self._phone_look_once(frame)
            except Exception as e:  # noqa: BLE001 - shown in the UI, the loop goes on
                self.on_status("gta_phone", f"Hata: {e}")
                time.sleep(2)

    def _phone_look_once(self, frame, reader=None):
        st = self._phone
        now = time.monotonic()
        found = phone.find_phone(frame)
        if not found:
            st["hits"] = 0
            if st["open"] and now - st["seen_at"] > PHONE_CLOSE:
                self._phone_close()
            return
        corners = found[0]
        st["hits"] += 1
        st["seen_at"] = now
        far = 0.04 * frame.shape[0]
        if st["corners"] is None:
            st["corners"] = corners
        elif float(np.abs(corners - st["corners"]).max()) > far:
            # The panel follows a phone that moved (seen there twice in a row), not the hand shaking or one look
            # that found only a part of the screen.
            moved = st.get("moved")
            st["moved"] = corners
            if moved is not None and float(np.abs(corners - moved).max()) <= far:
                st["corners"], st["moved"] = corners, None
                if self._phone_box is not None:
                    with self._lock:
                        self._phone_box = self._phone_panel(corners, self._phone_box)
                    self._send()
        else:
            st["moved"] = None
        if not st["open"]:
            if st["hits"] < 2:
                return
            st["open"] = True
            self.on_status("gta_phone", "Telefon açık")
        screen = phone.upright(frame, corners, phone.SCREEN)
        sig = phone.signature(screen)
        if phone.changed(sig, st["sig"]):
            st["changed_at"] = now          # scrolling / a new message: read when it stops
        st["sig"] = sig
        if now - st["changed_at"] < PHONE_SETTLE or not phone.changed(sig, st["read_sig"], 3.0):
            return
        st["read_sig"] = sig
        if reader is None:
            if self._phone_reader is None:
                self._phone_reader = AreaReader()   # ~1 s, the first time the phone is up
            reader = self._phone_reader
        title, messages = phone.read_screen(reader, screen)
        english = "\n".join(m["text"] for m in messages)
        if not english:
            return                          # the home screen, a picture: the last panel stays until it closes
        # The same screen read again (the hand moved it a little): a letter or a line break read differently must not
        # change the TV, so a reading this much like the shown one is left alone.
        if st["english"] and fuzz.ratio(normalize(english.replace("\n", " ")),
                                        normalize(st["english"].replace("\n", " "))) >= PHONE_SAME:
            return
        # A message seen before in this phone session keeps its first reading and its translation (after a scroll
        # the old messages are read again, a little differently).
        for m in messages:
            seen = max(st["known"], key=lambda k: fuzz.ratio(normalize(k), normalize(m["text"])), default=None)
            if seen is not None and fuzz.ratio(normalize(seen), normalize(m["text"])) >= PHONE_SAME:
                m["text"] = seen
        english = "\n".join(m["text"] for m in messages)
        self.debug["gta_phone"] = {"time": now, "title": title, "messages": messages}
        missing = [m["text"] for m in messages if "phone:" + m["text"] not in self._cache]
        if missing:
            self.on_status("gta_phone", "Çevriliyor…")
        via = set()
        for text in missing:
            tr, used = self._translate_phone(text, title)
            self._cache["phone:" + text] = tr
            via.add(used)
        if missing:
            self._save_cache()
        turkish = {m["text"]: self._cache.get("phone:" + m["text"], m["text"]) for m in messages}
        st["known"] = (st["known"] + [m["text"] for m in messages if m["text"] not in st["known"]])[-200:]
        st.update(english=english, title=title, messages=messages)
        text = phone.panel_text(title, messages, turkish)
        self.last["gta_phone"] = {"en": english, "tr": text, "via": " + ".join(sorted(via)) or "önbellek"}
        view = {"tr": text, "title": title, "messages": messages, "turkish": turkish}
        with self._lock:
            self._phone_box = self._phone_panel(st["corners"], view)
        self.on_status("gta_phone", f"Çevrildi · {self.last['gta_phone']['via']}")
        self._send()

    def _translate_phone(self, english, title=None):
        """A phone message: DeepL first (the packs hold spoken dialogue, not texts), then the pack / local model."""
        deepl = self._client()
        if deepl is not None and deepl.up:
            context = self._context("phone") + (f" Chat: {title}." if title else "")
            try:
                turkish = from_xml(deepl.translate_xml(to_xml(english), context))
                if self.engine is not None:
                    turkish = self.engine.polish(english, turkish, self.cfg)
                return turkish, "DeepL"
            except Exception:  # noqa: BLE001 - the pack / local model below
                pass
        return self._translate_block("phone", english)

    def _phone_panel(self, corners, view):
        """What the TV shows next to the phone -> view with its "boxes": chat bubbles at the height of their messages
        (phone.bubble_boxes), or one panel of text the full width of that side (letters sized for the TV, the box
        grows down with the text, smaller letters when it does not fit the phone's height)."""
        w, h = self._size
        look = self.phone_look()
        if look.get("bubbles", True) and view.get("messages"):
            return dict(view, boxes=phone.bubble_boxes(view.get("title"), view["messages"], view.get("turkish") or {},
                                                       corners, w, h, look))
        x0, y0, pw, ph = phone.panel_place(corners, w, h)
        line = 0.034 * h * max(0.5, min(2.0, float(look.get("size", 100)) / 100))
        opacity = max(0, min(100, int(look.get("opacity", 90))))
        return dict(view, boxes=[{"id": "gta_phone", "x": x0 / w, "y": y0 / h, "w": pw / w, "h": line / h,
                                  "mw": pw / w, "mh": ph / h, "lines": 1, "tr": view["tr"], "icons": {},
                                  "fg": look.get("fg", "#FFFFFF"), "bg": look.get("bg", "#10151C"),
                                  "alpha": opacity / 100, "scale": 1.0, "shadow": opacity == 0, "align": "left"}])

    def _phone_close(self):
        if self._phone["open"] or self._phone_box is not None:
            self._phone = self._phone_state()
            with self._lock:
                self._phone_box = None
            self.on_status("gta_phone", "Telefon kapalı")
            self._send()

    # ---- translating ----

    def _client(self):
        from .conductor import DeepL
        key = self.cfg.get("online", {}).get("deepl_key", "").strip()
        if key != self._deepl_key:
            self._deepl_key = key
            self._deepl = DeepL(key) if key else None
        return self._deepl

    def _context(self, kind):
        title = self.engine.game_title(self.cfg) if self.engine else ""
        return KINDS[kind]["context"] + (f" Game: {title}." if title else "")

    def translate(self, kind, english):
        """-> (turkish with ⟦n⟧ tokens, which translator)."""
        blocks = english.split("\n")
        out, via = [], set()
        for block in blocks:
            tr, used = self._translate_block(kind, block)
            out.append(tr)
            via.add(used)
        return "\n".join(out), " + ".join(sorted(via))

    def _translate_block(self, kind, english):
        plain = TOKEN.sub(" ", english).strip()
        if not TOKEN.search(english) and self.engine is not None:
            hit = self.engine.pack_hit(english, self.cfg)
            if hit:
                return hit.turkish, f"Paket · {hit.pack.title}"
        deepl = self._client()
        turkish = None
        if deepl is not None and deepl.up:
            try:
                turkish, used = from_xml(deepl.translate_xml(to_xml(english), self._context(kind))), "DeepL"
            except Exception:  # noqa: BLE001 - the local model below
                turkish = None
        if turkish is None:
            # The local model keeps "[1]" better than other marks.
            marked = TOKEN.sub(lambda m: f"[{m.group(1)}]", english)
            raw = self.engine.machine_translate(marked, self.cfg) if self.engine else marked
            turkish, used = re.sub(r"\[(\d+)\]", lambda m: f"⟦{m.group(1)}⟧", raw), "yerel model"
        if self.engine is not None:
            turkish = self.engine.polish(plain, turkish, self.cfg)
        return restore_tokens(english, turkish), used

    def _translate_loop(self):
        while True:
            kind, english = self._todo.get()
            a = self._areas[kind]
            if a.english != english:
                continue                # the box changed meanwhile
            self.on_status(kind, "Çevriliyor…")
            try:
                tr, via = self.translate(kind, english)
            except Exception as e:  # noqa: BLE001
                self.on_status(kind, f"Çeviri hatası: {e}")
                continue
            self._cache[english] = tr
            self._save_cache()
            self.last[kind] = {"en": english, "tr": tr, "via": via}
            with self._lock:
                if a.english == english:
                    a.tr = tr
            self.on_status(kind, f"Çevrildi · {via}")
            self._send()

    # ---- TV ----

    def _box(self, kind, rect, rows, tr, icons, w, h, pitch=None):
        """The Turkish box for the TV with the area's own look: where (over the English, under / above it, or at a
        fixed place at the top / bottom of the screen), how big, which colours, with or without a box."""
        a = self.area(kind)
        x0, y0, x1, y1 = rect
        bw, bh = x1 - x0, y1 - y0
        place = a.get("place", "cover")
        gap = int(0.012 * h)
        roi = a.get("roi") or [0, 0, 1, 1]
        center = a.get("align") == "center"
        if place == "below":
            y0 = min(h - bh, y1 + gap)
        elif place == "above":
            y0 = max(0, y0 - bh - gap)
        elif place in ("top", "bottom"):
            edge = int(float(a.get("offset", 8)) / 100 * h)
            y0 = edge if place == "top" else max(0, h - edge - bh)
            x0 = (w - bw) // 2
            center = True
        # Turkish runs ~25% longer: the box may grow (to the right, or both ways when centred, up to the area's
        # edge) and down.
        if center:
            # at the fixed top / bottom place there is room: up to 3x the English width (at most 45% of the screen)
            wide = max(bw * 1.6, min(0.45 * w, bw * 3)) if place in ("top", "bottom") else max(bw * 1.15, roi[2] * w)
            cx = x0 + bw / 2
            half = max(bw / 2, min(wide / 2, cx - 4, w - cx - 4))
            mw = 2 * half
        else:
            right = max(x0 + bw, int((roi[0] + roi[2]) * w))
            mw = min(w - x0 - 4, max(bw * 1.15, right - x0))
        # As many lines as the English ("Paradise Taxi / Dialing..." stays two lines; "Arama yapılıyor..." wrapped
        # onto a third): the TV makes the letters a bit smaller instead of growing the box downwards.
        mh = min(h - y0 - 4, bh * (1.08 if a.get("keep_lines", True) else 1.8))
        opacity = max(0, min(100, int(a.get("opacity", 92))))
        # The TV takes the letters' size from the box height / rows; one reading's box can be a bit taller or
        # shorter (an icon, a cut row), so the size is corrected to the area's usual row distance.
        scale = float(a.get("size", 100)) / 100
        if pitch:
            scale *= pitch / max(1.0, bh / max(1, rows))
        return {"id": kind, "x": x0 / w, "y": y0 / h, "w": bw / w, "h": bh / h, "mw": mw / w, "mh": mh / h,
                "lines": max(1, rows), "tr": tr, "icons": icons, "fg": a.get("fg", "#FFFFFF"),
                "bg": a.get("bg", "#10151C"), "alpha": opacity / 100, "scale": round(max(0.4, min(2.5, scale)), 3),
                "shadow": opacity == 0, "align": "center" if center else "left"}

    def _send(self):
        w, h = self._size
        boxes = []
        with self._lock:
            for kind, a in self._areas.items():
                if a.english and a.tr and a.rect:
                    pitch = statistics.median(a.pitches) if a.pitches else None
                    boxes.append(self._box(kind, a.rect, a.rows, a.tr, a.icons, w, h, pitch))
            phone_tr = self._phone_box["tr"] if self._phone_box is not None else ""
            if self._phone_box is not None:
                boxes.extend(self._phone_box["boxes"])
        key = json.dumps(boxes, sort_keys=True)
        if key == self._sent:
            return
        self._sent = key
        self.server.send({"type": "regions", "boxes": boxes})
        phone_logged = False
        for b in boxes:
            if b["id"].startswith("gta_phone"):
                if not phone_logged:
                    phone_logged = True
                    self._log("gta_phone", en=self._phone["english"], tr=phone_tr,
                              bubbles=[[round(x["y"], 4), x["bg"], x["tr"][:40]] for x in boxes
                                       if x["id"].startswith("gta_phone")])
                continue
            a = self._areas[b["id"]]
            self._log(b["id"], en=a.english, tr=b["tr"], rows=b["lines"], scale=b["scale"],
                      box=[round(b[k], 4) for k in ("x", "y", "w", "h")],
                      pitch=round(statistics.median(a.pitches), 1) if a.pitches else None)

    def _log(self, kind, **info):
        """With the debug log on: what the areas showed / skipped, in logs/regions-<day>.jsonl."""
        if not self.cfg.get("debug_log", True):
            return
        try:
            path = ROOT / "logs" / f"regions-{time.strftime('%Y%m%d')}.jsonl"
            path.parent.mkdir(exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.strftime("%H:%M:%S"), "kind": kind, **info}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ---- cache ----

    def _load_cache(self):
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_cache(self):
        try:
            if len(self._cache) > 2000:
                self._cache = dict(list(self._cache.items())[-1500:])
            CACHE_FILE.write_text(json.dumps(self._cache, ensure_ascii=False, indent=0), encoding="utf-8")
        except OSError:
            pass


def _sample_icon(label, round_):
    """A drawn button icon for the preview."""
    s = 64
    img = np.zeros((s, s + (0 if round_ else 12), 4), np.uint8)
    if round_:
        cv2.circle(img, (s // 2, s // 2), s // 2 - 2, (245, 245, 245, 255), -1, cv2.LINE_AA)
    else:
        cv2.rectangle(img, (2, 6), (img.shape[1] - 3, s - 7), (245, 245, 245, 255), -1, cv2.LINE_AA)
    size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)[0]
    org = ((img.shape[1] - size[0]) // 2, (s + size[1]) // 2)
    cv2.putText(img, label, org, cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 30, 30, 255), 2, cv2.LINE_AA)
    ok, data = cv2.imencode(".png", img)
    return base64.b64encode(data.tobytes()).decode("ascii")
