import difflib
import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_ENDS_SENTENCE = re.compile(r"[.!?…]['\"”’)]*$")


def normalize(text):
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def similar(a, b, threshold=0.9):
    if a == b:
        return True
    if not a or not b:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold


def same_line(a, b):
    """Also true when one reading only lacks / adds an edge, e.g. a half-visible speaker name."""
    if similar(a, b):
        return True
    if not a or not b:
        return False
    short, long = sorted((a, b), key=len)
    return len(short) >= 0.6 * len(long) and short in long


class SubtitleTracker:
    """Turns per-frame OCR text into 'line' / 'clear' events. Every line is sent once.

    - A line is sent once it reads the same on `stable_reads` frames; a line that does not end a
      sentence must also stay unchanged for `partial_wait` seconds (games that reveal words one
      by one pause between words).
    - The area must stay empty for `clear_after` seconds before the line counts as gone, so a
      frame or two of failed OCR does not make the subtitle flicker.
    Small OCR differences ('Iook' vs 'look') count as the same line.
    """

    def __init__(self, stable_reads=2, min_chars=1, partial_wait=0.2, clear_after=0.6):
        self.stable_reads = stable_reads
        self.min_chars = min_chars
        self.partial_wait = partial_wait
        self.clear_after = clear_after
        self._norm = ""
        self._count = 0
        self._first_seen = None
        self._emitted = ""

    def feed(self, t_frame, text):
        norm = normalize(text)
        if len(norm.replace(" ", "")) < self.min_chars:
            norm, text = "", ""
        if similar(norm, self._norm):
            self._count += 1
        else:
            self._norm = norm
            self._count = 1
            self._first_seen = t_frame

        if not norm:
            if self._emitted and t_frame - self._first_seen >= self.clear_after:
                self._emitted = ""
                return ("clear", "", self._first_seen)
            return None

        complete = bool(_ENDS_SENTENCE.search(text.strip()))
        if not complete and t_frame - self._first_seen < self.partial_wait:
            return None
        if self._count < self.stable_reads:
            return None
        grown = bool(self._emitted) and norm.startswith(self._emitted) and len(norm) > len(self._emitted) + 2
        if grown or not same_line(norm, self._emitted):
            self._emitted = norm
            return ("line", text, self._first_seen)
        return None
