"""Writing pictures to disk.

OpenCV's cv2.imwrite cannot write into a folder whose path has letters outside plain ASCII on Windows: a Windows user
name like "Ali Şık" puts the app under C:\\Users\\Ali Şık\\AppData\\Local\\Programs\\Oyun Ceviri, imwrite returned False
and wrote nothing, so the logs had no pictures (dialogue pictures, per-second pictures, shown lines). Here OpenCV
only encodes the picture and Python writes the file, which works with any path.
"""
from pathlib import Path

import cv2


def write(path, img, params=()):
    """cv2.imwrite that works on every path -> True when the file was written."""
    path = Path(path)
    ok, data = cv2.imencode(path.suffix or ".png", img, list(params))
    if not ok:
        return False
    try:
        path.write_bytes(data.tobytes())
    except OSError:
        return False
    return True
