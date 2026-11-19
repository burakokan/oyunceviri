"""Register this PC with a PS5 for Remote Play, without chiaki-ng.

1. find the PS5 on the network (couchsubs_native.dll discovery),
2. the PSN account id of the second account: the user signs in on Sony's page inside the app (the redirect URL
   is caught by the app) or in the PC's browser (the copied redirect link is taken from the clipboard or pasted),
   and the code in it is turned into the 8-byte account id,
3. the 8-digit code from the PS5 (Settings > System > Remote Play > Link Device) -> registration keys.

The keys are saved in ps5.json next to config.json (never shown).
"""
import base64
import ctypes as C
import json
import re
import socket
import threading
import urllib.parse
import urllib.request

from .config import ROOT

DLL = ROOT / "vendor" / "couchsubs_native.dll"
REG_FILE = ROOT / "ps5.json"

# Sony's Remote Play app credentials (public; the same in chiaki, chiaki-ng, CouchSubs)
CLIENT_ID = "ba495a24-818c-472b-b12d-ff231c1b5745"
CLIENT_SECRET = "mvaiZkRsAsI1IBkY"
REDIRECT = "https://remoteplay.dl.playstation.net/remoteplay/redirect"
TOKEN_URL = "https://auth.api.sonyentertainmentnetwork.com/2.0/oauth/token"
SCOPE = ("psn:clientapp referenceDataService:countryConfig.read pushNotification:webSocket.desktop.connect "
         "sessionManager:remotePlaySession.system.update")
LOGIN_URL = ("https://auth.api.sonyentertainmentnetwork.com/2.0/oauth/authorize?" + urllib.parse.urlencode({
    "service_entity": "urn:service-entity:psn", "response_type": "code", "client_id": CLIENT_ID,
    "redirect_uri": REDIRECT, "scope": SCOPE, "request_locale": "tr_TR", "ui": "pr", "service_logo": "ps",
    "layout_type": "popup", "smcid": "remoteplay", "prompt": "always", "PlatformPrivacyWs1": "minimal",
}, quote_via=urllib.parse.quote))

# PS5's answer when registration fails ("Reported Application Reason")
REASONS = {
    0x80108B02: "Bu PSN hesabı PS5'te yok ya da Uzaktan Oynatma için bağlanmamış. PS5'te ikinci hesapla oturum "
                "açıp \"Cihazı Bağla\"yı o hesapla yap ve aynı hesapla giriş yap.",
    0x80108B09: "Kod kabul edilmedi. PS5'teki 8 haneli kodu yeniden kontrol et (kod birkaç dakikada yenilenir).",
    0x80108B10: "PS5 başka bir Remote Play bağlantısıyla meşgul. Diğer bağlantıyı kapatıp tekrar dene.",
    0x80108B11: "PS5'in sistem yazılımı ile Remote Play sürümü uyuşmuyor. PS5'i güncelleyip tekrar dene.",
    0x80108B15: "PS5 kayıt sırasında hata verdi. PS5'i yeniden başlatıp tekrar dene.",
}

LOG = C.CFUNCTYPE(None, C.c_int, C.c_char_p, C.c_void_p)
CONSOLE = C.CFUNCTYPE(None, C.c_char_p, C.c_char_p, C.c_int, C.c_void_p)


class RegisteredConsole(C.Structure):
    _fields_ = [("nickname", C.c_char * 32), ("regist_key", C.c_ubyte * 16), ("morning", C.c_ubyte * 16)]


class LinkError(Exception):
    pass


_dll = None
_lock = threading.Lock()


def _native():
    global _dll
    with _lock:
        if _dll is None:
            dll = C.CDLL(str(DLL))
            dll.cs_init.restype = C.c_int
            dll.cs_discover.argtypes = [C.POINTER(C.c_char_p), C.c_int, C.c_int, CONSOLE, C.c_void_p]
            dll.cs_discover.restype = C.c_int
            dll.cs_register.argtypes = [C.c_char_p, C.c_char_p, C.c_uint32, C.POINTER(RegisteredConsole),
                                        C.POINTER(C.c_uint32), LOG, C.c_void_p]
            dll.cs_register.restype = C.c_int
            if dll.cs_init() != 0:
                raise LinkError("Remote Play bileşeni başlatılamadı.")
            _dll = dll
        return _dll


# ---------------------------------------------------------------- 1. find the PS5

def _broadcasts():
    out = ["255.255.255.255"]
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 9))
            me = s.getsockname()[0]
        out.append(me.rsplit(".", 1)[0] + ".255")
    except OSError:
        pass
    return out


def discover(timeout_ms=3000, targets=None):
    """-> [{"host", "name", "awake"}] of the PS5s that answer (on, or in rest mode)."""
    dll = _native()
    found = {}

    @CONSOLE
    def on_console(host, name, awake, _user):
        h = host.decode(errors="replace")
        found[h] = {"host": h, "name": (name or b"PS5").decode(errors="replace"), "awake": bool(awake)}

    targets = targets or _broadcasts()
    arr = (C.c_char_p * len(targets))(*[t.encode() for t in targets])
    dll.cs_discover(arr, len(targets), timeout_ms, on_console, None)
    return list(found.values())


# ---------------------------------------------------------------- 2. PSN account id

def code_from_redirect(text):
    """The ?code=... of Sony's redirect after signing in, or None. Also takes a link copied from a browser's
    address bar (with spaces, quotes or without https://)."""
    text = (text or "").strip().strip("\"'<>")
    if "remoteplay/redirect" not in text:
        return None
    m = re.search(r"[?&]code=([^&#\s\"']+)", text)
    return urllib.parse.unquote(m.group(1)) if m else None


def error_from_redirect(text):
    """Sony's ?error=... when sign-in was refused, or None."""
    text = (text or "").strip()
    if "remoteplay/redirect" not in text:
        return None
    m = re.search(r"[?&]error_description=([^&#\s]+)", text) or re.search(r"[?&]error=([^&#\s]+)", text)
    return urllib.parse.unquote_plus(m.group(1)) if m else None


def _basic():
    return "Basic " + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()


def account_from_code(code):
    """-> 8-byte PSN account id (what Remote Play registration needs)."""
    body = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code, "scope": SCOPE,
                                   "redirect_uri": REDIRECT}).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST", headers={
        "Authorization": _basic(), "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            token = json.load(r)["access_token"]
        req = urllib.request.Request(f"{TOKEN_URL}/{token}", headers={"Authorization": _basic()})
        with urllib.request.urlopen(req, timeout=20) as r:
            user_id = int(json.load(r)["user_id"])
    except (OSError, ValueError, KeyError) as e:
        raise LinkError(f"PSN hesap bilgisi alınamadı ({e}). Girişi tekrar dene.") from e
    return user_id.to_bytes(8, "little")


# ---------------------------------------------------------------- 3. register with the 8-digit code

def register(host, account, pin):
    """-> registration dict (host, nickname, regist_key, morning, account). Raises LinkError."""
    if len(account) != 8:
        raise LinkError("PSN hesabı alınmadı; önce giriş yap.")
    digits = "".join(ch for ch in str(pin) if ch.isdigit())
    if len(digits) != 8:
        raise LinkError("Kod 8 haneli olmalı.")
    dll = _native()
    out = RegisteredConsole()
    reason = C.c_uint32(0)

    @LOG
    def on_log(_level, _msg, _user):
        pass

    result = dll.cs_register(host.encode(), bytes(account), int(digits), C.byref(out), C.byref(reason), on_log, None)
    if result == 0:
        return {"host": host, "nickname": out.nickname.decode(errors="replace") or "PS5",
                "regist_key": bytes(out.regist_key), "morning": bytes(out.morning), "account": bytes(account)}
    if result == 2:
        raise LinkError("Kayıt iptal edildi.")
    if reason.value in REASONS:
        raise LinkError(REASONS[reason.value])
    raise LinkError("PS5 yanıt vermedi ya da kaydı reddetti. PS5 açık mı, \"Cihazı Bağla\" ekranı ve kod hâlâ "
                    "görünüyor mu? Kontrol edip tekrar dene.")


def save(reg):
    REG_FILE.write_text(json.dumps({
        "host": reg["host"], "nickname": reg["nickname"], "regist_key": reg["regist_key"].hex(),
        "morning": reg["morning"].hex(), "account": base64.b64encode(reg["account"]).decode(),
    }, indent=1), encoding="utf-8")


def load():
    """-> the registration saved by this app, or None."""
    try:
        d = json.loads(REG_FILE.read_text(encoding="utf-8"))
        reg = {"host": d["host"], "nickname": d.get("nickname") or "PS5",
               "regist_key": bytes.fromhex(d["regist_key"]), "morning": bytes.fromhex(d["morning"]),
               "account": base64.b64decode(d["account"])}
    except (OSError, ValueError, KeyError):
        return None
    if (len(reg["regist_key"]), len(reg["morning"]), len(reg["account"])) != (16, 16, 8):
        return None
    return reg


def forget():
    try:
        REG_FILE.unlink()
    except OSError:
        pass
