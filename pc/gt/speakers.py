"""A color for every speaker's name on the TV: the same name always gets the same color (kept in speakers.json, so
Lucia is the same color tomorrow too). A new name gets the color used least so far, avoiding the colors of the people
who just spoke, so the people talking in one scene look different."""
import json
import re
import threading
import time
from collections import Counter

from rapidfuzz import fuzz

from .config import ROOT
from .filters import CUT

PATH = ROOT / "speakers.json"
# Bright, clearly different colors that read well over the game with a dark outline (white is the text itself).
PALETTE = ["#FFD54F", "#4FC3F7", "#81C784", "#F48FB1", "#FFB74D", "#B39DDB", "#4DB6AC", "#FF8A80", "#DCE775",
           "#90A4AE"]
RECENT_SECONDS = 90.0
# A word and a colon inside a row ("…transmisJoey: There ya go.")
_INSIDE = re.compile(r"([A-Za-z][\w'’.\-]{2,})\s*:\s+(?=\S)")


class SpeakerColors:
    def __init__(self, path=PATH):
        self.path = path
        self._lock = threading.Lock()
        self._recent = {}     # name -> last time it was used
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
