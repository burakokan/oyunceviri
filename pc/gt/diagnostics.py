"""Genel → "Sorun bildir": the logs of the last sessions in one zip on the Desktop, to send to whoever helps.

What goes in: the app and TV app versions, Windows version, the settings WITHOUT any key (API keys, GitHub token),
the last sessions' readings and translations (logs/session-*.jsonl), the subtitle-area picture of every line
(logs/crops), a sample of the per-second pictures (logs/frames), the area translator's log, the Remote Play, TV
install, update, self-test and crash logs. Never in it: ps5.json (PS5 / PSN keys), tv-keys/ (TV certificates),
config.json as it is (it holds the keys).
"""
import copy
import json
import platform
import time
import zipfile
from pathlib import Path

from . import config
from .settings_io import SECRET_KEYS, _pop
from .version import TV_APP, TV_WEB, VERSION

SESSIONS = 3            # the last sessions' readings
CROPS_MAX = 400         # pictures of shown lines (last session)
FRAMES_MAX = 300        # per-second pictures, evenly picked (last session)
TEXT_TAIL = 400_000     # bytes kept from the end of the long text logs


def _newest(folder, pattern, n):
    return sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime)[-n:] if folder.is_dir() else []


def _tail(path):
    data = path.read_bytes()
    return data[-TEXT_TAIL:] if len(data) > TEXT_TAIL else data


def settings_without_keys(cfg):
    """The settings as config.json stores them (only what differs from the defaults), every key removed."""
    clean = config._diff(copy.deepcopy(cfg), config.DEFAULTS)
    for path in SECRET_KEYS:
        if _get_path(clean, path):
            _pop(clean, path)
            _set_path(clean, path, "(var, pakete konmadı)")
    return clean


def _get_path(d, path):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _set_path(d, path, value):
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = value


def make_bundle(cfg, root=None, dest=None, tv_clients=()):
    """-> path of the zip made in `dest` (default: the Desktop)."""
    root = Path(root or config.ROOT)
    logs = root / "logs"
    dest = Path(dest or Path.home() / "Desktop")
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"OyunCeviri-kayitlar-{time.strftime('%Y%m%d-%H%M')}.zip"
    info = {"made": time.strftime("%Y-%m-%d %H:%M:%S"), "app": VERSION, "tv_app": TV_APP, "tv_web": TV_WEB,
            "windows": platform.platform(), "python": platform.python_version(),
            "tv_clients": [{k: c.get(k) for k in ("ip", "version")} for c in tv_clients]}
    sessions = _newest(logs, "session-*.jsonl", SESSIONS)
    last = sessions[-1].stem[len("session-"):] if sessions else None
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bilgi.json", json.dumps(info, ensure_ascii=False, indent=1))
        z.writestr("ayarlar-anahtarsiz.json", json.dumps(settings_without_keys(cfg), ensure_ascii=False, indent=1))
        for s in sessions:
            z.write(s, f"logs/{s.name}")
        for name in ("remoteplay.log", "tv-install.log", "update.log", "selftest.txt", "crash.log"):
            p = logs / name
            if p.is_file():
                z.writestr(f"logs/{name}", _tail(p))
        for p in _newest(logs, "regions-*.jsonl", 2):
            z.writestr(f"logs/{p.name}", _tail(p))
        if last:
            crops = sorted((logs / "crops").glob(f"{last}-*.jpg"))[-CROPS_MAX:] if (logs / "crops").is_dir() else []
            for p in crops:
                z.write(p, f"logs/crops/{p.name}", compress_type=zipfile.ZIP_STORED)
            frames = sorted((logs / "frames" / last).glob("*.jpg")) if (logs / "frames" / last).is_dir() else []
            step = max(1, len(frames) // FRAMES_MAX)
            for p in frames[::step][:FRAMES_MAX]:
                z.write(p, f"logs/frames/{last}/{p.name}", compress_type=zipfile.ZIP_STORED)
    return path
