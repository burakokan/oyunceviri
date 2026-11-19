"""Batch translation of game lines with the Gemini API (the user's own key)."""
import json
import re
import time

import requests

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODELS = [
    ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite (hızlı, ücretsiz limiti yüksek — önerilen)"),
    ("gemini-3.8-flash", "Gemini 3.8 Flash (daha kaliteli, ücretsiz limiti düşük)"),
]

SYSTEM = """You translate English video game subtitles into natural, spoken Turkish — the way people really talk in Turkey, not textbook Turkish.
Rules:
- Characters talk to each other informally ("sen") unless the line is clearly formal or speaks to a group.
- Keep names of people, places, organizations, factions, items and weapons exactly as they are.
- Keep the tone: anger, humor, sarcasm, slang. Translate swearing and insults with equally strong Turkish ones; never soften, censor or leave them out ("Fuck!", "Shit!", "Coño!", "Mierda!" = "Siktir!", not "Kahretsin").
- Keep the meaning; do not add or drop information. Keep each line about as short as the original, since it is a subtitle.
- Lines or words in Spanish or any other language are translated into Turkish too (the player only reads Turkish). Only very well-known short words may stay ("amigo", "gracias" -> better "sağ ol").
- Repeated words and stutters stay repeated in Turkish ("No-no-no!" = "Hayır-hayır-hayır!").
- Keep "...", "!", "?" and numbers. Do not add quotation marks or speaker names.
- The previous lines and the scene are context only: use them to understand who speaks to whom and what is going on, but translate only the numbered lines.
Answer with a JSON array that has exactly one Turkish string for every numbered line, in the same order."""

SAFETY = [{"category": c, "threshold": "BLOCK_NONE"} for c in (
    "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "HARM_CATEGORY_DANGEROUS_CONTENT")]


class QuotaExhausted(Exception):
    """The model's daily free quota is used up; retry_s = seconds until it resets."""

    def __init__(self, text, retry_s=3600):
        super().__init__(text)
        self.retry_s = retry_s


# When the chosen model's free daily quota is used up, these free models are used next (best first).
# Each model has its own daily free quota. A model without free quota is skipped (NotFree), never paid for.
FALLBACKS = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
             "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]


def _retry_seconds(text):
    m = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", text)
    if m and any(m.groups()):
        h, mi, s = (float(x) if x else 0 for x in m.groups())
        return int(h * 3600 + mi * 60 + s) + 60
    m = re.search(r'"retryDelay":\s*"(\d+)', text)
    return int(m.group(1)) + 60 if m else 3600


class BadKey(Exception):
    pass


class Blocked(Exception):
    pass


class Busy(Exception):
    """Gemini is overloaded or unreachable for a while (503, network); try again later."""


class NotFree(Exception):
    """The model has no free quota on this key; never fall back to paid use."""


def free_models(key):
    """Flash-Lite / Flash model names this key can call (newest first), from the models list."""
    r = requests.get(API.rsplit("/", 1)[0], params={"pageSize": 200}, headers={"x-goog-api-key": key.strip()},
                     timeout=30)
    if r.status_code != 200:
        return []
    names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    names = [n for n in names if re.fullmatch(r"gemini-[\d.]+-flash(-lite)?", n)]
    return sorted(names, key=lambda n: ("lite" not in n, [-float(x) for x in re.findall(r"[\d.]+", n)[:1]]))


class Gemini:
    def __init__(self, key, model, system=None):
        self.key = key.strip()
        self.model = model
        self.system = system or SYSTEM      # screen translation (gt.screen) has its own instructions
        self.session = requests.Session()
        # Fields the API accepted; dropped one by one if a request is rejected as invalid.
        self.use_schema = True
        self.use_thinking = True

    def _body(self, prompt):
        cfg = {"temperature": 0.3, "responseMimeType": "application/json"}
        if self.use_schema:
            cfg["responseJsonSchema"] = {"type": "array", "items": {"type": "string"}}
        if self.use_thinking:
            cfg["thinkingConfig"] = {"thinkingLevel": "minimal" if "lite" in self.model else "low"}
        return {"systemInstruction": {"parts": [{"text": self.system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": cfg, "safetySettings": SAFETY}

    def _post(self, prompt):
        for attempt in range(8):
            try:
                r = self.session.post(API.format(model=self.model), json=self._body(prompt), timeout=120,
                                      headers={"x-goog-api-key": self.key})
            except requests.RequestException:
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            if r.status_code == 200:
                return r.json()
            msg = r.text[:2000]
            if r.status_code in (401, 403):
                raise BadKey("Gemini anahtarı geçersiz ya da yetkisiz.")
            if r.status_code == 400:
                if self.use_thinking and "thinking" in msg.lower():
                    self.use_thinking = False
                    continue
                if self.use_schema and ("schema" in msg.lower() or "responsejsonschema" in msg.lower()):
                    self.use_schema = False
                    continue
                if "API key" in msg or "API_KEY" in msg:
                    raise BadKey("Gemini anahtarı geçersiz.")
                raise RuntimeError(f"Gemini isteği reddedildi: {msg}")
            if r.status_code == 404:
                raise NotFree(f"\"{self.model}\" modeli bu anahtarla bulunamadı.")
            if r.status_code == 429:
                if re.search(r"limit:\s*0\b", r.text):
                    raise NotFree(f"\"{self.model}\" modelinin ücretsiz kotası yok; kullanılmayacak.")
                if re.search(r"PerDay|per day|daily", msg, re.I):
                    raise QuotaExhausted(f"{self.model}: günlük ücretsiz limit doldu.", _retry_seconds(r.text))
                m = re.search(r'"retryDelay":\s*"(\d+)', r.text)
                time.sleep(int(m.group(1)) + 1 if m else 20)
                continue
            if attempt >= 3:                         # 5xx ("high demand") again and again: use another model
                break
            time.sleep(5 * 2 ** attempt)
        raise Busy("Gemini şu an çok yoğun; birkaç dakika sonra kaldığı yerden devam edecek.")

    def ask_list(self, prompt, count):
        """Send a prompt, get back a JSON list of `count` strings."""
        data = self._post(prompt)
        cand = (data.get("candidates") or [{}])[0]
        if cand.get("finishReason") in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST") or "content" not in cand:
            raise Blocked("Gemini bu metni engelledi.")
        text = "".join(p.get("text", "") for p in cand["content"].get("parts", []) if not p.get("thought"))
        out = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip()))
        if not isinstance(out, list) or len(out) != count:
            raise ValueError(f"{count} metin gönderildi, {len(out) if isinstance(out, list) else '?'} geldi")
        return [str(x).strip() for x in out]

    def translate(self, title, scene, context, lines, notes=""):
        """lines: [{"speaker", "en"}]; context: [{"speaker", "en", "tr"}] -> list of Turkish strings."""
        parts = [f"Game: {title}"]
        if notes:
            parts.append(f"Terms for this game: {notes}")
        if scene:
            parts.append(f"Scene: {scene}")
        if context:
            parts.append("Previous lines (context only, already translated):")
            parts += [f"- [{c['speaker'] or '?'}] {c['en']}  =>  {c['tr']}" for c in context]
        parts.append("Lines to translate ([speaker] is context only, never write it in the answer):")
        parts += [f"{i + 1}. [{l['speaker'] or '?'}] {l['en']}" for i, l in enumerate(lines)]
        data = self._post("\n".join(parts))
        cand = (data.get("candidates") or [{}])[0]
        if cand.get("finishReason") in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST") or "content" not in cand:
            raise Blocked("Gemini bu satırları engelledi.")
        text = "".join(p.get("text", "") for p in cand["content"].get("parts", []) if not p.get("thought"))
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        out = json.loads(text)
        if not isinstance(out, list) or len(out) != len(lines):
            raise ValueError(f"{len(lines)} satır gönderildi, {len(out) if isinstance(out, list) else '?'} geldi")
        return [str(x).strip() for x in out]

    def test(self):
        return self.translate("Test", "", [], [{"speaker": "Dani", "en": "Let's get the hell out of here!"}])[0]
