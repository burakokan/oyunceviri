"""OCR training data, step 3: the gold test set. ~150 rows from groups that are kept out of training (every 10th group),
spread over sessions, bright / dark scenes, rows with a name; one picture per group, preferring a hard one (where the
tiny model disagrees with the label). Montages with the proposed text are made for checking by eye.
Output: <veri>\\gold_candidates.json, gold_XX.png"""
import collections
import json
import os
import random
import sys

import cv2
import numpy as np
from rapidfuzz import fuzz

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ortak import DATA  # noqa: E402
OUT = str(DATA)
labels = [json.loads(l) for l in open(OUT + r"\labels.jsonl", encoding="utf-8")]
held = [l for l in labels if l["group"] % 10 == 0]
by_group = collections.defaultdict(list)
for l in held:
    by_group[l["group"]].append(l)
random.seed(11)
picks = []
for g, members in by_group.items():
    hard = sorted(members, key=lambda m: fuzz.ratio(m["tiny"], m["label"]))
    picks.append(hard[0] if random.random() < 0.6 else random.choice(members))
random.shuffle(picks)
# spread: bright scenes and named rows are kept in proportion, at most 150
picks = sorted(picks, key=lambda m: (m["session"], m["group"]))[:: max(1, len(picks) // 150)][:150]
json.dump(picks, open(OUT + r"\gold_candidates.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
print(len(by_group), "tutulan grup,", len(picks), "aday")
font = cv2.FONT_HERSHEY_SIMPLEX
for page in range(0, len(picks), 15):
    tiles = []
    for i, m in enumerate(picks[page:page + 15]):
        img = cv2.imread(OUT + r"\rows" + "\\" + m["id"])
        scale = 40 / img.shape[0]
        img = cv2.resize(img, None, fx=scale, fy=scale)[:, :1150]
        tile = np.full((78, 1200, 3), 255, np.uint8)
        tile[:img.shape[0], 40:40 + img.shape[1]] = img
        cv2.putText(tile, f"{page + i:3d}", (0, 26), font, 0.5, (0, 0, 255), 1)
        cv2.putText(tile, m["label"][:120], (40, 66), font, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
        tiles.append(tile)
    cv2.imwrite(OUT + rf"\gold_{page // 15:02d}.png", np.vstack(tiles))
