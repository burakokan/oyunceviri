"""Ready-made game translations ("packs"): known English lines are shown in Turkish without machine translation.

Pack format 2 (shared with CouchSubs / GameTranslator, so their packs work as they are):
  {"format": 2, "id", "title", "source",
   "entries":  {key: turkish},   whole subtitle lines
   "segments": {key: turkish},   single sentences of longer lines
   "english":  {key: english}}   optional (our own packs): enables fuzzy matching of OCR-damaged lines
  key = first 8 bytes of SHA-256 of canon(english), as 16 hex characters.
"""
import gzip
import hashlib
import json
import os
import re
import shutil
import threading
import unicodedata
from collections import Counter, deque
from pathlib import Path

from .config import ROOT

PACK_DIR = ROOT / "packs"
# Corrections of wrong lines in ready-made packs: packs/fixes/<pack id>.json {"English line": "Türkçesi"}.
FIX_DIR = PACK_DIR / "fixes"
_TAG = re.compile(r"<[^<>]{0,40}>")
# Sentence boundaries, not before a lowercase word ("Mr. Fisk", "...and then")
_SENTENCES = re.compile(r"(?<=[.!?…])[\"'”’)]*\s+(?=[\"'“‘(¿¡]?[A-Z0-9])")
DETECT_WINDOW = 20
DETECT_HITS = 5


def canon(text):
    """CouchSubs' line normalization: tags out, NFKC, lowercase, accents dropped, punctuation -> one space."""
    s = unicodedata.normalize("NFKC", _TAG.sub(" ", text)).lower()
    out, gap = [], False
    for ch in unicodedata.normalize("NFD", s):
        cat = unicodedata.category(ch)
        if cat in ("Mn", "Mc", "Me"):
            continue
        if cat in ("Lu", "Ll", "Lt", "Lm", "Lo", "Nd", "Nl", "No"):
            if gap and out:
                out.append(" ")
            gap = False
            out.append(ch)
        else:
            gap = True
    return "".join(out)


def key(text):
    c = canon(text)
    return hashlib.sha256(c.encode("utf-8")).hexdigest()[:16] if c else None


def sentences(text):
    return [s.strip() for s in _SENTENCES.split(text.strip()) if s.strip()]


class Pack:
    def __init__(self, path):
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        self.id = data.get("id") or path.name.split(".")[0]
        self.title = data.get("title", self.id)
        self.source = data.get("source", "")
        self.lines = dict(data.get("segments", {}))
        self.lines.update(data.get("entries", {}))
        self.english = data.get("english", {})
        self._choices = None
        fixes = FIX_DIR / f"{self.id}.json"
        if fixes.exists():
            try:
                for en, tr in json.loads(fixes.read_text(encoding="utf-8")).items():
                    k = key(en)
                    if k and tr:
                        self.lines[k] = tr
            except (OSError, ValueError, AttributeError):
                pass

    def get(self, text):
        k = key(text)
        tr = self.lines.get(k) if k else None
        # A pack translation far shorter than the English lost part of the line: a translator does it instead.
        if tr and len(text) >= 20 and len(tr) < 0.45 * len(text):
            return None
        return tr

    def fuzzy(self, text, cutoff=90):
        """Closest known English line (OCR damage), only for packs that carry English."""
        if not self.english:
            return None
        from rapidfuzz import fuzz, process
        if self._choices is None:
            self._choices = {k: canon(en) for k, en in self.english.items()}
        query = canon(text)
        if len(query) < 12:
            return None
        hit = process.extractOne(query, self._choices, scorer=fuzz.ratio, score_cutoff=cutoff)
        return self.lines.get(hit[2]) if hit else None


class Hit:
    def __init__(self, turkish, pack, how):
        self.turkish, self.pack, self.how = turkish, pack, how


# A CouchSubs install on this PC downloads its ready-made packs (and newer versions of them, e.g. GTA 6 grows as
# players play) here; they are copied into packs/ when newer. "pool-*" files are its unchecked collections.
COUCHSUBS_PACKS = Path(os.environ.get("LOCALAPPDATA", "")) / "CouchSubs" / "packs"


def sync_couchsubs():
    """Copy CouchSubs' packs that are new or newer than ours into packs/. -> names copied."""
    copied = []
    if not COUCHSUBS_PACKS.is_dir():
        return copied
    PACK_DIR.mkdir(exist_ok=True)
    for src in COUCHSUBS_PACKS.glob("*.json.gz"):
        if src.name.startswith("pool-"):
            continue
        if (PACK_DIR / "build" / src.name.split(".")[0]).exists():
            continue        # a pack we made ourselves (Paket Oluştur) is never replaced
        dst = PACK_DIR / src.name
        try:
            if dst.exists() and (dst.stat().st_mtime >= src.stat().st_mtime or dst.read_bytes() == src.read_bytes()):
                continue
            shutil.copy2(src, dst)
            copied.append(src.name)
        except OSError:
            continue
    return copied


class PackLibrary:
    """All packs in packs/, loaded in the background. lookup() never blocks on loading."""

    def __init__(self):
        self.packs = {}
        self.ready = False
        self._recent = deque(maxlen=DETECT_WINDOW)
        self.detected = None
        self.mismatch = None    # a game is chosen, but the subtitles clearly belong to this other pack
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        self.synced = sync_couchsubs()
        if PACK_DIR.exists():
            for path in sorted(PACK_DIR.glob("*.json*")):
                try:
                    pack = Pack(path)
                    self.packs[pack.id] = pack
                except (OSError, ValueError):
                    continue
        self.ready = True

    def add(self, path):
        """Load (or reload) one pack file, e.g. one the pack builder just wrote."""
        try:
            pack = Pack(path)
        except (OSError, ValueError):
            return
        # A new dict instead of changing the old one: the engine may be looping over it right now.
        self.packs = {**self.packs, pack.id: pack}

    def reset_detection(self):
        """The user picked a game (or went back to auto): start detecting from scratch."""
        self._recent.clear()
        self.detected = None
        self.mismatch = None

    def titles(self):
        return sorted(((p.id, p.title, len(p.lines), p.source) for p in list(self.packs.values())),
                      key=lambda x: x[1])

    def _scope(self, game):
        if game and game not in ("auto", "off"):
            # The chosen game first, then every other pack: a wrong choice must never cost a known line.
            first = self.packs.get(game)
            return ([first] if first else []) + [p for p in self.packs.values() if p is not first]
        if self.detected in self.packs:
            first = self.packs[self.detected]
            return [first] + [p for p in self.packs.values() if p is not first]
        return list(self.packs.values())

    def _exact(self, pack, text):
        tr = pack.get(text)
        if tr:
            return tr, "satır"
        parts = sentences(text)
        if len(parts) > 1:
            found = [pack.get(p) for p in parts]
            if all(found):
                return " ".join(found), "cümle"
        return None, None

    def lookup(self, english, game="auto"):
        """-> Hit or None. game: "auto", "off" or a pack id."""
        if game == "off" or not self.packs:
            return None
        scope = self._scope(game)
        hits = []
        for pack in scope:
            tr, how = self._exact(pack, english)
            if tr:
                hits.append(Hit(tr, pack, how))
        # Only lines unique to one pack tell which game this is ("Okay." is in every game).
        self._recent.append(hits[0].pack.id if len(hits) == 1 else None)
        counts = Counter(p for p in self._recent if p)
        best, n = counts.most_common(1)[0] if counts else (None, 0)
        if game == "auto":
            if n >= DETECT_HITS:
                self.detected = best
        else:
            self.mismatch = best if n >= DETECT_HITS and best != game and counts.get(game, 0) == 0 else None
        # Only the game being played (chosen, or detected): a short line from another game's pack is often wrong
        # here ("Figures." -> "Rakamlar.", "Oh, yeah?" -> "Aynen öyle."). Other packs only count for detection.
        target_id = game if game != "auto" else self.detected
        hit = next((h for h in hits if h.pack.id == target_id), None)
        if hit:
            return hit
        target = scope[0] if scope and target_id and scope[0].id == target_id else None
        if target:
            tr = target.fuzzy(english)
            if tr:
                return Hit(tr, target, "benzer")
        return None
