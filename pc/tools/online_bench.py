"""Online translators on the same 22 hard lines as llm_bench, measured the way live subtitles would use them:
one kept-alive HTTPS connection per service, warmed up first, one line per request.
  .venv\\Scripts\\python.exe pc\\tools\\online_bench.py <keys.json>      keys.json: {"deepl": ..., "groq": ...}
"""
import json
import statistics
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")
from llm_bench import LINES, ROOT, SYSTEM_TR  # noqa: E402

KEYS = json.load(open(sys.argv[1], encoding="utf-8"))


class DeepL:
    def __init__(self, model_type, context=None):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": "DeepL-Auth-Key " + KEYS["deepl"]})
        self.model_type, self.context = model_type, context

    def __call__(self, en):
        body = {"text": [en], "source_lang": "EN", "target_lang": "TR", "model_type": self.model_type}
        if self.context:
            body["context"] = self.context
        r = self.s.post("https://api-free.deepl.com/v2/translate", json=body, timeout=30)
        r.raise_for_status()
        return r.json()["translations"][0]["text"]


class Groq:
    def __init__(self, model, **extra):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": "Bearer " + KEYS["groq"]})
        self.model, self.extra = model, extra

    def __call__(self, en):
        body = {"model": self.model, "temperature": 0, "max_tokens": 300,
                "messages": [{"role": "system", "content": SYSTEM_TR}, {"role": "user", "content": en}], **self.extra}
        for _ in range(5):
            r = self.s.post("https://api.groq.com/openai/v1/chat/completions", json=body, timeout=30)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("retry-after", 5)))
                continue
            if r.status_code == 400 and self.extra:
                print("   (ayar kabul edilmedi:", r.text[:160], ")")
                body = {k: v for k, v in body.items() if k not in self.extra}
                self.extra = {}
                continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        raise RuntimeError("rate limit")


ENGINES = {
    "DeepL (hızlı model)": DeepL("latency_optimized"),
    "DeepL (kaliteli model)": DeepL("prefer_quality_optimized"),
    "DeepL (kaliteli + bağlam)": DeepL("prefer_quality_optimized",
                                      "Video game dialogue between characters, spoken informally (sen, not siz)."),
    "Groq GPT-OSS 120B": Groq("openai/gpt-oss-120b", reasoning_effort="low", include_reasoning=False),
    "Groq GPT-OSS 20B": Groq("openai/gpt-oss-20b", reasoning_effort="low", include_reasoning=False),
    "Groq Qwen 3.8 27B": Groq("qwen/qwen3.8-27b", reasoning_effort="none", reasoning_format="hidden"),
}


def main():
    results = {}
    for name, engine in ENGINES.items():
        try:
            engine("Warm up the connection.")
        except Exception as e:  # noqa: BLE001
            print(name, "çalışmadı:", e)
            continue
        rows = []
        for en, _ in LINES:
            t = time.perf_counter()
            try:
                tr = engine(en)
            except Exception as e:  # noqa: BLE001
                tr = f"(hata: {e})"
            ms = (time.perf_counter() - t) * 1000
            rows.append((tr, ms))
            print(f"{name:26} {ms:6.0f} ms | {tr}")
        results[name] = rows
    out = ["# Çevrimiçi çeviriciler · zor cümle testi", "",
           "Bağlantı açık tutuldu (gerçek kullanımdaki gibi). Süre: satırın gidip Türkçesinin gelmesi.", "",
           "| Çevirici | Ortanca | Ortalama | En yavaş |", "|---|---|---|---|"]
    for name, rows in results.items():
        t = sorted(ms for _, ms in rows)
        out.append(f"| {name} | {statistics.median(t):.0f} ms | {statistics.mean(t):.0f} ms | {t[-1]:.0f} ms |")
    for i, (en, ref) in enumerate(LINES):
        out += ["", f"### {i + 1}. {en}", "", f"*Benim çevirim:* {ref}", "", "| Çevirici | Türkçe | Süre |",
                "|---|---|---|"]
        for name, rows in results.items():
            tr, ms = rows[i]
            out.append(f"| {name} | {tr.replace('|', '/')} | {ms:.0f} ms |")
    (ROOT / "logs" / "online-bench.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out[4:4 + len(results) + 2]))


if __name__ == "__main__":
    main()
