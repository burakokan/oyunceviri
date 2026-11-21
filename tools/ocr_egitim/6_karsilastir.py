"""Recognizers side by side on the gold rows (checked by eye), the way the app calls them (one row per call, 4 CPU
threads): character error rate, whole rows right, speaker name right, ms per row.
usage (app venv): python bench.py [extra.onnx ...]"""
import json
import os
import statistics
import sys
import time

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ortak import DATA  # noqa: E402
sys.stdout.reconfigure(encoding="utf-8")
import rapidfuzz.distance.Levenshtein as L  # noqa: E402
from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR  # noqa: E402

from gt import filters  # noqa: E402

HERE = str(DATA)
BASE = {"Global.log_level": "error", "EngineConfig.onnxruntime.intra_op_num_threads": 4}
MODELS = {
    "v6 tiny (şimdiki)": {"Rec.model_type": ModelType.TINY},
    "v6 small (doğrulama)": {"Rec.model_type": ModelType.SMALL},
    "en v5 mobile": {"Rec.lang_type": LangRec.EN, "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE},
    "en v4 mobile": {"Rec.lang_type": LangRec.EN, "Rec.ocr_version": OCRVersion.PPOCRV4, "Rec.model_type": ModelType.MOBILE},
}
for extra in sys.argv[1:]:
    MODELS[os.path.basename(extra)] = {"Rec.model_path": extra}

gold = json.load(open(os.path.join(HERE, "gold.json"), encoding="utf-8"))
imgs = [cv2.imread(os.path.join(HERE, os.environ.get("ROWS", "rows2"), g["id"])) for g in gold]
SUBST = {"’": "'", "‘": "'", "“": '"', "”": '"', "…": "..."}


def norm(t):
    return " ".join("".join(SUBST.get(c, c) for c in t).split())


results = {}
for name, params in MODELS.items():
    try:
        eng = RapidOCR(params={**BASE, **params})
    except Exception as e:  # noqa: BLE001
        print(name, "yüklenemedi:", e)
        continue
    for img in imgs[:5]:
        eng(img, use_det=False, use_cls=False)             # warm up
    times, errs, exact, names, named = [], 0.0, 0, 0, 0
    wrong = []
    for img, g in zip(imgs, gold):
        t0 = time.perf_counter()
        r = eng(img, use_det=False, use_cls=False)
        times.append((time.perf_counter() - t0) * 1000)
        text = norm(r.txts[0]) if r.txts else ""
        e = L.distance(text, g["label"]) / max(1, len(g["label"]))
        errs += e
        exact += text == g["label"]
        want = filters.split_speaker(g["label"])[0]
        if want:
            named += 1
            names += filters.split_speaker(text)[0] == want
        if text != g["label"]:
            wrong.append((g["label"], text))
    n = len(gold)
    results[name] = {"cer": errs / n, "exact": exact / n, "names": f"{names}/{named}",
                     "ms": statistics.median(times), "wrong": wrong[:12]}
    print(f"{name:26} hata %{100 * errs / n:5.2f}  tam doğru satır %{100 * exact / n:5.1f}  ad {names}/{named}  "
          f"satır başına {statistics.median(times):5.1f} ms", flush=True)
json.dump(results, open(os.path.join(HERE, "bench.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
