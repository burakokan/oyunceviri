"""The translation pipeline: chiaki-ng window -> subtitle area -> OCR -> filters -> EN->TR -> TV."""
import queue
import re
import threading
import time
from collections import deque

import numpy as np
from rapidfuzz import fuzz

from . import filters, imgio, profanity
from .capture import WindowGrabber
from .conductor import Conductor
from .guards import RepeatGuard, StickyRows, non_speech
from .logbook import Logbook
from .ocr import (RowCache, baseline, box_mask, changed, keep_boxes, make_ocr, outline_mask, outline_ratio,
                  signature, subtitle_lines, text_lines, text_mask)
from .packs import Hit, PackLibrary
from .remoteplay import RemotePlaySource, active_roi, needs_link, uses_builtin
from .snapshots import Snapshots
from .speakers import SpeakerColors, SpeakerNames, name_tint
from .tracker import SubtitleTracker, normalize, same_line, similar
from .winutil import find_window

PREVIEW_INTERVAL = 0.2
# A sentence split over subtitle screens is joined if the next part comes within this time.
CONTINUATION_SECONDS = 8.0
# Unfinished lines that may still be completed (one per speaker in a busy scene).
OPEN_MAX = 4
# Lines shown within this time are not translated again when they stay on (or come back to) the screen.
HISTORY_SECONDS = 20.0
# Objectives / button hints stay on screen long: not shown again within this time.
HINT_SECONDS = 120.0
HISTORY_MAX = 60
# The subtitle area is read this much wider on both sides (fraction of the screen width).
ROI_MARGIN = 0.06
HEARTBEAT_SECONDS = 15.0
# A short line (up to this many words) of the same speaker is overwritten by their next line within this time.
REPLACE_WORDS = 3
REPLACE_SECONDS = 3.0
# A line shown without a name gets its name if the same line is read with one within this time.
RENAME_SECONDS = 6.0
# Two subtitles one under the other are further apart than the rows of one: more than this part of the screen height
# (GTA 6 at 1080p: 48 px within one, 57 between two), or this much more than the rows of one seen so far.
SUBTITLE_PITCH = 0.0485
SUBTITLE_GAP = 1.09
REREAD_SECONDS = 1.0
FRAME_EVERY = 1.0
FRAME_LIMIT = 3600
# Joined sentences longer than this are not joined further.
MAX_JOIN = 260
_ASIDE = re.compile(r"^\(.*\)$", re.S)
# "..." / "…" at the end: the sentence goes on on the next screen; ".." too (the third dot of a cut-off row)
_ELLIPSIS = re.compile(r"\s*(\.{2,}|…)\s*$")
_SENTENCE_END = re.compile(r"[.!?]['\"”’)]*$")
_TURKISH = re.compile(r"[çğışöüÇĞİŞÖÜ]")
_LEADING_DASH = re.compile(r"^\s*[-–—]\s+|(?<=[.!?])\s+[-–—]\s+")
# Speech cut off by someone else ("I promise I got-"): over, nothing follows on the next screen.
_CUT_OFF = re.compile(r"\w[-–—]['\"”’)]*$")
# Only names ("Lucia Caminos.", "Jason!"): the same in Turkish, still shown.
_NAME_ONLY = re.compile(r"^(?:[A-Z][\w'’.\-]*[\s,]*){1,4}[.!?]*$")
# A fragment ending in one of these words always continues on the next screen.
_CONNECTORS = {
    "a", "an", "the", "of", "and", "or", "but", "nor", "to", "in", "on", "at", "for", "with", "from", "into",
    "onto", "about", "by", "than", "as", "if", "when", "while", "because", "so", "that", "this", "these", "those",
    "your", "my", "his", "her", "their", "our", "its", "be", "is", "are", "was", "were", "will", "would", "could",
    "should", "can", "have", "has", "had", "not", "no", "very", "some", "any", "every", "all", "just", "going",
}


_TRAILING_ASIDE = re.compile(r"\s*\([^()]*\)\s*$")


def unfinished(english):
    """The line does not end a sentence (or ends in '…'): its rest will come on the next screen.
    A trailing "(aside)" does not end the sentence it interrupts."""
    english = _TRAILING_ASIDE.sub("", english).strip() or english.strip()
    return bool(_ELLIPSIS.search(english)) or not _SENTENCE_END.search(english)


def cut_off(english):
    """Speech broken off ("I promise I got-"): complete as it is."""
    return bool(_CUT_OFF.search(english.strip()))


def continues(first, second):
    """`second` (the next screen) completes the sentence `first` started.

    A comma / connector word at the end, or a next part starting in lowercase ("…" + "…or is there"). A trailing "…"
    alone is no sign (GTA ends lines that trail off with it, "Ugh, jackass..."), nor is a dash (speech cut off)."""
    if not unfinished(first) or not second:
        return False
    if second[:1].islower() or second.lstrip().startswith(("...", "…")):
        return True
    if _ELLIPSIS.search(first) or cut_off(first):
        return False
    if first.rstrip().endswith((",", ";")):
        return True
    words = first.split()
    return bool(words) and words[-1].lower().strip("\"'’”") in _CONNECTORS


def rereads(first, second):
    """`second` is the line `first` again: revealed further ("…you're-" -> "…you're- you're the only one…") or read
    better ("Tourist You're a jokel" -> "You're a joke!")."""
    a, b = normalize(first), normalize(second)
    if not a or not b or len(b) < 0.5 * len(a):
        return False
    return b.startswith(a) or same_line(a, b) or (len(a) >= 8 and fuzz.partial_ratio(a, b) >= 90)


_PRONOUN_I = re.compile(r"I\b|I['’]")


def rest_of(old, new):
    """The words `new` adds after `old` when the game revealed the line further ("I'd like to make sure we're all
    hunky dory" -> "… hunky dory after whatever you boys did the other day.") -> "after whatever…", or None when
    `new` is only `old` read again (a better reading)."""
    old_words, new_words = old.split(), new.split()
    target = normalize(old.rstrip(".…-–— "))
    if not target:
        return None
    tries = [(fuzz.ratio(normalize(" ".join(new_words[:k])), target), k)
             for k in range(max(1, len(old_words) - 2), min(len(new_words) - 1, len(old_words) + 2) + 1)]
    score, k = max(tries, default=(0, 0))       # the best match, not the first close one ("…all hunky" ~ "…dory")
    if score < 90:
        return None
    rest = " ".join(new_words[k:])
    return rest if len(normalize(rest)) >= 2 else None


def lower_start(turkish):
    """A Turkish part that goes on mid-sentence starts in lowercase (Turkish I -> ı)."""
    return ({"I": "ı", "İ": "i"}.get(turkish[:1], turkish[:1].lower()) + turkish[1:]) if turkish else turkish


def remainder(shown, full):
    """What the full sentence's translation adds after the part already on the TV, when it starts with it word for
    word ("Her şeyin yolunda olduğundan emin olmak istiyorum" + "geçen gün yaptıklarınızdan sonra, çocuklar.");
    None when it is worded differently."""
    a, b = shown.split(), full.split()
    if len(b) <= len(a):
        return None
    key = lambda w: normalize(w)    # noqa: E731 - small local comparison helper
    if [key(w) for w in a] != [key(w) for w in b[:len(a)]]:
        return None
    return " ".join(b[len(a):])


def join_parts(english_parts, turkish_parts):
    """The pack's translations of a sentence's screens, joined as one sentence: a part going on mid-sentence starts
    in lowercase ("Yarın silahçıya gideceğim, her iki durumda…"), unless its English starts with a name."""
    out = []
    for en, tr in zip(english_parts, turkish_parts):
        en, tr = en.strip(), tr.strip()
        if out and tr and out[-1][-1:] not in ".!?…" and (en[:1].islower() or _PRONOUN_I.match(en)):
            tr = {"I": "ı", "İ": "i"}.get(tr[0], tr[0].lower()) + tr[1:]
        out.append(tr)
    return " ".join(out)


_WORD = re.compile(r"[A-Za-z][A-Za-z'’]+")
_JUNK = re.compile(r"[^\w\s.,!?'’:;\-…\"()]")


def reading_score(text):
    """How good a reading of the subtitle area looks: letters in real words, a bonus for a speaker's name, minus
    stray symbols (a reading of the scene behind the text)."""
    score = sum(len(w) for w in _WORD.findall(text)) - 3 * len(_JUNK.findall(text))
    rows = [r for r in text.split("\n") if r.strip()]
    if rows and filters.split_speaker(rows[0])[0]:
        score += 15
    return score


def read_on_box(cfg, crops, roi, ocr):
    """Reading on the game's subtitle background (box mode) -> (total score, clearest reading)."""
    total, sample = 0, ""
    for crop in crops:
        mask = box_mask(crop)
        boxes = Engine.lines(cfg, crop, mask, roi)
        text = filters.clean(ocr.read(crop, mask, boxes=boxes), cfg["filters"]) if boxes else ""
        total += reading_score(text)
        if reading_score(text) > reading_score(sample):
            sample = text
    return total, sample


def calibrate(cfg, crops, roi, ocr):
    """The brightness / colour thresholds that read the subtitles on screen best ("Otomatik ayarla"): every pair
    on a grid is tried on the given pictures of the subtitle area (each PS5 picture differs: HDR, the game's
    subtitle background, a colour cast) -> (v_min, s_max, best reading, score, box mode).
    Box mode (reading against the game's subtitle background) is chosen when it reads clearly better than the
    best pair: with the box on and a dim or colour-cast picture; without the box it reads worse and stays off."""
    best = None
    for v_min in (120, 140, 160, 180, 200, 220, 240):
        for s_max in (15, 30, 60, 100, 150, 220):
            trial = dict(cfg, text_v_min=v_min)
            total, sample = 0, ""
            for crop in crops:
                text = ""
                for make in (outline_mask, text_mask):
                    mask = make(crop, v_min, s_max)
                    boxes = Engine.lines(trial, crop, mask, roi)
                    if boxes:
                        text = filters.clean(ocr.read(crop, mask, boxes=boxes), cfg["filters"])
                        if text:
                            break
                total += reading_score(text)
                if reading_score(text) > reading_score(sample):
                    sample = text           # the clearest reading is shown to the user
            # ties go to the pair nearest the defaults (200 / 60)
            key = (total, -abs(v_min - 200) / 20 - abs(s_max - 60) / 40)
            if (v_min, s_max) == (200, 60):
                default = (key, v_min, s_max, sample)
            if best is None or key > best[0]:
                best = (key, v_min, s_max, sample)
    # The defaults read well in most scenes: another pair is kept only when it reads clearly better here (a pair
    # that wins in one scene by a letter or two can lose in the next one).
    if best[0][0] < default[0][0] * 1.1 + 5:
        best = default
    box_total, box_sample = read_on_box(cfg, crops, roi, ocr)
    # Equal readings keep what the user chose (with the box on, both read a normal picture equally well).
    if box_total > best[0][0] * 1.05 + 5 or (cfg.get("text_box") and box_total >= best[0][0] * 0.97):
        return best[1], best[2], box_sample, box_total, True
    return best[1], best[2], best[3], best[0][0], False


def punch(mask, holes):
    """The mask with the given rectangles [(y0, y1, x0, x1)] emptied."""
    for y0, y1, x0, x1 in holes:
        mask[y0:y1, x0:x1] = 0
    return mask


def compatible(speaker_a, speaker_b):
    return not (speaker_a and speaker_b and speaker_a != speaker_b)


def screen_center(roi):
    """Horizontal screen center as a fraction of the subtitle-area width."""
    x, _, w, _ = roi
    return min(max((0.5 - x) / w, 0.0), 1.0) if w else 0.5


class Engine:
    """Runs on a background thread and reports through callbacks:

    on_status(state, text)  state: "stopped" | "loading" | "waiting" | "running" | "error"
    on_line(dict)           a new subtitle line with timings
    on_clear()              the subtitle disappeared
    on_preview(crop, mask)  what OCR currently sees, a few times per second
    """

    def __init__(self, server, on_status, on_line, on_clear, on_preview, rp=None):
        self.server = server
        self.rp = rp  # built-in Remote Play (remoteplay.RemotePlay), shared with the preview
        self.packs = PackLibrary()
        self.conductor = Conductor(self.machine_translate)
        self.last_source = ""
        self.last_candidates = None
        self.on_status = on_status
        self.on_line = on_line
        self.on_clear = on_clear
        self.on_preview = on_preview
        self.cfg = None
        self.log = None
        self._thread = None
        self._stop = threading.Event()
        self._translator = None
        self._translator_key = None
        self._ocr = None
        self._ocr_key = None
        self._lock = threading.Lock()
        self._last = None      # the line shown last
        # Unfinished lines already on the TV: when the next screen completes one (or it is read again, longer or
        # better), the TV writes the whole sentence over that row instead of adding a row.
        self._opens = deque(maxlen=OPEN_MAX)
        self._ended = deque(maxlen=20)  # whether recent lines ended with punctuation
        self.colors = SpeakerColors()
        # The names read this session (misread / cut-off names are fixed with them) and whether the game names the
        # speaker on every line (then a line without a name is not given the previous speaker's name).
        self.names = SpeakerNames()
        self._named = deque(maxlen=60)
        self._pitches = deque(maxlen=40)     # spacing of the rows of one subtitle (pixels)
        # Lines shown without a name: when the name is read a moment later (it was cut or faded in), the TV writes
        # the line again over its row, with the name and its colour.
        self._unnamed = deque(maxlen=6)
        self._sticky = StickyRows()     # objectives / notices that stay while people talk
        # Genel → "Diyalog görüntülerini topla": pictures of the dialogue for tuning (off until asked for).
        self.snaps = Snapshots()
        self._last_msg = None           # (time, message) of the last line the TV got
        self.repeats = RepeatGuard()    # signs / billboards read again and again
        self._cleared = True  # the screen was empty since the previous line
        self._history = []     # (line, time, hint) shown recently, so lines left on screen are not re-translated
        self._last_clear = 0.0
        self._last_sent = None   # the line the TV shows last (translation thread)
        self._sent_tr = {}       # line id -> the Turkish sent for it (a growing sentence adds its rest under it)
        # Translation runs on its own thread, in reading order, so the screen is read on meanwhile.
        self._jobs = queue.Queue()
        threading.Thread(target=self._translation_worker, daemon=True).start()
        self.line_id = 0
        self._builtin = False  # built-in Remote Play is used (decided on Start)

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, cfg):
        if self.running:
            return
        self.cfg = cfg
        self.names = SpeakerNames()         # a new session may be another game
        self._named.clear()
        self._pitches.clear()
        self._unnamed.clear()
        self.conductor.warm(cfg)            # open the online connections / start Gemma before the first line
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.conductor.stop()
        self.colors.flush()         # the people's name colours seen this time, kept for good

    # ---- models (also used by the UI for test translations) ----

    def translator(self, cfg):
        from .translate import LocalTranslator
        key = tuple(sorted(cfg["translator"].items()))
        with self._lock:
            if self._translator is None or self._translator_key != key:
                self._translator = None
                self._translator = LocalTranslator(**cfg["translator"])
                self._translator_key = key
            return self._translator

    def ocr(self, cfg):
        key = (cfg["ocr_engine"], cfg["ocr_accurate"])
        with self._lock:
            if self._ocr is None or self._ocr_key != key:
                self._ocr = make_ocr(cfg["ocr_engine"], accurate=cfg["ocr_accurate"])
                self._ocr_key = key
            return self._ocr

    def translate_text(self, english, cfg, context=None, parts=None):
        """-> (turkish, ms) with swear words and the user's corrections applied.

        A line found in a game pack (ready-made translation) is used as it is; only other lines
        go to the translation model. self.last_source tells which one was used.
        parts: the screens a split sentence was joined from; when the pack knows every screen (it knows them one by
        one, not joined), their translations are joined instead of asking a translator (that took 1-2 s).
        """
        t0 = time.perf_counter()
        hit = self.pack_hit(english, cfg)
        if not hit and parts and len(parts) > 1:
            found = [self.pack_hit(p, cfg) for p in parts]
            if all(found):
                hit = Hit(join_parts(parts, [h.turkish for h in found]), found[0].pack, "parçalar")
        if hit:
            self.last_source = f"Paket · {hit.pack.title}"
            self.last_candidates = None
            return filters.correct(hit.turkish, cfg["corrections"]), (time.perf_counter() - t0) * 1000
        if context is None:
            context = self._context(english, cfg)
        turkish, used = self.conductor.translate(english, cfg, context)
        self.last_source = used
        self.last_candidates = self.conductor.last["candidates"]
        return self.polish(english, turkish, cfg), (time.perf_counter() - t0) * 1000

    def pack_hit(self, english, cfg):
        """The chosen / detected game pack's translation of the line (packs.Hit) or None."""
        packs = cfg.get("packs", {})
        game = packs.get("game", "auto")
        # A game typed by hand (not in the list, e.g. "GTA 6") has no pack: none of the packs is used.
        if game == "off" or (game == "auto" and packs.get("custom_title", "").strip()):
            return None
        return self.packs.lookup(english, game)

    @staticmethod
    def polish(english, turkish, cfg):
        """The same finishing touches for every translator: no dialogue dash, real swear words, corrections."""
        if not english.lstrip().startswith(("-", "–", "—")):
            turkish = _LEADING_DASH.sub(lambda m: "" if m.start() == 0 else " ", turkish)
        if cfg["uncensored"]:
            turkish = profanity.uncensor(english, turkish)
        return filters.correct(turkish, cfg["corrections"])

    def game_title(self, cfg):
        """The game being played, for the translators: the chosen or detected pack, else the name the user typed
        (a game without a pack, e.g. "GTA 6")."""
        packs = cfg.get("packs", {})
        game = packs.get("game", "auto")
        pack = self.packs.packs.get(self.packs.detected if game in ("auto", "off") else game)
        if pack and game != "off":
            return pack.title
        return packs.get("custom_title", "").strip()

    def _context(self, english, cfg, completes=None):
        """What the online translators get besides the line: the game and the line before (same scene).
        completes: the unfinished line this one completes (it is part of this line, not the line before)."""
        parts = ["Video game dialogue between characters, spoken informally (\"sen\", not \"siz\")."]
        title = self.game_title(cfg)
        if title:
            parts.append(f"Game: {title}.")
        last = self._last
        if (last and time.perf_counter() - last["time"] < CONTINUATION_SECONDS and last["english"] != english
                and not (completes and last["english"] == completes)):
            who = f"{last['speaker']}: " if last.get("speaker") else ""
            parts.append(f"Previous line: {who}{last['english']}")
        return " ".join(parts)

    def machine_translate(self, english, cfg):
        """The local model's translation, with the dialogue-dash and swear-word fixes (no packs)."""
        turkish = self.translator(cfg).translate(english)
        if not english.lstrip().startswith(("-", "–", "—")):
            # The model learned from film subtitles and often starts a line with a dialogue dash.
            turkish = _LEADING_DASH.sub(lambda m: "" if m.start() == 0 else " ", turkish)
        if cfg["uncensored"]:
            turkish = profanity.uncensor(english, turkish)
        return turkish

    def translate_line(self, text, cfg):
        """-> (speaker, english body, turkish body, translate ms)."""
        speaker, body = filters.split_speaker(text)
        turkish, ms = self.translate_text(body, cfg)
        return speaker, body, turkish, ms

    @staticmethod
    def lines(cfg, crop, mask, roi=None):
        """Subtitle text lines in the area (edge HUD dropped when the subtitle is centered)."""
        if cfg["filters"].get("centered", True):
            return subtitle_lines(crop, mask, screen_center(roi or active_roi(cfg)), cfg["text_v_min"])
        return text_lines(mask)

    # ---- pipeline ----

    def _run(self):
        cfg = self.cfg
        try:
            self._builtin = uses_builtin(cfg) and self.rp is not None
            if not self._builtin and needs_link(cfg):
                self.on_status("error", "PS5 henüz bağlanmadı. Önce PS5 Bağlantısı sayfasından PS5'i bağla (chiaki-ng gerekmez).")
                return
            if not self.roi():
                self.on_status("error", "Önce Altyazı Alanı sayfasından altyazının çıktığı yeri seç.")
                return
            self.on_status("loading", "Modeller yükleniyor…")
            self.log = Logbook() if cfg["debug_log"] else None
            ocr = self.ocr(cfg)
            self.translator(cfg)
            if self._builtin:
                # Built-in Remote Play reconnects by itself; the source just has no frames meanwhile.
                self._watch(RemotePlaySource(self.rp, self.roi()), ocr)
            while not self._stop.is_set() and not self._builtin:
                hwnd, title = find_window(cfg["window_process"])
                if not hwnd:
                    self.on_status("waiting", "chiaki-ng penceresi bekleniyor (açık olmalı, simge durumunda olmamalı)")
                    self._stop.wait(1.0)
                    continue
                self._watch_window(hwnd, ocr)
        except Exception as e:  # noqa: BLE001 - shown to the user instead of crashing the thread
            self.on_status("error", f"Hata: {e}")
            return
        self.on_status("stopped", "Durduruldu")

    def _watch_window(self, hwnd, ocr):
        self._watch(WindowGrabber(hwnd, self.cfg["roi"]), ocr)

    def _watch(self, source, ocr):
        """Read subtitles from a frame source (window capture or built-in Remote Play) until it closes."""
        cfg = self.cfg
        self.on_status("running", "Çalışıyor — altyazılar okunuyor")
        tracker = SubtitleTracker(stable_reads=cfg["stable_reads"], partial_wait=cfg["partial_wait_ms"] / 1000)
        seq, last_sig, last_text, ocr_ms, last_preview, frame = 0, None, "", 0.0, 0.0, None
        # Outline mode: when the game's subtitles turn out to be white letters with a dark outline / shadow (GTA 6
        # and most games), the rows are found with outline_mask(), which keeps a bright, busy scene (sunlit
        # streets, foliage) from melting into the subtitle row - there text_mask() made lines come late or never.
        outlined, votes, last_frame_at, last_ocr_at = False, deque(maxlen=8), None, 0.0
        # Heartbeat in the session log (what the reader sees, also when nothing is read) and, while the debug log is
        # on, one picture of the subtitle area per second: silent stretches can be checked afterwards.
        beat = {"at": time.perf_counter(), "frames": 0, "ocr": 0, "read_rows": 0, "rows": 0, "stalls": 0,
                "longest": 0.0}
        recorder = self._frame_recorder(cfg)
        # Rows whose letters did not change keep their text: in a busy scene (driving, signs, a car's badge in the
        # area) only the changed rows are read again instead of all 7-9 on every frame.
        rows_cache = RowCache()
        self._sticky = StickyRows()
        try:
            while not self._stop.is_set():
                roi = self._read_roi()
                source.roi = roi
                seq, item = source.next(seq, timeout=0.05)
                if item is None:
                    if source.closed:
                        return
                    event = tracker.feed(time.perf_counter(), last_text)
                else:
                    t_frame, bgr = item
                    if last_frame_at is not None:
                        gap = t_frame - last_frame_at
                        beat["longest"] = max(beat["longest"], gap)
                        if gap > 0.5:
                            beat["stalls"] += 1
                            if self.log:
                                self.log.note(stall_ms=round(gap * 1000))     # no new picture (stream froze)
                    last_frame_at = t_frame
                    beat["frames"] += 1
                    if recorder:
                        recorder(bgr, t_frame)
                    boxes, kind = None, None
                    holes = self._holes(roi, bgr.shape)
                    if cfg.get("text_box"):
                        # The game's own subtitle background is on: letters are read against the box, no fixed
                        # thresholds (a dim or colour-cast picture reads too; coloured names stay).
                        mask = punch(box_mask(bgr), holes)
                        boxes, kind = self.lines(cfg, bgr, mask, roi), "box"
                    if outlined and not boxes:
                        mask = punch(outline_mask(bgr, cfg["text_v_min"], cfg["text_s_max"]), holes)
                        boxes, kind = self.lines(cfg, bgr, mask, roi), "outline"
                    if not boxes:
                        mask = punch(text_mask(bgr, cfg["text_v_min"], cfg["text_s_max"]), holes)
                        boxes, kind = self.lines(cfg, bgr, mask, roi), "white"
                    beat["rows"] = max(beat["rows"], len(boxes))
                    sig = signature(keep_boxes(mask, boxes))
                    # Read when the text changed, and at least once a second while there is text (a change too
                    # small for the signature must not hide a new line for long).
                    forced = bool(boxes) and t_frame - last_ocr_at >= REREAD_SECONDS
                    if changed(sig, last_sig) or forced:
                        last_ocr_at = t_frame
                        t0 = time.perf_counter()
                        # The once-a-second read reads every row again (also a change too small for the cache).
                        raw = ocr.read(bgr, mask, boxes=boxes, cache=rows_cache, fresh=forced)
                        beat["ocr"] += 1
                        beat["read_rows"] += rows_cache.last_read
                        before, last_text = last_text, self._unstick(filters.clean(raw, cfg["filters"]), t_frame)
                        if not outlined and last_text and last_text != before:
                            ratio = outline_ratio(bgr, mask, boxes)
                            if ratio is not None:
                                votes.append(ratio >= 0.9)
                                if len(votes) >= 3 and sum(votes) / len(votes) >= 0.8:
                                    outlined = True
                                    if self.log:
                                        self.log.note(outline_mode=True)
                        ocr_ms = (time.perf_counter() - t0) * 1000
                        frame = (bgr, mask, boxes, list(getattr(ocr, "rows", [])))
                        if self.log:
                            self.log.read(raw, last_text)
                        if self.snaps.on:
                            self.snaps.offer(t_frame, bgr, raw, last_text, boxes, kind, cfg, self._whole_picture(),
                                             self._last_msg)
                    last_sig = sig
                    event = tracker.feed(t_frame, last_text)
                    if t_frame - last_preview > PREVIEW_INTERVAL:
                        last_preview = t_frame
                        self.on_preview(bgr, mask, boxes)
                if event:
                    self._event(event, ocr_ms, frame, ocr)
                now = time.perf_counter()
                if now - beat["at"] >= HEARTBEAT_SECONDS:
                    if self.log:
                        secs = now - beat["at"]
                        self.log.note(fps=round(beat["frames"] / secs, 1), ocr_runs=beat["ocr"],
                                      rows_read=beat["read_rows"], rows=beat["rows"], stalls=beat["stalls"],
                                      longest_gap_ms=round(beat["longest"] * 1000), outline=outlined,
                                      queue=self._jobs.qsize(), text=last_text[:60])
                    beat = {"at": now, "frames": 0, "ocr": 0, "read_rows": 0, "rows": 0, "stalls": 0,
                            "longest": 0.0}
        finally:
            source.stop()

    def _whole_picture(self):
        """For a dialogue picture: the whole PS5 picture (built-in Remote Play only; a window capture has the
        subtitle area alone)."""
        if not (self._builtin and self.rp is not None):
            return None
        return lambda: self.rp.frame()[1]

    def _unstick(self, text, now):
        """The reading without rows that stay on screen while new dialogue comes (objectives, notices)."""
        if not text or not self.cfg["filters"].get("sticky_rows", True):
            return text
        text = self._sticky.filter(text, now, continues)
        if self._sticky.dropped and self.log:
            self.log.note(sticky=[r[:60] for r in self._sticky.dropped])
        return text

    def _frame_recorder(self, cfg):
        """While the debug log is on: one JPEG of the subtitle area per second in logs/frames/<session>/, the last
        FRAME_LIMIT of them (the oldest go: it used to stop after the first hour, so a mistake later in the evening had
        no picture), to find out afterwards why a line was read late, wrong or not at all."""
        if not (self.log and cfg.get("record_frames", True)):
            return None
        import cv2
        folder = self.log.dir / "frames" / self.log.session
        folder.mkdir(parents=True, exist_ok=True)
        state = {"last": 0.0}
        kept = deque()

        def record(bgr, t):
            if t - state["last"] < FRAME_EVERY:
                return
            state["last"] = t
            path = folder / (time.strftime("%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}.jpg")
            if imgio.write(path, bgr, [cv2.IMWRITE_JPEG_QUALITY, 80]):
                kept.append(path)
            while len(kept) > FRAME_LIMIT:
                try:
                    kept.popleft().unlink()
                except OSError:
                    pass

        return record

    def roi(self):
        return self.cfg.get("roi_builtin") if self._builtin else self.cfg.get("roi")

    def _holes(self, roi, shape):
        """The extra areas that are on (objective, hint box, phone) inside the subtitle area, in its pixels
        [(y0, y1, x0, x1)]: the subtitle reader leaves them to the area translator, so the objective under the
        subtitles is not read as dialogue too. The areas exist only with built-in Remote Play."""
        if not self._builtin or not roi:
            return []
        h, w = shape[:2]
        x, y, rw, rh = roi
        out = []
        for a in (self.cfg.get("regions") or {}).values():
            r = a.get("roi") if a.get("enabled") else None
            if not r or rw <= 0 or rh <= 0:
                continue
            x0, x1 = max(0, int((r[0] - x) / rw * w)), min(w, int((r[0] + r[2] - x) / rw * w))
            y0, y1 = max(0, int((r[1] - y) / rh * h)), min(h, int((r[1] + r[3] - y) / rh * h))
            if x1 > x0 and y1 > y0:
                out.append((y0, y1, x0, x1))
        return out

    def _read_roi(self):
        """The chosen subtitle area, widened a little on both sides: GTA's longest lines run past a tight area and
        lost their first letters / final full stop (then the line was held as unfinished). The centered-block finder
        still ignores HUD text at the edges."""
        roi = self.roi()
        if not roi or not self.cfg["filters"].get("centered", True):
            return roi
        x, y, w, h = roi
        x0, x1 = max(0.0, x - ROI_MARGIN), min(1.0, x + w + ROI_MARGIN)
        return [x0, y, x1 - x0, h]

    def _seen(self, chunk, now, hint=False):
        """True if this line (or a longer version of it, or a slightly different reading of it) was shown recently.
        A short line said again after the screen was empty (a new "Got it.") is not a repeat."""
        for old, t, was_hint in self._history:
            age = now - t
            if age >= (HINT_SECONDS if (hint or was_hint) else HISTORY_SECONDS):
                continue
            if not (hint or was_hint) and len(chunk) < 25 and self._last_clear > t and age > 6:
                continue
            if chunk == old or (len(chunk) >= 12 and chunk in old):
                return True
            if similar(chunk, old) and len(chunk) <= len(old) + 2:
                return True
            if len(chunk) >= 12 and fuzz.ratio(chunk, old) >= 85:
                return True
            if len(chunk) >= 20 and len(chunk) <= len(old) + 2 and fuzz.partial_ratio(chunk, old) >= 92:
                return True
        return False

    def _event(self, event, ocr_ms, frame, ocr):
        kind, text, t_first = event
        now = time.perf_counter()
        if kind == "clear":
            self._cleared = True
            self._last_clear = now
            self.server.send({"type": "clear"})
            self.on_clear()
            if self.log:
                self.log.clear()
            return
        cfg = self.cfg
        # Every row read with its box: the colour of a speaker's name is measured in its row.
        read_rows = frame[3] if frame is not None and len(frame) > 3 else []
        if cfg["ocr_accurate"] and frame is not None:
            t0 = time.perf_counter()
            bgr, mask, boxes = frame[:3]
            better = self._unstick(filters.clean(ocr.read(bgr, mask, accurate=True, boxes=boxes), cfg["filters"]), now)
            ocr_ms += (time.perf_counter() - t0) * 1000
            if better:
                text = better
                read_rows = list(getattr(ocr, "rows", [])) or read_rows
        # A menu next to the dialogue on the same screen row (GTA's garage: "the torque and top speed. Pair with
        # transmisJoey: There ya go."): the row starts at the name of someone who already spoke several times. Not
        # only in games that name everyone: badly read lines there made that test fail, and the menu text was
        # translated and shown with a second "Joey:" in the middle.
        text = "\n".join(row if filters.split_speaker(row)[0] else (self.names.find(row) or row)
                         for row in text.split("\n"))
        # Every speaker's line on its own row, in screen order (a busy scene shows several at once); lines that
        # stay on screen (or come back) are not translated again. A row the spacing shows to be another subtitle
        # starts its own line even when its name was not read.
        starts = self._subtitle_starts(text, frame)
        for rows in filters.utterance_rows(text, starts):
            language = filters.language_of(rows[0])     # "In Spanish:" -> shown as "İspanyolca:"
            speaker, first = filters.split_speaker(rows[0])
            speaker = self.names.resolve(speaker)   # "CO wiison" -> "CO Wilson", "…ress" -> "Waitress"
            rows = [first] + rows[1:]
            if len(rows) > 1:
                # Two people's unnamed lines read as one block ("You can still walk away" over "Do you know how bad
                # this will look?", shown a moment ago): rows already shown are left out, the new ones go on.
                fresh = [r for r in rows if len(normalize(r)) < 12 or not self._seen(normalize(r), now)]
                if not fresh:
                    continue
                rows = fresh
            english = " ".join(rows)
            if (cfg["filters"].get("repeat_block", True) and non_speech(english, speaker)
                    and self.repeats.blocked(normalize(english), now)):
                continue        # a sign / billboard shown 3 times in the last minutes
            hint = not speaker and filters.is_hint(english)
            line = {"speaker": speaker, "english": english, "ocr": "\n".join(rows), "t_first": t_first,
                    "since": now, "ocr_ms": ocr_ms, "crop": frame[0] if frame is not None else None, "hint": hint,
                    "lang": language,
                    "name_tint": self._game_tint(read_rows, frame[0] if frame is not None else None, speaker)}
            if hint:
                # Objectives / button hints: shown at once (they have no full stop), never joined with dialogue.
                if not self._seen(normalize(english), now, hint):
                    self._show(line)
                continue
            if speaker and self._unnamed:
                key = normalize(english)
                late = next((u for u in self._unnamed if now - u["time"] < RENAME_SECONDS
                             and fuzz.ratio(u["norm"], key) >= 90), None)
                if late:
                    # The same line again, now with its name: written over the row that had none.
                    self._unnamed.remove(late)
                    self._show(line, replaces=late)
                    continue
            op = self._open_for(speaker, now)
            if op and rereads(op["english"], english):
                # The unfinished line on the TV again: written over it when this reading is longer or now ends the
                # sentence ("…you're-" -> "…you're- you're the only one…", "You're a jokel" -> "You're a joke!").
                if (unfinished(op["english"]) and not unfinished(english)
                        or len(normalize(english)) > len(normalize(op["english"])) + 1):
                    self._show(dict(line, speaker=speaker or op["speaker"], grows=rest_of(op["english"], english)),
                               replaces=op)
                continue
            if self._seen(normalize(english), now):
                continue
            self._utterance(line, op, now)

    def _subtitle_starts(self, text, frame):
        """Rows of `text` that begin another subtitle although no name was read in front of them.

        GTA 6 writes the rows of one subtitle closer together than two subtitles one under the other: 48 against 57
        pixels from baseline to baseline at 1080p (of 723 recorded pairs 719 told apart right; the row's middle moved
        with "g" and capitals and split three of Jason's own two-row lines). Glued to the line above, such a row put
        one person's words in another's mouth (Mendez's "What we do know right now," came out as Lucia's). Only in a
        game that names every speaker: there a row without a name is the same subtitle or a name not read."""
        if frame is None or len(frame) < 4 or len(frame[3]) < 2 or frame[1] is None or not self.names_always():
            return set()
        bgr, mask, _, rows = frame[:4]
        placed = sorted((y, read.strip()) for y, read in ((baseline(mask, box), read) for box, read in rows)
                        if y is not None and read.strip())
        roi = self._read_roi()
        if len(self._pitches) >= 8:
            limit = float(np.median(self._pitches)) * SUBTITLE_GAP     # this picture's own spacing of one subtitle
        elif roi and roi[3] > 0:
            limit = SUBTITLE_PITCH * bgr.shape[0] / roi[3]
        else:
            return set()
        lines = [r.strip() for r in text.split("\n") if r.strip()]
        out = set()
        for (c1, t1), (c2, t2) in zip(placed, placed[1:]):
            if filters.split_speaker(t2)[0]:
                continue
            if t2[:1].islower():
                self._pitches.append(c2 - c1)      # goes on mid-sentence: one subtitle's spacing
                continue
            if c2 - c1 > limit:
                best = max(lines, key=lambda r: fuzz.ratio(r, t2), default=None)
                if best is not None and fuzz.ratio(best, t2) >= 80:
                    out.add(best)
        return out

    @staticmethod
    def _game_tint(read_rows, bgr, speaker):
        """The tint the game gave this speaker's name on screen now -> (hue, saturation) or None (not measured)."""
        if not speaker or bgr is None:
            return None
        want = speaker.casefold()
        for box, text in read_rows:
            name = filters.split_speaker(text)[0]
            if name and (name.casefold() == want or fuzz.ratio(name.casefold(), want) >= 75):
                return name_tint(bgr, box, text)
        return None

    def names_always(self):
        """The game writes the speaker's name in front of (nearly) every line of dialogue."""
        named = list(self._named)
        recent = named[-12:]
        if len(recent) >= 6 and sum(recent) >= 0.85 * len(recent):
            return True
        # GTA 6 names everyone, yet a few names cut off or faded in brought the last 12 lines below that now and then
        # (a quarter of the time): Lucia's nameless "I just need the number," was then given Jason's name and written
        # over his line. The game's habit shows over a longer stretch.
        return sum(named) >= 6 and sum(named) >= 0.7 * len(named)

    def _open_for(self, speaker, now):
        """The newest unfinished line on the TV this line may complete: the same speaker's (a line without a name:
        the newest one)."""
        if not self.cfg["hold_unfinished"]:
            return None
        for op in reversed(self._opens):
            if now - op["time"] >= CONTINUATION_SECONDS:
                continue
            if not speaker or not op["speaker"] or op["speaker"] == speaker:
                return op
        return None

    def _utterance(self, line, op, now):
        """A new line: completes the open (unfinished) line `op` on the TV, or goes on its own row.
        Split sentences are not held back any more: the first part is shown at once and, when the rest comes, the
        whole sentence is written over it (it used to wait 2-3.5 s for the rest)."""
        speaker, english = line["speaker"], line["english"]
        if op and bool(speaker) != bool(op["speaker"]) and self.names_always():
            # The game names everyone: a line read without a name is not glued to someone else's, and a named line
            # ("Jason: Yeah, I don't…") starts anew instead of finishing a nameless one (whose name was missed: it may
            # be anyone's; Lucia's "I just need the number," came out as Jason's).
            op = None
        if op:
            stripped = english.strip()
            if _ASIDE.match(stripped):
                # "(is that the right term?)" in the middle of a sentence: kept inside the sentence.
                self._show(dict(line, english=f'{op["english"]} {stripped}', joined=True, grows=stripped,
                                speaker=op["speaker"] or speaker), replaces=op, parts=op["parts"] + [stripped])
                return
            if continues(op["english"], english):
                joined = f'{_ELLIPSIS.sub("", op["english"])} {english}'
                if len(joined) <= MAX_JOIN:
                    self._show(dict(line, english=joined, joined=True, speaker=op["speaker"] or speaker,
                                    grows=english), replaces=op, parts=op["parts"] + [english])
                    return
        self._show(line)

    def _show(self, line, replaces=None, parts=None):
        """Decide what is shown (speaker, context) right away on the reading thread, then hand the line to the
        translation thread: reading goes on while DeepL / Qwen answer (it used to stop for 0.3-0.9 s per line, so the
        next lines were read late). replaces: the open line this one is written over on the TV."""
        cfg = self.cfg
        now = time.perf_counter()
        last = self._last
        hint = bool(line.get("hint"))
        speaker = line["speaker"]
        if (not speaker and not hint and last and not self._cleared and now - last["time"] < CONTINUATION_SECONDS
                and not self.names_always()):
            # Games drop the name when the same person keeps talking and the line is replaced directly. A game
            # that names the speaker on every line (GTA 6) does not: there a line without a name had its name
            # misread or cut off, and giving it the previous speaker's name put one person's words in another's
            # mouth ("cO Wilson: Shit, you haven't heard?" was shown as Lucia's).
            speaker = last["speaker"]
        if (not speaker and not hint and replaces is None and cfg["filters"].get("names_only")
                and self.names_always()):
            # "Only lines with a name": the game writes "Name:" in front of every line, so a line without one is a
            # sign / HUD text (or its name is not read yet: it comes again with the name and is shown then).
            if self.log:
                self.log.note(no_name=line["english"][:60])
            return
        if not hint and replaces is None:
            self._named.append(bool(line["speaker"]))
        english = line["english"]
        if _TURKISH.search(english):
            return  # already Turkish (PS5 menus, Turkish-language games): nothing to translate
        context = self._context(english, cfg, replaces["english"] if replaces else None)
        self._history = ([h for h in self._history if now - h[1] < HINT_SECONDS][-HISTORY_MAX:]
                         + [(normalize(english), now, hint)])
        if not hint:
            self._last = {"speaker": speaker, "english": english, "time": now}
        self._cleared = False
        if (replaces is None and non_speech(english, line["speaker"]) and self.repeats.shown(normalize(english), now)
                and self.log):
            self.log.note(repeat_blocked=english[:60])
        self.line_id += 1
        if not hint and not speaker:
            self._unnamed.append({"id": self.line_id, "english": english, "norm": normalize(english), "time": now,
                                  "parts": parts or [english]})
        incomplete = False
        if not hint:
            self._ended.append(not unfinished(english))
            incomplete = self._incomplete(english)
            # The open lines: the one written over is done; a new line of a speaker ends their older open one.
            self._opens = deque((o for o in self._opens if o is not replaces
                                 and not (replaces is None and speaker and o["speaker"] == speaker)), maxlen=OPEN_MAX)
            # Also speech cut off with a dash stays open: the same screen may still grow ("…you're-" ->
            # "…you're- you're the only one…"), it is just not shown as unfinished.
            if cfg["hold_unfinished"] and unfinished(english):
                self._opens.append({"id": self.line_id, "speaker": speaker, "english": english,
                                    "parts": parts or [english], "time": now})
        self._jobs.put({"id": self.line_id, "line": line, "speaker": speaker, "english": english,
                        "context": context, "hint": hint, "queued": now, "parts": parts, "partial": incomplete,
                        "replaces": replaces["id"] if replaces else None})

    def _incomplete(self, english):
        """The line may go on on the next screen: it ends with a comma / "…" / a connector word, or without
        punctuation in a game that uses punctuation at all (some never do; there every line would look unfinished).
        Speech cut off with a dash is over."""
        if not unfinished(english) or cut_off(english):
            return False
        words = english.split()
        if (_ELLIPSIS.search(english) or english.rstrip().endswith((",", ";"))
                or (words and words[-1].lower().strip("\"'’”") in _CONNECTORS)):
            return True
        ends = list(self._ended)
        return len(ends) < 10 or any(ends)

    def _grow(self, job, shown, cfg):
        """The sentence on the TV went on (next screen, or the same row revealed further): the Turkish already shown
        stays as it is and only the rest is put under it, on its own line, so nothing jumps or changes wording.
        The rest is taken from the whole sentence's pack translation when that starts with the shown part,
        otherwise the new English part is translated on its own (with the beginning as context)."""
        t0 = time.perf_counter()
        english, rest_en = job["english"], job["line"]["grows"]
        rest = None
        hit = self.pack_hit(english, cfg)
        if hit:
            rest = remainder(shown, filters.correct(hit.turkish, cfg["corrections"]))
            if rest:
                self.last_source, self.last_candidates = f"Paket · {hit.pack.title}", None
        if not rest:
            context = (self._context(rest_en, cfg, job["line"].get("completes"))
                       + f' This is only the end of a sentence that began: "{english[:len(english) - len(rest_en)].strip()}"'
                       " - translate only this end.")
            rest, _ = self.translate_text(rest_en, cfg, context)
        if rest_en[:1].islower() or rest_en[:1] in ",;":
            rest = lower_start(rest)
        lines = shown.split("\n")
        return "\n".join(lines + [rest.strip()]), (time.perf_counter() - t0) * 1000

    def _translation_worker(self):
        """Translates the lines in the order they were read and sends them to the TV."""
        while True:
            job = self._jobs.get()
            try:
                self._deliver(job)
            except Exception as e:  # noqa: BLE001 - one bad line must not stop the subtitles
                if self.log:
                    self.log.note(error=f"çeviri: {e}"[:200])

    def _deliver(self, job):
        cfg = self.cfg
        line, english, speaker = job["line"], job["english"], job["speaker"]
        shown = self._sent_tr.get(job.get("replaces")) if job.get("replaces") is not None else None
        if line.get("grows") and shown and cfg.get("append_rest", True):
            turkish, tr_ms = self._grow(job, shown, cfg)
        else:
            turkish, tr_ms = self.translate_text(english, cfg, job["context"], job.get("parts"))
        if similar(normalize(turkish), normalize(english)):
            # Nobody translated it. Longer: not English (a Turkish menu), unless it is only names ("Lucia Caminos.").
            # One word without a speaker: a car's badge, a sign or a plate read as a subtitle ("Canboniare!").
            if len(english) > 12 and not (speaker and _NAME_ONLY.match(english.strip())):
                return
            if not line["speaker"] and len(english.split()) <= 1 and not job["hint"]:
                return
        partial = job["partial"]
        if line.get("lang") and not (line.get("grows") and shown) and not turkish.startswith(line["lang"]):
            # The game's "In Spanish:" in front of the line, in Turkish: "M7: İspanyolca: Hadi gidelim!"
            turkish = f'{line["lang"]}: {turkish}'
        shown_speaker = speaker if cfg["filters"]["speaker_names"] else None
        now = time.perf_counter()
        prev = self._last_sent
        replaces = job.get("replaces")
        if (replaces is None and prev and speaker and prev["speaker"] == speaker and not job["hint"]
                and not prev["hint"] and now - prev["time"] < REPLACE_SECONDS
                and len(prev["english"].split()) <= REPLACE_WORDS):
            # The same person saying something short again right away ("Hey!" … "Hey, big man!"): the game writes it
            # over the short line on the same row, so the TV does too instead of stacking another row.
            replaces = prev["id"]
        # "update": the newest row is written over (TV apps before 1.1 know only this); "replaces": that row's id,
        # also when it has moved up (busy scene).
        update = replaces is not None and prev is not None and replaces == prev["id"]
        self._last_sent = {"id": job["id"], "speaker": speaker, "english": english, "hint": job["hint"], "time": now}
        self._sent_tr[job["id"]] = turkish
        while len(self._sent_tr) > 60:
            self._sent_tr.pop(next(iter(self._sent_tr)))
        msg = {"type": "line", "id": job["id"], "speaker": shown_speaker or "", "en": english, "tr": turkish,
               "partial": partial, "update": update}
        if replaces is not None:
            msg["replaces"] = replaces
        # The game's colour of the name (measured on screen), like the game shows it; or the app's own colours.
        color = self.colors.pick(shown_speaker, line.get("name_tint"),
                                 cfg["filters"].get("speaker_color_game", True)) if shown_speaker else None
        if color:
            msg["color"] = color
        self.server.send(msg)
        self._last_msg = (now, msg)
        info = {
            "id": job["id"], "time": time.strftime("%H:%M:%S"), "speaker": shown_speaker,
            "en": english, "tr": turkish, "ocr_ms": line["ocr_ms"], "tr_ms": tr_ms,
            "pc_ms": (time.perf_counter() - line["t_first"]) * 1000,
            "held_ms": (job["queued"] - line["since"]) * 1000, "joined": bool(line.get("joined")), "partial": partial,
            "hint": job["hint"], "replaced": replaces is not None, "replaces": replaces, "color": color,
            "wait_ms": round((time.perf_counter() - job["queued"]) * 1000 - tr_ms),
            "source": self.last_source,
            "candidates": self.last_candidates,     # every translator's answer (None: from a game pack)
        }
        self.on_line(info)
        if self.log:
            self.log.line({**info, "ocr": line["ocr"]}, line["crop"])
