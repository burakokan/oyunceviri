"""Realistic Gemini latency for live subtitles: one kept-alive HTTPS connection (no new TLS handshake per
line), plain text answer, minimal thinking, short system prompt. Same 22 hard lines as llm_bench."""
import json
import statistics
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")
from gt import config  # noqa: E402
from llm_bench import LINES  # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else "gemini-3.5-flash-lite"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
SYSTEM = ("Translate the English video game subtitle into natural spoken Turkish. Use \"sen\". Idioms and slang by "
          "meaning, never word by word. Keep swearing just as strong (Fuck = Siktir). Keep names. Reply with the "
          "Turkish line only.")
key = config.load()["gemini"]["key"]
s = requests.Session()
s.headers.update({"x-goog-api-key": key, "Content-Type": "application/json"})


def ask(text, thinking="minimal"):
    body = {"systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 200}}
    if thinking:
        body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": thinking}
    t = time.perf_counter()
    r = s.post(URL, data=json.dumps(body), timeout=30)
    ms = (time.perf_counter() - t) * 1000
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip(), ms


t = time.perf_counter(); s.get(URL.rsplit("/", 1)[0], timeout=30); print(f"ilk bağlantı (TLS): {(time.perf_counter()-t)*1000:.0f} ms")
t = time.perf_counter(); s.get(URL.rsplit("/", 1)[0], timeout=30); print(f"açık bağlantıda boş istek (ağ gidiş-dönüş): {(time.perf_counter()-t)*1000:.0f} ms")
ask("Warm up.")
times = []
for en, _ in LINES:
    tr, ms = ask(en)
    times.append(ms)
    print(f"{ms:6.0f} ms | {tr}")
times.sort()
print(f"\n{MODEL}: ortanca {statistics.median(times):.0f} ms · ortalama {statistics.mean(times):.0f} ms · "
      f"en hızlı {times[0]:.0f} · en yavaş {times[-1]:.0f} · %90 {times[int(len(times)*0.9)-1]:.0f} ms")
