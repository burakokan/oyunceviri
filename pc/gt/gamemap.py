"""GTA 6's map: the card a place shows when the cursor is on its blip (a shop's, a garage's, a mission's description)
in Turkish, painted over the English the card's own way (its colour, its white letters, about its size).

The map is told by the pause menu's tab bar ("JASON & LUCIA  MAP  BRIEF  PROGRESS", MAP in pink): a quick colour check
first (pink in the top band, ~1 ms), then reading the bar. While the map is open, the picture is read when it has
stopped changing (the cursor stopped): the whole picture is searched for text and the card is found among it: a title
in capitals with lines of sentences under it, lined up on the same left edge. The title (the place's name) stays; the
description, a price line ("$150 - Collectibles to sell") and the tags under it ("STYLE", "SOUVENIR") are translated.
Map labels ("Key Lento", "Sunbelt Hwy"), the button hints and the money are left alone.
"""
import re

import cv2
import numpy as np

from . import paint

BAR = 0.09              # the tab bar's height (share of the picture)
MIN_SCORE = 0.8
_LOWER = re.compile(r"[a-z]")
_LETTERS = re.compile(r"[A-Za-z]")


TAB_BAND = 0.12        # the tab bar's words stand in this top share of the picture


def _pink(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return (hsv[..., 0] >= 150) & (hsv[..., 0] <= 175) & (hsv[..., 1] > 70) & (hsv[..., 2] > 150)


def pink_tab(frame):
    """Where a pink word stands in the top band (the pause menu's chosen tab) -> (x0, y0, x1, y1) or None (~1 ms)."""
    h, w = frame.shape[:2]
    x0 = int(0.2 * w)
    pink = _pink(frame[:int(TAB_BAND * h), x0:int(0.85 * w)]).astype(np.uint8)
    if int(pink.sum()) < 40:
        return None
    # the letters of one word joined into one patch
    joined = cv2.dilate(pink, np.ones((5, 15), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(joined)
    if n < 2:
        return None
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    bx, by, bw, bh = stats[k, :4]
    if bh < 0.015 * h or bw < bh or bw > 8 * bh:
        return None
    m = int(0.25 * bh)
    return max(0, x0 + bx - m), max(0, by - m), min(w, x0 + bx + bw + m), min(h, by + bh + m)


class MapReader:
    """Text search + reading for the map (the subtitle and area readers' models, a smaller search picture)."""

    def __init__(self):
        from rapidocr import ModelType, RapidOCR
        base = {"Global.log_level": "error", "EngineConfig.onnxruntime.intra_op_num_threads": 2}
        self.det = RapidOCR(params={**base, "Det.limit_side_len": 960, "Det.limit_type": "max"})
        self.rec = RapidOCR(params={**base, "Rec.model_type": ModelType.SMALL})

    def lines(self, img, offset=(0, 0), skip=lambda rect: False, min_h=10):
        """-> [{"rect": (x0, y0, x1, y1), "text"}] of the text pieces found (each a line or a part of one). skip(rect)
        and min_h leave pieces unread (reading is the slow part: ~30 ms a piece)."""
        r = self.det(img, use_det=True, use_cls=False, use_rec=False)
        h, w = img.shape[:2]
        out = []
        for q in (r.boxes if r.boxes is not None else []):
            x0, y0 = np.floor(q.min(0)).astype(int)
            x1, y1 = np.ceil(q.max(0)).astype(int)
            x0, y0, x1, y1 = max(0, x0 - 2), max(0, y0 - 2), min(w, x1 + 2), min(h, y1 + 2)
            if y1 - y0 < min_h or x1 - x0 < 1.6 * (y1 - y0):
                continue                    # too small, or square: a map icon, not a word
            if skip((x0 + offset[0], y0 + offset[1], x1 + offset[0], y1 + offset[1])):
                continue
            rr = self.rec(img[y0:y1, x0:x1], use_det=False, use_cls=False)
            if not rr.txts or rr.scores[0] < MIN_SCORE:
                continue
            text = rr.txts[0].strip()
            if len(_LETTERS.findall(text)) < 2:
                continue
            out.append({"rect": (int(x0 + offset[0]), int(y0 + offset[1]), int(x1 + offset[0]), int(y1 + offset[1])),
                        "text": text})
        return out


def is_map(reader, frame):
    """The pause menu's map is open: the pink (chosen) tab in the top band reads MAP (one word read, ~20 ms)."""
    box = pink_tab(frame)
    if box is None:
        return False
    x0, y0, x1, y1 = box
    r = reader.rec(frame[y0:y1, x0:x1], use_det=False, use_cls=False)
    return bool(r.txts) and re.sub(r"[^A-Z]", "", r.txts[0].upper()) == "MAP"


def _caps(text):
    letters = _LETTERS.findall(text)
    return len(letters) >= 2 and not _LOWER.search(text)


def _sentence(text):
    """A line of a description: a word in lower case after the first ("Nautical-themed souvenir"), or an end mark
    (not a map label like "Key Lento" or "Sunbelt Hwy": names, every word capitalised)."""
    words = text.split()
    return bool(_LOWER.search(text)) and (any(w[:1].islower() for w in words[1:])
                                          or text.rstrip().endswith((".", "!", "?", ",")))


def find_card(reader, frame):
    """The place card on the map -> {"title": rect, "blocks": [{"kind": "body" | "sub" | "tag", "text", "rows"}]} or
    None. body: the description (its lines as one text); sub: a price line; tag: a word under the description."""
    h, w = frame.shape[:2]
    top = int(BAR * h)

    def ignored(r):
        # the button hints (bottom right), the money (top right), the icon column (left)
        x0, y0, x1, y1 = r
        return (x0 > 0.8 * w and y0 > 0.6 * h) or (x0 > 0.85 * w and y1 < 0.25 * h) or x1 < 0.07 * w

    lines = reader.lines(frame[top:], (0, top), ignored, min_h=int(0.024 * h))
    lines.sort(key=lambda ln: (ln["rect"][1], ln["rect"][0]))
    # paragraphs: sentence lines on the same left edge, one under the other
    paras = []
    for ln in lines:
        if not _sentence(ln["text"]) and not ln["text"].lstrip().startswith("$"):
            continue
        x0, y0, x1, y1 = ln["rect"]
        lh = y1 - y0
        for p in paras:
            px0, _, _, py1 = p["rows"][-1]
            if (abs(px0 - x0) <= 0.6 * lh and -0.4 * lh <= y0 - py1 <= 0.8 * lh and not p["sub"]
                    and not ln["text"].lstrip().startswith("$")):
                p["rows"].append(ln["rect"])
                p["texts"].append(ln["text"])
                break
        else:
            paras.append({"rows": [ln["rect"]], "texts": [ln["text"]], "sub": ln["text"].lstrip().startswith("$")})
    for p in paras:
        x0, y0, x1, y1 = p["rows"][0]
        lh = y1 - y0
        # the title: capitals right over it (or over the price line over it), its left edge near
        p["title"] = None
        for ln in lines:
            a0, b0, a1, b1 = ln["rect"]
            if _caps(ln["text"]) and 0 <= y0 - b1 <= 2.6 * lh and abs(a0 - x0) <= 3.5 * lh and a1 > x0:
                p["title"] = ln["rect"]
    bodies = [p for p in paras if not p["sub"] and (p["title"] is not None or len(p["rows"]) >= 2)]
    if not bodies:
        return None
    body = max(bodies, key=lambda p: sum(r[2] - r[0] for r in p["rows"]))
    bx0 = min(r[0] for r in body["rows"])
    bx1 = max(r[2] for r in body["rows"])
    by1 = body["rows"][-1][3]
    lh = body["rows"][0][3] - body["rows"][0][1]
    blocks = [{"kind": "body", "text": " ".join(t.strip() for t in body["texts"]), "rows": body["rows"]}]
    for p in paras:
        if p["sub"] and abs(p["rows"][0][0] - bx0) <= 1.5 * lh and body["rows"][0][1] - p["rows"][0][3] <= 2 * lh \
                and p["rows"][0][3] <= body["rows"][0][1]:
            blocks.append({"kind": "sub", "text": p["texts"][0], "rows": p["rows"]})
    # tags: words in capitals just under the description, within the card's width
    for ln in lines:
        a0, b0, a1, b1 = ln["rect"]
        if _caps(ln["text"]) and 0 <= b0 - by1 <= 1.6 * lh and a0 >= bx0 - lh and a1 <= max(bx1, a0) + 2 * lh \
                and len(ln["text"].split()) <= 3:
            blocks.append({"kind": "tag", "text": ln["text"].strip(), "rows": [ln["rect"]]})
    return {"title": body["title"], "blocks": blocks}


def paint_card(frame, card, turkish):
    """The card's texts in Turkish over the English -> (x, y, BGRA) in frame pixels, or None. The English letters are
    taken out of the picture (filled in from the card around them: the card is see-through, the map shows through
    it) and the Turkish is written there, in the card's letters' colour; the rest of the card stays the game's own."""
    h, w = frame.shape[:2]
    rects = [r for b in card["blocks"] for r in b["rows"]]
    lh = float(np.median([r[3] - r[1] for r in rects]))
    # the picture covers the card and a margin (a longer Turkish text may grow down a little)
    cx0, cy0 = max(0, int(min(r[0] for r in rects) - 2 * lh)), max(0, int(min(r[1] for r in rects) - lh))
    cx1, cy1 = min(w, int(max(r[2] for r in rects) + 4 * lh)), min(h, int(max(r[3] for r in rects) + 3 * lh))
    base = np.zeros((cy1 - cy0, cx1 - cx0, 4), np.uint8)
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB).astype(np.float32)
    blocks = sorted(card["blocks"], key=lambda b: b["rows"][0][1])
    texts = []
    for k, b in enumerate(blocks):
        tr = (turkish.get(b["text"]) or "").strip()
        if not tr or _key(tr) == _key(b["text"]):
            continue
        rows = b["rows"]
        rect = (min(r[0] for r in rows), min(r[1] for r in rows), max(r[2] for r in rows), max(r[3] for r in rows))
        bg = paint.background(frame, rect, pad=max(3, int(0.15 * lh)))
        tight = paint.tight(frame, rect, bg)
        fg = paint.ink(frame, tight, bg)
        room = paint.room(frame, tight, bg, (cx0, cy0, cx1, cy1), lab=lab)
        pad = int(max(3, min(0.25 * lh, tight[0] - room[0], tight[1] - room[1])))
        tx0, ty0, tx1, ty1 = tight
        right_edge = False
        if b["kind"] == "tag":
            # capitals like the game's ("STİL"), as high as its; a tag on the card's right edge stays right-aligned
            tr = tr.replace("i", "İ").upper()
            right_edge = tx0 > (rect[0] + cx1) / 2 and tx0 > min(r[0] for r in rects) + 3 * lh
            width = (tx1 - room[0] - pad) if right_edge else (room[2] - pad - tx0)
            cap = ty1 - ty0
            fnt = paint.font(cap / paint.CAP_EM, "condensed")
            while fnt.getlength(tr) > max(width, tx1 - tx0) and fnt.size > 0.6 * cap / paint.CAP_EM:
                fnt = paint.font(fnt.size * 0.94, "condensed")
            lines, p = [tr], cap / paint.CAP_EM * 1.2
            asc = fnt.getbbox("H")[1]
            top = ty0 - asc - (p - sum(fnt.getmetrics())) / 2       # the capitals' tops where the English ones were
            weight = "condensed"
        else:
            if len(rows) >= 2:
                centres = [(r[1] + r[3]) / 2 for r in rows]
                pitch = (centres[-1] - centres[0]) / (len(rows) - 1)
            else:
                pitch = 1.45 * (ty1 - ty0)
            nxt = blocks[k + 1]["rows"][0][1] - 0.3 * lh if k + 1 < len(blocks) else cy1
            width = max(tx1 - tx0, room[2] - pad - tx0)
            height = max(ty1 - ty0, min(room[3], nxt) - pad - ty0)
            fnt, lines, p, fits = paint.layout(tr, width, height, pitch, "regular", 0.7)
            if not fits:
                keep = max(1, int((height + 0.35 * p) // p))
                if keep < len(lines):
                    lines = lines[:keep]
                    lines[-1] = lines[-1].rstrip(" ,.") + "…"
            text_h = len(lines) * p
            top = ty0 + (ty1 - ty0) / 2 - text_h / 2 if text_h <= (ty1 - ty0) + 0.4 * p else ty0 - 0.2 * p
            weight = "regular"
        text_w = max(fnt.getlength(line) for line in lines)
        text_x = tx1 - text_w if right_edge else tx0
        # the English letters out (a little around them, so a slightly shifted TV picture shows none of them)
        e0, e1 = max(cx0, tx0 - pad), min(cx1, tx1 + pad)
        f0, f1 = max(cy0, ty0 - pad), min(cy1, ty1 + pad)
        patch = paint.erase(frame, (e0, f0, e1, f1), bg)
        region = base[f0 - cy0:f1 - cy0, e0 - cx0:e1 - cx0]
        # laid over what is there already ("over", with straight colours: no dark seams at the faded borders)
        a = patch[..., 3:4].astype(np.float32) / 255
        r = region[..., 3:4].astype(np.float32) / 255
        out_a = a + r * (1 - a)
        colour = (patch[..., :3] * a + region[..., :3] * r * (1 - a)) / np.maximum(out_a, 1e-3)
        region[..., :3] = np.clip(colour, 0, 255).astype(np.uint8)
        region[..., 3] = (out_a[..., 0] * 255).astype(np.uint8)
        ink_ = tuple(int(v) for v in np.clip(fg[::-1], 0, 255)) + (255,)
        texts.append((text_x - cx0, top - cy0, lines, fnt.size, weight, p, ink_))
    if not texts:
        return None
    s = paint.SUPER
    rgba = cv2.cvtColor(base, cv2.COLOR_BGRA2RGBA)
    img = paint.Image.fromarray(cv2.resize(rgba, (rgba.shape[1] * s, rgba.shape[0] * s),
                                           interpolation=cv2.INTER_LINEAR))
    draw = paint.ImageDraw.Draw(img)
    for x, y, lines, size, weight, p, ink_ in texts:
        paint.draw_text(draw, x * s, y * s, lines, paint.font(size * s, weight), p * s, ink_)
    return paint.cut(cx0, cy0, paint.shrink(img))

def _key(text):
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def signature(frame):
    """A small grey picture of everything under the tab bar: the map moved or a card came / went when it changes."""
    h = frame.shape[0]
    small = cv2.resize(frame[int(BAR * h):], (96, 48), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)


def changed(a, b, limit=3.0):
    return a is None or b is None or float(np.abs(a - b).mean()) > limit
