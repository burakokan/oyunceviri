"""Diagnostic session log: what OCR read, what was shown and the subtitle-area image of each line."""
import json
import threading
import time

import cv2

from .config import ROOT

LOG_DIR = ROOT / "logs"


class Logbook:
    def __init__(self):
        self.session = time.strftime("%Y%m%d-%H%M%S")
        self.dir = LOG_DIR
        (self.dir / "crops").mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"session-{self.session}.jsonl"
        self._lock = threading.Lock()
        self._last_read = None

    def _write(self, entry):
        entry = {"t": time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}", **entry}
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read(self, raw, cleaned):
        """Every change of the raw OCR text, including what the filters threw away."""
        if raw != self._last_read:
            self._last_read = raw
            self._write({"read": raw, "clean": cleaned})

    def line(self, info, crop=None):
        if crop is not None:
            name = f"{self.session}-{info['id']:04d}.jpg"
            cv2.imwrite(str(self.dir / "crops" / name), crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
            info = {**info, "crop": name}
        self._write({"line": info})

    def clear(self):
        self._write({"clear": True})

    def note(self, **info):
        """Something about the picture itself: outline mode switched on, the stream stalled."""
        self._write({"note": info})
