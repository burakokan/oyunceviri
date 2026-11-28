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
import re

import cv2
import numpy as np

SCALE_W = 480           # px: the frame is searched at this width
WARP = (300, 600)       # the screen's picture for telling it from blinds / doors
SCREEN = (420, 840)     # the screen's picture that is read
MIN_LETTERS = 30
MIN_MARKS = 12          # the trained finder's screen must hold this many letter-like marks (either way round)
# The trained finder's mean certainty over the screen it marked. On the training frames, clean and in every scene
# (night, sun, very dark, a car, neon, fog): phones 0.967 and more, false alarms (a car park from above, blinds, a dark
# door) 0.83 and less.
MIN_SCORE = 0.9


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


# The screen is the light part; how light depends on the scene (~155 in a dim room, ~175 in daylight). On sunlit
# grey pavement as light as the phone the two run together at the lowest level: the higher ones cut the screen out.
LIGHT_LEVELS = (130, 160, 185)
# A sunset or a lamp tints the white screen warm (saturation ~80 of 255 instead of ~20): a second, looser colour limit
# finds it there (the shape and the letters on it keep a beige wall or sand from passing).
GREY_LIMITS = (70, 100)


def lift(picture, spread=160):
    """A dark or washed-out picture (night, a very dark room, haze, glare) spread over the full range of grey, or None
    when it already uses that much of it."""
    small = cv2.resize(picture, (192, max(1, round(192 * picture.shape[0] / picture.shape[1]))),
                       interpolation=cv2.INTER_AREA)
    lo, hi = np.percentile(small, (1, 99.5))
    if hi - lo >= spread:
        return None
    k = 235 / max(hi - lo, 12)
    return cv2.LUT(picture, np.clip((np.arange(256) - lo) * k, 0, 255).astype(np.uint8))


def phone_model():
    """The trained phone finder (assets/ocr/telefon_bulucu.onnx), or None when the file is missing."""
    from .config import ASSETS
    path = ASSETS / "ocr" / "telefon_bulucu.onnx"
    return path if path.is_file() else None


class PhoneFinder:
    """GTA 6's phone found by a small network trained on recorded play and on real phones put into other scenes - in a
    dark room, a sunset's or a lamp's tint, moving, tilted, partly out of the picture, a finger over it, a dark
    screen - and on light panels full of text that are not a phone (car stats, menus). It marks the phone's screen on
    the frame at 384 x 216 (~5 ms); the screen's corners come from that mark."""

    SIZE = (384, 216)

    def __init__(self, path, threads=2):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        self.session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        self.name = self.session.get_inputs()[0].name

    def screen(self, frame):
        """-> (corners 4x2 in frame pixels, info) or None. A dark or washed-out frame (night, a dark room, haze, the
        sun on the screen) is looked at a second time spread over the full range of grey."""
        got = self._look(frame)
        if got is None:
            lifted = lift(frame)
            if lifted is not None:
                got = self._look(lifted)
                if got is not None:
                    got[1]["lifted"] = True
        return got

    def _look(self, frame):
        H, W = frame.shape[:2]
        w, h = self.SIZE
        small = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
        small = cv2.copyMakeBorder(small, 0, -(-h // 16) * 16 - h, 0, 0, cv2.BORDER_REFLECT)
        x = (small.astype(np.float32) / 255 - 0.5).transpose(2, 0, 1)[None]
        logit = self.session.run(None, {self.name: x})[0][0, 0][:h // 2, :w // 2]
        mark = (logit > 0).astype(np.uint8)
        n, lab, st, _ = cv2.connectedComponentsWithStats(mark, connectivity=8)
        if n <= 1:
            return None
        k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        gh, gw = mark.shape
        if st[k, cv2.CC_STAT_AREA] < 0.03 * gw * gh:
            return None
        blob = (lab == k).astype(np.uint8)
        contours = cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
        (cx, cy), (rw, rh), angle = cv2.minAreaRect(max(contours, key=cv2.contourArea))
        long_, short = max(rw, rh), min(rw, rh)
        tilt = angle if rw < rh else angle - 90
        tilt = (tilt + 90) % 180 - 90
        fill = float(st[k, cv2.CC_STAT_AREA]) / max(1.0, rw * rh)
        # the shape of a phone's screen held up (not a wide panel or a strip)
        if short < 4 or not (1.3 <= long_ / short <= 2.9) or long_ < 0.3 * gh or abs(tilt) > 35 or fill < 0.7:
            return None
        box = self._fine_box(logit, blob)
        if box is None:
            box = cv2.boxPoints(((cx + 0.5, cy + 0.5), (rw, rh), angle)) * np.float32([W / gw, H / gh])
        else:
            box = box * np.float32([W / gw, H / gh])
        box = order(box)
        score = float(1 / (1 + np.exp(-logit[blob > 0])).mean())
        if score < MIN_SCORE:
            return None
        # Something to read on it, dark on light or light on dark: a dark shutter, a shirt's back or a door is a dark
        # upright rectangle too. (A splash screen with only a logo is left out as well: nothing to translate there.)
        pic = upright(frame, box, WARP)
        marks = max(letters(pic)[0], letters(255 - pic)[0])
        if marks < MIN_MARKS:
            return None
        return box, {"tilt": round(float(tilt), 1), "fill": round(fill, 2), "score": round(score, 3),
                     "marks": marks, "model": True}


    @staticmethod
    def _fine_box(logit, blob, up=4):
        """The screen's rectangle finer than the mark's grid (one cell is 10 px of a 1080p frame: the corners jumped by
        that much between looks at a still phone, and the screen read as changed): the mark's edge where the network's
        answer crosses zero, from its answer enlarged 4x. -> 4 corners in grid cells, or None."""
        gh, gw = blob.shape
        fine = cv2.resize(logit, (gw * up, gh * up), interpolation=cv2.INTER_LINEAR) > 0
        near = cv2.resize(cv2.dilate(blob, np.ones((3, 3), np.uint8)), (gw * up, gh * up),
                          interpolation=cv2.INTER_NEAREST) > 0
        mask = (fine & near).astype(np.uint8)
        contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
        if not contours:
            return None
        rect = cv2.minAreaRect(max(contours, key=cv2.contourArea))
        return (cv2.boxPoints(rect) + 0.5) / up


_finder = {"model": None, "path": None}


def _model_finder():
    path = phone_model()
    if path is None:
        return None
    if _finder["path"] != path:
        _finder["model"], _finder["path"] = PhoneFinder(path), path
    return _finder["model"]


def find_phone(frame):
    """The trained finder when its file is there (whatever it says: the light-screen test below took a car's stats
    panel or a menu for the phone, and missed it in a dark room); otherwise the light-screen test."""
    finder = _model_finder()
    if finder is not None:
        return finder.screen(frame)
    return find_light_screen(frame)


def find_light_screen(frame):
    """-> (corners 4x2 in frame pixels, info) or None. Tested on recorded GTA 6 play: 91 of 101 pictures with the
    phone up found (the rest: blurred while scrolling, the home screen of icons), none of 655 without it."""
    H, W = frame.shape[:2]
    k = SCALE_W / W
    small = cv2.resize(frame, (SCALE_W, round(H * k)), interpolation=cv2.INTER_AREA)
    h, w = small.shape[:2]
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    contours = []
    for grey in GREY_LIMITS:
        for level in LIGHT_LEVELS:
            bright = ((hsv[:, :, 2] >= level) & (hsv[:, :, 1] <= grey)).astype(np.uint8) * 255
            bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
            contours += [(c, grey > GREY_LIMITS[0]) for c in
                         cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]]
    best = None
    for c, tinted in contours:
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
        # the looser colour limit takes in more of the scene: only a clean screen shape full of text passes there (a
        # grey concrete wall passed at fill 0.74 / text share 0.07; the tinted phone: 0.95 / 0.49)
        if abs(tilt) > 30 or fill < (0.85 if tinted else 0.72):
            continue
        corners = order(cv2.boxPoints(((cx, cy), (rw, rh), angle)) / k)
        count, share = letters(upright(frame, corners, WARP))
        if count < MIN_LETTERS or share < (0.15 if tinted else 0.02):
            continue
        score = count * fill
        if best is None or score > best[2]:
            best = (corners, {"tilt": round(float(tilt), 1), "letters": count, "fill": round(float(fill), 2)}, score)
    return best[:2] if best else None


def signature(screen):
    """A small grey picture of the screen's middle: tells a scroll / a new message from the hand shaking a little
    (the edges, where a shake shows the scene behind, are left out)."""
    h, w = screen.shape[:2]
    middle = screen[int(0.08 * h):int(0.92 * h), int(0.08 * w):int(0.92 * w)]
    return cv2.resize(cv2.cvtColor(middle, cv2.COLOR_BGR2GRAY), (24, 48), interpolation=cv2.INTER_AREA).astype(np.int16)


def changed(a, b, limit=6.0):
    return a is None or b is None or float(np.abs(a - b).mean()) > limit


def _text(row):
    return " ".join(p for p in row["pieces"] if isinstance(p, str)).strip()


def _around(lab, rect):
    """The colour right above and below a text row: its bubble's (LAB)."""
    x0, y0, x1, y1 = rect
    band = np.concatenate([lab[max(0, y0 - 3):y0, x0:x1].reshape(-1, 3), lab[y1:y1 + 3, x0:x1].reshape(-1, 3)])
    return np.median(band, axis=0) if band.size else None


def _header(text):
    """A chat list's heading ("Suggested", "Messages"), an icon read in front of it or not ("@Suggested")."""
    return re.sub(r"^[^a-z]+|[^a-z]+$", "", text.casefold()) in LIST_HEADERS


LIST_HEADERS = {"suggested", "messages", "contacts", "recent", "favorites", "favourites", "chats"}
_NOT_LATIN = re.compile("[^\x00-\u024f\u2013-\u201f\u2026\u20ac\u00a3$]+")


def read_screen(reader, screen):
    """The upright screen -> (chat title or None, [{"text", "mine", "sender", "rect", "bg", "note"}]) top to bottom.
    mine: a blue bubble, the player's own text (light blue: sent; dark blue: a reply to choose). rect: the message's
    text (x0, y0, x1, y1) on the upright screen; bg: its bubble's colour ("#rrggbb"); note: a short centred line with
    no bubble around it ("New message", a time)."""
    h, w = screen.shape[:2]
    # at night / in a dark room / under the sun's glare the letters stand out little: spread over the range of grey
    lifted = lift(screen)
    if lifted is not None:
        screen = lifted
    # a line cut by the screen's bottom edge is read wrong ("hunting" -> "buntina"): left out
    rows = [r for r in reader.read(screen, {"filter": "any"}) if r.get("ok", True) and _text(r)
            and r["rect"][3] < h - 2]
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
    for b in bubbles:
        colours = [c for c in (_around(lab, r["rect"]) for r in b["rows"]) if c is not None]
        b["colour"] = np.median(colours, axis=0) if colours else np.array([255.0, 128.0, 128.0])
    # The scene's light tints the whole screen (a sunset: everything warm), so a light blue bubble is told by being
    # bluer than the others on the same screen, and by its place: the player's bubbles stand on the right.
    usual_b = float(np.median([b["colour"][2] for b in bubbles])) if bubbles else 128.0
    # The chat list ("Suggested", "Messages"): every row is a contact's name over the start of the last message; the
    # name is kept as the sender, the message is translated.
    listing = _header(title or "") or any(len(b["rows"]) == 1 and _header(_text(b["rows"][0])) for b in bubbles)
    out = []
    for b in bubbles:
        c = b["colour"]
        chroma = float(np.hypot(c[1] - 128, c[2] - 128))
        right = b["x0"] >= 0.2 * w and b["x1"] >= 0.85 * w
        # dark blue (a reply to choose) or light blue (sent: "Left the Phoenix at your place"); grey / white: theirs
        mine = (c[0] < 130 and chroma > 25) or (right and c[2] - usual_b <= -6)
        rows_ = b["rows"]
        sender = None
        if not mine and len(rows_) >= 2 and (listing or _is_sender(lab, rows_[0])):
            sender, rows_ = _text(rows_[0]), rows_[1:]
        # a piece of an icon read as a mark in front of the text (")Swamp Meditation Spot")
        text = " ".join(_text(r) for r in rows_).lstrip(")]}|>•·-–—_~ ")
        # an icon read as a Chinese / Japanese sign by the general reader ("白 Standard Ryde")
        text = " ".join(_NOT_LATIN.sub(" ", text).split())
        if sum(ch.isalpha() for ch in text) >= 2:
            x0 = min(r["rect"][0] for r in b["rows"])
            x1 = max(r["rect"][2] for r in b["rows"])
            y0, y1 = b["rows"][0]["rect"][1], b["rows"][-1]["rect"][3]
            bgr = cv2.cvtColor(np.uint8([[np.clip(c, 0, 255)]]), cv2.COLOR_LAB2BGR)[0, 0]
            note = (not mine and len(b["rows"]) == 1 and len(text.split()) <= 4 and x1 - x0 < 0.6 * w
                    and abs((x0 + x1) / 2 - w / 2) < 0.07 * w)
            out.append({"text": text, "mine": bool(mine), "sender": sender, "rect": (int(x0), int(y0), int(x1), int(y1)),
                        "bg": "#%02X%02X%02X" % (int(bgr[2]), int(bgr[1]), int(bgr[0])), "note": bool(note),
                        "rows": [tuple(int(v) for v in r["rect"]) for r in rows_],
                        "sender_row": tuple(int(v) for v in b["rows"][0]["rect"]) if sender else None})
    if out and out[0]["text"][:1].islower():
        out = out[1:]       # the end of a message scrolled up under the title bar ("it")
    return title, out


def _is_sender(lab, row):
    """The sender's name on top of a group chat bubble: a short row of capitalised words in colour (green "Lucia",
    purple "Billy"); message text is dark grey."""
    words = _text(row).split()
    if not 1 <= len(words) <= 3 or not all(w[:1].isupper() for w in words) or words[-1][-1:] in ".!?,":
        return False
    x0, y0, x1, y1 = row["rect"]
    px = lab[y0:y1, x0:x1].reshape(-1, 3)
    if len(px) < 20:
        return False
    ink = px[px[:, 0] <= np.percentile(px[:, 0], 10)]        # the letters: the darkest tenth
    a, b = np.median(ink[:, 1]) - 128, np.median(ink[:, 2]) - 128
    return float(np.hypot(a, b)) > 12          # names 18-28, dark grey message text 2-4


def panel_text(title, messages, turkish):
    """What the TV panel shows: the chat's name, then every message (its Turkish) on its own line, the sender's name
    in front in a group chat."""
    lines = [title] if title else []
    for m in messages:
        tr = (turkish.get(m["text"]) or m["text"]).strip()
        name = f"{m['sender']}: " if m.get("sender") else ""
        lines.append(("» " if m["mine"] else "• ") + name + tr)
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


# The TV's chat bubbles: the phone's own look, not the stream's dim greys (a light phone screen comes through grey).
BUBBLE_THEIRS = ("#EEF0F3", "#1B1D21")      # (background, letters)
BUBBLE_SENT = ("#CFE2FA", "#0D3B85")        # the player's sent message (light blue)
BUBBLE_REPLY = ("#1F4E9E", "#FFFFFF")       # a reply to choose (dark blue)


def _screen_to_frame(corners):
    sw, sh = SCREEN
    return cv2.getPerspectiveTransform(np.float32([[0, 0], [sw, 0], [sw, sh], [0, sh]]), np.float32(corners))


def bubble_boxes(title, messages, turkish, corners, w, h, look):
    """The phone shown on the TV as chat bubbles beside it (TV "regions" boxes, coordinates as fractions of the
    picture): every message's Turkish at the height of its message on the phone, theirs light, the player's blue and
    moved toward the phone side, short centred lines ("New message") and the chat's name as dark labels. A bubble may
    use the room down to the next one: a longer Turkish text gets smaller letters, it never covers the next bubble."""
    x0, _, pw, _ = panel_place(corners, w, h)
    scale = max(0.5, min(2.0, float(look.get("size", 100)) / 100))
    line = 0.034 * h * scale
    gap = 0.3 * line
    alpha = max(0.85, max(0, min(100, int(look.get("opacity", 90)))) / 100)
    label = (look.get("bg", "#10151C"), look.get("fg", "#FFFFFF"))
    to_frame = _screen_to_frame(corners)
    items = []
    top = max(0.04 * h, float(corners[:, 1].min()))
    if title:
        items.append({"kind": "label", "text": title, "y": top})
    for m in messages:
        x_a, y_a, x_b, _ = m["rect"]
        y = float(cv2.perspectiveTransform(np.float32([[[(x_a + x_b) / 2, y_a]]]), to_frame)[0, 0, 1]) - 0.2 * line
        tr = (turkish.get(m["text"]) or m["text"]).strip()
        if m.get("sender"):
            tr = f"{m['sender']}: {tr}"
        if m.get("note"):
            kind = "label"
        elif m["mine"]:
            dark = int(m.get("bg", "#FFFFFF")[1:3], 16) + int(m.get("bg", "#FFFFFF")[3:5], 16) < 200
            kind = "reply" if dark else "sent"
        else:
            kind = "theirs"
        items.append({"kind": kind, "text": tr, "y": y})
    # top to bottom, a line apart at least (the letters on the TV can be bigger than on the phone)
    prev = None
    for it in items:
        if prev is not None:
            it["y"] = max(it["y"], prev + line + gap)
        prev = it["y"]
    bottom = max(float(corners[:, 1].max()), top + 4 * line)
    boxes = []
    for i, it in enumerate(items):
        y = it["y"]
        if y + line > 0.97 * h:
            break
        nxt = items[i + 1]["y"] if i + 1 < len(items) else min(0.97 * h, max(bottom, y + 4 * line))
        room = max(line, nxt - y - gap)
        if it["kind"] == "label":
            bg, fg = label
            bx, bw, mw, align = x0 + pw / 2 - line / 2, line, pw, "center"
        elif it["kind"] == "theirs":
            (bg, fg), bx, bw, mw, align = BUBBLE_THEIRS, x0, line, 0.82 * pw, "left"
        else:
            bg, fg = BUBBLE_SENT if it["kind"] == "sent" else BUBBLE_REPLY
            bx, bw, mw, align = x0 + 0.18 * pw, line, 0.82 * pw, "left"
        boxes.append({"id": f"gta_phone_{i}", "x": bx / w, "y": y / h, "w": bw / w, "h": line / h, "mw": mw / w,
                      "mh": room / h, "lines": 1, "tr": it["text"], "icons": {}, "fg": fg, "bg": bg, "alpha": alpha,
                      "scale": 1.0, "shadow": False, "align": align})
    return boxes


# ---- the Turkish on the phone itself ----
# Every message's Turkish is painted over its English on the upright screen, in the bubble's own colour and letters
# (gt/paint.py), and that picture is bent back onto the phone: on the TV the phone looks like the game's, in Turkish.

MAX_BUBBLE = 0.8        # a message bubble is at most this share of the screen wide


def _plain(img, rect):
    """The background colour inside a text's box (BGR floats): what most of its pixels are."""
    x0, y0, x1, y1 = rect
    px = img[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
    if len(px) == 0:
        return np.array([240.0, 240.0, 240.0])
    lum = px.mean(axis=1)
    keep = px[np.abs(lum - np.median(lum)) <= 18]
    return np.median(keep if len(keep) else px, axis=0)


def _same(a, b):
    """The Turkish is the English (letters and digits alike, case and marks aside)."""
    def key(t):
        return "".join(ch for ch in t.casefold() if ch.isalnum())
    return key(a) == key(b)


def _union(rects, w, h):
    return (max(0, min(r[0] for r in rects)), max(0, min(r[1] for r in rects)),
            min(w, max(r[2] for r in rects)), min(h, max(r[3] for r in rects)))


def _pitch(messages, tight_h):
    """The distance between two lines of a message (px on the upright screen): from the messages of two lines or
    more, else from a line's letters."""
    steps = []
    for m in messages:
        rows = m.get("rows") or []
        if len(rows) >= 2:
            centres = [(r[1] + r[3]) / 2 for r in rows]
            steps.append((centres[-1] - centres[0]) / (len(rows) - 1))
    if steps:
        return float(np.median(steps))
    return 1.3 * float(np.median(tight_h)) if tight_h else 30.0


def cover_layer(screen, messages, turkish, title_bottom=0):
    """The upright screen's messages in Turkish -> (BGRA picture as big as the screen, transparent where nothing is
    painted, [patch rects for the log]). Each message: its bubble's colour over its English, its Turkish in its
    letters' colour and size; a longer text gets smaller letters, then the patch grows down over the gap below, never
    over the next message."""
    from . import paint

    h, w = screen.shape[:2]
    lifted = lift(screen)
    look = lifted if lifted is not None else screen
    items = []
    for m in messages:
        tr = (turkish.get(m["text"]) or "").strip()
        if not tr or _same(tr, m["text"]):
            continue                        # a name ("'72 Tulip"): the game's own text stays
        rows = m.get("rows") or [m["rect"]]
        rect = _union(rows, w, h)
        ceiling = 0
        if m.get("sender_row"):
            # the sender's name over the message (its row's box may reach into the message's): left as it is
            name = m["sender_row"]
            ceiling = paint.tight(look, name, _plain(look, name))[3] + 2
            rect = (rect[0], max(rect[1], ceiling), rect[2], rect[3])
        if rect[2] - rect[0] < 4 or rect[3] - rect[1] < 4:
            continue
        bg_look = _plain(look, rect)
        tight = paint.tight(look, rect, bg_look)
        items.append({"m": m, "rect": rect, "tight": tight, "bg_look": bg_look, "rows": len(rows), "ceiling": ceiling})
    if not items:
        return None, []
    pitch = _pitch([i["m"] for i in items], [i["tight"][3] - i["tight"][1] for i in items if i["rows"] == 1])
    lab = cv2.cvtColor(look, cv2.COLOR_BGR2LAB).astype(np.float32)
    img, draw = paint.canvas(w, h)
    s = paint.SUPER
    patches = []
    for k, it in enumerate(items):
        m, (tx0, ty0, tx1, ty1) = it["m"], it["tight"]
        bg = _plain(screen, it["rect"])
        fg = paint.ink(screen, it["tight"], bg)
        room = paint.room(look, it["tight"], it["bg_look"], (0, title_bottom, w, h), lab=lab)
        pad = int(max(2, min(0.3 * pitch, tx0 - room[0], ty0 - room[1])))
        right = min(room[2] - pad, tx0 + MAX_BUBBLE * w - 2 * pad, w - pad)
        width = max(tx1 - tx0, right - tx0)
        note = bool(m.get("note"))
        # a short line in a card ("Map Pin Unavailable") stays one line: smaller letters, it never grows out of its card
        height = ty1 - ty0 if note else max(ty1 - ty0, room[3] - pad - ty0)
        nxt = items[k + 1]["tight"][1] - 0.6 * pitch if k + 1 < len(items) else h - pad
        weight = "semibold" if m.get("note") else "regular"
        tr = (turkish.get(m["text"]) or m["text"]).strip()
        fnt, lines, p, fits = paint.layout(tr, width, height, pitch, weight, 0.6 if note else paint.MIN_SHARE)
        if not fits and not note:
            fnt, lines, p, fits = paint.layout(tr, width, max(height, nxt - ty0 - pad), pitch, weight)
            if not fits:
                keep = max(1, int((nxt - ty0 - pad) // p))
                if keep < len(lines):
                    lines = lines[:keep]
                    lines[-1] = lines[-1].rstrip(" ,.") + "…"
        text_w = max(fnt.getlength(line) for line in lines)
        text_h = len(lines) * p
        # the Turkish lines centred on the English ones when they take less room, from the same top when more
        top = ty0 + (ty1 - ty0) / 2 - text_h / 2 if text_h <= (ty1 - ty0) + 0.4 * p else ty0 - 0.2 * p
        x0, y0 = tx0 - pad, min(ty0, top) - pad
        x1 = max(tx1, tx0 + text_w) + pad
        y1 = max(ty1, top + text_h) + pad
        if m.get("note"):
            mid = (tx0 + tx1) / 2
            x0, x1 = min(x0, mid - text_w / 2 - pad), max(x1, mid + text_w / 2 + pad)
        # inside the bubble / card (its plain colour's reach), unless the Turkish needs more room
        # not above the message's own first line: the sender's name over it stays
        x0, y0 = max(x0, room[0] + 1, 0), max(y0, room[1] + 1, it["rect"][1] - 2, it["ceiling"], title_bottom)
        x1 = min(x1, w) if tx0 + text_w > room[2] - 1 else min(x1, room[2] - 1)
        y1 = min(y1, h) if top + text_h > room[3] - 1 else min(y1, room[3] - 1)
        fill = tuple(int(v) for v in np.clip(bg[::-1], 0, 255)) + (255,)
        draw.rounded_rectangle([x0 * s, y0 * s, x1 * s, y1 * s], radius=min(pad, 0.25 * pitch) * s, fill=fill)
        ink_ = tuple(int(v) for v in np.clip(fg[::-1], 0, 255)) + (255,)
        if m.get("note"):
            paint.draw_text(draw, (x0 + pad) * s, top * s, lines, paint.font(fnt.size * s, weight), p * s, ink_, "center",
                            (x1 - x0 - 2 * pad) * s)
        else:
            paint.draw_text(draw, tx0 * s, top * s, lines, paint.font(fnt.size * s, weight), p * s, ink_)
        patches.append([int(x0), int(y0), int(x1), int(y1)])
    return paint.shrink(img), patches

