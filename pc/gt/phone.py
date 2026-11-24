"""GTA 6's hand-held phone, found and read by itself (no area to pick): the Turkish of the messages goes to the TV in a
panel next to the phone.

Finding the phone needs no OCR (~5 ms a look): the phone's screen is a light, upright (or a little tilted) rectangle
about two thirds of the picture high, with small dark marks lined up like text on it (window blinds or a white door
are long dark lines or nothing). Two looks in a row open it; it closes when it has not been seen for a while (a blurred
frame while scrolling or the hand shaking does not close it).

While it is open, the screen is cut out of the frame and made upright (a tilted phone too), read with the area
reader when it stopped changing (not in the middle of a scroll) and its rows are grouped into messages: the lines of
one bubble touch, two bubbles have the bubbles' padding between them. The title bar gives the chat's name. A dark
blue bubble is the player's own text (a sent message or a reply to choose): "»" in front of it on the TV.
"""
import cv2
import numpy as np

SCALE_W = 480           # px: the frame is searched at this width
WARP = (300, 600)       # the screen's picture for telling it from blinds / doors
SCREEN = (420, 840)     # the screen's picture that is read
MIN_LETTERS = 30


def order(box):
    """Corners as top-left, top-right, bottom-right, bottom-left of the upright phone."""
    s, d = box.sum(1), np.diff(box, axis=1).ravel()
    return np.float32([box[np.argmin(s)], box[np.argmin(d)], box[np.argmax(s)], box[np.argmax(d)]])


def upright(frame, corners, size):
    w, h = size
    m = cv2.getPerspectiveTransform(np.float32(corners), np.float32([[0, 0], [w, 0], [w, h], [0, h]]))
    return cv2.warpPerspective(frame, m, size, flags=cv2.INTER_CUBIC)


def letters(picture):
    """Small dark marks like letters on the light screen -> (how many, share of the dark pixels they make up)."""
    gray = cv2.cvtColor(picture, cv2.COLOR_BGR2GRAY)
    dark = (gray < 0.62 * np.percentile(gray, 70)).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    count = inside = 0
    for _, _, w, h, a in stats[1:]:
        if 5 <= h <= 34 and w <= 45 and a >= 6:
            count += 1
            inside += a
    return count, inside / max(1, int(dark.sum()))


def find_phone(frame):
    """-> (corners 4x2 in frame pixels, info) or None. Tested on recorded GTA 6 play: 91 of 101 pictures with the
    phone up found (the rest: blurred while scrolling, the home screen of icons), none of 655 without it."""
    H, W = frame.shape[:2]
    k = SCALE_W / W
    small = cv2.resize(frame, (SCALE_W, round(H * k)), interpolation=cv2.INTER_AREA)
    h, w = small.shape[:2]
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    bright = ((hsv[:, :, 2] >= 130) & (hsv[:, :, 1] <= 70)).astype(np.uint8) * 255
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in contours:
        area = cv2.contourArea(c)
        if area < 0.03 * w * h:
            continue
        (cx, cy), (rw, rh), angle = cv2.minAreaRect(c)
        long_, short = max(rw, rh), min(rw, rh)
        # upright, about 1.7-1.9 times as high as wide, at least four tenths of the picture high
        if short < 1 or not (1.45 <= long_ / short <= 2.7) or long_ < 0.42 * h or short > 0.4 * w:
            continue
        tilt = angle if rw < rh else angle - 90
        tilt = (tilt + 90) % 180 - 90
        fill = area / (rw * rh)
        if abs(tilt) > 30 or fill < 0.72:
            continue
        corners = order(cv2.boxPoints(((cx, cy), (rw, rh), angle)) / k)
        count, share = letters(upright(frame, corners, WARP))
        if count < MIN_LETTERS or share < 0.02:
            continue
        score = count * fill
        if best is None or score > best[2]:
            best = (corners, {"tilt": round(float(tilt), 1), "letters": count, "fill": round(float(fill), 2)}, score)
    return best[:2] if best else None


def signature(screen):
    """A small grey picture of the screen: tells a scroll / a new message from the hand shaking a little."""
    return cv2.resize(cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY), (24, 48), interpolation=cv2.INTER_AREA).astype(np.int16)


def changed(a, b, limit=6.0):
    return a is None or b is None or float(np.abs(a - b).mean()) > limit


def _text(row):
    return " ".join(p for p in row["pieces"] if isinstance(p, str)).strip()


def _around(lab, rect):
    """The colour right above and below a text row: its bubble's (LAB)."""
    x0, y0, x1, y1 = rect
    band = np.concatenate([lab[max(0, y0 - 3):y0, x0:x1].reshape(-1, 3), lab[y1:y1 + 3, x0:x1].reshape(-1, 3)])
    return np.median(band, axis=0) if band.size else None


def read_screen(reader, screen):
    """The upright screen -> (chat title or None, [{"text", "mine"}]) top to bottom. mine: a dark blue bubble, the
    player's own text."""
    h = screen.shape[0]
    rows = [r for r in reader.read(screen, {"filter": "any"}) if r.get("ok", True) and _text(r)]
    rows.sort(key=lambda r: r["rect"][1])
    if not rows:
        return None, []
    title = None
    first = rows[0]
    if first["rect"][1] < 0.07 * h and len(_text(first).split()) <= 6:
        title = _text(first).lstrip("<‹(|[ ").strip() or None
        top = first["rect"][3]
        # a message half under the title bar (cut letters, misread): left out
        rows = [r for r in rows[1:] if r["rect"][1] >= top - 2]
    bubbles = []
    for r in rows:
        x0, y0, x1, y1 = r["rect"]
        last = bubbles[-1] if bubbles else None
        if last is not None:
            lx0, ly0, lx1, ly1 = last["rows"][-1]["rect"]
            # The lines of one bubble touch (the found boxes even overlap); two bubbles have the bubbles' padding
            # between them: at least a third of a line (measured: -24..5 px inside, 17..63 px between, of ~40).
            if y0 - ly1 <= 0.3 * min(y1 - y0, ly1 - ly0) and min(x1, last["x1"]) > max(x0, last["x0"]):
                last["rows"].append(r)
                last["x0"], last["x1"] = min(last["x0"], x0), max(last["x1"], x1)
                continue
        bubbles.append({"rows": [r], "x0": x0, "x1": x1})
    lab = cv2.cvtColor(screen, cv2.COLOR_BGR2LAB).astype(np.float32)
    out = []
    for b in bubbles:
        colours = [c for c in (_around(lab, r["rect"]) for r in b["rows"]) if c is not None]
        c = np.median(colours, axis=0) if colours else np.array([255.0, 128.0, 128.0])
        mine = c[0] < 130 and float(np.hypot(c[1] - 128, c[2] - 128)) > 25
        # a piece of an icon read as a mark in front of the text (")Swamp Meditation Spot")
        text = " ".join(_text(r) for r in b["rows"]).lstrip(")]}|>•·-–—_~ ")
        if sum(ch.isalpha() for ch in text) >= 2:
            out.append({"text": text, "mine": bool(mine)})
    return title, out


def panel_text(title, messages, turkish):
    """What the TV panel shows: the chat's name, then every message (its Turkish) on its own line."""
    lines = [title] if title else []
    for m in messages:
        tr = (turkish.get(m["text"]) or m["text"]).strip()
        lines.append(("» " if m["mine"] else "• ") + tr)
    return "\n".join(lines)


def panel_place(corners, w, h, width=0.34):
    """Where the panel goes: on the side of the phone with more room, as high as the phone -> (x0, y0, pw, ph) in
    pixels."""
    xs, ys = corners[:, 0], corners[:, 1]
    gap = 0.015 * w
    left_room, right_room = xs.min() - gap, w - xs.max() - gap
    pw = max(0.18 * w, min(width * w, max(left_room, right_room) - 0.02 * w))
    x0 = xs.max() + gap if right_room >= left_room else max(0.01 * w, xs.min() - gap - pw)
    y0 = max(0.05 * h, float(ys.min()))
    ph = max(0.3 * h, min(0.9 * h - y0, float(ys.max() - ys.min())))
    return float(x0), float(y0), float(pw), float(ph)
