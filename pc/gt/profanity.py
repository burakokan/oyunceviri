"""Undo the softening of swear words by the translation model.

OPUS-MT keeps many swear words ("Fuck!" -> "Siktir!", "Son of a bitch!" -> "Orospu çocuğu!") but
softens others ("Shit!" -> "Kahretsin!", "What the fuck was that?" -> "Bu da neydi böyle?").
Each rule fires only when the English line contains the swear word, so ordinary uses of
"Kahretsin" or "pislik" stay untouched.
"""
import re

# (English pattern, softened Turkish, unsoftened Turkish)
RULES = [
    (r"\bholy shit\b", r"\b[Vv]ay anas[ıi]n[ıi]\b|\b[Vv]ay be\b|\b[Hh]ay aksi\b", "Hassiktir"),
    (r"\bshit\b", r"\b[Kk]ahretsin\b|\b[Ll]anet olsun\b|\b[Hh]ay aksi\b|\b[Tt]üh\b", "Siktir"),
    (r"\bmother ?fuck", r"\b[Aa]şağılık herif\b|\b[Pp]islik\b|\b[Ş]erefsiz\b", "Orospu çocuğu"),
    (r"\bfuck (you|off)\b", r"\b[Cc]anın cehenneme\b|\b[Dd]efol( git)?\b|\b[Kk]ahrol\b", "Siktir git"),
    (r"\bfuck\b(?! (you|off))", r"\b[Kk]ahretsin\b|\b[Ll]anet olsun\b|\b[Hh]ay aksi\b", "Siktir"),
    (r"\bbullshit\b", r"\b[Ss]açmalık\b|\b[Ss]açmalama\b", "Hassiktir"),
    (r"\bassholes?\b", r"\b[Pp]islik\b|\b[Aa]şağılık\b", "göt herif"),
    (r"\bassholes?\b", r"(?<!göt )(?<!Göt )\b(?=herif)", "göt "),
    (r"\bpricks?\b", r"\b[Pp]islik\b", "şerefsiz"),
    (r"\bdick(head)?s?\b", r"\b[Pp]islik\b", "yarak kafalı"),
    (r"\bbitch(es)?\b", r"\b[Ss]ürtük\b|\b[Kk]altak\b", "orospu"),
    (r"\bcunts?\b", r"\b[Pp]islik\b|\b[Ss]ürtük\b", "amcık"),
]
_STRONG = re.compile(r"sik|siktir|orospu|piç|amk|amına|göt|yarak|amcık|bok", re.I)
# "What the fuck ...", "Got your fucking uranium" are often translated without any swear word at all;
# then one is added in front so the tone survives.
_WTF = re.compile(r"\bfuck\w*|\bshit\w*|\bmotherfuck\w*", re.I)
_COMPILED = [(re.compile(en, re.I), re.compile(tr), out) for en, tr, out in RULES]


def _match_case(found, replacement):
    return replacement[0].upper() + replacement[1:] if found[:1].isupper() else replacement


def uncensor(english, turkish):
    for en, tr, out in _COMPILED:
        if en.search(english):
            turkish = tr.sub(lambda m: _match_case(m.group(0), out), turkish, count=1)
    # No "Siktir, " glued in front any more: "fuckin'" / "this shit" are mostly emphasis, and a curse added at the
    # start changed the line ("They will pick you up for fuckin' anything" -> "Siktir, seni …").
    return turkish
