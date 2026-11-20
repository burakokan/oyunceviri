"""Settings carried to another PC: Genel → "Ayarları taşı" writes them to a file and reads them back there.

Only what is the same on every PC goes into the file: subtitle and area choices, filters, translation engine,
TV look, speaker colours… What belongs to one PC / one TV stays out and is set up again there: the PS5 link and
PSN account (ps5.json is never touched), the TV's address and brand, chiaki-ng's path, the first-run guide, and the
reading thresholds (brightness / colour: they depend on that PS5's picture). The API
keys (DeepL, Groq, Gemini, GitHub) go in only when the user says so; a file without keys never removes the keys a PC
already has.
"""
import copy
import json
import time

from . import config
from .version import VERSION

FORMAT = "oyun-ceviri-ayarlar"
# Never in the file, never changed by a file: set up on each PC.
# The reading thresholds belong here too: they fit one PS5's picture (HDR, the game's subtitle background, colour);
# 108 / 15 brought from another PC made a friend's subtitles unreadable. Each PC finds its own ("Otomatik ayarla").
DEVICE_KEYS = [("tv_ip",), ("tv_brand",), ("tv_app_brand",), ("chiaki_path",), ("window_process",), ("onboarded",),
               ("gemini", "building"), ("packs", "game"), ("text_v_min",), ("text_s_max",)]
# Only with the user's yes.
SECRET_KEYS = [("online", "deepl_key"), ("online", "groq_key"), ("gemini", "key"), ("update", "token")]


class SettingsFileError(Exception):
    """A file that is not an Oyun Çeviri settings file (message in Turkish)."""


def _get(d, path):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _pop(d, path):
    for k in path[:-1]:
        d = d.get(k)
        if not isinstance(d, dict):
            return
    d.pop(path[-1], None)


def _set(d, path, value):
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = value


def _prune(d):
    """Empty sections left after removing keys are dropped."""
    for k in list(d):
        if isinstance(d[k], dict):
            _prune(d[k])
            if not d[k]:
                del d[k]
    return d


def has_keys(cfg):
    return any(_get(cfg, p) for p in SECRET_KEYS)


def export(cfg, include_keys, tv_style=None, speakers=None):
    """-> the file's content (dict). Settings are written as they differ from the defaults, like config.json."""
    settings = config._diff(copy.deepcopy(cfg), config.DEFAULTS)
    for path in DEVICE_KEYS:
        _pop(settings, path)
    keys = {}
    for path in SECRET_KEYS:
        value = _get(cfg, path)
        _pop(settings, path)
        if include_keys and value:
            keys[".".join(path)] = value
    data = {"format": FORMAT, "app_version": VERSION, "made": time.strftime("%Y-%m-%d %H:%M"),
            "settings": _prune(settings)}
    if keys:
        data["keys"] = keys
    if tv_style:
        data["tv_style"] = tv_style
    if speakers:
        data["speaker_colors"] = speakers
    return data


def write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def read(path):
    """-> the file's content, checked."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        raise SettingsFileError("Dosya okunamadı ya da bozuk.")
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("settings"), dict):
        raise SettingsFileError("Bu bir Oyun Çeviri ayar dosyası değil.")
    return data


def summary(data):
    """A short Turkish description of what the file brings."""
    parts = [f"{data.get('made', '?')} tarihli, Oyun Çeviri {data.get('app_version', '?')}"]
    parts.append("API anahtarları VAR" if data.get("keys") else "API anahtarları yok (bu bilgisayardakiler kalır)")
    if data.get("tv_style"):
        parts.append("TV görünümü var")
    if data.get("speaker_colors"):
        parts.append(f"{len(data['speaker_colors'])} konuşmacı rengi")
    return " · ".join(parts)


def apply(cfg, data):
    """Bring the file's settings into cfg (in place). The PC's own settings (DEVICE_KEYS) and, unless the file has
    them, its API keys stay as they are. -> how many settings changed."""
    before = copy.deepcopy(cfg)
    incoming = copy.deepcopy(data["settings"])
    for path in DEVICE_KEYS + SECRET_KEYS:
        _pop(incoming, path)            # a hand-edited file cannot change them either
    fresh = copy.deepcopy(config.DEFAULTS)
    config._merge(fresh, incoming)      # every setting the file does not name goes back to its default
    for path in DEVICE_KEYS + SECRET_KEYS:
        value = _get(before, path)
        if value is not None:
            _set(fresh, path, value)
    for name, value in (data.get("keys") or {}).items():
        path = tuple(name.split("."))
        if path in SECRET_KEYS and isinstance(value, str):
            _set(fresh, path, value)
    cfg.clear()
    cfg.update(fresh)
    return _count_changes(before, cfg)


def _count_changes(a, b):
    n = 0
    for k in set(a) | set(b):
        x, y = a.get(k), b.get(k)
        if isinstance(x, dict) and isinstance(y, dict):
            n += _count_changes(x, y)
        elif x != y:
            n += 1
    return n
