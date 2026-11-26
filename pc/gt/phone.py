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


# The screen is the light part; how light depends on the scene (~155 in a dim room, ~175 in daylight). On sunlit
# grey pavement as light as the phone the two run together at the lowest level: the higher ones cut the screen out.
LIGHT_LEVELS = (130, 160, 185)
# A sunset or a lamp tints the white screen warm (saturation ~80 of 255 instead of ~20): a second, looser colour limit
# finds it there (the shape and the letters on it keep a beige wall or sand from passing).
GREY_LIMITS = (70, 100)


def find_phone(frame):
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


def read_screen(reader, screen):
    """The upright screen -> (chat title or None, [{"text", "mine", "sender", "rect", "bg", "note"}]) top to bottom.
    mine: a blue bubble, the player's own text (light blue: sent; dark blue: a reply to choose). rect: the message's
    text (x0, y0, x1, y1) on the upright screen; bg: its bubble's colour ("#rrggbb"); note: a short centred line with
    no bubble around it ("New message", a time)."""
    h, w = screen.shape[:2]
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
    out = []
    for b in bubbles:
        c = b["colour"]
        chroma = float(np.hypot(c[1] - 128, c[2] - 128))
        right = b["x0"] >= 0.2 * w and b["x1"] >= 0.85 * w
        # dark blue (a reply to choose) or light blue (sent: "Left the Phoenix at your place"); grey / white: theirs
        mine = (c[0] < 130 and chroma > 25) or (right and c[2] - usual_b <= -6)
        rows_ = b["rows"]
        sender = None
        if not mine and len(rows_) >= 2 and _is_sender(lab, rows_[0]):
            sender, rows_ = _text(rows_[0]), rows_[1:]
        # a piece of an icon read as a mark in front of the text (")Swamp Meditation Spot")
        text = " ".join(_text(r) for r in rows_).lstrip(")]}|>•·-–—_~ ")
        if sum(ch.isalpha() for ch in text) >= 2:
            x0 = min(r["rect"][0] for r in b["rows"])
            x1 = max(r["rect"][2] for r in b["rows"])
            y0, y1 = b["rows"][0]["rect"][1], b["rows"][-1]["rect"][3]
            bgr = cv2.cvtColor(np.uint8([[np.clip(c, 0, 255)]]), cv2.COLOR_LAB2BGR)[0, 0]
            note = (not mine and len(b["rows"]) == 1 and len(text.split()) <= 4 and x1 - x0 < 0.6 * w
                    and abs((x0 + x1) / 2 - w / 2) < 0.07 * w)
            out.append({"text": text, "mine": bool(mine), "sender": sender, "rect": (int(x0), int(y0), int(x1), int(y1)),
                        "bg": "#%02X%02X%02X" % (int(bgr[2]), int(bgr[1]), int(bgr[0])), "note": bool(note)})
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
