"""Clean OCR text before it is tracked and translated."""
import re

# "Karl: text", "German Infantry: text" - up to four capitalized words before the colon
# A name: up to four capitalised words, "&" between two of them ("Kolt & Associates": without it the row went into
# the line above as plain text, "Vicki: … Kolt & Associates: What the fuck?", or on its own without a name, white).
_SPEAKER = re.compile(r"^\s*([A-Z][\w'’.\-]*(?:\s+(?:&\s+)?[A-Z][\w'’.\-]*){0,3})\s*:\s*(.+)$", re.S)
# A name OCR read a little wrong ("cO Wilson:", "CO wiison:"): one to three words before the colon, a capital in it.
_LOOSE_SPEAKER = re.compile(r"^\s*([A-Za-z][\w'’.\-]*(?:\s+[A-Za-z][\w'’.\-]*){0,2})\s*:\s*(.+)$", re.S)
# ...but not a sentence with a colon ("Here's the deal: …", "Listen up: …").
_NOT_NAME = {"a", "an", "the", "it", "is", "up", "to", "me", "you", "this", "that", "now", "here", "there", "and",
             "or", "of", "so", "what", "my", "your", "we", "i", "deal", "thing", "is", "are", "was", "do", "go",
             "him", "her", "them", "us", "he", "she", "they", "his", "its", "our", "their", "all", "then", "tell",
             "said", "say", "says", "look", "listen", "remember", "note", "rule", "one", "two", "first", "last"}
# The end of a name cut off by the area's edge: "ress: Another one?" (Waitress), "ison Recording: The Hamlet…"
_CUT_SPEAKER = re.compile(r"^\s*([a-z][a-z'’.\-]{0,11}(?:\s+[A-Z][\w'’.\-]*){0,2})\s*:\s*(.+)$", re.S)
# A cut-off name starts with this: the engine completes it from the names seen before ("…ress" -> "Waitress").
CUT = "…"
# A name with its colon as the row's first word ("M7:", "Joey:"): never trimmed as a HUD token
_NAME_TAG = re.compile(r"^[A-Z][\w'’.\-]*:$")
# Specks read in front of a row (". ", "• ", "'"): not part of a name
_LEAD_JUNK = re.compile(r"^[\s.,:;·•*'\"`´|\-–—]+")
# A lowercase letter or two glued in front of a name: "gJason"
_LOWER_NOISE = re.compile(r"^[a-z]{1,3}(?=[A-Z][a-z])")
# GTA's note on a line spoken in another language: "In Spanish: Take it…"
_LANGUAGE = re.compile(r"^\s*In [A-Z][a-z]+\s*:\s*")
# HUD letters stuck to the front of a name: "WARaiza" -> "Raiza"
_NAME_NOISE = re.compile(r"^[A-Z]{1,3}(?=[A-Z][a-z])")
# OCR reads the pronoun "I" as a lowercase "l"
_LOWER_L = re.compile(r"(?<![\w'’])l(?=('|’)(m|ll|ve|d)\b|\b)")


def _is_hud_token(token):
    """Ammo '30/120', distance '150m', timer '12:45', 'x3', '100%', a stray icon glyph or one HUD letter."""
    letters = sum(c.isalpha() for c in token)
    digits = sum(c.isdigit() for c in token)
    if digits == 0:
        if letters == 0:
            return True
        word = token.strip(".,!?:;")
        return len(word) <= 2 and word.islower() and word not in _SHORT_WORDS or (len(word) == 1 and word not in "IAa")
    return letters <= 2 and len(token) <= 10


_SMALL_WORDS = {"a", "an", "the", "as", "of", "to", "for", "in", "on", "at", "and", "or", "with", "into", "from"}
# Two-letter words that are real; other 1-2 letter lowercase tokens at the edges are icon misreads ("oo").
_SHORT_WORDS = {"a", "I", "an", "to", "of", "in", "on", "at", "is", "it", "we", "he", "me", "my", "no", "so",
                "go", "do", "be", "us", "up", "or", "oh", "ok", "hi", "if", "by", "am", "as", "an", "OK"}


_POSSESSIVE = re.compile(r"(?<=[A-Za-z])['’]s\b")


def _is_title(text):
    """HUD text, not dialogue:
    banners 'FORT QUITO' (all capitals), button prompts 'Collect Scraps', 'Enter as Driver'
    (short Title Case, no punctuation) and sound captions '(Combat Ends)'.
    Shouted dialogue ('ARGH!!', 'NO!') has punctuation and is kept."""
    stripped = text.strip()
    if stripped.startswith(("(", "[")) and stripped.endswith((")", "]")):
        return True
    words = stripped.split()
    # A possessive is no sign of dialogue: shop / place names "Chuck's Gun Shop", "Joey's".
    if not words or len(words) > 4 or any(c in ".!?…,:;'’\"" for c in _POSSESSIVE.sub("", stripped)):
        return False
    letters = [c for c in stripped if c.isalpha()]
    if len(letters) >= 3 and all(c.isupper() for c in letters):
        return True
    return all(w[:1].isupper() or w.lower() in _SMALL_WORDS for w in words) and words[0][:1].isupper()


def clean(text, f):
    """Apply the filter settings in `f` (cfg["filters"]) to every screen row (rows are separated by
    newlines); rows with nothing worth showing are dropped. Returns "" when nothing is left."""
    rows = (_clean_row(row, f) for row in text.split("\n"))
    return "\n".join(r for r in rows if r)


def _clean_row(text, f):
    for phrase in f.get("cut_phrases", []):
        if phrase:
            idx = text.find(phrase)
            if idx >= 0:
                text = text[:idx]
    lowered = text.lower()
    if any(p and p.lower() in lowered for p in f.get("ignore_lines", [])):
        return ""
    if f.get("hud_numbers", True):
        # Only the edges are trimmed: numbers inside a sentence ("5 minutes") belong to the dialogue,
        # and so does a number that ends the sentence ("back in the 70s.").
        tokens = text.split()
        # A speaker's name in front stays, also one with a digit ("M7: Let's go!" lost its "M7:" as a HUD token).
        name = [tokens.pop(0)] if tokens and _NAME_TAG.match(tokens[0]) else []
        while tokens and _is_hud_token(tokens[0]):
            tokens.pop(0)
        while tokens and _is_hud_token(tokens[-1]) and not tokens[-1].endswith((".", "!", "?", "…")):
            tokens.pop()
        text = " ".join(name + tokens) if tokens else ""
    text = _LOWER_L.sub("I", text.strip())
    if f.get("skip_titles", True) and _is_title(text):
        return ""
    letters = sum(c.isalpha() for c in text)
    if letters < f.get("min_letters", 3):
        return ""
    if f.get("hud_numbers", True):
        visible = sum(not c.isspace() for c in text)
        if letters / max(1, visible) < 0.5:
            return ""
    return text.strip()


def _clean_name(name):
    """HUD text glued to the front of a name: 'WARaiza' -> 'Raiza', 'Alarm TrigaJuan' -> 'Juan'."""
    words = name.split()
    for i in range(len(words) - 1, -1, -1):
        m = re.search(r"[a-z]([A-Z][a-z]+)$", words[i])
        if m:
            return m.group(1)
    return _NAME_NOISE.sub("", name)


# "In Spanish:" (also after the name: "M7: In Spanish: Let's go!") -> "Spanish"
_LANGUAGE_IN = re.compile(r"^\s*(?:[A-Z][\w'’.\-]*(?:\s+(?:&\s+)?[A-Z][\w'’.\-]*){0,3}\s*:\s*)?In ([A-Z][a-z]+)\s*:")
LANGUAGES_TR = {"Spanish": "İspanyolca", "French": "Fransızca", "Italian": "İtalyanca", "German": "Almanca",
                "Portuguese": "Portekizce", "Russian": "Rusça", "Chinese": "Çince", "Mandarin": "Çince",
                "Cantonese": "Kantonca", "Japanese": "Japonca", "Korean": "Korece", "Arabic": "Arapça",
                "Creole": "Kreolce", "Haitian": "Haiti dilinde", "Vietnamese": "Vietnamca", "Hindi": "Hintçe",
                "Polish": "Lehçe", "Ukrainian": "Ukraynaca", "English": "İngilizce"}


def language_of(row):
    """The game's note that a line is spoken in another language -> its Turkish name ("İspanyolca"), or None."""
    m = _LANGUAGE_IN.match(row)
    return LANGUAGES_TR.get(m.group(1), m.group(1)) if m else None


def split_speaker(text):
    """-> (speaker or None, line without the speaker). A name cut off by the area's edge comes as CUT + its end
    ("…ress"); a misread one as read with a capital first letter ("cO Wilson" -> "CO Wilson"). The game's note that
    a line is spoken in another language ("M7: In Spanish: Let's go!") is no speaker and is taken off the line (it
    is looked up and translated without it); language_of() gives it, and the TV shows it in Turkish."""
    text = _LANGUAGE.sub("", text, count=1)
    # A speck read in front of the name (".Jason: Hey." on a grey subtitle box) hid the name: it went into the line
    # as plain text and the TV showed it white, without the speaker's colour.
    name, body = _split_speaker(_LEAD_JUNK.sub("", text))
    if not name:
        return None, text
    return name, _LANGUAGE.sub("", body, count=1)


def _split_speaker(text):
    m = _SPEAKER.match(text)
    if m and len(m.group(1)) <= 30 and m.group(2).strip():
        return _clean_name(m.group(1)), m.group(2).strip()
    m = _LOOSE_SPEAKER.match(text)
    if m and m.group(2).strip() and len(m.group(1)) <= 24:
        words = m.group(1).split()
        lower = [w for w in words if not any(c.isupper() for c in w)]
        # The first word has a capital ("cO", "CO"); an all-lowercase first word is a cut-off name (below).
        if (words[0] not in lower and len(lower) <= 1
                and not any(w.lower() in _NOT_NAME for w in words)):
            name = _LOWER_NOISE.sub("", m.group(1))       # "gJason" -> "Jason" ("cO Wilson" stays)
            return name[0].upper() + name[1:], m.group(2).strip()
    m = _CUT_SPEAKER.match(text)
    if m and m.group(2).strip():
        return CUT + m.group(1), m.group(2).strip()
    return None, text


# Mission objectives and button hints ("Go with the prison guard", "Press [R1] to threaten the teller"): no speaker,
# no full stop, an imperative first word. They stay on screen for a long time, under the dialogue.
_HINT = re.compile(
    r"^(Press|Hold|Tap|Use|Go|Get|Wait|Follow|Find|Lose|Return|Drive|Enter|Head|Pick|Leave|Escape|Kill|Steal|"
    r"Reach|Meet|Talk|Collect|Deliver|Park|Stay|Aim|Shoot|Threaten|Rob|Grab|Open|Climb|Hide|Search|Exit|Take|"
    r"Bring|Chase|Protect|Defend|Destroy|Eliminate|Investigate|Help|Call|Answer|Buy|Change|Put|Board|Fly|Swim|"
    r"Run|Walk|Move|Select|Choose|Equip|Switch|Look|Watch|Check|Sit|Stand|Approach|Break|Evade|Cross|Jump|"
    r"Pull|Push|Turn|Toggle|Hack|Rotate|Zoom|Scroll|Hurry|Tail|Clear)\b")
_HINT_END = re.compile(r"[.!?…]['\"”’)]*\s*$")


def is_hint(text):
    """A mission objective / button hint, not dialogue."""
    t = text.strip()
    return bool(t) and len(t) <= 90 and not _HINT_END.search(t) and bool(_HINT.match(t))


def utterances(text):
    """Split a subtitle area showing several speakers' lines -> [line, ...].

    Every screen row that starts with "Name:" begins a new line; rows without a name continue
    the line above (a long line wraps onto two rows), except an objective / button hint row, which is its own line.
    """
    return [" ".join(g) for g in utterance_rows(text)]


def utterance_rows(text, starts=()):
    """Like utterances(), but each line as its screen rows -> [[row, ...], ...]. starts: rows known to begin a new
    subtitle although no name was read in front of them (by the spacing on screen)."""
    groups = []
    for row in (r.strip() for r in text.split("\n")):
        if not row:
            continue
        if not groups or split_speaker(row)[0] or is_hint(row) or _LANGUAGE.match(row) or row in starts:
            groups.append([row])
        elif is_hint(" ".join(groups[-1])):
            groups.append([row])        # dialogue under a hint row
        else:
            groups[-1].append(row)
    return groups


def correct(text, corrections):
    for wrong, right in corrections:
        if wrong:
            text = text.replace(wrong, right)
    return text
