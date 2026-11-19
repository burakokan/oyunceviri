"""A color for every speaker's name on the TV: the same name always gets the same color (kept in speakers.json, so
Lucia is the same color tomorrow too). A new name gets the color used least so far, avoiding the colors of the people
who just spoke, so the people talking in one scene look different."""
import json
import threading
import time

from .config import ROOT

PATH = ROOT / "speakers.json"
# Bright, clearly different colors that read well over the game with a dark outline (white is the text itself).
PALETTE = ["#FFD54F", "#4FC3F7", "#81C784", "#F48FB1", "#FFB74D", "#B39DDB", "#4DB6AC", "#FF8A80", "#DCE775",
           "#90A4AE"]
RECENT_SECONDS = 90.0


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
