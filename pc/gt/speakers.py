"""The color of every speaker's name on the TV.

By default the game's own color of the name is measured on every line (name_tint) and sent, so the TV looks like the
game. The app's own colors are the fallback (and the choice when "Ad rengi oyundaki gibi" is off): the same name
always gets the same color (kept in speakers.json, so Lucia is the same color tomorrow too); a new name gets the color
used least so far, avoiding the colors of the people who just spoke, so the people talking in one scene look
different."""
import colorsys
import json
import math
import re
import threading
import time
from collections import Counter, deque

import cv2
import numpy as np
from rapidfuzz import fuzz

from .config import ASSETS, ROOT
from .filters import CUT
from .ocr import _OUTLINE, _letters_only

PATH = ROOT / "speakers.json"
# Every person's name colours seen in the game, kept for good (the user's own, grows while playing), and the table
# that comes with the app (people whose colour never changes, from recorded GTA 6 play).
GAME_PATH = ROOT / "speaker_game_colors.json"
GAME_START = ASSETS / "speaker_game_colors.json"
# The stream (Remote Play video) halves the colour of thin letters: a cream "Jason:" arrives nearly white. The
# measured saturation is multiplied by this to look like the game again (Filtreler -> "Ad rengi canlılığı").
BOOST = 2.2
# GTA 6's "white" names are mostly faint pastel tints, steady per person (Kenton light cyan, Dobbs and Cal light
# pink: 1.6-2.7 % after the stream): a tint from this on counts, when the person's readings agree on the hue.
WHITE = 0.018
SCENE_SECONDS = 90.0    # the colour a person had in the last lines within this time (a scene)
SCENE_LINES = 3
KEEP_SAMPLES = 40       # per person in the lasting table
# Labels the game gives anybody: several people in one scene share them ("Local", "Tourist") and the game tells them
# apart by colour (one Local yellow, the next white), so every line keeps the colour measured on it.
GENERIC = {"local", "locals", "tourist", "tourists", "stranger", "strangers", "cop", "cops", "driver", "drivers",
           "pedestrian", "pedestrians", "criminal", "criminals", "mugger", "muggers", "worker", "workers",
           "staff member", "clerk", "security", "guard", "guards", "gang member", "gang members", "victim", "man",
           "woman", "guy", "girl", "kid", "biker", "bikers", "dealer", "customer", "passenger", "officer", "trooper",
           "hostage", "bystander", "witness", "fan", "fans", "protester", "protesters", "inmate", "prisoner"}
# The hues names come in (yellow measures 48-62 degrees: snapped to one, so it does not switch to gold line by line)
HUES = (0, 30, 57, 90, 120, 160, 185, 210, 240, 275, 300, 330)
# Bright, clearly different colors that read well over the game with a dark outline (white is the text itself).
PALETTE = ["#FFD54F", "#4FC3F7", "#81C784", "#F48FB1", "#FFB74D", "#B39DDB", "#4DB6AC", "#FF8A80", "#DCE775",
           "#90A4AE"]
RECENT_SECONDS = 90.0
# A word and a colon inside a row ("…transmisJoey: There ya go.")
_INSIDE = re.compile(r"([A-Za-z][\w'’.\-]{2,})\s*:\s+(?=\S)")


def name_tint(bgr, box, row_text):
    """The tint of the speaker's name in the game, measured in the row ("Jason: Hey.") -> (hue 0-360, saturation 0-1)
    or None.

    Measured against the white text of the same row, so the picture's own colour cast does not count. The letters are
    the bright pixels with the game's dark outline next to them; the name is the part of the row before the colon
    (found by the share of characters, only its first 85 %), the text the part after it; the brighter half of the
    pixels is taken (the edges blend into the outline). None when too few letter pixels are found, they disagree or
    are dark (a bright scene behind a thin name)."""
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
    core = cv2.erode(letters.astype(np.uint8), np.ones((2, 2), np.uint8)) > 0
    # The name's letters are there: about as many letter blobs as the name has letters (a map icon or a leaf where
    # the name should be is one or two blobs).
    count = cv2.connectedComponents(letters[:, a:hi].astype(np.uint8), connectivity=8)[0]
    if count - 1 < max(2, (colon * 85 // 100) // 2):
        return None

    def brighter_half(px):
        if len(px) < 20:
            return None
        return px[px.max(axis=1) >= np.percentile(px.max(axis=1), 50)].astype(np.float32)

    name = brighter_half(part[:, a:hi][core[:, a:hi]])
    if name is None or float(name.std(axis=0).max()) > 28:
        return None
    color = np.median(name, axis=0)
    if color.max() < 200:
        return None         # the game's name colours are all bright: a dark one is the scene behind a thin name
    after = int(end) + 8
    text = brighter_half(part[:, after:][core[:, after:]]) if after < part.shape[1] else None
    white = np.median(text, axis=0) if text is not None else np.full(3, 250.0, np.float32)
    tint = np.clip(color / np.maximum(white, 180), 0, 1)
    tint = tint / max(float(tint.max()), 1e-6)
    b_, g_, r_ = (float(c) for c in tint)
    h, sat, _ = colorsys.rgb_to_hsv(r_, g_, b_)
    return round(h * 360, 1), round(sat, 3)


def tint_color(hue, sat, boost=BOOST):
    """The colour for the TV: white below WHITE, else the measured hue with the saturation brought back (rounded, so
    one person does not flicker between shades line by line)."""
    if sat < WHITE:
        return "#FFFFFF"
    sat = min(0.6, max(0.1, round(sat * boost / 0.1) * 0.1))
    hue = min(HUES, key=lambda h: abs((hue - h + 180) % 360 - 180))
    r, g, b = colorsys.hsv_to_rgb(hue / 360, sat, 1.0)
    return f"#{round(r * 255):02X}{round(g * 255):02X}{round(b * 255):02X}"


def name_color(bgr, box, row_text, boost=BOOST):
    """name_tint as the colour the TV gets (None when it cannot be measured)."""
    t = name_tint(bgr, box, row_text)
    return tint_color(*t, boost) if t else None


FAINT = 0.045           # white and a tint weaker than this are told apart by many readings, not by a scene's few


def same_kind(a, b):
    """Two tints are the same colour in the game: both white or faint (a faint pastel name reads white now and then:
    the person's long record decides), or both coloured with a near hue."""
    if a[1] < FAINT and b[1] < FAINT:
        return True
    if (a[1] < WHITE) != (b[1] < WHITE):
        return False
    return abs((a[0] - b[0] + 180) % 360 - 180) <= 25


def typical(samples):
    """The usual tint of a list of (hue, saturation): white when most are white, else the circular mean hue and the
    median saturation of the coloured ones -> (hue, saturation), or None when the readings contradict each other."""
    if not samples:
        return None
    coloured = [(h, s) for h, s in samples if s >= WHITE]
    # A tie goes to the colour: a colour seen is there, a white reading may be a coloured name read faintly.
    if len(coloured) * 2 < len(samples):
        return 0.0, 0.0
    if len(coloured) == 1 and coloured[0][1] < FAINT:
        return 0.0, 0.0     # one faint reading alone: a white name read a little off as often as a pastel one
    # The hue weighted by how strong each reading is: a faint stray reading does not pull a yellow towards orange.
    x = sum(s * math.cos(math.radians(h)) for h, s in coloured)
    y = sum(s * math.sin(math.radians(h)) for h, s in coloured)
    if len(coloured) >= 2 and math.hypot(x, y) / sum(s for _, s in coloured) < 0.75:
        # The readings disagree on the hue: faint ones only, a white name read a little off -> white; a strong one
        # among them, something else was read as the name (leaves, a sign behind it) -> unknown (the record decides).
        return (0.0, 0.0) if all(s < FAINT for _, s in coloured) else None
    return round(math.degrees(math.atan2(y, x)) % 360, 1), round(float(np.median([s for _, s in coloured])), 3)


class SpeakerColors:
    def __init__(self, path=PATH, game_path=GAME_PATH, game_start=GAME_START):
        self.path = path
        self._lock = threading.Lock()
        self._recent = {}     # name -> last time it was used
        self.scene = {}       # name -> deque of (time, hue, saturation): this person's last lines
        self.learned = {}     # name -> [[hue, saturation], ...]: the colours seen in the game, kept for good
        self.game_path = game_path
        self._learned_saved = 0.0
        self._learned_dirty = False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.colors = {str(k): str(v) for k, v in data.items() if str(v) in PALETTE}
        except (OSError, ValueError, AttributeError):
            self.colors = {}
        for source in (game_start, game_path):      # the user's own table over the one that comes with the app
            try:
                for k, v in json.loads(source.read_text(encoding="utf-8")).items():
                    self.learned[str(k)] = [[float(h), float(s_)] for h, s_ in v][-KEEP_SAMPLES:]
            except (OSError, ValueError, AttributeError, TypeError):
                pass

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

    def pick(self, name, tint=None, from_game=True, boost=BOOST, now=None):
        """The colour sent to the TV.

        With the game's colours: the colour this person has in the scene, i.e. the usual one of their last lines (this
        one's measured tint included), so one line read a little off does not turn the name white for a moment; a
        new scene's colour takes over after two lines. Without a line in the scene: the colour kept for this person
        from earlier play (the lasting table). Never measured: white. Without the game's colours: the app's own
        colour for the person."""
        if not name or not name.strip():
            return None
        if not from_game:
            return self.color(name)
        key = self._key(name)
        now = time.monotonic() if now is None else now
        with self._lock:
            lines = self.scene.setdefault(key, deque(maxlen=SCENE_LINES))
            while lines and now - lines[0][0] > SCENE_SECONDS:
                lines.popleft()
            if tint:
                lines.append((now, float(tint[0]), float(tint[1])))
                seen = self.learned.setdefault(key, [])
                seen.append([float(tint[0]), float(tint[1])])
                del seen[:-KEEP_SAMPLES]
                self._learned_dirty = True
                self._save_learned(now)
            scene = typical([(h, s_) for _, h, s_ in lines])
            kept = typical(self.learned.get(key, []))
            # The scene decides the colour (GTA 6 gives some people another colour in another scene); when it is the
            # one this person usually has, the usual shade is shown, so the name does not change shade line by line.
            # Another colour than the person's usual one needs two lines of the scene: one reading alone may be a
            # leaf or a sign where the name is.
            usual = kept if scene is None or (kept is not None and (same_kind(scene, kept) or len(lines) < 2)) else scene
            if tint and key in GENERIC:
                usual = typical([tint])     # "Local", "Tourist"…: this line's own colour (another person maybe)
            if usual is not None and WHITE <= usual[1] < FAINT and len(self.learned.get(key, [])) < 5:
                usual = (0.0, 0.0)  # a faint pastel tint is trusted only after a few readings agree on it
        # never measured and not in any table: white, the colour most names have in the game
        return tint_color(*usual, boost) if usual is not None else "#FFFFFF"

    def _save_learned(self, now, force=False):
        """The lasting table to disk, at most every 20 s while playing (and when the engine stops)."""
        if not self._learned_dirty or (not force and now - self._learned_saved < 20):
            return
        self._learned_saved, self._learned_dirty = now, False
        try:
            self.game_path.write_text(json.dumps(self.learned, ensure_ascii=False, separators=(",", ":")),
                                      encoding="utf-8")
        except OSError:
            pass

    def flush(self):
        with self._lock:
            self._save_learned(time.monotonic(), force=True)

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
