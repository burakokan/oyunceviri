# PyInstaller recipe for the installed app (setup.exe). Build: packaging\build.bat
# Everything ends up next to OyunCeviri.exe (contents_directory "."), so gt.config.ROOT = the install folder,
# the same layout as the project folder: models\, vendor\, assets\, packs\, OyunCeviri-TV.apk.
# Never bundled: config.json (API keys), ps5.json (PS5 keys), tv-keys\ (TV certificates), logs\, packs\build\.
import glob
import sys
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
SITE = os.path.join(ROOT, ".venv", "Lib", "site-packages")
sys.path.insert(0, os.path.join(ROOT, "pc"))


def tree(folder, dest=None, skip=()):
    """All files of a project folder, kept at the same relative place (skip: sub folders left out)."""
    out = []
    base = os.path.join(ROOT, folder)
    for path in glob.glob(os.path.join(base, "**", "*"), recursive=True):
        if os.path.isfile(path) and not any(os.sep + s + os.sep in path for s in skip):
            rel = os.path.relpath(os.path.dirname(path), ROOT)
            out.append((path, rel if dest is None else dest))
    return out


LLAMA = os.path.join(ROOT, "vendor", "llama")
llama = [(p, os.path.join("vendor", "llama")) for p in
         [os.path.join(LLAMA, "llama-server.exe"), os.path.join(LLAMA, "LICENSE-LLVM-OpenMP")]
         + [p for p in glob.glob(os.path.join(LLAMA, "*.dll"))
            if not os.path.basename(p).startswith("cublas")
            and (not p.endswith("-impl.dll") or os.path.basename(p) == "llama-server-impl.dll")]]

datas = (tree("models/opus-mt-tc-big-en-tr") + tree("models/llm/gemma4e2b") + llama + tree("models/quickmt-en-tr") + tree("assets") + tree("vendor", skip=("llama",))
         + [(p, "packs") for p in glob.glob(os.path.join(ROOT, "packs", "*.json.gz"))]
         + [(p, os.path.join("packs", "fixes")) for p in glob.glob(os.path.join(ROOT, "packs", "fixes", "*.json"))]
         + [(os.path.join(ROOT, name), ".") for name in ("OyunCeviri-TV.apk", "OyunCeviri-Samsung.wgt", "OyunCeviri-LG.ipk")]
         + collect_data_files("rapidocr") + collect_data_files("windows_capture"))

binaries = ([(p, os.path.join("nvidia", "cublas", "bin"))
             for p in glob.glob(os.path.join(SITE, "nvidia", "cublas", "bin", "*.dll"))]
            + collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("onnxruntime"))

hiddenimports = (collect_submodules("gt") + collect_submodules("ui") + collect_submodules("winrt")
                 + ["rapidfuzz", "psutil", "sentencepiece", "websockets.asyncio.server", "paramiko"])

a = Analysis(
    [os.path.join(ROOT, "pc", "app.py")],
    pathex=[os.path.join(ROOT, "pc")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "dnfile", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OyunCeviri",
    icon=os.path.join(ROOT, "assets", "icon.ico"),
    console=False,
    upx=False,
    contents_directory=".",
)
coll = COLLECT(exe, a.binaries, a.datas, name="OyunCeviri", upx=False)
