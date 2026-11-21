"""Genel → "Diyalog görüntülerini topla": pictures of the dialogue to find out afterwards why a speaker's name or
colour was missed and which reading settings suit this PS5 / TV picture best.

While it is on, at every dialogue moment (a reading with words in it), at most once every EVERY seconds:
  - the subtitle area exactly as the reader got it, as PNG (lossless: the colours the thresholds saw),
  - the whole PS5 picture as JPEG (built-in Remote Play only: is the name cut off by the area's edge?),
  - one line in index.jsonl: the time (same clock as logs/session-*.jsonl), the reading settings, which letter mask
    found the rows, the rows, what OCR read, the speaker found, and the last line the TV got.
It stops by itself after LIMIT pictures. Each start makes a new folder in logs/snapshots/. The pictures are written
by a background thread, so reading is not slowed down.
"""
import json
import queue
import re
import threading
import time

import cv2

from . import filters
from .config import ROOT

DIR = ROOT / "logs" / "snapshots"
EVERY = 2.0
LIMIT = 600
_WORD = re.compile(r"[A-Za-z][a-z'’]+")


def is_dialogue(text):
    """A reading with at least two lower-case words (dialogue, not a HUD number or an all-caps sign)."""
    return len(_WORD.findall(text or "")) >= 2


def _clock():
    return time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"


class Snapshots:
    def __init__(self, folder=None, every=EVERY, limit=LIMIT):
        self.root = folder or DIR
        self.every, self.limit = every, limit
        self.on = False
        self.dir = None
        self.count = 0
        self._last = -1e9
        self._jobs = queue.Queue(maxsize=16)
        self._thread = None

    def start(self):
        """A new folder, the count from zero."""
        self.dir = self.root / time.strftime("%Y%m%d-%H%M%S")
        self.count, self._last, self.on = 0, -1e9, True
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._writer, daemon=True)
            self._thread.start()

    def stop(self):
        self.on = False

    def offer(self, now, crop, raw, clean, boxes, mask, cfg, full=None, sent=None):
        """Called after every reading. full: a function giving the whole picture (or None); sent: (time, message)
        of the last line the TV got."""
        if not self.on or now - self._last < self.every or not is_dialogue(clean):
            return False
        self._last = now
        self.count += 1
        n = self.count
        first = clean.split("\n")[0]
        record = {
            "n": n, "t": _clock(), "roi": f"{n:04d}-alan.png",
            "settings": {"text_v_min": cfg.get("text_v_min"), "text_s_max": cfg.get("text_s_max"),
                         "text_box": bool(cfg.get("text_box"))},
            "mask": mask, "rows": [[int(v) for v in b] for b in (boxes or [])],
            "read": raw, "clean": clean, "speaker": filters.split_speaker(first)[0],
        }
        if sent:
            at, msg = sent
            record["tv"] = {k: msg.get(k) for k in ("speaker", "color", "en", "tr")}
            record["tv"]["ago_s"] = round(now - at, 1)
        picture = None
        if full is not None:
            try:
                picture = full()
            except Exception:  # noqa: BLE001 - the subtitle area alone is still useful
                picture = None
        if picture is not None:
            record["full"] = f"{n:04d}-ekran.jpg"
        try:
            self._jobs.put_nowait((self.dir, crop.copy(), picture, record))
        except queue.Full:
            self.count -= 1
            return False
        if self.count >= self.limit:
            self.on = False
        return True

    def _writer(self):
        while True:
            folder, crop, picture, record = self._jobs.get()
            try:
                folder.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(folder / record["roi"]), crop, [cv2.IMWRITE_PNG_COMPRESSION, 3])
                if picture is not None:
                    cv2.imwrite(str(folder / record["full"]), picture, [cv2.IMWRITE_JPEG_QUALITY, 92])
                with open(folder / "index.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError:
                pass

    def flush(self, timeout=5.0):
        """Waits until the pictures taken so far are on disk (tests, packing)."""
        end = time.time() + timeout
        while not self._jobs.empty() and time.time() < end:
            time.sleep(0.05)
        time.sleep(0.2)
