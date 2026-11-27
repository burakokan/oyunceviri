"""OyunCeviri.exe --selftest: checks every part without opening a window or touching the PS5 / TV, and writes
the result to logs/selftest.txt. For checking an installed copy on another PC."""
import multiprocessing as mp
import time
import traceback

import numpy as np

from . import config


def _child(q):
    q.put("ok")


def _checks(cfg):
    yield "Klasör", lambda: str(config.ROOT)
    yield "Dosyalar", lambda: ", ".join(f"{name}: {'var' if (config.ROOT / name).exists() else 'YOK'}" for name in (
        cfg["translator"]["model"], "vendor/couchsubs_native.dll", "vendor/adb/adb.exe", "OyunCeviri-TV.apk",
        "assets/icon.ico"))

    def translate():
        from .translate import LocalTranslator as Translator
        t = Translator(cfg["translator"]["model"], cfg["translator"]["device"], cfg["translator"]["compute_type"],
                       cfg["translator"]["beam_size"])
        start = time.perf_counter()
        out = t.translate("Let's get the hell out of here, now!")
        return f"{out!r} · {t.device} · {(time.perf_counter() - start) * 1000:.0f} ms"
    yield "Çeviri modeli", translate

    def ocr():
        import cv2
        from .ocr import make_ocr, text_mask
        img = np.zeros((70, 760, 3), np.uint8)
        cv2.putText(img, "Keep your head down, the sniper is out there.", (12, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (255, 255, 255), 2, cv2.LINE_AA)
        return repr(make_ocr("trained", accurate=False).read(img, text_mask(img, 160, 60)))
    yield "Yazı okuma (OCR)", ocr

    def finder():
        """The trained subtitle letter finder: a white, outlined line on a light, busy picture (where thresholds
        fail) must be found and read."""
        import cv2
        from .ocr import LetterFinder, letter_finder_model, make_ocr, subtitle_lines
        path = letter_finder_model()
        if path is None:
            raise RuntimeError("assets/ocr/altyazi_bulucu.onnx yok")
        rng = np.random.default_rng(3)
        img = np.clip(rng.normal(175, 35, (274, 1719, 3)), 0, 255).astype(np.uint8)
        for color, width in (((20, 20, 20), 6), ((250, 250, 250), 2)):
            cv2.putText(img, "Jason: Keep your head down, okay?", (520, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.1, color,
                        width, cv2.LINE_AA)
        start = time.perf_counter()
        f = LetterFinder(path)
        mask, cells = f.find(img, 0.5)
        rows = subtitle_lines(img, mask, 0.489, 120, widen=False, runs_mask=cells)
        found = (time.perf_counter() - start) * 1000
        return f"{make_ocr('trained', accurate=False).read(img, mask, boxes=rows)!r} · {found:.0f} ms"
    yield "Altyazı bulucu (yapay zekâ)", finder

    def packs():
        from .packs import PackLibrary
        lib = PackLibrary()
        end = time.time() + 60
        while not lib.ready and time.time() < end:
            time.sleep(0.1)
        return f"{len(lib.packs)} paket"
    yield "Oyun paketleri", packs

    def webengine():
        from PySide6 import QtWebEngineWidgets  # noqa: F401
        return "var"
    yield "PSN giriş penceresi (WebEngine)", webengine

    def remoteplay():
        from . import ps5link
        ps5link._native()
        return "yüklendi"
    yield "Remote Play bileşeni", remoteplay

    def child():
        q = mp.get_context("spawn").Queue()
        p = mp.get_context("spawn").Process(target=_child, args=(q,))
        p.start()
        got = q.get(timeout=60)
        p.join(30)
        return got
    yield "Arka plan işlemi (Remote Play için)", child

    def adb():
        from . import tvctl
        ok, out = tvctl._adb("version", timeout=30)
        return out.splitlines()[0] if ok else f"HATA: {out}"
    yield "TV bağlantı aracı (adb)", adb

    def gemma():
        from .conductor import Gemma
        g = Gemma()
        if not g.available():
            raise RuntimeError("dosyalar yok")
        try:
            start = time.perf_counter()
            if not g.start():
                raise RuntimeError("llama-server açılmadı")
            boot = (time.perf_counter() - start) * 1000
            out = g.translate("Hold your horses, kid.", "")
            return f"{out!r} · açılış {boot:.0f} ms · çeviri {g.last_ms:.0f} ms"
        finally:
            g.stop()
    yield "Gemma 4 (yedek model, ekran kartında)", gemma

    def samsung():
        import subprocess
        import tempfile
        from .tvweb import Samsung
        wgt = config.ROOT / "OyunCeviri-Samsung.wgt"
        out = __import__("pathlib").Path(tempfile.gettempdir()) / "oyunceviri-selftest.wgt"
        r = subprocess.run([str(Samsung.HELPER), "selftest-sign", str(wgt), str(out)], capture_output=True,
                           text=True, timeout=120, creationflags=0x08000000)
        out.unlink(missing_ok=True)
        if '"ok":true' not in r.stdout:
            raise RuntimeError((r.stdout + r.stderr).strip()[-300:])
        return "paket imzalanabiliyor"
    yield "Samsung TV kurulum aracı", samsung

    def lg():
        import paramiko
        return f"paramiko {paramiko.__version__}, paket: {'var' if (config.ROOT / 'OyunCeviri-LG.ipk').exists() else 'YOK'}"
    yield "LG TV kurulum aracı", lg


def run():
    cfg = config.load()
    lines, failed = [], 0
    for name, check in _checks(cfg):
        try:
            lines.append(f"[OK]   {name}: {check()}")
        except Exception as e:  # noqa: BLE001 - reported in the file
            failed += 1
            lines.append(f"[HATA] {name}: {e}\n{traceback.format_exc()}")
    lines.append("SONUÇ: " + ("hepsi çalışıyor" if not failed else f"{failed} sorun var"))
    out = config.ROOT / "logs" / "selftest.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failed else 0
