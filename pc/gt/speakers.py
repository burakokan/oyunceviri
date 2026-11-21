"""The color of every speaker's name on the TV.

By default the game's own color of the name is measured on every line (name_color) and sent, so the TV looks like the
game. The app's own colors are the fallback (and the choice when "Ad rengi oyundaki gibi" is off): the same name
always gets the same color (kept in speakers.json, so Lucia is the same color tomorrow too); a new name gets the color
used least so far, avoiding the colors of the people who just spoke, so the people talking in one scene look
different."""
import json
import re
import threading
import time
from collections import Counter

import cv2
import numpy as np
from rapidfuzz import fuzz

from .config import ROOT
from .filters import CUT
from .ocr import _OUTLINE, _letters_only

PATH = ROOT / "speakers.json"
# Bright, clearly different colors that read well over the game with a dark outline (white is the text itself).
PALETTE = ["#FFD54F", "#4FC3F7", "#81C784", "#F48FB1", "#FFB74D", "#B39DDB", "#4DB6AC", "#FF8A80", "#DCE775",
           "#90A4AE"]
RECENT_SECONDS = 90.0
# A word and a colon inside a row ("…transmisJoey: There ya go.")
_INSIDE = re.compile(r"([A-Za-z][\w'’.\-]{2,})\s*:\s+(?=\S)")


def name_color(bgr, box, row_text):
    """The colour of the speaker's name in the game, measured in the row ("Jason: Hey.") -> "#RRGGBB" or None.

    GTA 6 does not give a person one colour for good: in each scene the speakers get colours (white, pale yellow,
    yellow, pink, light blue…) to tell them apart, so the colour is measured on every line. The letters are the bright
    pixels with the game's dark outline next to them, in the part of the row before the colon (found by the share of
    characters, only its first 85 %); the brighter half of their pixels is taken (the edges blend into the outline).
    None when too few letter pixels are found, they disagree or are dark (a bright scene behind the name)."""
    colon = row_text.find(":")
    if colon < 1 or bgr is None:
        return None
    y0, y1, x0, x1 = box
    part = bgr[y0:y1, x0:x1]
    if part.size == 0:
        return None
    v = part.max(axis=2)
    outlined = (v >= 140) & (cv2.erode(v, _OUTLINE) < 60)
    letters = _letters_only((outlined * 255).astype(np.uint8)) > 0
    cols = np.flatnonzero(letters.any(axis=0))
    if cols.size < 10:
        return None
    a, b = int(cols[0]), int(cols[-1])
    end = a + (b - a) * colon / max(len(row_text), 1)
    hi = int(a + 0.85 * (end - a))
    if hi - a < 6:
        return None
    core = cv2.erode(letters[:, a:hi].astype(np.uint8), np.ones((2, 2), np.uint8)) > 0
    px = part[:, a:hi][core]
    if len(px) < 20:
        return None
    px = px[px.max(axis=1) >= np.percentile(px.max(axis=1), 50)].astype(np.float32)
    if float(px.std(axis=0).max()) > 28:
        return None
    color = np.median(px, axis=0)
    if color.max() < 200:
        return None         # the game's name colours are all bright: a dark one is the scene behind a thin name
    b_, g_, r_ = (int(round(c)) for c in color)
    return f"#{r_:02X}{g_:02X}{b_:02X}"


class SpeakerColors:
    def __init__(self, path=PATH):
        self.path = path
        self._lock = threading.Lock()
        self._recent = {}     # name -> last time it was used
        self.game = {}        # name -> the colour the game gave it last (this session)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.colors = {str(k): str(v) for k, v in data.items() if str(v) in PALETTE}
        except (OSError, ValueError, AttributeError):
            self.colors = {}

    @staticmethod
    def _key(name):
        return " ".join(name.split()).casefold()

    def color(self, name):
        """-> "#RRGGBB" for the speaker (None without a name)."""
        if not name or not name.strip():
            return None
        key = self._key(name)
        now = time.monotonic()
        with self._lock:
            color = self.colors.get(key)
            if color is None:
                busy = {self.colors.get(k) for k, t in self._recent.items() if now - t < RECENT_SECONDS}
                used = {c: 0 for c in PALETTE}
                for c in self.colors.values():
                    used[c] = used.get(c, 0) + 1
                free = [c for c in PALETTE if c not in busy] or PALETTE
                color = min(free, key=lambda c: (used[c], PALETTE.index(c)))
                self.colors[key] = color
                self._save()
            self._recent[key] = now
            return color

    def pick(self, name, measured=None, from_game=True):
        """The colour sent to the TV: the game's colour of this line's name (measured), or the one the game gave this
        person last when it could not be measured; the app's own colour for the person when the game's colour is not
        wanted or was never measured."""
        if not name or not name.strip():
            return None
        if from_game:
            key = self._key(name)
            with self._lock:
                if measured:
                    self.game[key] = measured
                    return measured
                if key in self.game:
                    return self.game[key]
        return self.color(name)

    def _save(self):
        try:
            self.path.write_text(json.dumps(self.colors, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass


class SpeakerNames:
    """The speakers' names read in this session, used to put right a name OCR got a little wrong ("CO wiison" ->
    "CO Wilson") or the area's edge cut off ("…ress" -> "Waitress"), so the line keeps its speaker (and colour)
    instead of losing the name or getting someone else's. The spelling read most often wins."""

    def __init__(self):
        self.counts = Counter()
        self._lock = threading.Lock()

    def resolve(self, name):
        if not name:
            return None
        with self._lock:
            if name.startswith(CUT):
                end = " ".join(name[len(CUT):].split()).casefold()
                if len(end) < 3:
                    return None
                hits = [k for k in self.counts if k.casefold().endswith(end) and len(k) > len(end)]
                return max(hits, key=lambda k: self.counts[k]) if hits else None
            folded = name.casefold()
            if name not in self.counts:
                # A menu word glued in front of a known name: "RED Joey" (the garage's colour list) -> "Joey".
                words = name.split()
                for i in range(1, len(words)):
                    tail = " ".join(words[i:])
                    if self.counts.get(tail, 0) >= 2:
                        self.counts[tail] += 1
                        return tail
            alike = [k for k in self.counts if k != name and abs(len(k) - len(name)) <= 2
                     and fuzz.ratio(k.casefold(), folded) >= 85
                     and folded + "s" != k.casefold() and k.casefold() + "s" != folded]   # "Cop" / "Cops"
            self.counts[name] += 1
            return max(alike + [name], key=lambda k: self.counts[k])

    def find(self, row):
        """A known speaker's name with its colon after other text in a row - a menu glued to the dialogue on the
        same screen row ("…Pair with transmisJoey: There ya go.", "…paint job ad oey: You wanna…") -> the row from
        that name on, with the name written in full; None when there is none."""
        with self._lock:
            known = sorted((k for k, c in self.counts.items() if c >= 3), key=len, reverse=True)
        for m in _INSIDE.finditer(row):
            if m.start() == 0:
                continue
            word = m.group(1).casefold()
            for name in known:
                last = name.split()[-1].casefold()
                # "transmisJoey" ends with "Joey"; "oey" is "Joey" without its first letter
                if word.endswith(last) or (len(word) >= max(3, len(last) - 2) and last.endswith(word)):
                    return f"{name}: {row[m.end():]}"
        return None
