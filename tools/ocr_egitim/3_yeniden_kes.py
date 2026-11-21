"""OCR training data, step 4: every row cut again with the app's new rule (the dots after a row are taken in), into
rows2/ with the same ids; the dots at the end of each new crop are counted on the picture (n_dots in recrop.jsonl).
usage (app venv): python recrop.py"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ortak import DATA, LOGS as _LOGS  # noqa: E402
sys.stdout.reconfigure(encoding="utf-8")
from gt import ocr  # noqa: E402
from gt.config import DEFAULTS  # noqa: E402
from gt.engine import Engine  # noqa: E402

HERE = str(DATA)
LOGS = str(_LOGS)
OUT = os.path.join(HERE, "rows2")
os.makedirs(OUT, exist_ok=True)
ROI = [0.25, 0.7, 0.5, 0.25]
cfg = json.loads(json.dumps(DEFAULTS))
K = np.ones((7, 7), np.uint8)


def source(r):
    if r["kind"] == "frame":
        return os.path.join(LOGS, "frames", r["session"], r["src"])
    if r["kind"] == "snap":
        return os.path.join(LOGS, "snapshots", r["session"], r["src"])
    return os.path.join(LOGS, "crops", r["src"])


def rows_of(img):
    for v, s, make in ((200, 60, ocr.outline_mask), (200, 60, ocr.text_mask), (140, 40, ocr.outline_mask)):
        mask = make(img, v, s)
        boxes = Engine.lines(dict(cfg, text_v_min=v), img, mask, ROI)
        if boxes:
            return mask, boxes
    return None, []


def trailing_dots(row):
    """How many dots end the row: small outlined bright marks on the baseline after the last full-height letter.
    3 only for a real "...": three marks of about the same size, on one line, evenly spaced (specks of a sunlit
    gravel road are not)."""
    v = row.max(axis=2)
    h = row.shape[0]
    lit = ((v >= 140) & (cv2.erode(v, K) < 70)).astype(np.uint8)
    n, _, st, cen = cv2.connectedComponentsWithStats(lit, connectivity=8)
    comps = [(st[i], cen[i]) for i in range(1, n) if st[i][4] >= 2]
    tall = [c for c, _ in comps if c[3] >= 0.4 * h]
    if not tall:
        return 0
    last = max(c[0] + c[2] for c in tall)
    marks = sorted(((c, m) for c, m in comps if c[0] >= last - 1 and c[3] <= 0.3 * h and c[1] >= 0.4 * h
                    and c[2] <= 0.3 * h), key=lambda cm: cm[0][0])
    if len(marks) != 3:
        return min(len(marks), 2) if len(marks) < 3 else 9
    sizes = [c[4] for c, _ in marks]
    ys = [m[1] for _, m in marks]
    xs = [m[0] for _, m in marks]
    gaps = [xs[1] - xs[0], xs[2] - xs[1]]
    if (max(sizes) > 2.2 * min(sizes) or max(ys) - min(ys) > 0.12 * h or min(gaps) < 2
            or max(gaps) > 1.6 * min(gaps) or xs[2] - xs[0] > 0.8 * h):
        return 9          # three marks, but not a "..."
    return 3


def main():
    rows = [json.loads(l) for l in open(os.path.join(HERE, "rows.jsonl"), encoding="utf-8")]
    cache = {}
    out = open(os.path.join(HERE, "recrop.jsonl"), "w", encoding="utf-8")
    moved = missing = 0
    for i, r in enumerate(rows):
        path = source(r)
        if path not in cache:
            cache.clear()
            img = cv2.imread(path)
            cache[path] = (img,) + rows_of(img) if img is not None else (None, None, [])
        img, mask, boxes = cache[path]
        if img is None or r["row"] >= len(boxes):
            missing += 1
            continue
        y0, y1, x0, x1 = ocr.tight_box(mask, boxes[r["row"]])
        if abs(y0 - r["box"][0]) > 3 or abs(x0 - r["box"][2]) > 3:
            missing += 1
            continue
        crop = img[y0:y1, x0:x1]
        cv2.imwrite(os.path.join(OUT, r["id"]), crop)
        moved += x1 != r["box"][3]
        out.write(json.dumps({"id": r["id"], "box": [int(y0), int(y1), int(x0), int(x1)], "n_dots": trailing_dots(crop),
                              "grew": int(x1 - r["box"][3])}) + "\n")
        if i % 2000 == 0:
            print(i, "satır", flush=True)
    out.close()
    print(f"BİTTİ: {len(rows)} satır, kesimi değişen {moved}, eşleşmeyen {missing}")


if __name__ == "__main__":
    main()
