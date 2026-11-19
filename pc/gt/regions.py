"""Extra screen areas translated as a whole and shown in ONE box on the TV, button icons included.

- "hint":  the tutorial / objective box ("Press (L3) to swim faster, and press again…"): all its rows are one
           paragraph, translated together.
- "phone": the in-game phone's messages: every message (paragraph) is translated on its own, one under the other.

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
import threading
import time

import cv2
import numpy as np
from rapidfuzz import fuzz

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
}
CHECK_EVERY = 0.15          # s between looks at the areas
MIN_READ_GAP = 0.35         # s between two readings of the same area
REREAD_SECONDS = 2.5        # read again at least this often while a translation is shown
EMPTY_READS_TO_HIDE = 2
MIN_SCORE = 0.6
SMALL_ROW = 28              # px: rows lower than this are enlarged x2 before reading
CACHE_FILE = ROOT / "region_cache.json"
TOKEN = re.compile(r"⟦(\d+)(?:\|([^⟧]*))?⟧")   # an icon: ⟦1|L3⟧ in English, ⟦1⟧ in Turkish
_LETTER = re.compile(r"[A-Za-z]")
STYLE = {"fg": "#ffffff", "bg": "#10151c", "alpha": 0.92}


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

    def read(self, crop):
        """-> rows [{"rect": (x0, y0, x1, y1), "pieces": ["text" | {"icon": png}]}], top to bottom."""
        r = self.det(crop, use_det=True, use_cls=False, use_rec=False)
        h, w = crop.shape[:2]
        boxes = []
        for quad in (r.boxes if r.boxes is not None else []):
            x0, y0 = np.floor(quad.min(0)).astype(int)
            x1, y1 = np.ceil(quad.max(0)).astype(int)
            x0, y0, x1, y1 = max(0, x0 - 2), max(0, y0 - 2), min(w, x1 + 2), min(h, y1 + 2)
            if y1 - y0 >= 8 and x1 - x0 >= 8:
                boxes.append((x0, y0, x1, y1))
        rows = []
        for b in sorted(boxes, key=lambda b: (b[1] + b[3]) / 2):
            cy, bh = (b[1] + b[3]) / 2, b[3] - b[1]
            for row in rows:
                if abs(row["cy"] - cy) < 0.5 * min(bh, row["h"]):
                    row["boxes"].append(b)
                    break
            else:
                rows.append({"cy": cy, "h": bh, "boxes": [b]})
        out = []
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
            out.append({"rect": rect, "pieces": pieces})
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
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._translate_loop, daemon=True).start()

    # ---- control ----

    def enabled(self, kind):
        a = self.cfg.get("regions", {}).get(kind, {})
        return bool(a.get("enabled") and a.get("roi"))

    def preview(self, kind, seconds=8):
        """A sample box on the TV at the chosen place (no game needed)."""
        roi = self.cfg.get("regions", {}).get(kind, {}).get("roi") or [0.03, 0.05, 0.3, 0.2]
        w, h = self._size
        rect = (int(roi[0] * w), int(roi[1] * h), int((roi[0] + roi[2] * 0.9) * w),
                int((roi[1] + roi[3] * 0.6) * h))
        sample = {"hint": "Daha hızlı yüzmek için ⟦1⟧ tuşuna bas, daha da hızlanmak için tekrar bas. Suda yana "
                          "kaymak ya da geri yüzmek için ⟦2⟧ tuşunu basılı tut.",
                  "phone": "Lucia: Neredesin? Herkes seni bekliyor.\nJason: Geliyorum, 5 dakika."}[kind]
        icons = {"1": _sample_icon("L3", True), "2": _sample_icon("L2", False)} if kind == "hint" else {}
        box = self._box(kind, rect, 3 if kind == "hint" else 2, sample, icons, w, h)
        self.server.send({"type": "regions", "boxes": [box]})

        def back():
            time.sleep(seconds)
            self._sent = None
            self._send()
        threading.Thread(target=back, daemon=True).start()

    def restyle(self):
        """The place setting changed: send the boxes again."""
        self._sent = None
        self._send()

    # ---- watching ----

    def _loop(self):
        seq = 0
        while True:
            time.sleep(CHECK_EVERY)
            kinds = [k for k in KINDS if self.enabled(k)]
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
        rows = self._reader.read(crop)
        english, icons, _ = compose(rows, KINDS[kind]["paragraph"])
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
        rect = (x0 + min(r["rect"][0] for r in rows), y0 + min(r["rect"][1] for r in rows),
                x0 + max(r["rect"][2] for r in rows), y0 + max(r["rect"][3] for r in rows))
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

    def _box(self, kind, rect, rows, tr, icons, w, h):
        x0, y0, x1, y1 = rect
        place = self.cfg.get("regions", {}).get(kind, {}).get("place", "cover")
        bw, bh = x1 - x0, y1 - y0
        if place == "below":
            y0 = min(h - bh, y1 + int(0.012 * h))
        # Turkish runs ~25% longer: the box may grow right (up to the area's edge) and down.
        roi = self.cfg.get("regions", {}).get(kind, {}).get("roi") or [0, 0, 1, 1]
        right = max(x1, int((roi[0] + roi[2]) * w))
        mw = min(w - x0 - 4, max(bw * 1.15, right - x0))
        mh = min(h - y0 - 4, bh * 1.8)
        return {"id": kind, "x": x0 / w, "y": y0 / h, "w": bw / w, "h": bh / h, "mw": mw / w, "mh": mh / h,
                "lines": max(1, rows), "tr": tr, "icons": icons, "fg": STYLE["fg"], "bg": STYLE["bg"],
                "alpha": STYLE["alpha"], "scale": 1.0, "shadow": False}

    def _send(self):
        w, h = self._size
        boxes = []
        with self._lock:
            for kind, a in self._areas.items():
                if a.english and a.tr and a.rect:
                    boxes.append(self._box(kind, a.rect, a.rows, a.tr, a.icons, w, h))
        key = json.dumps(boxes, sort_keys=True)
        if key == self._sent:
            return
        self._sent = key
        self.server.send({"type": "regions", "boxes": boxes})

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
