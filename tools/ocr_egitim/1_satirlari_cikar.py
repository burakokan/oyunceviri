"""OCR training data, step 1: every subtitle row in the recorded pictures (per-second frames, dialogue pictures, shown
lines' crops), cut the way the app cuts it for the recognizer (Engine.lines + tight_box), read by the small (accurate)
and the tiny model. Output: <veri>\\rows\\*.png + rows.jsonl."""
import glob
import json
import os
import sys
import time

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ortak import DATA, LOGS as _LOGS  # noqa: E402
sys.stdout.reconfigure(encoding="utf-8")
from gt import ocr  # noqa: E402
from gt.config import DEFAULTS  # noqa: E402
from gt.engine import Engine  # noqa: E402

OUT = str(DATA)
ROWS = os.path.join(OUT, "rows")
os.makedirs(ROWS, exist_ok=True)
LOGS = str(_LOGS)
ROI = [0.25, 0.7, 0.5, 0.25]            # only its horizontal centre is used: the crops are centred on the screen
cfg = json.loads(json.dumps(DEFAULTS))
small = ocr.RapidLineOcr(min_score=0.0, accurate=True)
tiny_engine = small.engine
small_engine = small.accurate_engine


def read(engine, img):
    r = engine(img, use_det=False, use_cls=False)
    return (r.txts[0].strip(), float(r.scores[0])) if r.txts else ("", 0.0)


def rows_of(img):
    for v, s, make in ((200, 60, ocr.outline_mask), (200, 60, ocr.text_mask), (140, 40, ocr.outline_mask)):
        mask = make(img, v, s)
        boxes = Engine.lines(dict(cfg, text_v_min=v), img, mask, ROI)
        if boxes:
            return mask, boxes
    return None, []


def sources():
    for session in sorted(os.listdir(os.path.join(LOGS, "frames"))):
        for f in sorted(glob.glob(os.path.join(LOGS, "frames", session, "*.jpg"))):
            yield "frame", session, os.path.basename(f)[:6], f
    for f in sorted(glob.glob(os.path.join(LOGS, "snapshots", "*", "*-alan.png"))):
        yield "snap", os.path.basename(os.path.dirname(f)), "", f
    for f in sorted(glob.glob(os.path.join(LOGS, "crops", "*.jpg"))):
        yield "crop", os.path.basename(f)[:15], "", f


out = open(os.path.join(OUT, "rows.jsonl"), "w", encoding="utf-8")
n = seen = 0
t0 = time.time()
for kind, session, clock, path in sources():
    seen += 1
    img = cv2.imread(path)
    if img is None:
        continue
    mask, boxes = rows_of(img)
    for i, box in enumerate(boxes):
        y0, y1, x0, x1 = ocr.tight_box(mask, box)
        row = img[y0:y1, x0:x1]
        if row.shape[0] < 12 or row.shape[1] < 30:
            continue
        s_txt, s_score = read(small_engine, row)
        if sum(c.isalpha() for c in s_txt) < 2:
            continue
        t_txt, t_score = read(tiny_engine, row)
        n += 1
        name = f"{n:06d}.png"
        cv2.imwrite(os.path.join(ROWS, name), row)
        out.write(json.dumps({"id": name, "kind": kind, "session": session, "clock": clock, "src": os.path.basename(path),
                              "row": i, "box": [int(y0), int(y1), int(x0), int(x1)], "h": int(y1 - y0),
                              "bright": round(float(img[y0:y1, x0:x1].max(axis=2).mean())),
                              "small": s_txt, "small_score": round(s_score, 3), "tiny": t_txt,
                              "tiny_score": round(t_score, 3)}, ensure_ascii=False) + "\n")
    if seen % 500 == 0:
        out.flush()
        print(f"{seen} resim, {n} satır, {time.time() - t0:.0f} sn", flush=True)
out.close()
print(f"BİTTİ: {seen} resim, {n} satır, {time.time() - t0:.0f} sn")
