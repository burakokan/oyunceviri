"""Builds game packs in the background: read the English source, translate it in batches with context,
write packs/<id>.json.gz. Progress is saved after every batch, so it continues where it stopped
(app closed, daily quota used up)."""
import gzip
import json
import re
import threading
import time

from ..config import ROOT
from ..packs import PACK_DIR, key, sentences
from . import sources
from .gemini import FALLBACKS, BadKey, Blocked, Busy, Gemini, NotFree, QuotaExhausted

WORK = ROOT / "packs" / "build"
QUOTA_RETRY_S = 3600
BUSY_RETRY_S = 300
BUSY_BLOCK_S = 900      # an overloaded model is left alone this long while the others work
BATCH = 60
CONTEXT = 6
SAVE_EVERY = 10   # write the pack every N batches so finished parts can already be used


_PREFIX = re.compile(r"^([^:\n]{1,30}):\s+")


def speaker_names(lines):
    """Every speaker of the game, in lowercase, also by first name ("peter parker", "peter")."""
    names = set()
    for line in lines:
        sp = (line.get("speaker") or "").strip().lower()
        if sp:
            names |= {sp, sp.split(" ")[0]}
    return names


def tidy(line, tr, names=()):
    """Remove a speaker name the model put in front of the translation ("Snake: ...", even a wrong one
    like "Tom: Doğru."): the TV shows the speaker separately."""
    m = _PREFIX.match(tr)
    if not m:
        return tr
    name = m.group(1).strip().lower()
    own = (line.get("speaker") or "").strip().lower()
    if name in names or name in (own, own.split(" ")[0] if own else ""):
        if not line["en"].lower().startswith(name + ":"):
            return tr[m.end():].strip()
    return tr


class Job:
    def __init__(self, src):
        self.src = src
        self.dir = WORK / src["id"]
        self.state = "idle"     # idle | queued | reading | translating | done | quota | error | stopped
        self.message = ""
        self.done = 0
        self.total = 0
        self.retries = 0
        self._load_counts()

    @property
    def source_file(self):
        return self.dir / "source.jsonl"

    @property
    def tr_file(self):
        return self.dir / "translations.jsonl"

    def _load_counts(self):
        if self.source_file.exists():
            lines = self.lines()
            self.total = len({key(l["en"]) for l in lines})
            self.done = len(self.translations())
            if self.done >= self.total > 0:
                self.state = "done"
            elif self.done:
                self.state = "stopped"
        elif (PACK_DIR / f"{self.src['id']}.json.gz").exists():
            self.state = "done"

    def lines(self):
        return [json.loads(l) for l in self.source_file.read_text(encoding="utf-8").splitlines() if l.strip()]

    def translations(self):
        if not self.tr_file.exists():
            return {}
        out = {}
        for raw in self.tr_file.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                t = json.loads(raw)
                out[t["key"]] = t["tr"]
        return out


class PackBuilder:
    def __init__(self, cfg, packs, on_change=lambda: None, on_quota=lambda: None, fallback=None):
        self.cfg = cfg
        self.packs = packs          # PackLibrary: finished packs are loaded into it right away
        self._ui_change = on_change
        self.on_quota = on_quota    # called (from the worker thread) when the free daily limit runs out
        self.fallback = fallback    # local model, for single lines Gemini refuses to translate
        self.jobs = {s["id"]: Job(s) for s in sources.SOURCES}
        self._queue = []
        self._stop = threading.Event()
        self._thread = None
        self._blocked = {}          # model -> time until which it can't be used (daily limit, overloaded)
        self._why = {}              # model -> "quota" | "busy" | "notfree"
        self.model = None           # the model translating right now

    def on_change(self):
        """UI refresh + packs/build/status.json (what is happening, readable without the app window)."""
        try:
            now = time.time()
            status = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "model": self.model,
                      "blocked": {m: [self._why.get(m), time.strftime("%H:%M", time.localtime(u))]
                                  for m, u in self._blocked.items() if u > now},
                      "jobs": {i: [j.state, j.done, j.total, j.message] for i, j in self.jobs.items()}}
            WORK.mkdir(parents=True, exist_ok=True)
            (WORK / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
        self._ui_change()

    # ---- free models ----

    def _models(self):
        first = self.cfg["gemini"]["model"]
        order = [first] + ([m for m in FALLBACKS if m != first] if self.cfg["gemini"].get("rotate", True) else [])
        return [m for m in order if self._blocked.get(m, 0) <= time.time()]

    def _client(self):
        free = self._models()
        if not free:
            now = time.time()
            if any(self._why.get(m) == "busy" for m, until in self._blocked.items() if until > now):
                raise Busy("Ücretsiz modeller şu an çok yoğun; birkaç dakika sonra devam edecek.")
            wait = max(60, min(u for u in self._blocked.values() if u > now) - now)
            raise QuotaExhausted("Bütün ücretsiz modellerin bugünkü limiti doldu.", wait)
        self.model = free[0]
        return Gemini(self.cfg["gemini"]["key"], self.model)

    def _block(self, model, seconds, why):
        self._blocked[model] = time.time() + seconds
        self._why[model] = why

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, ids):
        for i in ids:
            job = self.jobs[i]
            if i not in self._queue and job.state != "done":
                self._queue.append(i)
                job.state, job.message = "queued", "Sırada"
        self._stop.clear()
        if not self.running:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        self.on_change()

    def stop(self):
        self._stop.set()
        for i in self._queue:
            self.jobs[i].state, self.jobs[i].message = "stopped", "Durduruldu"
        self._queue.clear()
        self.on_change()

    def _run(self):
        while self._queue and not self._stop.is_set():
            job = self.jobs[self._queue[0]]
            try:
                self._build(job)
            except QuotaExhausted as e:
                # Every free model's daily limit is used up: tell the user, wait for the reset, continue.
                reset = time.time() + e.retry_s
                job.state = "quota"
                job.message = f"{e} Limit {time.strftime('%H:%M', time.localtime(reset))} civarı yenilenince devam eder."
                self.on_quota(reset)
                self.on_change()
                if self._stop.wait(min(e.retry_s, QUOTA_RETRY_S)):
                    job.state, job.message = "stopped", "Durduruldu"
                continue
            except Busy as e:
                # Overloaded / offline: wait a few minutes, then continue the same game where it stopped.
                job.state, job.message = "stopped", str(e)
                self.on_change()
                if self._stop.wait(BUSY_RETRY_S):
                    job.message = "Durduruldu"
                continue
            except (BadKey, NotFree) as e:
                job.state, job.message = "error", str(e)
                for i in self._queue[1:]:
                    self.jobs[i].state, self.jobs[i].message = "stopped", "Durduruldu"
                self._queue.clear()
            except Exception as e:  # noqa: BLE001 - shown in the UI
                job.state, job.message = "error", f"Hata: {e}"
                job.retries += 1
                if job.retries <= 2:            # try it once more after the other games
                    self._queue.append(job.src["id"])
            if self._queue and self._queue[0] == job.src["id"]:
                self._queue.pop(0)
            self.on_change()

    def _progress(self, job, text):
        job.message = text
        self.on_change()

    def _build(self, job):
        src = job.src
        job.dir.mkdir(parents=True, exist_ok=True)
        if not job.source_file.exists():
            job.state = "reading"
            rows = sources.read(src, lambda t: self._progress(job, t))
            with open(job.source_file, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        lines = job.lines()
        done = job.translations()
        todo, seen = [], set(done)
        for i, line in enumerate(lines):
            k = key(line["en"])
            if k and k not in seen:
                seen.add(k)
                todo.append(i)
        job.total = len(seen)
        job.done = len(done)
        job.state = "translating"
        try:
            self._translate_all(job, self._client(), lines, todo, done)
        finally:
            self._write_pack(job, lines, done)   # whatever is translated so far is usable right away
        if job.state == "translating":
            job.state, job.message = "done", f"Hazır: {len(done):,} replik".replace(",", ".")

    def _translate_all(self, job, gemini, lines, todo, done):
        src = job.src
        names = speaker_names(lines)
        batches = 0
        for start in range(0, len(todo), BATCH):
            if self._stop.is_set():
                job.state, job.message = "stopped", "Durduruldu"
                return
            idx = todo[start:start + BATCH]
            batch = [lines[i] for i in idx]
            first = idx[0]
            context = [dict(lines[j], tr=done.get(key(lines[j]["en"]), "")) for j in range(max(0, first - CONTEXT), first)]
            context = [c for c in context if c["tr"]]
            while True:
                try:
                    results = self._translate(gemini, src, batch[0].get("scene", ""), context, batch)
                    break
                except QuotaExhausted as e:             # this model's free day is over: next free model
                    self._block(gemini.model, e.retry_s, "quota")
                except NotFree:                         # no free use for this model: never use it
                    self._block(gemini.model, 24 * 3600, "notfree")
                except Busy:                            # overloaded right now: another model for a while
                    self._block(gemini.model, BUSY_BLOCK_S, "busy")
                gemini = self._client()                 # raises when no free model is left
                self.on_change()
            with open(job.tr_file, "a", encoding="utf-8") as f:
                for line, tr in zip(batch, results):
                    tr = tidy(line, tr, names)
                    if tr:
                        k = key(line["en"])
                        done[k] = tr
                        f.write(json.dumps({"key": k, "tr": tr}, ensure_ascii=False) + "\n")
            job.done = len(done)
            job.message = f"Çevriliyor: {job.done:,} / {job.total:,} · {gemini.model}".replace(",", ".")
            self.on_change()
            batches += 1
            if batches % SAVE_EVERY == 0:
                self._write_pack(job, lines, done)

    def _translate(self, gemini, src, scene, context, batch):
        """Split a refused or malformed batch into halves; single lines Gemini refuses go to the local model."""
        try:
            return gemini.translate(src["title"], scene, context, batch, src.get("notes", ""))
        except (Blocked, ValueError, json.JSONDecodeError):
            if len(batch) == 1:
                try:
                    return [self.fallback(batch[0]["en"]) if self.fallback else ""]
                except Exception:  # noqa: BLE001 - the line is simply left to the live model
                    return [""]
            mid = len(batch) // 2
            return (self._translate(gemini, src, scene, context, batch[:mid])
                    + self._translate(gemini, src, scene, context, batch[mid:]))

    def _write_pack(self, job, lines, done):
        if not done:
            return
        names = speaker_names(lines)
        pack = {"format": 2, "id": job.src["id"], "title": job.src["title"],
                "source": f"{job.src['about']}; Gemini ile bağlamıyla çevrildi ({time.strftime('%Y-%m-%d')}); "
                          "kişisel kullanım", "entries": {}, "segments": {}, "english": {}}
        for line in lines:
            k = key(line["en"])
            tr = done.get(k)
            if not tr or k in pack["entries"]:
                continue
            tr = tidy(line, tr, names)
            pack["entries"][k] = tr
            pack["english"][k] = line["en"]
            ep, tp = sentences(line["en"]), sentences(tr)
            if len(ep) > 1 and len(ep) == len(tp):
                for e, t in zip(ep, tp):
                    sk = key(e)
                    if sk and sk not in pack["entries"]:
                        pack["segments"].setdefault(sk, t)
                        pack["english"].setdefault(sk, e)
        PACK_DIR.mkdir(exist_ok=True)
        path = PACK_DIR / f"{job.src['id']}.json.gz"
        tmp = job.dir / "pack.tmp"      # outside packs/, so a half-written file is never loaded
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=9) as f:
            json.dump(pack, f, ensure_ascii=False, sort_keys=True)
        tmp.replace(path)
        self.packs.add(path)
