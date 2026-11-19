"""Two guards against text in the subtitle area that is not dialogue (ideas from CouchSubs / GameTranslator).

StickyRows: a mission objective, a phone notice or a shop name that stays in the subtitle area while people talk.
    A row that has been on screen for STICKY_SECONDS while a row at least YOUNGER_SECONDS younger is there is left
    out, so the old text is not glued to (or read again with) the new dialogue.
RepeatGuard: a billboard, a sign or a HUD text read again and again while driving past. A line without a speaker
    and without sentence punctuation that was shown REPEAT_COUNT times within REPEAT_WINDOW is not shown for
    REPEAT_BLOCK seconds.
"""
import re

from rapidfuzz import fuzz

from .tracker import normalize, similar

STICKY_SECONDS = 6.0
YOUNGER_SECONDS = 3.0
FORGET_SECONDS = 2.5        # a row not read for this long has left the screen

REPEAT_COUNT = 3
REPEAT_WINDOW = 300.0
REPEAT_BLOCK = 600.0

_SENTENCE_END = re.compile(r"[.!?…]['\"”’)]*\s*$")


def _same(a, b):
    return a == b or similar(a, b) or (len(a) >= 8 and fuzz.ratio(a, b) >= 85)


class StickyRows:
    def __init__(self):
        self._rows = []         # {"norm", "first", "last", "dropped"}
        self.dropped = []       # rows left out by the last filter() call (for the log)

    def filter(self, text, now, continues=lambda a, b: False):
        """text: the cleaned reading, one screen row per line -> the reading without sticky rows.
        continues(a, b): row b completes the sentence of row a (such a pair is never split)."""
        self._rows = [r for r in self._rows if now - r["last"] < FORGET_SECONDS]
        rows = [r for r in text.split("\n") if r.strip()]
        current = []
        for row in rows:
            norm = normalize(row)
            entry = next((e for e in self._rows if _same(e["norm"], norm)), None)
            if entry is None:
                entry = {"norm": norm, "first": now, "last": now, "dropped": False}
                self._rows.append(entry)
            entry["last"] = now
            current.append((row, entry))
        self.dropped = []
        if not current:
            return text
        youngest = max(e["first"] for _, e in current)
        keep = []
        for i, (row, e) in enumerate(current):
            if not e["dropped"] and len(current) >= 2:
                old = now - e["first"] >= STICKY_SECONDS and youngest - e["first"] >= YOUNGER_SECONDS
                nxt = current[i + 1][0] if i + 1 < len(current) else None
                prev = current[i - 1][0] if i > 0 else None
                if old and not (nxt and continues(row, nxt)) and not (prev and continues(prev, row)):
                    e["dropped"] = True
                    self.dropped.append(row)
            # Once left out, a row stays out while it is on screen (also when the dialogue under it is gone).
            if not e["dropped"]:
                keep.append(row)
        return "\n".join(keep)


def non_speech(english, speaker):
    """A sign, a billboard, a HUD text or an objective rather than something a person says."""
    if speaker:
        return False
    letters = [c for c in english if c.isalpha()]
    return not _SENTENCE_END.search(english.strip()) or (len(letters) >= 3 and all(c.isupper() for c in letters))


class RepeatGuard:
    def __init__(self):
        self._shown = {}        # norm -> [times shown]
        self._blocked = {}      # norm -> blocked until

    def _key(self, norm, table):
        if norm in table:
            return norm
        return next((k for k in table if len(norm) >= 6 and fuzz.ratio(k, norm) >= 90), None)

    def blocked(self, norm, now):
        key = self._key(norm, self._blocked)
        if key is None:
            return False
        if now >= self._blocked[key]:
            del self._blocked[key]
            return False
        return True

    def shown(self, norm, now):
        """Count a non-speech line shown -> True when it is blocked from now on."""
        key = self._key(norm, self._shown) or norm
        times = [t for t in self._shown.get(key, []) if now - t < REPEAT_WINDOW] + [now]
        self._shown[key] = times
        if len(self._shown) > 200:
            self._shown = {k: v for k, v in self._shown.items() if now - v[-1] < REPEAT_WINDOW}
        if len(times) >= REPEAT_COUNT:
            self._blocked[key] = now + REPEAT_BLOCK
            self._shown.pop(key, None)
            return True
        return False
