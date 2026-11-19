import asyncio

import cv2
import numpy as np


_OUTLINE = np.ones((7, 7), np.uint8)


def text_mask(bgr, v_min, s_max):
    """Bright, colorless pixels (white subtitle text) -> 255, everything else -> 0.

    Blobs that are much taller or wider than a typical letter (sky, lamps, snow)
    are dropped, so they neither trigger OCR nor get mistaken for a text line.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return _letters_only((((hsv[..., 2] >= v_min) & (hsv[..., 1] <= s_max)) * 255).astype(np.uint8))


def _letters_only(mask):
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return mask
    heights = stats[1:, cv2.CC_STAT_HEIGHT]
    widths = stats[1:, cv2.CC_STAT_WIDTH]
    areas = stats[1:, cv2.CC_STAT_AREA]
    # The typical letter height comes only from letter-sized blobs: on a bright, grainy background
    # (wood, gravel) hundreds of specks would otherwise make "typical" so small that real letters look too big.
    strip = mask.shape[0]
    plausible = (heights >= max(6, strip * 0.03)) & (heights <= strip * 0.5) & (areas >= 12)
    if not plausible.any():
        return np.zeros_like(mask)
    letter = np.median(heights[plausible])
    keep = (areas >= 4) & (heights >= letter * 0.25) & (heights <= letter * 2.2) & (widths <= letter * 6)
    lut = np.zeros(n, np.uint8)
    lut[1:][keep] = 255
    return lut[labels]


def signature(mask):
    """A coarse picture of where text is: 256 x 32 cells, a cell counts when ~6% of it is letter pixels (thin,
    medium-size subtitle letters fill far less of a cell than 25%, which made them invisible here)."""
    return cv2.resize(mask, (256, 32), interpolation=cv2.INTER_AREA) > 16


def changed(sig, last):
    """The text in the area changed: measured against the cells that hold text, not the whole area (a short line
    like "Got it." covers a tiny part of it, and appearing / disappearing went unnoticed)."""
    if last is None or sig.shape != last.shape:
        return True
    diff = int(np.count_nonzero(sig != last))
    return diff >= max(3, 0.05 * max(int(sig.sum()), int(last.sum())))


def text_lines(mask, min_height=8, max_gap=3, pad=6):
    """Split a subtitle mask into text lines -> [(y0, y1, x0, x1)], top to bottom."""
    h, w = mask.shape
    on = mask > 0
    rows = on.sum(axis=1) > max(3, w * 0.004)
    runs, start, gap = [], None, 0
    for y, filled in enumerate(rows):
        if filled:
            if start is None:
                start = y
            gap = 0
        elif start is not None:
            gap += 1
            if gap > max_gap:
                runs.append((start, y - gap + 1))
                start, gap = None, 0
    if start is not None:
        runs.append((start, h - gap))
    lines = []
    for y0, y1 in runs:
        if y1 - y0 < min_height:
            continue
        cols = np.flatnonzero(on[y0:y1].any(axis=0))
        lines.append((max(0, y0 - pad), min(h, y1 + pad),
                      max(0, cols[0] - 2 * pad), min(w, cols[-1] + 2 * pad)))
    return lines


def _runs(filled, gap):
    """Column runs of True, merging runs separated by less than `gap` columns -> [(x0, x1)]."""
    xs = np.flatnonzero(filled)
    if xs.size == 0:
        return []
    runs, start, prev = [], xs[0], xs[0]
    for x in xs[1:]:
        if x - prev > gap:
            runs.append((start, prev + 1))
            start = x
        prev = x
    runs.append((start, prev + 1))
    return runs


def subtitle_lines(bgr, mask, center, v_min, max_offset=0.12):
    """Text lines of a centered subtitle -> [(y0, y1, x0, x1)].

    Games center their subtitles, while HUD text (location names, ammo, button hints) sits
    toward the edges. On every row only the text block over the screen center is kept;
    rows with nothing near the center are dropped. The block is then widened with
    bright letters of any color on the same row, so colored speaker names ("Raiza:") are read too.
    center: horizontal screen center as a fraction of the crop width.
    """
    h, w = mask.shape
    cx = center * w
    colored = None
    out = []
    for y0, y1, _, _ in text_lines(mask):
        # Words of one line are closer than this; measured on the letters, not the row (a HUD notice a little
        # higher, like a phone call's "Chuck's Gun Shop", made the row tall and was glued to the dialogue).
        letters = letter_height(mask[y0:y1])
        gap = max(12, int(2.2 * letters)) if letters else max(12, int(1.6 * (y1 - y0)))
        runs = _runs(mask[y0:y1].any(axis=0), gap)
        if not runs:
            continue
        x0, x1 = min(runs, key=lambda r: 0 if r[0] <= cx <= r[1] else min(abs(r[0] - cx), abs(r[1] - cx)))
        if not (x0 <= cx <= x1) and min(abs(x0 - cx), abs(x1 - cx)) > max_offset * w:
            continue
        if colored is None:
            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
            colored = _letters_only(((hsv[..., 2] >= max(v_min - 25, 0)) * 255).astype(np.uint8))
        cols = colored[y0:y1].any(axis=0)
        while x0 > 0 and cols[max(0, x0 - gap // 2):x0].any():
            x0 = max(0, x0 - gap // 2) + int(np.argmax(cols[max(0, x0 - gap // 2):x0]))
        while x1 < w and cols[x1:min(w, x1 + gap // 2)].any():
            x1 = x1 + int(np.flatnonzero(cols[x1:min(w, x1 + gap // 2)])[-1]) + 1
        pad = (y1 - y0) // 3
        out.append((y0, y1, max(0, x0 - pad), min(w, x1 + pad)))
    return out


def tight_box(mask, box):
    """The row cut to the height of its letters (+ a small margin for the outline). The recognizer scales every row
    to a fixed height: a row twice as tall as its letters squeezed long lines into too few steps, so double letters
    merged and thin ones dropped ("I tell" -> "I el", "really stepped" -> "realy tepped", "I'll" -> "I'l")."""
    y0, y1, x0, x1 = box
    profile = np.count_nonzero(mask[y0:y1, x0:x1], axis=1)
    if profile.max(initial=0) < 2:
        return box
    # The row's letters: the strongest run of well-filled pixel rows, grown over its ascenders / descenders up to an
    # empty pixel row (the bottom of the line above, inside a padded box, stays out: it was read as ",").
    core = np.flatnonzero(profile >= 0.2 * profile.max())
    runs = np.split(core, np.flatnonzero(np.diff(core) > 1) + 1)
    run = max(runs, key=lambda r: int(profile[r].sum()))
    t0, t1 = int(run[0]), int(run[-1]) + 1
    while t0 > 0 and profile[t0 - 1] > 0:
        t0 -= 1
    while t1 < len(profile) and profile[t1] > 0:
        t1 += 1
    margin = max(4, int(0.15 * (t1 - t0)))
    top, bottom = t0, t1
    while top > 0 and t0 - top < margin and profile[top - 1] == 0:
        top -= 1
    while bottom < len(profile) and bottom - t1 < margin and profile[bottom] == 0:
        bottom += 1
    return y0 + top, y0 + bottom, x0, x1


def letter_height(mask):
    """Median height of the letter blobs in a mask band (0 when there are none)."""
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return 0
    heights = stats[1:, cv2.CC_STAT_HEIGHT][stats[1:, cv2.CC_STAT_AREA] >= 12]
    return float(np.median(heights)) if heights.size else 0


def keep_boxes(mask, boxes):
    """The mask with everything outside the subtitle lines erased (so HUD changes don't count)."""
    out = np.zeros_like(mask)
    for y0, y1, x0, x1 in boxes:
        out[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
    return out


class RowCache:
    """The text of the rows read last, with their letter pixels at that moment. A row is read again only when its
    letters changed (more than 3% of its pixels, compared with the moment it was read, so a slow fade-in is read
    again too); in a busy scene a moving sign or a car's badge no longer makes every subtitle row be read."""

    def __init__(self):
        self.rows = []          # (box, mask crop when read, text)
        self._next = []
        self.last_read = 0      # rows read (not reused) in the last call

    @staticmethod
    def _near(a, b):
        return abs(a[0] - b[0]) <= 3 and abs(a[1] - b[1]) <= 3 and abs(a[2] - b[2]) <= 6 and abs(a[3] - b[3]) <= 6

    def begin(self):
        self._next, self.last_read = [], 0

    def get(self, mask, box):
        for old_box, crop, text in self.rows:
            if not self._near(old_box, box):
                continue
            y0, y1, x0, x1 = old_box
            now = mask[y0:y1, x0:x1]
            if now.shape != crop.shape:
                continue
            on = max(int(np.count_nonzero(now)), int(np.count_nonzero(crop)))
            if on and int(np.count_nonzero(now != crop)) <= max(6, 0.03 * on):
                self._next.append((old_box, crop, text))
                return text
        return None

    def put(self, mask, box, text):
        y0, y1, x0, x1 = box
        self._next.append((tuple(box), mask[y0:y1, x0:x1].copy(), text))
        self.last_read += 1

    def end(self):
        self.rows = self._next


class RapidLineOcr:
    """PP-OCRv6 recognizer (RapidOCR, CPU), one call per text line.

    Detection is skipped: lines are found from the white-text mask instead.
    tiny (~10 ms/line) follows the screen; small (~25 ms/line) re-reads a line once it is
    stable, because on real game fonts it makes fewer I/l and dropped-letter mistakes.
    """

    language = "PP-OCRv6 tiny"

    def __init__(self, min_score=0.6, accurate=True):
        from rapidocr import ModelType, RapidOCR
        # A few threads are faster than all 12 for single short lines.
        params = {"Global.log_level": "error", "EngineConfig.onnxruntime.intra_op_num_threads": 4}
        self.engine = RapidOCR(params={**params, "Rec.model_type": ModelType.TINY})
        self.accurate_engine = RapidOCR(params={**params, "Rec.model_type": ModelType.SMALL}) if accurate else None
        self.min_score = min_score

    def read(self, bgr, mask, accurate=False, boxes=None, cache=None, fresh=False):
        """cache (RowCache): rows whose letters did not change since they were read keep their text;
        fresh: read every row anyway (and remember them)."""
        engine = self.accurate_engine if accurate and self.accurate_engine else self.engine
        out = []
        boxes = text_lines(mask) if boxes is None else boxes
        if cache is not None:
            cache.begin()
        for box in boxes:
            text = None if cache is None or fresh else cache.get(mask, box)
            if text is None:
                y0, y1, x0, x1 = tight_box(mask, box)
                r = engine(bgr[y0:y1, x0:x1], use_det=False, use_cls=False)
                text = r.txts[0].strip() if r.txts and r.scores[0] >= self.min_score else ""
                if cache is not None:
                    cache.put(mask, box, text)
            if text:
                out.append(text)
        if cache is not None:
            cache.end()
        # One screen row per line: rows tell apart several speakers' lines shown at once.
        return "\n".join(out)


class WinOcr:
    """Windows built-in OCR on the black-on-white mask: ~8 ms for the whole strip.

    Accurate only with the English OCR language installed; the Turkish one misreads
    English words ('all' -> 'ali').
    """

    def __init__(self):
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        langs = [l.language_tag for l in OcrEngine.available_recognizer_languages]
        tag = next((t for t in langs if t.lower().startswith("en")), None)
        self.engine = (OcrEngine.try_create_from_language(Language(tag)) if tag
                       else OcrEngine.try_create_from_user_profile_languages())
        self.language = "Windows " + self.engine.recognizer_language.language_tag
        self._loop = asyncio.new_event_loop()

    def read(self, bgr, mask, accurate=False, boxes=None, cache=None, fresh=False):
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        if cache is not None:
            cache.last_read = len(boxes) if boxes is not None else 1
        from winrt.windows.storage.streams import DataWriter
        if boxes is not None:
            mask = keep_boxes(mask, boxes)
        img = cv2.cvtColor(255 - mask, cv2.COLOR_GRAY2BGRA)
        h, w = img.shape[:2]
        writer = DataWriter()
        writer.write_bytes(img.tobytes())
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.BGRA8, w, h)
        result = self._loop.run_until_complete(self._recognize(bitmap))
        return "\n".join(line.text for line in result.lines)

    async def _recognize(self, bitmap):
        return await self.engine.recognize_async(bitmap)


def make_ocr(name, accurate=True):
    ocr = WinOcr() if name == "windows" else RapidLineOcr(accurate=accurate)
    # The first read loads the model (~150 ms); do it now instead of on the first subtitle.
    img = np.zeros((48, 220, 3), np.uint8)
    cv2.putText(img, "Warm up", (8, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    ocr.read(img, text_mask(img, 200, 60))
    ocr.read(img, text_mask(img, 200, 60), accurate=True)
    return ocr


def outline_mask(bgr, v_min, s_max, dark=60):
    """White text with a dark outline / shadow (GTA 6 and many games): only bright pixels with a near-black pixel
    within 3 px. On a bright, busy background (sunlit streets, foliage, posters) this keeps the subtitle row
    apart from the scene, where text_mask() lets the scene merge into the row."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2]
    near_dark = cv2.erode(v, _OUTLINE) < dark
    return _letters_only((((v >= v_min) & (hsv[..., 1] <= s_max) & near_dark) * 255).astype(np.uint8))


def outline_ratio(bgr, mask, boxes, dark=60):
    """Share of the text pixels in the boxes that have a near-black pixel next to them (1.0: outlined text)."""
    if not boxes:
        return None
    v = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[..., 2]
    near_dark = cv2.erode(v, _OUTLINE) < dark
    text = near = 0
    for y0, y1, x0, x1 in boxes:
        t = mask[y0:y1, x0:x1] > 0
        text += int(t.sum())
        near += int((t & near_dark[y0:y1, x0:x1]).sum())
    return near / text if text else None
