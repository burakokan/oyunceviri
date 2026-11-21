"""Screen translation: menus, quest log, objectives, map / location names, item texts.

The whole PS5 picture is searched for text now and then (detection is slow, ~0.3 s), each piece of text is
read once, translated (Gemini Flash-Lite when a key is set: slow but accurate; the local model otherwise) and
sent to the TV, which draws the Turkish over the English at the same place. Ten times a second a cheap check
looks whether each translated text is still on screen (its letter strokes are still there): when a menu
closes, the Turkish goes away at once; when a text moves or changes, the next search finds it again.

Modes: on (keeps translating whatever appears) or one-shot ("translate now": the current screen once).
The subtitle area is left to the subtitle engine.
"""
import json
import queue
import re
import threading
import time

import cv2
import numpy as np

from . import imgio
from .config import ROOT

DETECT_EVERY = 1.2       # s between searches for new text while screen translation is on
CHECK_EVERY = 0.1        # s between "is it still there" checks
MIN_SCORE = 0.75         # OCR confidence
SMALL_LINE = 28          # px: lines lower than this are enlarged x2 before reading (small HUD / menu text)
DEBUG_DIR = ROOT / "logs" / "screen"
COLORS = {"white": "#ffffff", "yellow": "#ffd54f"}
MISSES_TO_HIDE = 2       # failed checks in a row before a translation is taken off the TV
CACHE_FILE = ROOT / "screen_cache.json"
_LETTERS = re.compile(r"[A-Za-z]")

SYSTEM = """You translate English text shown on a video game's screen into Turkish, the way a professional Turkish localization of the game would show it. The texts come from menus, buttons, quest logs, objectives, map and location names, item / skill / codex descriptions, tutorials and HUD.
Rules:
- Keep each text about as short as the English. Menu items and buttons are short: "Resume" -> "Devam Et", "Settings" -> "Ayarlar", "Inventory" -> "Envanter", "Quit to Main Menu" -> "Ana Menüye Dön", "Load Game" -> "Oyun Yükle".
- Objectives and quests are short, natural commands: "Find the key" -> "Anahtarı bul", "Talk to Marcus" -> "Marcus ile konuş".
- Keep proper names (people, places, factions, brands, weapons) as they are, but translate generic words in them: "North Gate" -> "Kuzey Kapısı", "Old Mill" -> "Eski Değirmen".
- Keep numbers, units, symbols and button names (X, R2, L1, Options) exactly.
- A text that is only a name, a number or not English is returned unchanged.
- Translate every text on its own, but use the others as context (they are on the same screen, in reading order).
- No quotes, no explanations.
Answer with a JSON array of strings: one Turkish text per input text, same order."""


class Block:
    """One piece of text on screen (a line, or several lines of the same paragraph)."""
    _next_id = 1

    def __init__(self, rect, lines, text, frame):
        self.id = Block._next_id
        Block._next_id += 1
        self.rect = rect            # x0, y0, x1, y1 in frame pixels
        self.lines = lines          # number of text lines
        self.text = text
        self.tr = None
        self.misses = 0
        self._learn(frame)

    def _learn(self, frame):
        """Text / background colors and the letter strokes, for drawing and for the "still there" check."""
        x0, y0, x1, y1 = self.rect
        crop = frame[y0:y1, x0:x1]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        mid, split = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        bright = split > 0
        self.bright_text = bright.mean() < 0.5          # the smaller class is the text
        text = bright if self.bright_text else ~bright
        self.mid = mid
        self.strokes = text
        self.around = ~cv2.dilate(text.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        fg = np.median(crop[text], axis=0) if text.any() else np.array([255, 255, 255])
        bg = np.median(crop[~text], axis=0) if (~text).any() else np.array([0, 0, 0])
        self.fg = "#%02x%02x%02x" % tuple(int(v) for v in fg[::-1])
        self.bg = "#%02x%02x%02x" % tuple(int(v) for v in bg[::-1])
        # A busy background (the game world behind a HUD text) gets a dark box instead of its own color.
        self.busy = float(gray[~text].std()) > 28 if (~text).any() else True

    def present(self, frame):
        """Are the letter strokes still where they were?"""
        x0, y0, x1, y1 = self.rect
        gray = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        if gray.shape != self.strokes.shape:
            return False
        text = gray > self.mid if self.bright_text else gray < self.mid
        recall = (text & self.strokes).sum() / max(1, self.strokes.sum())
        noise = (text & self.around).sum() / max(1, self.around.sum())
        return recall >= 0.6 and noise <= 0.4

    def message(self, w, h, style, room):
        """style: cfg["screen"]; room: (max width, max height) in px the Turkish may use without covering
        another translated text."""
        x0, y0, x1, y1 = self.rect
        mode = style.get("bg", "auto")
        alpha = style.get("opacity", 90) / 100
        if mode == "none":
            bg, alpha = "#000000", 0.0
        elif mode == "dark" or self.busy:
            bg = "#0d1117"
        else:
            bg = self.bg
        color = style.get("text_color", "auto")
        fg = COLORS.get(color) or ("#ffffff" if (self.busy or mode != "auto") else self.fg)
        return {"id": self.id, "x": x0 / w, "y": y0 / h, "w": (x1 - x0) / w, "h": (y1 - y0) / h,
                "mw": room[0] / w, "mh": room[1] / h, "lines": self.lines, "tr": self.tr, "fg": fg, "bg": bg,
                "alpha": round(alpha, 2), "scale": style.get("text_scale", 100) / 100,
                "shadow": alpha < 0.5}


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


_END = re.compile(r"[.!?:…]['\"”’)]*$")
_JOINERS = {"a", "an", "the", "of", "and", "or", "but", "to", "in", "on", "at", "for", "with", "from", "into", "by",
            "as", "that", "who", "which", "your", "his", "her", "their", "its", "my", "our", "is", "are", "was", "were"}


def _continues(last, line, width):
    """Is `line` the next line of the same paragraph as `last`? (a sentence wrapped inside a narrow box)
    width: the widest line of the paragraph so far."""
    prev = last["text"].strip()
    nxt = line["text"].strip()
    if not prev or not nxt:
        return False
    words = prev.split()
    if nxt[:1].islower() or words[-1].lower().strip(",;") in _JOINERS or prev.endswith((",", ";", "-", "—")):
        return True                                      # clearly cut in the middle of a sentence
    if _END.search(prev):
        return False                                     # the sentence ended: a new text (or a new item)
    if len(nxt.split()) == 1 and not _END.search(nxt):
        return False                                     # a lone capitalised word: a button ("Track") or a title
    size = (line["rect"][3] - line["rect"][1]) / max(1, last["rect"][3] - last["rect"][1])
    if not 0.88 <= size <= 1.14:
        return False                                     # a bigger title over smaller text, or the other way
    # No punctuation at the end: a wrapped line fills the box, a menu entry / list item is short.
    return len(words) >= 3 and (last["rect"][2] - last["rect"][0]) >= 0.8 * width


def group(lines):
    """Lines of the same paragraph (a quest description wrapped in a small box, a letter, a long objective) -> one
    block, so the sentence is translated whole and drawn as one; menu items and list entries stay apart.
    Games set lines very tight: the found boxes of two lines overlap, so a small overlap still counts as "next line".
    Every line is joined to the line right above it, never to an older one."""
    blocks = []
    for line in sorted(lines, key=lambda l: (l["rect"][1], l["rect"][0])):
        x0, y0, x1, y1 = line["rect"]
        h = y1 - y0
        best = None
        for b in blocks:
            last = b["last"]
            lx0, ly0, lx1, ly1 = last["rect"]
            lh = ly1 - ly0
            gap = y0 - ly1
            same_size = 0.75 <= h / max(1, lh) <= 1.33
            aligned = abs(x0 - lx0) < 1.2 * lh or abs((x0 + x1) - (lx0 + lx1)) / 2 < 1.5 * lh
            if not (same_size and aligned and -0.6 * lh <= gap <= 0.8 * lh):
                continue
            if best is None or ly1 > best["last"]["rect"][3]:
                best = b                                     # the line right above
        width = max(l["rect"][2] - l["rect"][0] for l in (best["lines"] if best else []) + [line])
        if best is not None and _continues(best["last"], line, width):
            best["lines"].append(line)
            best["last"] = line
        else:
            blocks.append({"lines": [line], "last": line})
    out = []
    for b in blocks:
        rects = [l["rect"] for l in b["lines"]]
        rect = [min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)]
        out.append({"rect": rect, "lines": len(b["lines"]), "text": " ".join(l["text"] for l in b["lines"])})
    # Separate texts may still overlap a little (tight lines): the upper one ends where the lower one starts.
    out.sort(key=lambda g: g["rect"][1])
    for i, up in enumerate(out):
        for low in out[i + 1:]:
            if low["rect"][0] < up["rect"][2] and low["rect"][2] > up["rect"][0] and low["rect"][1] < up["rect"][3]:
                up["rect"][3] = max(up["rect"][1] + 8, low["rect"][1])
    for g in out:
        g["rect"] = tuple(g["rect"])
    return out


class ScreenTranslator:
    """Runs next to the subtitle engine on its own thread. on_status(text) reports what it is doing."""

    def __init__(self, server, rp, cfg, local_translate, game_title=lambda: "", on_status=lambda text: None):
        self.server = server
        self.rp = rp
        self.cfg = cfg
        self.local_translate = local_translate
        self.game_title = game_title
        self.on_status = on_status
        self.enabled = False
        self._oneshot = threading.Event()
        self._blocks = []
        self._sent = None
        self._size = (1920, 1080)
        self._cache = self._load_cache()
        self._todo = queue.Queue()
        self._ocr = None
        self._ocr_side = None
        self._lock = threading.Lock()
        self.last_model = ""
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._translate_loop, daemon=True).start()

    # ---- control ----

    def set_enabled(self, on):
        self.enabled = on
        if not on:
            self._clear()
            self.on_status("Kapalı")

    def translate_now(self):
        self._oneshot.set()

    def _clear(self):
        with self._lock:
            self._blocks = []
        self._send()

    # ---- main loop ----

    def _frame(self):
        if self.rp is None:
            return None
        _, frame = self.rp.frame()
        return frame

    def _loop(self):
        last_detect, seq = 0.0, 0
        while True:
            time.sleep(CHECK_EVERY)
            want = self.enabled or self._oneshot.is_set()
            if not want and not self._blocks:
                continue
            if self.rp is None or not self.rp.seq:
                if self._oneshot.is_set():
                    self._oneshot.clear()
                    self.on_status("PS5 görüntüsü yok: önce Başlat'a bas.")
                if self._blocks:
                    self._clear()
                continue
            if self.rp.seq == seq and not self._oneshot.is_set():
                continue
            seq = self.rp.seq
            frame = self._frame()
            if frame is None:
                continue
            self._size = (frame.shape[1], frame.shape[0])
            self._check(frame)
            now = time.monotonic()
            if self._oneshot.is_set() or (self.enabled and now - last_detect >= DETECT_EVERY):
                oneshot = self._oneshot.is_set()
                self._oneshot.clear()
                last_detect = now
                try:
                    self._detect(frame)
                except Exception as e:  # noqa: BLE001 - shown in the UI, the loop goes on
                    self.on_status(f"Hata: {e}")
                if oneshot and not self.enabled:
                    self.on_status(f"Ekran çevrildi: {len(self._blocks)} yazı")

    def _check(self, frame):
        """Take translations off the TV as soon as their English text is gone."""
        changed = False
        with self._lock:
            keep = []
            for b in self._blocks:
                if b.present(frame):
                    b.misses = 0
                    keep.append(b)
                else:
                    b.misses += 1
                    if b.misses < MISSES_TO_HIDE:
                        keep.append(b)
                    else:
                        changed = True
            self._blocks = keep
        if changed:
            self._send()

    def _ocr_engines(self):
        if self._ocr is not None and self._ocr_side != (1440 if self.cfg["screen"].get("small_text") else 960):
            self._ocr = None                                  # "small text" was switched: search again at that size
        if self._ocr is None:
            from rapidocr import ModelType, RapidOCR
            base = {"Global.log_level": "error", "EngineConfig.onnxruntime.intra_op_num_threads": 2}
            side = 1440 if self.cfg["screen"].get("small_text") else 960
            det = RapidOCR(params={**base, "Det.limit_side_len": side, "Det.limit_type": "max"})
            rec = RapidOCR(params={**base, "Rec.model_type": ModelType.SMALL})
            self._ocr = (det, rec)
            self._ocr_side = side
        return self._ocr

    def _detect(self, frame):
        det, rec = self._ocr_engines()
        h, w = frame.shape[:2]
        roi = self.cfg.get("roi_builtin")
        # The hint box / phone areas have their own translator (one box each).
        own = [a["roi"] for a in self.cfg.get("regions", {}).values() if a.get("enabled") and a.get("roi")]
        r = det(frame, use_det=True, use_cls=False, use_rec=False)
        found = []
        for quad in (r.boxes if r.boxes is not None else []):
            x0, y0 = np.floor(quad.min(0)).astype(int)
            x1, y1 = np.ceil(quad.max(0)).astype(int)
            x0, y0, x1, y1 = max(0, x0 - 2), max(0, y0 - 2), min(w, x1 + 2), min(h, y1 + 2)
            if y1 - y0 < 8 or x1 - x0 < 12:
                continue
            cx, cy = (x0 + x1) / 2 / w, (y0 + y1) / 2 / h
            if roi and roi[0] <= cx <= roi[0] + roi[2] and roi[1] <= cy <= roi[1] + roi[3]:
                continue                                        # subtitles: the subtitle engine's job
            if any(a[0] <= cx <= a[0] + a[2] and a[1] <= cy <= a[1] + a[3] for a in own):
                continue
            found.append((x0, y0, x1, y1))
        with self._lock:
            known = list(self._blocks)
        lines = []
        for rect in found:
            if any(_iou(rect, b.rect) > 0.5 or _inside(rect, b.rect) for b in known):
                continue                                        # already translated and still there
            x0, y0, x1, y1 = rect
            crop = frame[y0:y1, x0:x1]
            if y1 - y0 < SMALL_LINE:                            # small text reads much better enlarged
                crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            rr = rec(crop, use_det=False, use_cls=False)
            if not rr.txts or rr.scores[0] < MIN_SCORE:
                continue
            text = rr.txts[0].strip()
            if len(_LETTERS.findall(text)) < 2:
                continue                                        # numbers, symbols, button glyphs
            lines.append({"rect": rect, "text": text})
        if self.cfg.get("debug_log"):
            self._debug(frame, found, lines)
        new = []
        for g in group(lines):
            b = Block(g["rect"], g["lines"], g["text"], frame)
            b.tr = self._cache.get(g["text"])
            new.append(b)
            if b.tr is None:
                self._todo.put(g["text"])
        if new:
            with self._lock:
                self._blocks += new
            self._send()

    def _debug(self, frame, found, lines):
        try:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            img = frame.copy()
            for x0, y0, x1, y1 in found:
                cv2.rectangle(img, (x0, y0), (x1, y1), (0, 200, 255), 1)
            for l in lines:
                x0, y0, x1, y1 = l["rect"]
                cv2.rectangle(img, (x0, y0), (x1, y1), (0, 255, 0), 2)
            stamp = time.strftime("%H%M%S")
            imgio.write(DEBUG_DIR / f"{stamp}.jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            (DEBUG_DIR / f"{stamp}.json").write_text(json.dumps(
                {"found": [list(map(int, r)) for r in found],
                 "read": [{"rect": list(map(int, l["rect"])), "text": l["text"]} for l in lines]},
                ensure_ascii=False), encoding="utf-8")
            for old in sorted(DEBUG_DIR.glob("*"))[:-60]:          # keep the last 30 screens
                old.unlink()
        except OSError:
            pass

    # ---- translation (its own thread: Gemini can take a few seconds) ----

    def _translate_loop(self):
        while True:
            texts = [self._todo.get()]
            time.sleep(0.3)                                     # collect the rest of the same screen
            while not self._todo.empty():
                texts.append(self._todo.get())
            texts = list(dict.fromkeys(t for t in texts if t not in self._cache))
            if not texts:
                continue
            self.on_status(f"Çevriliyor: {len(texts)} yazı…")
            try:
                out = self._gemini(texts)
            except Exception as e:  # noqa: BLE001 - fall back to the local model
                out = None
                self.last_model = f"yerel model ({e})"
            if out is None:
                out = [self.local_translate(t) for t in texts]
                self.last_model = self.last_model if self.last_model.startswith("yerel") else "yerel model"
            for t, tr in zip(texts, out):
                self._cache[t] = tr or t
            self._save_cache()
            with self._lock:
                for b in self._blocks:
                    if b.tr is None and b.text in self._cache:
                        b.tr = self._cache[b.text]
            self._send()
            self.on_status(f"{len(self._shown())} yazı ekranda · {self.last_model}")

    def _gemini(self, texts):
        g = self.cfg.get("gemini", {})
        if self.cfg.get("screen", {}).get("translator", "gemini") != "gemini" or not g.get("key"):
            return None
        from .packbuild.gemini import FALLBACKS, Busy, Gemini, NotFree, QuotaExhausted
        models = [g.get("model") or FALLBACKS[-1]] + [m for m in FALLBACKS if m != g.get("model")]
        prompt = (f"Game: {self.game_title() or 'unknown'}\nTexts on screen, in reading order:\n"
                  + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts)))
        for model in models:
            if _blocked.get(model, 0) > time.time():
                continue
            try:
                out = Gemini(g["key"], model, system=SYSTEM).ask_list(prompt, len(texts))
                self.last_model = model
                return out
            except QuotaExhausted as e:
                _blocked[model] = time.time() + e.retry_s
            except (NotFree, Busy):
                _blocked[model] = time.time() + 900
        return None

    # ---- TV ----

    def _shown(self):
        """Translated blocks; a text that stays the same in Turkish (a name) is not covered."""
        with self._lock:
            return [b for b in self._blocks if b.tr and b.tr.strip().lower() != b.text.strip().lower()]

    def preview(self, seconds=8):
        """Sample menu boxes on the TV with the current look (no game needed)."""
        w, h = 1920, 1080
        style = self.cfg.get("screen", {})
        samples = [((60, 30, 520, 96), 2, "Eski fener bekçisini bul ve ona gemiyi sor", "#ffffff", "#141414", True),
                   ((110, 260, 330, 306), 1, "Devam Et", "#ebebeb", "#2a2420", False),
                   ((110, 326, 330, 372), 1, "Ayarlar", "#ebebeb", "#2a2420", False),
                   ((110, 392, 330, 438), 1, "Ana Menüye Dön", "#ebebeb", "#2a2420", False),
                   ((1500, 980, 1680, 1004), 1, "Kuzey Limanı", "#ffe6c8", "#101820", False)]

        class Sample:
            pass

        blocks = []
        for i, (rect, lines, tr, fg, bg, busy) in enumerate(samples):
            b = Sample()
            b.id, b.rect, b.lines, b.tr, b.fg, b.bg, b.busy, b.text = -1 - i, rect, lines, tr, fg, bg, busy, tr
            blocks.append(b)
        boxes = [Block.message(b, w, h, style, self._room(b, blocks, w, h)) for b in blocks]
        self.server.send({"type": "screen", "boxes": boxes})

        def clear():
            time.sleep(seconds)
            self._sent = None
            self._send()                                       # back to the real translations (or nothing)
        threading.Thread(target=clear, daemon=True).start()

    def restyle(self):
        """The look changed on the PC: send every box again."""
        self._sent = None
        self._send()

    @staticmethod
    def _room(block, others, w, h):
        """How far a translation may grow (right, then down) without covering another translated text."""
        x0, y0, x1, y1 = block.rect
        line = (y1 - y0) / max(1, block.lines)
        right = min([w] + [o.rect[0] for o in others if o is not block and o.rect[1] < y1 and o.rect[3] > y0
                           and o.rect[0] >= x1 - 2])
        max_w = min(right - 6, x0 + (x1 - x0) * 1.8) - x0
        bottom = min([h, y1 + line * 3] + [o.rect[1] for o in others if o is not block and o.rect[0] < x0 + max_w
                                             and o.rect[2] > x0 and o.rect[1] >= y1 - 2])
        return max(x1 - x0, max_w), max(y1 - y0, bottom - 6 - y0)

    def _send(self):
        w, h = self._size
        shown = self._shown()
        style = self.cfg.get("screen", {})
        boxes = [b.message(w, h, style, self._room(b, shown, w, h)) for b in shown]
        key = json.dumps(boxes, sort_keys=True)
        if key == self._sent:
            return
        self._sent = key
        self.server.send({"type": "screen", "boxes": boxes})

    # ---- cache ----

    def _load_cache(self):
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_cache(self):
        try:
            CACHE_FILE.write_text(json.dumps(self._cache, ensure_ascii=False, indent=0), encoding="utf-8")
        except OSError:
            pass


_blocked = {}   # Gemini model -> time until which it is not tried (daily limit, overloaded)


def _inside(a, b):
    """Rect a lies (mostly) within rect b: a line of a paragraph block that is already translated."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy >= 0.7 * (a[2] - a[0]) * (a[3] - a[1])
