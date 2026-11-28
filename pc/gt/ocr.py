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


class Rows(list):
    """Text lines [(y0, y1, x0, x1)]; cut: the (y0, y1) of the lines cut out of a taller band of the scene
    (_baseline_rows), which are read only when the recognizer is sure (CUT_SCORE)."""

    def __init__(self, items=(), cut=()):
        super().__init__(items)
        self.cut = set(cut)


# A line cut out of a busy scene is kept only with a sure reading: real subtitles there read at 0.94-0.98, a map's
# labels or a car's plate cut the same way at 0.64-0.82 ("Cr-stown", "A eL").
CUT_SCORE = 0.9


def text_lines(mask, min_height=8, max_gap=3, pad=6):
    """Split a subtitle mask into text lines -> Rows [(y0, y1, x0, x1)], top to bottom."""
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
    split = []
    for y0, y1 in runs:
        rows = _baseline_rows(mask, y0, y1) if y1 - y0 >= 3 * min_height else []
        # Only a band clearly taller than the lines of letters in it is replaced (a normal line stays as it was).
        if rows and (y1 - y0) > 1.6 * max(b - t for t, b in rows):
            split.extend((t, b, True) for t, b in rows)
        else:
            split.append((y0, y1, False))
    lines, cut_rows = [], []
    for i, (y0, y1, cut) in enumerate(split):
        if y1 - y0 < min_height:
            continue
        cols = np.flatnonzero(on[y0:y1].any(axis=0))
        top, bottom = max(0, y0 - pad), min(h, y1 + pad)
        # lines cut out of one band: the margin stops at the neighbour's letters (the top of the next line's letters
        # in this crop was read as a line of its own: "@@ele ee ecme ine")
        if cut and i > 0 and split[i - 1][2]:
            top = max(top, split[i - 1][1])
        if cut and i + 1 < len(split) and split[i + 1][2]:
            bottom = min(bottom, split[i + 1][0])
        lines.append((top, bottom, max(0, cols[0] - 2 * pad), min(w, cols[-1] + 2 * pad)))
        if cut:
            cut_rows.append((top, bottom))
    return Rows(lines, cut_rows)


def _baseline_rows(mask, y0, y1):
    """The lines of letters inside a band of the mask -> [(top, bottom)] (empty: no clear line).

    On a bright, busy scene (sunlit pavement, foliage, a shirt's print) specks of the scene fill the pixel rows above
    and below the subtitle, and the band of filled rows ran from the top of the area to the bottom: the recognizer got
    a crop four lines tall and read nothing (the line was lost whatever the brightness settings). The letters of a
    line stand on one baseline: a bottom shared by many letter-sized blobs spread along the row marks a line; the
    scene's specks share none."""
    n, _, st, _ = cv2.connectedComponentsWithStats(mask[y0:y1], connectivity=8)
    if n <= 5:
        return []
    tops, hs = st[1:, cv2.CC_STAT_TOP], st[1:, cv2.CC_STAT_HEIGHT]
    xs, ws, areas = st[1:, cv2.CC_STAT_LEFT], st[1:, cv2.CC_STAT_WIDTH], st[1:, cv2.CC_STAT_AREA]
    ok = (areas >= 12) & (hs >= 6) & (hs <= 0.6 * mask.shape[0])
    if ok.sum() < 5:
        return []
    tops, hs, xs, ws = tops[ok], hs[ok], xs[ok], ws[ok]
    bottoms = tops + hs
    votes = np.convolve(np.bincount(bottoms, minlength=y1 - y0 + 1).astype(float), np.ones(5), mode="same")
    rows, taken = [], []
    # A line of dialogue has ten letters and more; a few blobs on one bottom are a map's place name, a car's plate or
    # the scene (read as "Cr-stown", "TM oOT" and shown as a line). A second line is a fair share of the first one.
    least = max(10.0, 0.25 * float(votes.max()))
    for b in np.argsort(-votes, kind="stable"):
        if votes[b] < least:
            break
        near = np.abs(bottoms - b) <= 2
        if near.sum() < least:
            continue
        cap = float(np.percentile(hs[near], 75))
        # the next line of a subtitle stands about two letter heights lower; closer bottoms belong to this line
        # (descenders, the scene right under it)
        if any(abs(b - t) < 1.4 * max(cap, c) for t, c in taken):
            continue
        # Letters stand close together along the line: the longest run of these blobs with gaps under three letter
        # heights must be long and mostly letters (a subtitle's letters cover 50-70 % of its length; a map's roads
        # and labels or a plate with the scene around it 13-26 %).
        order = np.argsort(xs[near], kind="stable")
        x0s, x1s = xs[near][order], (xs[near] + ws[near])[order]
        breaks = np.flatnonzero(x0s[1:] - np.maximum.accumulate(x1s)[:-1] > 3 * cap) + 1
        chain = max(np.split(np.arange(len(x0s)), breaks), key=len)
        left, right = int(x0s[chain].min()), int(x1s[chain].max())
        if len(chain) < least or right - left < 4 * cap or (x1s[chain] - x0s[chain]).sum() < 0.4 * (right - left):
            continue
        taken.append((int(b), cap))
        rows.append((max(0, int(b - 1.3 * cap)), min(y1 - y0, int(b + 0.45 * cap) + 1)))
    rows.sort()
    # two lines that overlap after the margins: the second one starts where the first one's letters end
    out = []
    for top, bottom in rows:
        if out and top < out[-1][1]:
            top = out[-1][1]
        if bottom - top >= 6:
            out.append((top, bottom))
    return [(y0 + top, y0 + bottom) for top, bottom in out]


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


def subtitle_lines(bgr, mask, center, v_min, max_offset=0.12, widen=True, runs_mask=None):
    """Text lines of a centered subtitle -> [(y0, y1, x0, x1)].

    Games center their subtitles, while HUD text (location names, ammo, button hints) sits
    toward the edges. On every row only the text block over the screen center is kept;
    rows with nothing near the center are dropped. The block is then widened with
    bright letters of any color on the same row, so colored speaker names ("Raiza:") are read too.
    center: horizontal screen center as a fraction of the crop width.
    widen: False for the trained letter finder's mask, which holds coloured names and dots already (widening by
    brightness would let a sunlit scene pull the row sideways).
    runs_mask: where a row's words are told apart (the finder's letter cells: a word is one block there, so the space
    after "Jason:" never splits it off); the rows themselves still come from the letters (two lines close together
    are two rows).
    """
    h, w = mask.shape
    cx = center * w
    colored = None
    found = text_lines(mask)
    out = Rows(cut=found.cut)
    for y0, y1, _, _ in found:
        # Words of one line are closer than this; measured on the letters, not the row (a HUD notice a little
        # higher, like a phone call's "Chuck's Gun Shop", made the row tall and was glued to the dialogue).
        words = mask if runs_mask is None else runs_mask
        letters = letter_height(words[y0:y1])
        gap = max(12, int(2.2 * letters)) if letters else max(12, int(1.6 * (y1 - y0)))
        runs = _runs(words[y0:y1].any(axis=0), gap)
        if not runs:
            continue
        x0, x1 = min(runs, key=lambda r: 0 if r[0] <= cx <= r[1] else min(abs(r[0] - cx), abs(r[1] - cx)))
        if not (x0 <= cx <= x1) and min(abs(x0 - cx), abs(x1 - cx)) > max_offset * w:
            continue
        if not widen:
            pad = (y1 - y0) // 3
            out.append((y0, y1, max(0, x0 - pad), min(w, x1 + pad)))
            continue
        if colored is None:
            v = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[..., 2]
            bright = v >= max(v_min - 25, 0)
            # On a sunlit street the bright pavement melts into a coloured name ("Joey:") and the blob is thrown
            # away as too big, so the name stayed outside the row and the line had no speaker: letters with a dark
            # outline next to them are taken too (the pavement has none).
            outlined = bright & (cv2.erode(v, _OUTLINE) < 60)
            colored = (_letters_only((bright * 255).astype(np.uint8))
                       | _letters_only((outlined * 255).astype(np.uint8)))
        cols = colored[y0:y1].any(axis=0)
        # The gap measured on the letters themselves: on the game's semi-transparent subtitle box the outline mask
        # keeps only bits of the letters (the box is not dark enough to count as their outline), so their height
        # came out small, the gap too, and the row stopped at the space after the name ("Dobbs: Loud and clear."
        # was read "Loud and clear.").
        full = letter_height(colored[y0:y1])
        if full:
            gap = max(gap, int(2.2 * full))
        # To the left a bit further: the space after "Stranger:" (colon + space) is wider than between words.
        left = (3 * gap) // 4
        while x0 > 0 and cols[max(0, x0 - left):x0].any():
            x0 = max(0, x0 - left) + int(np.argmax(cols[max(0, x0 - left):x0]))
        while x1 < w and cols[x1:min(w, x1 + gap // 2)].any():
            x1 = x1 + int(np.flatnonzero(cols[x1:min(w, x1 + gap // 2)])[-1]) + 1
        # The dots right after the row ("causeway...", "so..."): too small to count as letters, so the row ended
        # at the first or second one, "..." was read "." or ".." and the line looked finished (its rest on the
        # next screen was not joined to it). Outlined bright marks in the lower half of the row, close together,
        # at most a row's height further.
        low = outlined[y0 + (y1 - y0) // 2:y1]
        step, limit = max(3, (y1 - y0) // 4), min(w, x1 + (y1 - y0))
        while x1 < limit and low[:, x1:min(limit, x1 + step)].any():
            x1 = x1 + int(np.flatnonzero(low[:, x1:min(limit, x1 + step)].any(axis=0))[-1]) + 1
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


def baseline(mask, box):
    """The line the row's letters stand on: the median bottom of its letters (descenders, dots and specks are the
    few) -> y in the mask, or None with fewer than 3 letters. Steadier than the row's middle, which moves with
    "g", "y" and capitals."""
    y0, y1, x0, x1 = box
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask[y0:y1, x0:x1], connectivity=8)
    if n <= 3:
        return None
    heights, tops, areas = stats[1:, cv2.CC_STAT_HEIGHT], stats[1:, cv2.CC_STAT_TOP], stats[1:, cv2.CC_STAT_AREA]
    big = areas >= 12
    if big.sum() < 3:
        return None
    ok = big & (heights >= 0.5 * np.median(heights[big]))
    if ok.sum() < 3:
        return None
    return y0 + float(np.median(tops[ok] + heights[ok]))


def row_light(bgr, mask, box):
    """How bright the row's letters are: the median of the brighter half of its letter pixels (the brightest of B, G,
    R, so a coloured name counts as bright) -> 0-255, or None with too few letter pixels. GTA 6 writes another
    person's short answer under the speaker's line in grey ("Oh shit." 156 under white 254)."""
    y0, y1, x0, x1 = box
    letters = mask[y0:y1, x0:x1] > 0
    if np.count_nonzero(letters) < 30:
        return None
    v = bgr[y0:y1, x0:x1].max(axis=2)[letters]
    return float(np.median(v[v >= np.median(v)]))


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


def trained_model():
    """The recognizer trained for game subtitles (assets/ocr): PP-OCRv6 tiny fine-tuned on the recorded subtitle rows
    of the games played with the app (GTA 6 most), with an output of English characters and the Turkish letters only
    (108 classes instead of 6 906; Turkish so that a PS5 menu in Turkish is still seen as Turkish and not translated):
    faster than tiny, as right as small, and it cannot answer "ó" or "〇". None when the file is missing."""
    from .config import ASSETS
    path = ASSETS / "ocr" / "game_rec_tiny_en.onnx"
    return path if path.is_file() else None


class RapidLineOcr:
    """PP-OCRv6 recognizer (RapidOCR, CPU), one call per text line.

    Detection is skipped: lines are found from the white-text mask instead.
    tiny (~10 ms/line) follows the screen; small (~25 ms/line) re-reads a line once it is
    stable, because on real game fonts it makes fewer I/l and dropped-letter mistakes.
    """

    language = "PP-OCRv6 tiny"

    def __init__(self, min_score=0.6, accurate=True, model=None):
        from rapidocr import ModelType, RapidOCR
        # A few threads are faster than all 12 for single short lines.
        params = {"Global.log_level": "error", "EngineConfig.onnxruntime.intra_op_num_threads": 4}
        if model is not None:
            self.engine = RapidOCR(params={**params, "Rec.model_path": str(model)})
            self.language = "Oyunlar için eğitilmiş (PP-OCRv6 tiny)"
        else:
            self.engine = RapidOCR(params={**params, "Rec.model_type": ModelType.TINY})
        self.accurate_engine = RapidOCR(params={**params, "Rec.model_type": ModelType.SMALL}) if accurate else None
        self.min_score = min_score
        self.rows = []          # [(box, text)] of the last read, every row (the speaker name's colour is measured there)

    def read(self, bgr, mask, accurate=False, boxes=None, cache=None, fresh=False):
        """cache (RowCache): rows whose letters did not change since they were read keep their text;
        fresh: read every row anyway (and remember them)."""
        engine = self.accurate_engine if accurate and self.accurate_engine else self.engine
        out, rows = [], []
        boxes = text_lines(mask) if boxes is None else boxes
        if cache is not None:
            cache.begin()
        for box in boxes:
            text = None if cache is None or fresh else cache.get(mask, box)
            if text is None:
                y0, y1, x0, x1 = tight_box(mask, box)
                r = engine(bgr[y0:y1, x0:x1], use_det=False, use_cls=False)
                least = CUT_SCORE if (box[0], box[1]) in getattr(boxes, "cut", ()) else self.min_score
                text = r.txts[0].strip() if r.txts and r.scores[0] >= least else ""
                if cache is not None:
                    cache.put(mask, box, text)
            rows.append((tuple(int(v) for v in box), text))
            if text:
                out.append(text)
        if cache is not None:
            cache.end()
        self.rows = rows
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


def letter_finder_model():
    """The trained subtitle letter finder (assets/ocr/altyazi_bulucu.onnx), or None when the file is missing."""
    from .config import ASSETS
    path = ASSETS / "ocr" / "altyazi_bulucu.onnx"
    return path if path.is_file() else None


class LetterFinder:
    """Finds subtitle letters with a small network trained on GTA 6 recordings and synthetic subtitles (white letters
    with an outline, on the game's subtitle background or without, on every kind of scene): no brightness / colour
    thresholds to set. The network marks the 4 x 4 cells holding subtitle letters (~5-10 ms a frame); inside those
    cells, row by row, the letters are the brighter part (the row's own Otsu threshold: white or coloured letters
    against their dark outline / the box). -> a letter mask like text_mask(), for the same row finder and reader."""

    def __init__(self, path, threads=4):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        self.session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        self.name = self.session.get_inputs()[0].name
        self.cells = None           # the last frame's letter cells (full size, 0 / 255), for the preview

    def letter_cells(self, bgr, scale=0.5):
        """The network's letter cells at the picture's size. scale: the network sees the picture as at 1080p / 2."""
        h, w = bgr.shape[:2]
        sh, sw = max(16, round(h * scale)), max(16, round(w * scale))
        small = cv2.resize(bgr, (sw, sh), interpolation=cv2.INTER_AREA)
        H, W = -(-sh // 16) * 16, -(-sw // 16) * 16
        small = cv2.copyMakeBorder(small, 0, H - sh, 0, W - sw, cv2.BORDER_REFLECT)
        x = (small.astype(np.float32) / 255 - 0.5).transpose(2, 0, 1)[None]
        logit = self.session.run(None, {self.name: x})[0][0, 0]
        cells = (logit[:-(-sh // 2), :-(-sw // 2)] > 0).astype(np.uint8)
        return cv2.resize(cells, (w, h), interpolation=cv2.INTER_NEAREST) * 255

    def find(self, bgr, scale=0.5):
        """-> (letter mask, letter cells). The rows are found on the cells (a word is one solid block there, so the
        space after "Jason:" never splits a line); the letters are what the reader and the change tests use."""
        letters = self.letters(bgr, scale)
        return letters, self.cells

    def letters(self, bgr, scale=0.5):
        cells = self.letter_cells(bgr, scale)
        self.cells = cells
        out = np.zeros_like(cells)
        rows = cells.any(axis=1)
        if not rows.any():
            return out
        h, w = cells.shape
        for y0, y1 in _runs(rows, 1):
            # only around this band of cells (not the whole picture)
            y0, y1 = max(0, y0 - 1), min(h, y1 + 1)
            cols = np.flatnonzero(cells[y0:y1].any(axis=0))
            if cols.size == 0:
                continue
            x0, x1 = max(0, int(cols[0]) - 1), min(w, int(cols[-1]) + 2)
            sel = cv2.dilate(cells[y0:y1, x0:x1], np.ones((3, 3), np.uint8)) > 0
            v = bgr[y0:y1, x0:x1].max(axis=2)
            vals = v[sel]
            if vals.size < 16:
                continue
            thr, _ = cv2.threshold(vals.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            out[y0:y1, x0:x1][sel & (v > thr)] = 255
        return out


def make_ocr(name, accurate=True):
    """name: "trained" (the model trained for game subtitles; the standard tiny one when its file is missing), "rapid"
    (standard PP-OCRv6 tiny) or "windows"."""
    if name == "windows":
        ocr = WinOcr()
    else:
        ocr = RapidLineOcr(accurate=accurate, model=trained_model() if name == "trained" else None)
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


def box_mask(bgr, contrast=70, box_max=120):
    """Subtitles on the game's own subtitle background (a dark box behind the text, semi-transparent or solid):
    letters of any colour that are clearly brighter than the box right around them. Measured against the box, not
    against fixed brightness / colour thresholds, so a dim, washed-out or colour-cast picture (HDR, a TV's picture
    mode) is read as well and coloured speaker names are kept. Where the background around a letter is not dark (no
    box there) nothing is taken."""
    v = bgr.max(axis=2)
    # The background without the letters: an opening wider than any letter stroke takes them out.
    side = max(9, int(bgr.shape[0] * 0.045)) | 1
    background = cv2.morphologyEx(v, cv2.MORPH_OPEN, np.ones((side, side), np.uint8))
    text = (v.astype(np.int16) - background >= contrast) & (background <= box_max)
    return _letters_only((text * 255).astype(np.uint8))


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
