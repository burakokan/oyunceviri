"""Which translator makes the Turkish of a line that is not in a game pack.

Engines (cfg["mt"]["engine"]):
  smart  DeepL + Qwen (Groq) + the local OPUS-MT at the same time; the best answer that arrives within the
         deadline is chosen by simple rules ("siz" to one person, softened swearing, English left in, cut-off
         or echoed text lose). Nothing in time / no internet -> OPUS-MT. Measured: ~0.3 s, quality close to Gemini.
  deepl  DeepL only (OPUS-MT if it does not answer in time)
  groq   Qwen 3.8 27B on Groq only (OPUS-MT if it does not answer in time)
  gemma  Gemma 4 E2B on this PC's graphics card (llama.cpp), ~0.2 s
  local  OPUS-MT on this PC, ~0.04 s

The Turkish on the TV never changes, so exactly one answer is chosen per line. HTTPS connections are kept
open (a new TLS handshake costs ~0.6 s from here) and pinged while the engine runs.
"""
import os
import re
import subprocess
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import requests

from .config import ROOT

DEEPL_URL = "https://api-free.deepl.com/v2"
GROQ_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "qwen/qwen3.8-27b"
LLAMA = ROOT / "vendor" / "llama" / "llama-server.exe"
GEMMA = ROOT / "models" / "llm" / "gemma4e2b" / "gemma-4-E2B-it-Q4_0.gguf"
GEMMA_PORT = 8092
KEEPALIVE_S = 25

SYSTEM = ("Translate the English game dialogue line into Turkish. Keep the exact meaning: the same people "
          "(I/you/he/she/we/they), tense and question. Natural spoken Turkish: \"sen\" to one person, idioms by "
          "meaning, swearing just as strong (Fuck -> Siktir). Keep names. Output only the Turkish line.")
FEWSHOT = [
    ("Are they safe?", "Güvendeler mi?"),
    ("Shit, get down!", "Siktir, yere yat!"),
]


def _game_only(context):
    """The previous line made Qwen mix up who is spoken to ("Are they all right?" -> "İyi misiniz?"): LLMs get
    only the game; DeepL, which is built for a context text, gets the previous line too."""
    return context.split(" Previous line:")[0]


ENGINES = {
    "smart": "Akıllı: DeepL + Qwen + OPUS-MT, en iyisi",
    "deepl": "DeepL",
    "groq": "Qwen 3.8 (Groq)",
    "gemma": "Gemma 4 E2B (bu bilgisayarda)",
    "local": "OPUS-MT (bu bilgisayarda)",
}

# "siz" endings, also with a case ending after them: istiyorsanız, yağmacılarınızla, geçmeniz, gelirseniz
_FORMAL = re.compile(r"n[ıiuü]z(?:d[ae]n|t[ae]n|d[ae]|t[ae]|[ae]|[ıiuü]|l[ae]|yl[ae]|[ıiuü]n)?$")
_FORMAL_WORDS = {"siz", "size", "sizi", "sizin", "sizinle", "sizde", "sizden",
                 # commands said to "siz" (olun, getirin): the most common ones in games
                 "olun", "gelin", "gidin", "durun", "bakın", "getirin", "tutun", "koşun", "yapın", "alın", "verin",
                 "bekleyin", "söyleyin", "dinleyin", "çıkın", "girin", "kaçın", "saklanın", "edin", "ediniz",
                 "bırakın", "atın", "vurun", "öldürün", "sakının", "susun", "yatın", "kalkın", "dikkat edin",
                 "çekilin", "geri çekilin", "takip edin", "gösterin", "anlatın", "unutmayın", "acele edin"}
_NOT_FORMAL = ("deniz", "yalnız", "boynuz", "henüz")


def formal(turkish):
    """How many words address someone with "siz"."""
    n = 0
    for w in re.findall(r"[a-zçğıöşü]+", turkish.replace("I", "ı").replace("İ", "i").lower()):
        if w in _FORMAL_WORDS or (len(w) >= 5 and not w.startswith(_NOT_FORMAL) and _FORMAL.search(w)):
            n += 1
    return n
_PLURAL_YOU = re.compile(r"\b(you all|you guys|y'all|everyone|everybody|you two|all of you|people)\b", re.I)
# Only real curses / insults count for "softened": "Fuck!", "fuck you", "son of a bitch", "asshole". Emphasis
# ("fuckin' stupid", "about fuckin' time") and "shit" as a thing ("this shit", "don't fuck around") is translated by
# meaning; forcing "siktir" there chose wrong answers ("don't fuck around" -> "siktir etme").
_SWEAR_EN = re.compile(r"(^|[.!?,]\s*)(fuck|shit|holy shit|goddamn(it)?)\s*[!.?,]|\bfuck (you|off|me|him|her|them|that|this)\b"
                       r"|\bwhat the fuck\b|\bmotherfuck\w*", re.I)
_SWEAR_TR = re.compile(r"sik|orospu|piç|amk|amına|göt|yarak|bok|kaltak|şerefsiz|lanet|kahretsin", re.I)
# Insults: a Turkish insult ("pislik", "şerefsiz", "göt herif"), not "siktir" ("Whatever, asshole." -> "…, siktir.").
_INSULT_EN = re.compile(r"\bbitch(es)?\b|\bbastards?\b|\bassholes?\b|\bdick(head)?s?\b|\bcunts?\b|\bpricks?\b"
                        r"|\bmotherfuckers?\b|\bjackass\b", re.I)
_INSULT_TR = re.compile(r"orospu|piç|göt|şerefsiz|pislik|kaltak|yavşak|pezevenk|puşt|ibne|sürtük|kahpe|dallama|"
                        r"hıyar|it herif|gerizekalı|aşağılık|\badi\b|serseri|ahmak|eşek|hödük|salak|dangalak", re.I)
_WORD = re.compile(r"[A-Za-z]{4,}")


def left_english(english, turkish):
    """English words (5+ letters, not names) that appear in the Turkish ("Raiderlerle")."""
    names = set(re.findall(r"\b[A-Z][a-z]+\b", english))   # names, and the first word of a sentence
    low = turkish.lower()
    return {w for w in {w.lower() for w in _WORD.findall(english) if w not in names and len(w) >= 5} if w[:5] in low}


def turkish_too(answers):
    """Words that two or more translators kept: Turkish uses them too ("tavern" -> "taverna")."""
    seen = {}
    for tr in answers:
        for w in left_english(*tr):
            seen[w] = seen.get(w, 0) + 1
    return {w for w, n in seen.items() if n >= 2}


def judge(english, turkish, accepted=frozenset()):
    """-> (penalty points, reasons). Lower is better. Only problems that are cheap to see and clearly wrong
    count; the program cannot judge the meaning itself. accepted: words not counted as English."""
    if not turkish:
        return 99, ["boş cevap"]
    points, why = 0, []
    if turkish.strip().lower() == english.strip().lower():
        points += 10
        why.append("çevirmedi")
    ratio = len(turkish) / max(1, len(english))
    if ratio < 0.4 or ratio > 2.6:
        points += 4
        why.append("yarım kalmış" if ratio < 0.4 else "fazla uzun")
    n = 0 if _PLURAL_YOU.search(english) else formal(turkish)
    if n:
        points += 2 * min(2, n)
        why.append("\"siz\" diyor")
    if _SWEAR_EN.search(english) and not _SWEAR_TR.search(turkish):
        points += 1
        why.append("küfrü yumuşatmış")
    if _INSULT_EN.search(english) and not _INSULT_TR.search(turkish):
        points += 2 if re.search(r"siktir", turkish, re.I) and not _SWEAR_EN.search(english) else 1
        why.append("hakareti çevirmemiş")
    left = left_english(english, turkish) - set(accepted)
    if left:
        points += len(left)
        why.append("İngilizce kelime bırakmış: " + ", ".join(sorted(left)))
    return points, why


def _norm(t):
    return re.sub(r"[^\wçğıöşü ]", " ", t.replace("I", "ı").replace("İ", "i").lower())


def agreement(name, voters):
    """0..100: how much one translation agrees with the others (letters and words)."""
    from rapidfuzz import fuzz
    mine = _norm(voters[name])
    others = [_norm(t) for n, t in voters.items() if n != name and t]
    if not others:
        return 0.0
    return sum((fuzz.ratio(mine, o) + fuzz.token_set_ratio(mine, o)) / 2 for o in others) / len(others)


def futures_pending(pending, futures, name):
    return any(futures[f] == name for f in pending)


def score(english, turkish, accepted=frozenset()):
    return judge(english, turkish, accepted)[0]


class _Http:
    """A kept-alive HTTPS session; down_until is set after errors / rate limits."""

    def __init__(self):
        self.s = requests.Session()
        self.down_until = 0.0
        self.last_ms = None
        self.error = ""

    @property
    def up(self):
        return time.time() >= self.down_until

    def fail(self, seconds, why):
        self.down_until = time.time() + seconds
        self.error = why


class DeepL(_Http):
    def __init__(self, key):
        super().__init__()
        self.s.headers.update({"Authorization": "DeepL-Auth-Key " + key})

    def ping(self):
        self.s.get(DEEPL_URL + "/usage", timeout=10)

    def translate(self, english, context):
        body = {"text": [english], "source_lang": "EN", "target_lang": "TR", "model_type": "prefer_quality_optimized",
                "context": context}
        t = time.perf_counter()
        r = self.s.post(DEEPL_URL + "/translate", json=body, timeout=5)
        if r.status_code in (429, 456):            # too many requests / monthly limit used up
            self.fail(3600 if r.status_code == 456 else 30, "DeepL limiti doldu")
            raise RuntimeError(self.error)
        r.raise_for_status()
        self.last_ms = (time.perf_counter() - t) * 1000
        return r.json()["translations"][0]["text"].strip()

    def translate_xml(self, xml, context):
        """Text with button tags (<x id="1">L3</x> = a button icon, kept as it is): DeepL puts each tag where it
        belongs in the Turkish sentence ("Press <x id="1">L3</x> to swim" -> "Yüzmek için <x id="1">L3</x>'e bas")."""
        body = {"text": [xml], "source_lang": "EN", "target_lang": "TR", "tag_handling": "xml", "ignore_tags": ["x"],
                "model_type": "prefer_quality_optimized", "context": context}
        t = time.perf_counter()
        r = self.s.post(DEEPL_URL + "/translate", json=body, timeout=8)
        if r.status_code in (429, 456):
            self.fail(3600 if r.status_code == 456 else 30, "DeepL limiti doldu")
            raise RuntimeError(self.error)
        r.raise_for_status()
        self.last_ms = (time.perf_counter() - t) * 1000
        return r.json()["translations"][0]["text"].strip()

    def usage(self):
        d = self.s.get(DEEPL_URL + "/usage", timeout=10).json()
        return d.get("character_count", 0), d.get("character_limit", 0)


class Groq(_Http):
    def __init__(self, key):
        super().__init__()
        self.s.headers.update({"Authorization": "Bearer " + key})

    def ping(self):
        self.s.get(GROQ_URL + "/models", timeout=10)

    def translate(self, english, context):
        context = _game_only(context)
        msgs = [{"role": "system", "content": SYSTEM + ("\n" + context if context else "")}]
        for en, tr in FEWSHOT:
            msgs += [{"role": "user", "content": en}, {"role": "assistant", "content": tr}]
        msgs.append({"role": "user", "content": english})
        body = {"model": GROQ_MODEL, "messages": msgs, "temperature": 0, "max_tokens": 300,
                "reasoning_effort": "none", "reasoning_format": "hidden"}
        t = time.perf_counter()
        r = self.s.post(GROQ_URL + "/chat/completions", json=body, timeout=5)
        if r.status_code == 429:
            self.fail(float(r.headers.get("retry-after", 30) or 30), "Groq limiti doldu")
            raise RuntimeError(self.error)
        r.raise_for_status()
        self.last_ms = (time.perf_counter() - t) * 1000
        return r.json()["choices"][0]["message"]["content"].strip().strip('"')


def _llama_env():
    """The installed app keeps one copy of cuBLAS (nvidia/cublas/bin, also used by OPUS-MT); llama.cpp finds it
    through PATH."""
    env = dict(os.environ)
    extra = [str(d) for d in (ROOT / "nvidia" / "cublas" / "bin",) if d.is_dir()]
    if extra:
        env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


class Gemma(_Http):
    """Gemma 4 E2B with llama.cpp on this PC's graphics card; started on first use, kept running."""

    def __init__(self):
        super().__init__()
        self.proc = None
        self._lock = threading.Lock()

    @staticmethod
    def available():
        return LLAMA.exists() and GEMMA.exists()

    def start(self):
        with self._lock:
            if self.proc and self.proc.poll() is None:
                return True
            if not self.available():
                return False
            self.proc = subprocess.Popen(
                [str(LLAMA), "-m", str(GEMMA), "--port", str(GEMMA_PORT), "-ngl", "99", "-c", "2048",
                 "--no-webui", "-np", "1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000, env=_llama_env())
            for _ in range(240):
                try:
                    if self.s.get(f"http://127.0.0.1:{GEMMA_PORT}/health", timeout=2).json().get("status") == "ok":
                        return True
                except (requests.RequestException, ValueError):
                    pass
                time.sleep(0.5)
            return False

    def stop(self):
        with self._lock:
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
            self.proc = None

    def translate(self, english, context):
        if not self.start():
            raise RuntimeError("Gemma 4 bu bilgisayarda yok")
        context = _game_only(context)
        msgs = [{"role": "system", "content": SYSTEM + ("\n" + context if context else "")}]
        for en, tr in FEWSHOT:
            msgs += [{"role": "user", "content": en}, {"role": "assistant", "content": tr}]
        msgs.append({"role": "user", "content": english})
        t = time.perf_counter()
        r = self.s.post(f"http://127.0.0.1:{GEMMA_PORT}/v1/chat/completions", timeout=5, json={
            "messages": msgs, "temperature": 0, "max_tokens": 160, "cache_prompt": True,
            "chat_template_kwargs": {"enable_thinking": False}})
        r.raise_for_status()
        self.last_ms = (time.perf_counter() - t) * 1000
        return r.json()["choices"][0]["message"]["content"].strip()


class Conductor:
    """Picks the translation of a line. Nothing "understands" the candidates: judge() only spots problems that
    are easy to see; among the online answers the one with the fewest penalty points wins (the shorter one on a tie),
    and the backup model (OPUS-MT, quickmt or Gemma 4) is used only when no online answer came in time."""

    def __init__(self, local_translate):
        self.local_translate = local_translate      # (english, cfg) -> Turkish with OPUS-MT / quickmt (+ fixes)
        self.pool = ThreadPoolExecutor(max_workers=6)
        self.deepl = self.groq = None
        self._keys = (None, None)
        self.gemma = Gemma()
        self.last = {"chosen": None, "candidates": []}   # the last line: every answer, for the history details
        self.active = False                          # the subtitle engine runs: keep connections warm
        threading.Thread(target=self._keepalive, daemon=True).start()

    def configure(self, cfg):
        keys = (cfg["online"].get("deepl_key", "").strip(), cfg["online"].get("groq_key", "").strip())
        if keys != self._keys:
            self._keys = keys
            self.deepl = DeepL(keys[0]) if keys[0] else None
            self.groq = Groq(keys[1]) if keys[1] else None

    def _keepalive(self):
        while True:
            time.sleep(KEEPALIVE_S)
            if not self.active:
                continue
            for client in (self.deepl, self.groq):
                if client is not None and client.up:
                    try:
                        client.ping()
                    except requests.RequestException:
                        pass

    def warm(self, cfg):
        """Open the connections (and start Gemma) before the first subtitle."""
        self.configure(cfg)
        self.active = True
        engine = cfg["mt"]["engine"]
        if engine == "gemma" or cfg["mt"].get("fallback") == "gemma":
            self.pool.submit(self.gemma.start)
        for client in (self.deepl, self.groq):
            if client is not None and engine in ("smart", "deepl" if client is self.deepl else "groq"):
                self.pool.submit(lambda c=client: c.ping())

    def stop(self):
        self.active = False

    # ---- the backup model ----

    @staticmethod
    def nmt_label(cfg):
        return "quickmt" if "quickmt" in cfg["translator"]["model"] else "OPUS-MT"

    def _nmt(self, cfg):
        return self.nmt_label(cfg), lambda english, context: self.local_translate(english, cfg)

    def _backup(self, cfg):
        """-> (label, function(english, context)) of the model used when nothing online answers."""
        if cfg["mt"].get("fallback") == "gemma" and self.gemma.available():
            def gemma_or_nmt(english, context):
                try:
                    return self.gemma.translate(english, context)
                except Exception:  # noqa: BLE001 - Gemma not running: the always-ready model
                    return self.local_translate(english, cfg)
            return "Gemma", gemma_or_nmt
        return self._nmt(cfg)

    # ---- one line ----

    @staticmethod
    def _timed(fn, english, context):
        t = time.perf_counter()
        tr = fn(english, context)
        return tr, (time.perf_counter() - t) * 1000

    def translate(self, english, cfg, context=""):
        """-> (turkish, label of the translator that was used). self.last keeps every answer."""
        self.configure(cfg)
        engine = cfg["mt"]["engine"]
        deadline = cfg["mt"].get("deadline_ms", 500) / 1000
        backup_name, backup = self._backup(cfg)
        main = []
        if engine in ("smart", "deepl") and self.deepl is not None and self.deepl.up:
            main.append(("DeepL", self.deepl.translate))
        if engine in ("smart", "groq") and self.groq is not None and self.groq.up:
            main.append(("Qwen", self.groq.translate))
        if engine == "gemma" and self.gemma.available():
            main.append(("Gemma", self.gemma.translate))
            if backup_name == "Gemma":
                backup_name, backup = self._nmt(cfg)
        if engine == "local":
            backup_name, backup = self._nmt(cfg)
        start = time.perf_counter()
        futures = {self.pool.submit(self._timed, fn, english, context): name for name, fn in main}
        spare = self.pool.submit(self._timed, backup, english, context)
        answers, failed = {}, {}

        def collect(done):
            for f in done:
                try:
                    answers[futures[f]] = f.result()
                except Exception as e:  # noqa: BLE001 - this translator is left out for this line
                    failed[futures[f]] = str(e)[:80]

        pending = set(futures)
        while pending:
            left = deadline - (time.perf_counter() - start)
            if left <= 0:
                break
            done, pending = wait(pending, timeout=left, return_when=FIRST_COMPLETED)
            collect(done)
            first = next((n for n, _ in main if n in answers or futures_pending(pending, futures, n)), None)
            if first in answers and score(english, answers[first][0]) == 0:
                break                       # the preferred translator answered without a visible mistake
        order = {"DeepL": 0, "Qwen": 1, "Gemma": 2}
        pool_answers = [(english, tr) for tr, _ in answers.values()]
        if spare.done():
            pool_answers.append((english, spare.result()[0]))
        accepted = turkish_too(pool_answers)            # e.g. "taverna": not an English leftover
        voters = {n: tr for n, (tr, _) in answers.items()}
        if spare.done():
            voters.setdefault(backup_name, spare.result()[0])
        if answers:
            chosen = self._pick(english, answers, accepted, order, voters)
        else:
            chosen = backup_name
            answers[backup_name] = spare.result()
        candidates = []
        for name, _ in main:
            if name in answers:
                tr, ms = answers[name]
                points, why = judge(english, tr, accepted)
                candidates.append({"name": name, "tr": tr, "ms": round(ms), "points": points, "why": why})
            else:
                late = f"{deadline:.2f} sn içinde yetişmedi".replace(".", ",")
                candidates.append({"name": name, "tr": None, "ms": None, "points": None,
                                   "why": [failed.get(name) or late]})
        if backup_name not in [c["name"] for c in candidates] and (spare.done() or chosen == backup_name):
            tr, ms = answers[backup_name] if chosen == backup_name else spare.result()
            points, why = judge(english, tr, accepted)
            candidates.append({"name": backup_name, "tr": tr, "ms": round(ms), "points": points, "why": why,
                               "backup": True})
        self.last = {"chosen": chosen, "candidates": candidates}
        return answers[chosen][0], chosen

    @staticmethod
    def _pick(english, answers, accepted, order, voters=None):
        """DeepL first: it keeps the meaning; Qwen sounds more natural but now and then changes who is spoken to
        ("Are they all right?" -> "İyi misiniz?") or the direction ("come with me" -> "bana gel"). So DeepL's answer
        is shown unless it has a visible mistake ("siz", softened swearing, English left, cut off) and another
        answer has fewer."""
        return min(answers, key=lambda n: (score(english, answers[n][0], accepted), order.get(n, 9)))

    # ---- the test box and the key test ----

    def run_one(self, name, english, cfg, context=""):
        """One online / Gemma translator on its own (the test box) -> (turkish, ms)."""
        self.configure(cfg)
        fn = {"DeepL": self.deepl.translate if self.deepl else None,
              "Qwen": self.groq.translate if self.groq else None,
              "Gemma": self.gemma.translate if self.gemma.available() else None}.get(name)
        if fn is None:
            raise RuntimeError("anahtar girilmedi" if name in ("DeepL", "Qwen") else "bu bilgisayarda yok")
        return self._timed(fn, english, context)

    def test(self, cfg):
        """Connection test for the settings page: name -> (ok, text)."""
        self.configure(cfg)
        out = {}
        sample = "You're toast if he catches you sneaking around his camp."
        for name, client in (("DeepL", self.deepl), ("Qwen (Groq)", self.groq)):
            if client is None:
                out[name] = (False, "anahtar girilmedi")
                continue
            try:
                client.ping()
                t = time.perf_counter()
                tr = client.translate(sample, "")
                out[name] = (True, f"{(time.perf_counter() - t) * 1000:.0f} ms · {tr}")
            except Exception as e:  # noqa: BLE001
                out[name] = (False, str(e)[:120])
        return out
