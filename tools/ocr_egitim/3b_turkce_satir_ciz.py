"""Turkish rows for training (the recorded games hardly show any: PS5 menus, notices): Turkish lines of the game packs
drawn the way games draw subtitles (white text with a dark outline, sometimes a coloured "Name:") on real GTA 6 scenes
without subtitles, cut by the app's own row finder. Labels are the drawn text. -> rows2/syn_*.png, labels_syn.jsonl
usage (app venv): python 3b_turkce_satir_ciz.py [count]"""
import glob
import gzip
import json
import os
import random
import sys
import unicodedata

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ortak import DATA, REPO  # noqa: E402
from gt import ocr  # noqa: E402
from gt.config import DEFAULTS  # noqa: E402
from gt.engine import Engine  # noqa: E402

HERE = str(DATA)
PACKS = str(REPO / "packs")
# recorded pictures of the subtitle area with no subtitle on them (a JSON list of paths)
BACKS = os.path.join(HERE, "bos_sahneler.json")
TR = set("çğıöşüÇĞİÖŞÜ")
OK = set(chr(c) for c in range(32, 127)) | TR
FONTS = [r"C:\Windows\Fonts\seguisb.ttf", r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\bahnschrift.ttf",
         r"C:\Windows\Fonts\arial.ttf"]
NAMES = ["Jason", "Lucia", "Cal", "Brian", "Boobie", "Raul", "Dre'Quan", "Real Dimez", "Cop", "Local", "Stranger",
         "Joey", "Mandy", "Donnie"]
NAME_COLORS = [(255, 253, 165), (255, 254, 214), (255, 236, 255), (225, 255, 252), (250, 255, 255), (255, 213, 79)]
ROI = [0.25, 0.7, 0.5, 0.25]
cfg = json.loads(json.dumps(DEFAULTS))


def lines():
    out = []
    for f in glob.glob(os.path.join(PACKS, "*.json.gz")):
        d = json.load(gzip.open(f, "rt", encoding="utf-8"))
        for t in list(d.get("entries", {}).values()) + list(d.get("segments", {}).values()):
            t = unicodedata.normalize("NFC", " ".join(str(t).replace("’", "'").replace("…", "...").split()))
            if 8 <= len(t) <= 58 and any(c in TR for c in t) and all(c in OK for c in t):
                out.append(t)
    return out


def draw(bg, text, name, font, color):
    img = Image.fromarray(cv2.cvtColor(bg, cv2.COLOR_BGR2RGB)).convert("RGBA")
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    full = f"{name}: {text}" if name else text
    width = d.textlength(full, font=font)
    x, y = img.size[0] / 2 - width / 2, img.size[1] - 70
    stroke = random.choice((2, 2, 3))
    if name:
        d.text((x, y), name + ":", font=font, fill=color + (255,), stroke_width=stroke, stroke_fill=(10, 10, 10, 255))
        x += d.textlength(name + ": ", font=font)
    d.text((x, y), text, font=font, fill=(245, 245, 245, 255), stroke_width=stroke, stroke_fill=(10, 10, 10, 255))
    return cv2.cvtColor(np.array(Image.alpha_composite(img, layer).convert("RGB")), cv2.COLOR_RGB2BGR), full


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    random.seed(5)
    texts = lines()
    random.shuffle(texts)
    backs = json.load(open(BACKS))
    out = open(os.path.join(HERE, "labels_syn.jsonl"), "w", encoding="utf-8")
    made = tried = 0
    for text in texts:
        if made >= count:
            break
        tried += 1
        bg = cv2.imread(random.choice(backs))
        font = ImageFont.truetype(random.choice(FONTS), random.choice((24, 26, 27, 29, 32)))
        name = random.choice(NAMES) if random.random() < 0.5 else None
        img, full = draw(bg, text, name, font, random.choice(NAME_COLORS))
        mask = ocr.outline_mask(img, 200, 60)
        boxes = Engine.lines(cfg, img, mask, ROI)
        if len(boxes) != 1:
            continue
        y0, y1, x0, x1 = ocr.tight_box(mask, boxes[0])
        crop = img[y0:y1, x0:x1]
        made += 1
        rid = f"syn_{made:05d}.png"
        cv2.imwrite(os.path.join(HERE, "rows2", rid), crop)
        out.write(json.dumps({"id": rid, "label": full, "group": 200000 + made * 10 + 1, "agreement": 100.0,
                              "box": [int(y0), int(y1), int(x0), int(x1)], "kind": "syn"}, ensure_ascii=False) + "\n")
    out.close()
    print(f"{len(texts)} Türkçe satır adayı, {tried} denendi, {made} satır yapıldı")


if __name__ == "__main__":
    main()
