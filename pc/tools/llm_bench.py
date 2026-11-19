"""Speed / quality test of local translation models on hard game lines (idioms, slang, swearing).

Runs each GGUF model with llama-server (vendor/llama) on the GPU, plus OPUS-MT and NLLB (CTranslate2), and
writes logs/llm-bench.md: one table per sentence with every model's Turkish and its time.
  .venv\\Scripts\\python.exe pc\\tools\\llm_bench.py
"""
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pc"))
sys.stdout.reconfigure(encoding="utf-8")
SERVER = ROOT / "vendor" / "llama" / "llama-server.exe"
PORT = 8091

LINES = [
    ("If you spill the beans to the king, you'll be barking up the wrong tree—he's already got an axe to grind with your clan.",
     "Krala ötersen yanlış kapıyı çalmış olursun; adam zaten senin klanına diş biliyor."),
    ("If you want to deal with your raiders, you come through me.", "Yağmacılarınla iş yapacaksan benimle muhatap olacaksın."),
    ("I'm off, be well, friend.", "Ben kaçtım, kendine iyi bak dostum."),
    ("What is it you do here, again?", "Sen burada ne iş yapıyordun, bir daha söylesene?"),
    ("All right, bring out my lieutenant.", "Pekâlâ, sağ kolumu getirin."),
    ("I'll make sure they're ready for you, and keep them in fighting shape.", "Senin için hazır olmalarını sağlarım, savaşa hazır tutarım."),
    ("Fuck! They found us. Get the hell out of here!", "Siktir! Bizi buldular. Defolup gidin buradan!"),
    ("You're toast if he catches you sneaking around his camp.", "Kampının etrafında sinsi sinsi dolaşırken seni yakalarsa yandın."),
    ("Hold your horses, we're not done yet.", "Dur bakalım, daha işimiz bitmedi."),
    ("Break a leg out there, kid.", "Bol şans evlat."),
    ("Don't beat around the bush. Who sent you?", "Lafı dolandırma. Seni kim gönderdi?"),
    ("Watch your six, there's a sniper on the ridge.", "Arkanı kolla, sırtta bir keskin nişancı var."),
    ("Oh great, just what we needed. Another storm.", "Ah harika, bir bu eksikti. Yine fırtına."),
    ("It's not rocket science, just pull the damn lever.", "Bunda çözülecek bir şey yok, şu lanet kolu çek işte."),
    ("We're all in the same boat now, whether you like it or not.", "Hoşuna gitse de gitmese de artık hepimiz aynı gemideyiz."),
    ("That son of a bitch sold us out!", "O orospu çocuğu bizi sattı!"),
    ("Keep your friends close and your enemies closer.", "Dostunu yakın tut, düşmanını daha da yakın."),
    ("Piece of cake. I could do this in my sleep.", "Çocuk oyuncağı. Bunu uykumda bile yaparım."),
    ("Shit, shit, shit! The bridge is gone!", "Siktir, siktir, siktir! Köprü gitti!"),
    ("You've got some nerve showing your face here after what you pulled.", "Yaptığın onca şeyden sonra burada yüzünü göstermeye nasıl cüret edersin."),
    ("Let's call it a day. We'll hit the road at dawn.", "Bugünlük bu kadar. Şafakta yola çıkarız."),
    ("No-no-no, don't touch that!", "Hayır-hayır-hayır, ona dokunma!"),
]

SYSTEM_TR = ("You translate English video game subtitles into natural spoken Turkish, the way people really talk. "
             "Address people with \"sen\", never \"siz\" (unless several people are addressed). Translate idioms and "
             "slang by meaning, never word by word. Swearing stays just as strong (Fuck -> Siktir, son of a bitch -> "
             "orospu çocuğu). Keep names. Answer with the Turkish line only.")


def http(path, body=None, timeout=120):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def start_server(model):
    proc = subprocess.Popen([str(SERVER), "-m", str(model), "--port", str(PORT), "-ngl", "99", "-c", "2048",
                             "--no-webui", "-np", "1"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)
    for _ in range(240):
        try:
            if http("/health", timeout=2).get("status") == "ok":
                return proc
        except Exception:  # noqa: BLE001 - still loading
            pass
        time.sleep(0.5)
    proc.kill()
    raise RuntimeError("llama-server did not start")


def chat(messages, **extra):
    body = {"messages": messages, "temperature": 0, "max_tokens": 160, "cache_prompt": True, **extra}
    t = time.perf_counter()
    r = http("/v1/chat/completions", body)
    ms = (time.perf_counter() - t) * 1000
    return r["choices"][0]["message"]["content"].strip(), ms


def raw(prompt):
    t = time.perf_counter()
    r = http("/completion", {"prompt": prompt, "temperature": 0, "n_predict": 160, "cache_prompt": True,
                             "stop": ["<end_of_turn>"]})
    return r["content"].strip(), (time.perf_counter() - t) * 1000


def run_llm(name, model, make):
    proc = start_server(model)
    try:
        template = http("/props").get("chat_template", "")
        make(LINES[0][0], template)                       # warm up
        out = []
        for en, _ in LINES:
            tr, ms = make(en, template)
            out.append((tr, ms))
            print(f"{name:16} {ms:6.0f} ms | {tr}")
        return out
    finally:
        proc.kill()
        time.sleep(2)


def hymt(en, _):
    return chat([{"role": "user", "content": f"Translate the following segment into Turkish, without additional "
                                             f"explanation.\n\n{en}"}])


def translategemma(en, _):
    prompt = ("<start_of_turn>user\nYou are a professional English (en) to Turkish (tr) translator. Your goal is to "
              "accurately convey the meaning and nuances of the original English text while adhering to Turkish "
              "grammar, vocabulary, and cultural sensitivities.\nProduce only the Turkish translation, without any "
              "additional explanations or commentary. Please translate the following English text into Turkish:\n\n\n"
              f"{en}<end_of_turn>\n<start_of_turn>model\n")
    return raw(prompt)


FEWSHOT = [  # different from the test lines, so the test stays fair
    ("Damn it, get down!", "Siktir, yere yat!"),
    ("You bastard, you'll pay for this!", "Seni piç kurusu, bunu ödeyeceksin!"),
    ("Cut the crap and tell me where she is.", "Saçmalamayı kes de onun nerede olduğunu söyle."),
    ("Long story short, we're screwed.", "Uzun lafın kısası, siktik belamızı."),
    ("You're pulling my leg, right?", "Dalga geçiyorsun, değil mi?"),
    ("If you need supplies, you talk to me.", "Malzeme lazımsa benimle konuşacaksın."),
    ("Take care, friend. See you around.", "Kendine iyi bak dostum. Görüşürüz."),
]


def gemma4_shots(en, _):
    msgs = [{"role": "system", "content": SYSTEM_TR}]
    for e, t in FEWSHOT:
        msgs += [{"role": "user", "content": e}, {"role": "assistant", "content": t}]
    return chat(msgs + [{"role": "user", "content": en}], chat_template_kwargs={"enable_thinking": False})


def gemma4(en, _):
    return chat([{"role": "system", "content": SYSTEM_TR}, {"role": "user", "content": en}],
                chat_template_kwargs={"enable_thinking": False})


HYMT_CONTEXT = ("Video game dialogue, spoken between characters. Natural spoken Turkish: always \"sen\", never "
                "\"siz\". Idioms by meaning. Swearing stays strong: Fuck = Siktir, son of a bitch = orospu çocuğu.")


def hymt_ctx(en, _):
    return chat([{"role": "user", "content": HYMT_CONTEXT + "\n参考上面的信息，把下面的文本翻译成土耳其语，"
                                             "注意不需要翻译上文，也不要额外解释：\n" + en}])


def run_ct2():
    from gt.translate import LocalTranslator
    res = {}
    for name, path in (("OPUS-MT (şimdiki)", "models/opus-mt-tc-big-en-tr"),):
        t = LocalTranslator(path, "cuda", "float16", 2)
        res[name] = []
        for en, _ in LINES:
            s = time.perf_counter()
            tr = t.translate(en)
            res[name].append((tr, (time.perf_counter() - s) * 1000))
    import ctranslate2
    import sentencepiece as spm
    nllb = ROOT / "models" / "nllb-600m-ct2"
    if (nllb / "model.bin").exists():
        tr = ctranslate2.Translator(str(nllb), device="cuda", compute_type="int8_float16")
        sp = spm.SentencePieceProcessor(model_file=str(nllb / "sentencepiece.bpe.model"))
        res["NLLB-600M"] = []
        for i, (en, _) in enumerate([LINES[0]] + LINES):
            s = time.perf_counter()
            src = ["eng_Latn"] + sp.encode(en, out_type=str) + ["</s>"]
            hyp = tr.translate_batch([src], target_prefix=[["tur_Latn"]], beam_size=2)[0].hypotheses[0][1:]
            ms = (time.perf_counter() - s) * 1000
            if i:
                res["NLLB-600M"].append((sp.decode(hyp), ms))
    return res


def main():
    models = ROOT / "models" / "llm"
    results = run_ct2()
    for name, (path, fn) in {
        "HY-MT1.5 1.8B": (models / "hymt" / "HY-MT1.5-1.8B-Q4_K_M.gguf", hymt),
        "HY-MT1.5 + kurallar": (models / "hymt" / "HY-MT1.5-1.8B-Q4_K_M.gguf", hymt_ctx),
        "TranslateGemma 4B": (models / "translategemma" / "translategemma-4b-it-Q4_K_M.gguf", translategemma),
        "Gemma 4 E2B": (models / "gemma4e2b" / "gemma-4-E2B-it-Q4_0.gguf", gemma4),
        "Gemma 4 E2B + örnekler": (models / "gemma4e2b" / "gemma-4-E2B-it-Q4_0.gguf", gemma4_shots),
    }.items():
        if path.exists():
            results[name] = run_llm(name, path, fn)
    out = ["# Yerel çeviri modelleri · zor cümle testi", "",
           "Ekran kartı: RTX 2060 6 GB. Süre: bir satırın çevirisi (model yüklü, ısınmış).", "",
           "| Model | Ortalama | En yavaş |", "|---|---|---|"]
    for name, rows in results.items():
        times = [ms for _, ms in rows]
        out.append(f"| {name} | {statistics.mean(times):.0f} ms | {max(times):.0f} ms |")
    for i, (en, ref) in enumerate(LINES):
        out += ["", f"### {i + 1}. {en}", "", f"*Benim çevirim:* {ref}", "", "| Model | Türkçe | Süre |", "|---|---|---|"]
        for name, rows in results.items():
            tr, ms = rows[i]
            out.append(f"| {name} | {tr.replace('|', '/')} | {ms:.0f} ms |")
    (ROOT / "logs" / "llm-bench.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("yazıldı: logs/llm-bench.md")


if __name__ == "__main__":
    main()
