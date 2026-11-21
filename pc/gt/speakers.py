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
# The stream (Remote Play video) all but wipes out the colour of thin letters: a name the TV shows in a clear lake
# green ("Shirley:") arrives nearly white (R254 G253 B244 next to the text's R255 G252 B250). Only the family of the
# colour can be told from the stream, so the TV gets a saturated shade of that family. Several shades per family:
# two people of one family in a dialogue get different ones. The first shade is the game's look on the TV.
FAMILIES = {
    "teal": ["#3FD5C4", "#4FC3F7", "#80DEEA", "#26A69A"],
    "pink": ["#F48FB1", "#F06292", "#CE93D8", "#FF8A80"],
    "yellow": ["#FFD54F", "#FFCA28", "#FFB74D"],
    "cream": ["#FFF59D", "#FFF176", "#E6EE9C"],
    "green": ["#9CCC65", "#81C784", "#AED581"],
    "blue": ["#64B5F6", "#7986CB", "#90CAF9"],
    "orange": ["#FFB74D", "#FF8A65", "#FFAB91"],
}
# For a name whose colour cannot be told (or that the game writes white): a colour all the same, never white.
# (none of them is a shade of a family above, so a stand-in colour is never taken for a family's)
FALLBACK = ["#B39DDB", "#A5D6A7", "#FFCCBC", "#B2DFDB", "#D1C4E9", "#B3E5FC", "#F8BBD0", "#DCE775", "#FFE0B2",
            "#C5CAE9"]
CREAM = 0.15            # a yellow weaker than this in the stream is the game's cream (Jason), stronger: yellow (Kyle)
CLEAR = 0.12            # a colour this strong in the stream is clear (yellow names), not a washed-out pastel
BOOST = 2.2             # kept for old callers; the shades above are used now
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
    if np.count_nonzero(letters) < 60:
        # Letters without a dark outline (on the game's semi-transparent box over a bright scene): the pixels clearly
        # brighter than the background right around them.
        ground = cv2.morphologyEx(v, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
        lifted = ((v.astype(np.int16) - ground) >= 45) & (v >= 170)
        letters = _letters_only((lifted * 255).astype(np.uint8)) > 0
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


def family_of(tint):
    """The colour family of a measured tint (None: white or unknown)."""
    if tint is None or tint[1] < WHITE:
        return None
    h, sat = tint
    if 40 <= h < 80:
        return "cream" if sat < CREAM else "yellow"
    if 20 <= h < 40:
        return "orange"
    if 80 <= h < 215:
        # The game's lake green ("Shirley:") reads anywhere from green to cyan in the washed-out stream (97 in one
        # picture, 180 in the next): one family.
        return "teal"
    if 215 <= h < 265:
        return "blue"
    return "pink"


def family_of_color(color):
    """The family a TV shade belongs to (None: a fallback colour)."""
    return next((f for f, shades in FAMILIES.items() if color in shades), None)


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
    """The usual tint of a list of (hue, saturation): white when most are white, else the tint of the colour family
    most coloured readings belong to (circular mean hue weighted by strength, median saturation) -> (hue,
    saturation), or None when the readings contradict each other."""
    if not samples:
        return None
    coloured = [(h, s) for h, s in samples if s >= WHITE]
    # A tie goes to the colour: a colour seen is there, a white reading may be a coloured name read faintly.
    if len(coloured) * 2 < len(samples):
        return 0.0, 0.0
    if len(coloured) == 1 and coloured[0][1] < FAINT:
        return 0.0, 0.0     # one faint reading alone: a white name read a little off as often as a pastel one
    # Agreement on the family, not on the exact hue: the game's lake green reads anywhere from 97 to 180 degrees.
    votes = Counter(family_of((h, s)) for h, s in coloured)
    family, n = votes.most_common(1)[0]
    if n < 0.6 * len(coloured):
        # Mixed families: faint ones only, a white name read a little off -> white; a strong one among them,
        # something else was read as the name (leaves, a sign behind it) -> unknown (the record decides).
        return (0.0, 0.0) if all(s < FAINT for _, s in coloured) else None
    chosen = [(h, s) for h, s in coloured if family_of((h, s)) == family]
    if np.median([s for _, s in chosen]) < FAINT and n < 0.6 * len(samples):
        # A faint colour on only some of the readings: a white name the stream tints a little now and then (pink in
        # one scene, cyan in the next). A pastel name reads its faint colour nearly every time.
        return 0.0, 0.0
    x = sum(s * math.cos(math.radians(h)) for h, s in chosen)
    y = sum(s * math.sin(math.radians(h)) for h, s in chosen)
    return round(math.degrees(math.atan2(y, x)) % 360, 1), round(float(np.median([s for _, s in chosen])), 3)


class SpeakerColors:
    def __init__(self, path=PATH, game_path=GAME_PATH, game_start=GAME_START):
        self.path = path
        self._lock = threading.Lock()
        self._recent = {}     # name -> last time it was used
        self.scene = {}       # name -> deque of (time, hue, saturation): this person's last lines
        self.learned = {}     # name -> [[hue, saturation], ...]: the colours seen in the game, kept for good
        self.record = {}      # name -> {"family": family or None, "color": "#RRGGBB"}: the TV colour, kept for good
        self.shown = {}       # name -> (time, colour) of the last line: the people of the dialogue
        self.pending = {}     # name -> (family, lines in a row) another family than the one on record has won
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
                data = json.loads(source.read_text(encoding="utf-8"))
                samples = data.get("samples", data) if isinstance(data.get("samples"), dict) else data
                for k, v in samples.items():
                    if isinstance(v, list):
                        self.learned[str(k)] = [[float(h), float(s_)] for h, s_ in v][-KEEP_SAMPLES:]
                for k, v in (data.get("colors") or {}).items():
                    if isinstance(v, dict) and str(v.get("color", "")).startswith("#"):
                        self.record[str(k)] = {"family": v.get("family"), "color": str(v["color"])}
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

        With the game's colours: the family of the colour this person has in the scene (the usual one of their last
        lines, this one's measured tint included; their long record when the scene is unclear), shown as a saturated
        shade of that family. Every person keeps their shade for good (the record), and two people of one dialogue
        never get the same colour. A person whose colour cannot be told gets a colour all the same (never white),
        kept too. Without the game's colours: the app's own colour for the person."""
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
            samples = self.learned.get(key, [])
            scene = typical([(h, s_) for _, h, s_ in lines])
            kept = typical(samples)
            others = {c for k, (t, c) in self.shown.items() if k != key and now - t < SCENE_SECONDS}
            if key in GENERIC:
                color = self._generic(key, tint, others, now)
            else:
                # The person's own family: the one most of their last readings (up to 40) belong to; a faint one only
                # after a few readings. It moves slowly, so the name keeps its colour line after line.
                # (someone new: from their third reading, when most of their readings agree on a family)
                faint_ok = kept is not None and (kept[1] >= FAINT or len(samples) >= 3)
                own = family_of(kept) if faint_ok else None
                # A scene where the game clearly gives this person another colour (strong colour, two lines or more):
                # shown for that scene only, the record stays.
                strong = family_of(scene) if scene is not None and scene[1] >= CLEAR and len(lines) >= 2 else None
                rec = self.record.get(key)
                family = own or (rec or {}).get("family")
                if rec and own and own != rec.get("family"):
                    # Another family than the one on record: only after it wins six lines in a row (a person whose
                    # readings are half pink, half lake green must not swap colours back and forth); from a stand-in
                    # colour (the family was not known yet) after three.
                    pending = self.pending.get(key)
                    count = pending[1] + 1 if pending and pending[0] == own else 1
                    self.pending[key] = (own, count)
                    if count < (1 if rec.get("family") is None and len(samples) <= 5 else
                                3 if rec.get("family") is None else 6):
                        family = rec.get("family")
                else:
                    self.pending.pop(key, None)
                if strong and strong != family:
                    color = self._free(strong, others)
                elif rec and rec.get("family") in (family, None) and \
                        (family is None or family_of_color(rec["color"]) == family):
                    # This person's colour, as always; when someone else of this dialogue has it (two people of one
                    # family), another shade for now: the record stays.
                    color = rec["color"] if rec["color"] not in others else self._free(family, others)
                else:
                    color = self._free(family, others, rec["color"] if rec and family is None else None)
                    self.record[key] = {"family": family, "color": color}
                    self._learned_dirty = True
            self.shown[key] = (now, color)
            self._save_learned(now)
            return color

    def _generic(self, key, tint, others, now):
        """"Local", "Tourist"…: several people of one scene, told apart by colour in the game. Each line gets the
        family measured on it; another family or an unclear one is another person, so not the last one's colour."""
        family = family_of(typical([tint])) if tint else None
        last = self.shown.get(key)
        recent = last is not None and now - last[0] < SCENE_SECONDS
        if tint is None and recent and now - last[0] < 10 and last[1] not in others:
            return last[1]          # unmeasured: the same "Local" still talking, most likely
        if recent and family_of_color(last[1]) == family and last[1] not in others:
            return last[1]          # the same colour as the last "Local" (or unclear again): the same one
        if recent and (family is None or family_of_color(last[1]) != family):
            others = others | {last[1]}
        return self._free(family, others)

    def _free(self, family, others, previous=None):
        """A shade of the family (any colour when unknown) no one else in the dialogue has, the one used least by
        the people on record (so people stay told apart in later dialogues too)."""
        shades = FAMILIES.get(family) or FALLBACK
        used = Counter(r["color"] for r in self.record.values())
        free = [c for c in shades if c not in others] or [c for c in FALLBACK if c not in others] or shades
        if previous in free and family is None:
            return previous
        if family in FAMILIES:
            return free[0]      # the family's own shade first (the game's look); the others when it is taken here
        return min(free, key=lambda c: (used[c], FALLBACK.index(c) if c in FALLBACK else len(FALLBACK)))

    def _save_learned(self, now, force=False):
        """The lasting table to disk, at most every 20 s while playing (and when the engine stops)."""
        if not self._learned_dirty or (not force and now - self._learned_saved < 20):
            return
        self._learned_saved, self._learned_dirty = now, False
        try:
            self.game_path.write_text(json.dumps({"samples": self.learned, "colors": self.record}, ensure_ascii=False,
                                                 separators=(",", ":")), encoding="utf-8")
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
