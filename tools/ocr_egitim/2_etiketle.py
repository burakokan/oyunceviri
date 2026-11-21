"""OCR training data, step 2: labels. The same subtitle row is on screen in several pictures (1 per second, several
seconds); the small model's readings of all of them are grouped and the reading that agrees best with the others
(the medoid) becomes the label of every picture of that row. A misreading in one picture is outvoted.
Output: <veri>\\labels.jsonl (id, label, group, agreement) and the character set."""
import collections
import json
import re
import os
import sys
import unicodedata

from rapidfuzz import fuzz

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ortak import DATA  # noqa: E402
OUT = str(DATA)
rows = [json.loads(l) for l in open(OUT + r"\rows.jsonl", encoding="utf-8")]
SUBST = {"’": "'", "‘": "'", "“": '"', "”": '"', "…": "...", "—": "-", "–": "-", "´": "'", "`": "'"}
TR = set("çğıöşüÇĞİÖŞÜ")      # kept: a line with them is Turkish (PS5 menus) and is not translated


def clean(text):
    text = "".join(SUBST.get(c, c) for c in text)
    text = "".join(c if c in TR else "".join(k for k in unicodedata.normalize("NFKD", c)
                                                 if not unicodedata.combining(k)) for c in text)
    return " ".join(text.split())


def ascii_ok(text):
    return all(32 <= ord(c) < 127 or c in TR for c in text)


_NAMED = re.compile(r"^([A-Z][\w'. -]{0,24}):\s*(.*)$")


def similar(a, b):
    """Same row? With a speaker's name in front, only what follows it is compared (the name made two different short
    lines of one person look alike: "Kingfishers: Here." / "Kingfishers: Yeah.")."""
    ma, mb = _NAMED.match(a), _NAMED.match(b)
    if ma and mb:
        if fuzz.ratio(ma.group(1), mb.group(1)) < 70:
            return 0
        a, b = ma.group(2), mb.group(2)
    score = fuzz.ratio(a, b)
    if min(len(a), len(b)) < 12 and score < 90:
        return 0
    return score


def junk(text):
    """A scene fragment read as letters ("ONAC", "MOLS"): one short all-capital word."""
    words = text.split()
    return len(words) == 1 and len(text) <= 6 and text.isupper()


def seconds(clock):
    return int(clock[:2]) * 3600 + int(clock[2:4]) * 60 + int(clock[4:6]) if clock else None


# groups: per source and session; frames also by time (a row seen again within 6 s)
groups = []
open_groups = collections.defaultdict(list)       # (kind, session) -> [group]
for r in rows:
    r["text"] = clean(r["small"])
    key = (r["kind"], r["session"])
    t = seconds(r["clock"])
    best, best_score = None, 0
    for g in open_groups[key][-40:]:
        if t is not None and g["t"] is not None and t - g["t"] > 6:
            continue
        if abs(g["h"] - r["h"]) > 0.25 * g["h"]:
            continue
        score = similar(g["texts"][-1], r["text"])
        if score > best_score:
            best, best_score = g, score
    if best is not None and best_score >= 80:
        best["members"].append(r)
        best["texts"].append(r["text"])
        best["t"] = t if t is not None else best["t"]
    else:
        g = {"members": [r], "texts": [r["text"]], "t": t, "h": r["h"], "id": len(groups)}
        groups.append(g)
        open_groups[key].append(g)

out = open(OUT + r"\labels.jsonl", "w", encoding="utf-8")
chars = collections.Counter()
kept = dropped = 0
sizes = collections.Counter()
for g in groups:
    texts = [t for t in g["texts"] if ascii_ok(t)] or g["texts"]
    weights = [m["small_score"] for m in g["members"]]
    # medoid: the reading closest to all others (weighted by the small model's confidence)
    best = max(set(texts), key=lambda c: sum(w * fuzz.ratio(c, t) for t, w in zip(g["texts"], weights)))
    agreement = sum(fuzz.ratio(best, t) for t in g["texts"]) / len(g["texts"])
    sizes[min(len(g["members"]), 10)] += 1
    if not ascii_ok(best) or sum(c.isalpha() for c in best) < 4 or junk(best):
        dropped += len(g["members"])
        continue
    for m in g["members"]:
        own = fuzz.ratio(m["text"], best)
        if own < 70:
            dropped += 1
            continue
        kept += 1
        chars.update(best)
        out.write(json.dumps({"id": m["id"], "label": best, "group": g["id"], "size": len(g["members"]),
                              "agreement": round(agreement, 1), "own": round(own, 1), "kind": m["kind"],
                              "session": m["session"], "small": m["small"], "tiny": m["tiny"], "h": m["h"],
                              "bright": m["bright"]}, ensure_ascii=False) + "\n")
out.close()
charset = sorted(c for c in chars if c != " ")
json.dump(charset, open(OUT + r"\charset_seen.json", "w", encoding="utf-8"), ensure_ascii=False)
print(f"{len(rows)} satır resmi, {len(groups)} grup (farklı satır); etiketli {kept}, atılan {dropped}")
print("grup boyutları:", dict(sorted(sizes.items())))
print("görülen karakterler:", "".join(charset))
