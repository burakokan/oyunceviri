import copy
import json
import os
import sys
from pathlib import Path

# Installed app (setup.exe, PyInstaller): everything lives next to OyunCeviri.exe; otherwise the project folder.
ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.json"
TV_APK = ROOT / "OyunCeviri-TV.apk"
ASSETS = ROOT / "assets"

DEFAULTS = {
    # "auto": built-in Remote Play when a registered PS5 is found, otherwise the chiaki-ng window
    "capture": "auto",
    "window_process": "chiaki.exe",
    "chiaki_path": os.path.expandvars(r"%LOCALAPPDATA%\Programs\chiaki-ng\chiaki-ng-Win\chiaki.exe"),
    # Subtitle area as fractions of the captured chiaki-ng window: [x, y, w, h]
    "roi": None,
    # ...and of the PS5 picture with built-in Remote Play (no window frame around it)
    "roi_builtin": None,
    # A pixel counts as subtitle text if it is bright and colorless (white text)
    "text_v_min": 200,
    "text_s_max": 60,
    "text_box": False,          # the game's own subtitle background is on: read the letters against it
    # How many consecutive frames must read the same before a line is shown
    "stable_reads": 2,
    # A line without sentence-ending punctuation must stay unchanged this long (word-by-word subtitles)
    "partial_wait_ms": 200,
    # Hold a sentence that continues on the next screen and show the whole sentence once, translated together
    "hold_unfinished": True,
    # ...but show the part we have if the screen does not change for this long
    "max_hold_ms": 4500,
    # Text reader: "windows" needs the English OCR language installed
    "ocr_engine": "trained",      # trained for game subtitles (assets/ocr); "rapid": standard tiny; "windows"
    # Read a settled line once more with the big (small-size, 4x slower) model. The trained model reads as well on
    # its own (checked on 132 rows by eye and 257 TV lines), so it is off: lines come ~30 ms sooner.
    "ocr_accurate": False,
    # Undo the model's softening of swear words ("Shit!" -> "Siktir!" instead of "Kahretsin!")
    "uncensored": True,
    # Write logs/session-*.jsonl and an image of the subtitle area for every line
    "debug_log": True,
    "ws_port": 8765,
    "translator": {
        # or "models/quickmt-en-tr": ~2.5x faster (15 vs 38 ms) but more literal
        "model": "models/opus-mt-tc-big-en-tr",
        "device": "cuda",
        "compute_type": "float16",
        "beam_size": 2,
    },
    "filters": {
        # Drop ammo counters, distances, timers and other number-only HUD text
        "hud_numbers": True,
        # Read only the text block over the screen center; HUD at the edges (location names) is ignored
        "centered": True,
        # Skip short ALL-CAPS text without punctuation: location / mission banners ("FORT QUITO")
        "skip_titles": True,
        "min_letters": 2,
        # Keep "Karl:" in front of the line (the name itself is not translated)
        "speaker_names": True,
        "speaker_color_game": True,     # the name's colour on the TV as the game shows it
        # In a game that writes "Name:" in front of every line (GTA 6 with speaker names on), lines without a name
        # are not shown (signs, HUD); objectives / button hints still are
        "names_only": False,
        # Text from these phrases to the end of the line is removed (HUD prompts)
        "cut_phrases": ["Swap "],
        # Lines containing any of these are ignored completely
        "ignore_lines": [],
        # A row on screen for 6 s while newer dialogue comes under it (objective, notice) is left out
        "sticky_rows": True,
        # A line without speaker / punctuation shown 3 times in 5 minutes is not shown for 10 minutes (signs, ads)
        "repeat_block": True,
    },
    # Fixes applied to the Turkish output: [["wrong", "right"], ...]
    "corrections": [],
    # Ready-made game translations (packs/): "auto" detects the game, "off", or a pack id
    "packs": {"game": "auto"},
    # Screen translation (menus, quests, map names) drawn over the English on the TV.
    # translator: "gemini" (accurate, needs the key, a few seconds) or "local" (the subtitle model)
    # look: bg auto (the game's own colour) | dark | none (no box, shadowed text); opacity %; text_scale % of the
    # English text's size; text_color auto | white | yellow. small_text: search at a higher resolution (slower).
    "screen": {"enabled": False, "translator": "gemini", "bg": "auto", "opacity": 90, "text_scale": 100,
               "text_color": "auto", "small_text": False},
    # Extra areas of the PS5 picture translated as a whole into ONE box on the TV (built-in Remote Play only):
    # hint = tutorial / objective box (button icons kept), phone = the in-game phone's messages, objective = the
    # short mission objective under the subtitles ("Go to the bank."; the subtitle reader leaves its area out).
    # roi: [x, y, w, h] fractions of the PS5 picture.
    # Reading: filter dark_box (white text in a dark box) | outlined (white text with a dark outline) | bright |
    # plain (text on a plain light or dark card: phone messages) | any; text_min: the letters' least brightness (0-255); bg_max: a dark box's most brightness; skip_menus: a
    # reading whose every word is capitalised and has no punctuation (the pause menu) is left out; ignore: phrases
    # whose readings are left out (the user's exceptions).
    # Look on the TV: place cover (over the English) | below | above | top | bottom (fixed, centred; offset % from
    # the edge); align left | center; size % of the English text; fg / bg colours; opacity % of the box (0: none,
    # shadowed text); keep_lines: the Turkish has as many lines as the English (smaller letters instead of a taller
    # box).
    "regions": {
        "hint": {"enabled": False, "roi": None, "filter": "dark_box", "text_min": 170, "bg_max": 80,
                 "skip_menus": True, "ignore": [],
                 "place": "cover", "offset": 8, "align": "left", "size": 100, "fg": "#FFFFFF", "bg": "#10151C",
                 "opacity": 92},
        "phone": {"enabled": False, "roi": None, "filter": "plain", "text_min": 170, "bg_max": 80,
                  "skip_menus": True, "ignore": [],
                  "place": "cover", "offset": 8, "align": "left", "size": 100, "fg": "#FFFFFF", "bg": "#10151C",
                  "opacity": 92},
        "objective": {"enabled": False, "roi": None, "filter": "outlined", "text_min": 190, "bg_max": 80,
                      "skip_menus": False, "ignore": [],
                      "place": "cover", "offset": 8, "align": "center", "size": 100, "fg": "#FFFFFF",
                      "bg": "#000000", "opacity": 80},
    },
    # Lines that are not in a game pack: smart (DeepL + Qwen + OPUS-MT, best of them) | deepl | groq |
    # gemma (Gemma 4 E2B on this PC) | local (OPUS-MT). deadline_ms: the longest wait for an online answer.
    # fallback: the model used when no online answer comes in time / no internet: nmt (OPUS-MT or quickmt,
    # see "translator") | gemma (Gemma 4 E2B on this PC)
    "mt": {"engine": "smart", "deadline_ms": 500, "fallback": "nmt"},
    "online": {"deepl_key": "", "groq_key": ""},
    # Pack builder: the user's own Gemini API key (stays on this PC) and model
    # building: unfinished packs continue by themselves when the app starts
    "gemini": {"key": "", "model": "gemini-3.5-flash-lite", "building": False},
    "minimize_to_tray": True,
    # In-place updates from GitHub Releases: auto = look for a new version at start and every hour and tell the
    # user (never downloaded or installed without the user's click, so the app never restarts during a game).
    # token: a read-only GitHub token, only needed if the repository is private again (stays on this PC).
    "update": {"auto": True, "token": ""},
    # The first-run guide ("Başlarken") was finished
    "onboarded": False,
    # A sentence that goes on (next screen, or the same row revealed further): the Turkish already on the TV stays
    # and only the rest is added under it on its own line (False: the whole sentence is written over the row)
    "append_rest": True,
    "tv_ip": "",
}


def _merge(base, user):
    for key, value in user.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def _diff(cfg, base):
    out = {}
    for key, value in cfg.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            sub = _diff(value, base[key])
            if sub:
                out[key] = sub
        elif key not in base or base[key] != value:
            out[key] = value
    return out


def load():
    cfg = copy.deepcopy(DEFAULTS)
    if CONFIG_PATH.exists():
        _merge(cfg, json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    return cfg


def save(cfg):
    """Only settings that differ from DEFAULTS are written, so new defaults still apply."""
    CONFIG_PATH.write_text(json.dumps(_diff(cfg, DEFAULTS), indent=2, ensure_ascii=False), encoding="utf-8")
