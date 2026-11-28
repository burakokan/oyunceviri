"""Versions: the PC app, and the TV apps it carries (packaging/publish.py and the updater read these)."""
VERSION = "1.2.0"
TV_APP = "1.5"      # Android TV app: tv/app/build.gradle.kts versionName
TV_WEB = "1.7"      # Samsung / LG web app: tv-web/app.js VERSION ("1.2-web")
# Where updates come from: GitHub Releases of this (public) repository
REPO = "burakokan/oyunceviri"


def parse(v):
    """"v1.2" / "1.2.0-web-tizen" -> (1, 2, 0), for comparing versions."""
    out = []
    for part in str(v).strip().lstrip("vV").split("-")[0].split("."):
        out.append(int(part) if part.isdigit() else 0)
    return tuple((out + [0, 0, 0])[:3])
