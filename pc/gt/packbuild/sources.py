"""Where each game's English dialogue comes from, and how it is read into ordered lines.

Every source yields dicts {"scene", "speaker", "en"} in play order, so translation can use the lines before
as context. The texts stay on this PC for personal use only (fan wikis are CC BY-SA; game text is the
publisher's).
"""
import html
import re
import time

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GameTranslatePersonal/0.2"
SM = "https://marvels-spider-man.fandom.com/api.php"
RE = "https://residentevil.fandom.com/api.php"
FC = "https://farcry.fandom.com/api.php"
AC = "https://assassinscreedwiki.accesstheanimus.com/api.php"

# Extra instructions per game, so recurring names are translated the same way in every batch
SPIDER_NOTES = ('Always write "Spider-Man" as "Örümcek Adam" (no hyphen), also inside names: '
                '"Friendly Neighborhood Spider-Man" = "Dost Canlısı Örümcek Adam". '
                'Other hero and villain names (Venom, Rhino, Tinkerer, Underground, Prowler...) stay in English.')

SOURCES = [
    {"id": "far-cry-6", "title": "Far Cry 6", "kind": "fc6",
     "pages": ["Far Cry 6 oasisstrings subtitles.txt", "Far Cry 6 oasisstrings subtitles.txt (part 2)"],
     "about": "Oyun dosyasından çıkarılmış tüm altyazılar (DLC'ler dahil)"},
    {"id": "marvels-spider-man-remastered", "title": "Marvel's Spider-Man Remastered", "kind": "wiki", "api": SM,
     "pages": ["Marvel's Spider-Man script"], "about": "Wiki senaryosu: hikâye, DLC'ler, yan görevler, podcastler",
     "notes": SPIDER_NOTES},
    {"id": "marvels-spider-man-miles-morales", "title": "Marvel's Spider-Man: Miles Morales", "kind": "wiki", "api": SM,
     "pages": ["Miles Morales script"], "about": "Wiki senaryosu", "notes": SPIDER_NOTES},
    {"id": "resident-evil-village", "title": "Resident Evil Village", "kind": "wiki", "api": RE,
     "pages": ["Resident Evil Village/Transcript"], "categories": ["Resident Evil Village cutscenes"],
     "about": "Wiki transkripti + 69 ara sahne"},
    {"id": "resident-evil-4-remake", "title": "Resident Evil 4 (2023)", "kind": "wiki", "api": RE,
     "categories": ["Resident Evil 4 remake cutscenes"], "pages": ["Resident Evil 4/Transcript"],
     "about": "Remake ara sahneleri + orijinal RE4 tam transkripti (ortak replikler için)"},
    {"id": "metal-gear-solid-delta", "title": "Metal Gear Solid Delta: Snake Eater", "kind": "mgs3",
     "url": "https://raw.githubusercontent.com/amio/mgs-scripts/master/MGS3-SnakeEater/game-script.txt",
     "about": "MGS3 tam senaryo (ara sahneler + telsiz konuşmaları)"},
    {"id": "assassins-creed-valhalla", "title": "Assassin's Creed Valhalla", "kind": "ac",
     "categories": ["Memories of Eivor Varinsdottir"], "about": "Görev diyalogları (548 sayfa)"},
    {"id": "assassins-creed-mirage", "title": "Assassin's Creed Mirage", "kind": "ac",
     "categories": ["Memories of Basim ibn Ishaq"], "about": "Görev diyalogları (94 sayfa)"},
    {"id": "assassins-creed-origins", "title": "Assassin's Creed Origins", "kind": "ac",
     "categories": ["Memories of Bayek"], "about": "Görev diyalogları (195 sayfa)"},
    {"id": "assassins-creed-unity", "title": "Assassin's Creed Unity", "kind": "ac",
     "categories": ["Memories of Arno Dorian"], "about": "Görev diyalogları (180 sayfa)"},
    {"id": "assassins-creed-syndicate", "title": "Assassin's Creed Syndicate", "kind": "ac",
     "categories": ["Memories of Jacob Frye", "Memories of Evie Frye"], "about": "Görev diyalogları (274 sayfa)"},
    {"id": "assassins-creed-black-flag", "title": "Assassin's Creed IV Black Flag", "kind": "ac",
     "categories": ["Memories of Edward Kenway"], "about": "Görev diyalogları (144 sayfa); Resynced'in eski içeriği"},
    {"id": "assassins-creed-rogue", "title": "Assassin's Creed Rogue", "kind": "ac",
     "categories": ["Memories of Shay Cormac"], "about": "Görev diyalogları (42 sayfa)"},
    {"id": "assassins-creed-ezio-collection", "title": "Assassin's Creed: Ezio Collection", "kind": "ac",
     "categories": ["Memories of Ezio Auditore da Firenze"], "about": "AC II, Brotherhood, Revelations (410 sayfa)"},
    {"id": "assassins-creed-iii", "title": "Assassin's Creed III Remastered", "kind": "ac",
     "categories": ["Memories of Ratonhnhaké:ton", "Memories of Haytham Kenway"], "about": "Görev diyalogları (178 sayfa)"},
    {"id": "assassins-creed-odyssey", "title": "Assassin's Creed Odyssey", "kind": "ac",
     "categories": ["Memories of Kassandra"], "about": "Görev diyalogları (806 sayfa, dallanan, eksikleri var)"},
]

_session = requests.Session()
_session.headers["User-Agent"] = UA


def _get(url, params=None, tries=4):
    for i in range(tries):
        try:
            r = _session.get(url, params=params, timeout=60)
            if r.status_code == 200:
                return r
        except requests.RequestException:
            pass
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"İndirilemedi: {url}")


def wikitext(api, page):
    j = _get(api, {"action": "parse", "page": page, "prop": "wikitext", "format": "json", "redirects": 1}).json()
    return j.get("parse", {}).get("wikitext", {}).get("*", "")


def category_pages(api, category):
    out, cont = [], {}
    while True:
        j = _get(api, {"action": "query", "list": "categorymembers", "cmtitle": f"Category:{category}",
                       "cmlimit": 500, "cmnamespace": 0, "format": "json", **cont}).json()
        out += [m["title"] for m in j["query"]["categorymembers"]]
        if "continue" not in j:
            return out
        cont = j["continue"]


def raw_page(api, page):
    """Page source; some wikis refuse index.php?action=raw, so the API is tried as well."""
    if "fandom.com" in api:          # Fandom answers action=raw with 403
        return wikitext(api, page)
    try:
        return _get(api.replace("api.php", "index.php"), {"title": page, "action": "raw"}, tries=2).text
    except RuntimeError:
        return wikitext(api, page)


# ---------------------------------------------------------------- wikitext cleanup

_LINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
_REF = re.compile(r"<ref[^>]*?/>|<ref[^>]*>.*?</ref>", re.S)
_TAG = re.compile(r"<[^>]+>")
_STAGE = re.compile(r"\[[^\]]*\]")
_LEAD_ACTION = re.compile(r"^\s*\((?:[^()]{1,60})\)\s*")
_HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")
_SPEAKER_LINE = re.compile(r"^\s*[*:#]*\s*'''\s*([^'\n]{1,60}?)\s*:?\s*'''\s*:?\s*(.+)$")


def clean(text):
    text = _REF.sub("", text)
    for _ in range(3):
        text = _TEMPLATE.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = text.replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
    text = _TAG.sub("", text)
    text = html.unescape(text).replace("'''", "").replace("''", "")
    text = _STAGE.sub("", text)
    text = _LEAD_ACTION.sub("", text)
    return re.sub(r"\s+", " ", text).strip(" -—")


_QUOTED = re.compile(r'^\s*[*:#]*\s*["“](.+)["”]\s*$')


def _unquote(text):
    if len(text) > 1 and text[0] in "\"“" and text[-1] in "\"”":
        return text[1:-1].strip()
    return text


def dialogue_lines(wiki, scene=""):
    """'''Speaker:''' line  ->  {"scene", "speaker", "en"}; headings become scene names.
    A quoted line without a speaker right after a speaker's line is that speaker continuing (RE wiki)."""
    last = None
    for raw in wiki.splitlines():
        h = _HEADING.match(raw.strip())
        if h:
            scene = clean(h.group(2)) or scene
            last = None
            continue
        m = _SPEAKER_LINE.match(raw)
        if m:
            speaker, text = clean(m.group(1)).rstrip(":"), _unquote(clean(m.group(2)))
        else:
            q = _QUOTED.match(raw)
            if not (q and last):
                if raw.strip() and not raw.strip().startswith(("<", "|", "-")):
                    last = None
                continue
            speaker, text = last, _unquote(clean(q.group(1)))
        if speaker.lower() in ("on-screen", "onscreen", "note", "text"):
            last = None
            continue
        last = speaker
        if text and re.search(r"[A-Za-z]", text):
            yield {"scene": scene, "speaker": speaker, "en": text}


def dialogue_section(raw):
    m = re.search(r"==\s*(Dialogue|Transcript|Script)\s*==(.*?)(\n==[^=]|\Z)", raw, re.S | re.I)
    text = m.group(2) if m else raw
    # <tabber> holds several versions (official English, literal translation...): keep the first one
    t = re.search(r"<tabber>\s*[^=|\n]*=(.*?)(\|-\||</tabber>)", text, re.S)
    return t.group(1) if t else text


# ---------------------------------------------------------------- per-source readers

_GLUED = re.compile(r"([.!?…])(?=[A-Z¿¡\"“])")


def read_fc6(src, progress):
    rows = []
    for page in src["pages"]:
        progress(f"İndiriliyor: {page}")
        for line in wikitext(FC, page).splitlines():
            parts = line.split("\t")
            if len(parts) == 4 and parts[0].startswith("0x"):
                text = clean(_GLUED.sub(r"\1 ", parts[3]))
                if text and re.search(r"[A-Za-z]", text):
                    rows.append((int(parts[2]), parts[1], text))
    rows.sort()   # the line ids roughly follow the order of the conversations
    return [{"scene": "", "speaker": f"S{sp[-4:]}", "en": text} for _, sp, text in rows]


def read_wiki(src, progress):
    out = []
    api = src["api"]
    for page in src.get("pages", []):
        progress(f"İndiriliyor: {page}")
        out += dialogue_lines(wikitext(api, page))
    for cat in src.get("categories", []):
        pages = category_pages(api, cat)
        for i, page in enumerate(pages):
            progress(f"İndiriliyor: {cat} ({i + 1}/{len(pages)})")
            out += dialogue_lines(dialogue_section(raw_page(api, page)), scene=page)
    return out


def read_ac(src, progress):
    out = []
    for cat in src["categories"]:
        pages = category_pages(AC, cat)
        for i, page in enumerate(pages):
            progress(f"İndiriliyor: {page} ({i + 1}/{len(pages)})")
            out += dialogue_lines(dialogue_section(raw_page(AC, page)), scene=page)
    return out


_MGS_LINE = re.compile(r"^([A-Z][A-Za-z.' ]{1,25}):\s+(.+)$")


_PAREN = re.compile(r"\([^()]*\)")


def read_mgs3(src, progress):
    """Plain text: 'Speaker: line' wrapped over several lines, speeches separated by blank lines."""
    progress("İndiriliyor: MGS3 senaryosu")
    out, current = [], None
    for raw in _get(src["url"]).text.splitlines() + [""]:
        line = raw.strip()
        m = _MGS_LINE.match(line)
        if m:
            current = {"scene": "", "speaker": m.group(1).strip(), "en": m.group(2)}
            out.append(current)
        elif line and current is not None and not line.startswith(("=", "-", "*")):
            current["en"] += " " + line      # wrapped continuation of the same speech
        else:
            current = None                    # blank line / section marker ends the speech
    for row in out:
        row["en"] = clean(_PAREN.sub("", row["en"]))   # stage directions are not subtitled
    return [r for r in out if re.search(r"[A-Za-z]", r["en"])]


READERS = {"fc6": read_fc6, "wiki": read_wiki, "ac": read_ac, "mgs3": read_mgs3}


def read(src, progress=lambda text: None):
    return READERS[src["kind"]](src, progress)
