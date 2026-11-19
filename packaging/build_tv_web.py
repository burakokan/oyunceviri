"""Packages tv-web/ (the Samsung / LG TV app) into
  OyunCeviri-Samsung.wgt  (Tizen widget; Samsung TVs install only signed widgets: sign it with a Samsung
                           certificate in Tizen Studio, see the TV page of the PC app)
  OyunCeviri-LG.ipk       (webOS package, installs with LG's Developer Mode + ares-install)
next to OyunCeviri-TV.apk in the project folder.  Run: .venv\\Scripts\\python.exe packaging\\build_tv_web.py
"""
import gzip
import io
import json
import tarfile
import time
import zipfile
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tv-web"
VERSION = "1.3.0"
WEBOS_ID = "com.oyunceviri.tv"
APP_FILES = ["index.html", "app.js", "style.css"]

TIZEN_CONFIG = f"""<?xml version="1.0" encoding="UTF-8"?>
<widget xmlns="http://www.w3.org/ns/widgets" xmlns:tizen="http://tizen.org/ns/widgets"
        id="http://oyunceviri.local/tv" version="{VERSION}" viewmodes="maximized">
    <tizen:application id="OyCvrTV001.OyunCeviri" package="OyCvrTV001" required_version="5.0"/>
    <content src="index.html"/>
    <feature name="http://tizen.org/feature/screen.size.normal.1080.1920"/>
    <icon src="icon.png"/>
    <name>Oyun Çeviri</name>
    <access origin="*" subdomains="true"/>
    <tizen:allow-navigation>*</tizen:allow-navigation>
    <tizen:privilege name="http://tizen.org/privilege/tv.window"/>
    <tizen:privilege name="http://tizen.org/privilege/tv.inputdevice"/>
    <tizen:privilege name="http://tizen.org/privilege/internet"/>
    <tizen:privilege name="http://tizen.org/privilege/network.get"/>
    <tizen:privilege name="http://tizen.org/privilege/application.launch"/>
    <tizen:profile name="tv-samsung"/>
    <tizen:setting screen-orientation="landscape" context-menu="disable" background-support="disable"
                   encryption="disable" install-location="auto" hwkey-event="enable"/>
</widget>
"""


def icon(size):
    img = cv2.imread(str(ROOT / "assets" / "icon.png"), cv2.IMREAD_UNCHANGED)
    ok, png = cv2.imencode(".png", cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA))
    return png.tobytes()


def wgt(out):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("config.xml", TIZEN_CONFIG)
        for name in APP_FILES:
            z.write(SRC / name, name)
        z.writestr("icon.png", icon(512))


def _tar_gz(files):
    """files: {path in archive: bytes} -> .tar.gz bytes (directories added)."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as tar:
        dirs = set()
        for path in files:
            parts = path.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                dirs.add("/".join(parts[:i]))
        for d in sorted(dirs):
            info = tarfile.TarInfo("./" + d)
            info.type, info.mode, info.mtime = tarfile.DIRTYPE, 0o755, int(time.time())
            tar.addfile(info)
        for path, data in files.items():
            info = tarfile.TarInfo("./" + path)
            info.size, info.mode, info.mtime = len(data), 0o644, int(time.time())
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _ar(members):
    out = bytearray(b"!<arch>\n")
    for name, data in members:
        header = (f"{name:<16}{int(time.time()):<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n").encode()
        out += header + data + (b"\n" if len(data) % 2 else b"")
    return bytes(out)


def ipk(out):
    app_dir = f"usr/palm/applications/{WEBOS_ID}"
    appinfo = {"id": WEBOS_ID, "version": VERSION, "vendor": "Oyun Ceviri", "type": "web", "main": "index.html",
               "title": "Oyun Çeviri", "icon": "icon.png", "largeIcon": "largeIcon.png",
               "resolution": "1920x1080", "disableBackHistoryAPI": True}
    files = {f"{app_dir}/{name}": (SRC / name).read_bytes() for name in APP_FILES}
    files[f"{app_dir}/appinfo.json"] = json.dumps(appinfo, ensure_ascii=False, indent=1).encode()
    files[f"{app_dir}/icon.png"] = icon(80)
    files[f"{app_dir}/largeIcon.png"] = icon(130)
    files[f"usr/palm/packages/{WEBOS_ID}/packageinfo.json"] = json.dumps(
        {"app": WEBOS_ID, "id": WEBOS_ID, "loc_name": "Oyun Çeviri", "package_format_version": 2,
         "vendor": "Oyun Ceviri", "version": VERSION}, ensure_ascii=False, indent=1).encode()
    size = sum(len(v) for v in files.values())
    control = (f"Package: {WEBOS_ID}\nVersion: {VERSION}\nSection: misc\nPriority: optional\nArchitecture: all\n"
               f"Installed-Size: {max(1, size // 1024)}\nMaintainer: Oyun Ceviri\n"
               f"Description: Oyun Ceviri TV app\nwebOS-Package-Format-Version: 2\n"
               f"webOS-Packager-Version: x.y.x\n").encode()
    Path(out).write_bytes(_ar([("debian-binary", b"2.0\n"), ("control.tar.gz", _tar_gz({"control": control})),
                               ("data.tar.gz", _tar_gz(files))]))


if __name__ == "__main__":
    wgt(ROOT / "OyunCeviri-Samsung.wgt")
    ipk(ROOT / "OyunCeviri-LG.ipk")
    for name in ("OyunCeviri-Samsung.wgt", "OyunCeviri-LG.ipk"):
        print(name, (ROOT / name).stat().st_size, "bytes")
