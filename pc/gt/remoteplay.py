"""Built-in PS5 Remote Play: no chiaki-ng window needed.

Uses couchsubs_native.dll (libchiaki + FFmpeg, from CouchSubs, AGPL-3.0) through ctypes and the
console registration made on the PS5 page (ps5.json, see ps5link.py); an older chiaki-ng /
GameTranslator registration in chiaki-ng.ini is used when there is none. The session runs in a
child process (the DLL can crash on some protected content); frames reach this process through
shared memory. Fixed by the DLL: PS5 only, 1080p, 30 fps, H.264, no audio, no controller input.
"""
import base64
import configparser
import ctypes as C
import multiprocessing as mp
import os
import queue
import threading
import time
from multiprocessing import shared_memory

import numpy as np

from .config import ROOT

DLL = ROOT / "vendor" / "couchsubs_native.dll"
RP_LOG = ROOT / "logs" / "remoteplay.log"


def _rp_log(text):
    """logs/remoteplay.log: state changes and libchiaki's error messages (why a session ended)."""
    try:
        RP_LOG.parent.mkdir(exist_ok=True)
        with open(RP_LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(text).rstrip() + "\n")
    except OSError:
        pass
CHIAKI_INI = os.path.join(os.environ.get("APPDATA", ""), "chiaki-ng", "chiaki-ng.ini")
MAX_W, MAX_H = 1920, 1080
HEADER = 16  # uint64 sequence, uint32 width, uint32 height
QUIT_REASONS = {
    0: "bağlantı kapandı",
    1: "PS5 başka bir Remote Play bağlantısında (chiaki-ng açık mı?)",
    2: "PS5 kaydı reddedildi — PS5 Bağlantısı sayfasından yeniden kaydet",
    3: "ağ bağlantısı koptu",
    4: "bağlantı hatası",
}


def _qt_bytes(value):
    """chiaki-ng.ini values: plain hex (GameTranslator) or Qt '@ByteArray(...)' with escapes."""
    value = value.strip().strip('"')
    if value.startswith("@ByteArray(") and value.endswith(")"):
        raw = value[len("@ByteArray("):-1]
        return raw.encode("latin1").decode("unicode_escape").encode("latin1")
    try:
        return bytes.fromhex(value)
    except ValueError:
        return base64.b64decode(value)


def load_registration():
    """-> dict(host, nickname, regist_key, morning, account) of the registered PS5, or None."""
    from . import ps5link
    return ps5link.load() or _chiaki_registration()


def _chiaki_registration(path=CHIAKI_INI):
    """The first PS5 chiaki-ng (or GameTranslator) registered."""
    if not os.path.exists(path):
        return None
    cp = configparser.RawConfigParser()
    cp.optionxform = str
    try:
        cp.read(path, encoding="utf-8-sig")
        h = cp["registered_hosts"]
        if int(h.get("size", "0")) < 1:
            return None
        reg = {
            "host": h["1\\host"].strip(),
            "nickname": h.get("1\\server_nickname", "PS5").strip(),
            "regist_key": _qt_bytes(h.get("1\\rp_regist_key") or h["1\\regist_key"]),
            "morning": _qt_bytes(h["1\\rp_key"]),
            "account": _qt_bytes(cp["General"]["user_id"]),
        }
    except (KeyError, ValueError):
        return None
    if (len(reg["regist_key"]), len(reg["morning"]), len(reg["account"])) != (16, 16, 8):
        return None
    return reg


def uses_builtin(cfg):
    cap = cfg.get("capture", "auto")
    return cap == "builtin" or (cap == "auto" and DLL.exists() and load_registration() is not None)


def needs_link(cfg):
    """The built-in Remote Play is there but no PS5 is registered yet: the PS5 page comes first (chiaki-ng is only
    used when it is chosen on purpose)."""
    return cfg.get("capture", "auto") != "window" and DLL.exists() and load_registration() is None


def active_roi(cfg):
    return cfg.get("roi_builtin") if uses_builtin(cfg) else cfg.get("roi")


# ---------------------------------------------------------------- child process

def _session_worker(reg, shm_name, lock, status, stop, may_wake=True):
    """Runs in the child process: wake the PS5 if needed (may_wake), stream, copy frames into shared memory."""
    LOG = C.CFUNCTYPE(None, C.c_int, C.c_char_p, C.c_void_p)
    FRAME = C.CFUNCTYPE(None, C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_void_p)
    EVENT = C.CFUNCTYPE(None, C.c_int, C.c_int, C.c_char_p, C.c_void_p)
    CONSOLE = C.CFUNCTYPE(None, C.c_char_p, C.c_char_p, C.c_int, C.c_void_p)
    dll = C.CDLL(str(DLL))
    dll.cs_init.restype = C.c_int
    dll.cs_discover.argtypes = [C.POINTER(C.c_char_p), C.c_int, C.c_int, CONSOLE, C.c_void_p]
    dll.cs_discover.restype = C.c_int
    dll.cs_wake.argtypes = [C.c_char_p, C.c_uint64]
    dll.cs_wake.restype = C.c_int
    dll.cs_session_start.argtypes = [C.c_char_p] * 4 + [C.c_int, FRAME, EVENT, LOG, C.c_void_p]
    dll.cs_session_start.restype = C.c_void_p
    dll.cs_session_stop.argtypes = [C.c_void_p]
    dll.cs_session_stop.restype = None

    shm = shared_memory.SharedMemory(name=shm_name)
    header = np.ndarray((2,), dtype=np.uint64, buffer=shm.buf[:HEADER])
    pixels = np.ndarray((MAX_H * MAX_W * 4,), dtype=np.uint8, buffer=shm.buf[HEADER:])
    host = reg["host"].encode()
    quit_event = threading.Event()
    seq = [0]

    @FRAME
    def on_frame(ptr, w, h, stride, _user):
        # libchiaki's network thread: copy and return quickly.
        if w > MAX_W or h > MAX_H:
            return
        src = np.ctypeslib.as_array((C.c_uint8 * (stride * h)).from_address(ptr)).reshape(h, stride)
        with lock:
            pixels[:h * w * 4].reshape(h, w * 4)[:] = src[:, :w * 4]
            seq[0] += 1
            header[0] = seq[0]
            header[1] = (w << 32) | h

    @EVENT
    def on_event(ev, why, text, _user):
        if ev == 0:
            status.put(("connected", "PS5'e bağlandı"))
        elif ev == 1:
            status.put(("quit", QUIT_REASONS.get(why, "bağlantı kapandı")))
            quit_event.set()
        elif ev == 2:
            status.put(("error", "PS5 kullanıcı giriş şifresi istiyor — ikinci hesabın giriş şifresini kapat"))
            quit_event.set()

    @LOG
    def on_log(level, msg, _user):
        if level == 0 and msg:
            status.put(("log", msg.decode("utf-8", "replace")[:200]))

    @CONSOLE
    def on_console(_host, _name, awake, _user):
        found.append(awake)

    try:
        if dll.cs_init() != 0:
            status.put(("error", "Remote Play kütüphanesi başlatılamadı"))
            return
        found = []
        targets = (C.c_char_p * 1)(host)
        status.put(("connecting", f"{reg['nickname']} aranıyor…"))
        dll.cs_discover(targets, 1, 1500, on_console, None)
        if found and not any(found):
            if not may_wake:
                # Reconnecting by itself after a drop: a PS5 that went to rest mode was turned off on purpose.
                status.put(("asleep", "PS5 bekleme modunda (kapatılmış). Açınca kendiliğinden bağlanır."))
                return
            status.put(("connecting", "PS5 bekleme modunda, uyandırılıyor…"))
            dll.cs_wake(host, int(reg["regist_key"].rstrip(b"\0"), 16))
            for _ in range(10):
                if stop.is_set():
                    return
                found.clear()
                dll.cs_discover(targets, 1, 2000, on_console, None)
                if found and any(found):
                    break
        status.put(("connecting", "Remote Play bağlantısı kuruluyor…"))
        session = dll.cs_session_start(host, reg["regist_key"], reg["morning"], reg["account"], 30,
                                       on_frame, on_event, on_log, None)
        if not session:
            status.put(("quit", "bağlantı kurulamadı"))
            return
        parent = mp.parent_process()
        try:
            # Also stop when the app itself is gone (killed), so the PS5 is not left streaming.
            while not stop.is_set() and not quit_event.is_set() and (parent is None or parent.is_alive()):
                stop.wait(0.2)
        finally:
            dll.cs_session_stop(session)
    finally:
        del header, pixels
        shm.close()


# ---------------------------------------------------------------- parent side

class RemotePlay:
    """One built-in Remote Play session shared by the engine and the preview (reference counted).

    Reconnects with back-off while anyone holds it; reports status through on_status(state, text).
    """

    def __init__(self, on_status=lambda state, text: None):
        self.on_status = on_status
        self.state = "off"
        self.text = ""
        self._users = 0
        self._lock = threading.Lock()
        self._thread = None
        self._wanted = threading.Event()
        self._may_wake = True
        self._shm = None
        self._frame_lock = None

    @staticmethod
    def available():
        return DLL.exists() and load_registration() is not None

    def acquire(self):
        with self._lock:
            self._users += 1
            if self._users == 1:
                # Başlat (or opening the preview) may wake the PS5; reconnecting after a drop never does.
                self._may_wake = True
                self._wanted.set()
                if not (self._thread and self._thread.is_alive()):
                    self._thread = threading.Thread(target=self._supervise, daemon=True)
                    self._thread.start()

    def release(self):
        with self._lock:
            self._users = max(0, self._users - 1)
            if self._users == 0:
                self._wanted.clear()

    def _set(self, state, text):
        self.state, self.text = state, text
        _rp_log(f"[{state}] {text}")
        self.on_status(state, text)

    def _supervise(self):
        ctx = mp.get_context("spawn")
        delay = 1
        last_connected = None       # when the last session ended (a drop is followed by a quick reconnect)
        self._frame_lock = ctx.Lock()
        self._shm = shared_memory.SharedMemory(create=True, size=HEADER + MAX_W * MAX_H * 4)
        np.ndarray((2,), dtype=np.uint64, buffer=self._shm.buf[:HEADER])[:] = 0
        try:
            while self._wanted.is_set():
                reg = load_registration()
                if reg is None:
                    self._set("error", "Kayıtlı PS5 yok. PS5 Bağlantısı sayfasından PS5'i bağla.")
                    time.sleep(5)
                    continue
                status, stop = ctx.Queue(), ctx.Event()
                proc = ctx.Process(target=_session_worker,
                                   args=(reg, self._shm.name, self._frame_lock, status, stop, self._may_wake),
                                   daemon=True)
                started = time.monotonic()
                proc.start()
                connected_at = None
                last_seq, last_frame_at = 0, time.monotonic()
                while self._wanted.is_set() and proc.is_alive():
                    try:
                        state, text = status.get(timeout=0.5)
                        if state == "log":
                            _rp_log("  chiaki: " + text)
                            continue
                        if state == "connected":
                            connected_at = time.monotonic()
                            last_frame_at = connected_at
                            delay = 1
                            self._may_wake = False
                            _rp_log(f"  bağlantı {connected_at - started:.1f} sn'de kuruldu")
                        self._set(state, text)
                        if state in ("quit", "error", "asleep"):
                            break
                    except queue.Empty:
                        pass
                    seq = self.seq
                    if seq != last_seq:
                        last_seq, last_frame_at = seq, time.monotonic()
                    elif connected_at and time.monotonic() - last_frame_at > 5:
                        self._set("quit", "görüntü 5 sn dondu, yeniden bağlanılıyor")
                        break
                if connected_at:
                    last_connected = time.monotonic()
                    _rp_log(f"  oturum {last_connected - connected_at:.0f} sn sürdü")
                stop.set()
                proc.join(4)
                if proc.is_alive():
                    proc.terminate()
                if not self._wanted.is_set():
                    break
                if proc.exitcode not in (0, None) and self.state not in ("quit", "error", "asleep"):
                    self._set("quit", f"Remote Play süreci kapandı (kod {proc.exitcode}; korumalı içerik olabilir)")
                # Right after a drop: retry every 1-5 s (the PS5 may still hold the old session for a moment);
                # otherwise slower. A PS5 in rest mode is only looked for every 10 s (looking does not wake it).
                recent = last_connected is not None and time.monotonic() - last_connected < 300
                wait = 10 if self.state == "asleep" else delay
                for _ in range(int(wait * 10)):
                    if not self._wanted.is_set():
                        break
                    time.sleep(0.1)
                delay = min(delay * 2, 5 if recent else 30)
        finally:
            shm, self._shm = self._shm, None
            time.sleep(0.3)
            shm.close()
            shm.unlink()
            self._set("off", "Remote Play kapalı")

    # ---- frame access ----

    @property
    def seq(self):
        shm = self._shm
        if shm is None:
            return 0
        return int(np.ndarray((2,), dtype=np.uint64, buffer=shm.buf[:HEADER])[0])

    def frame(self, roi=None):
        """-> (seq, BGR copy of the frame or of the roi part) or (seq, None)."""
        shm, lock = self._shm, self._frame_lock
        if shm is None or lock is None:
            return 0, None
        header = np.ndarray((2,), dtype=np.uint64, buffer=shm.buf[:HEADER])
        with lock:
            seq = int(header[0])
            if not seq:
                return 0, None
            w, h = int(header[1]) >> 32, int(header[1]) & 0xFFFFFFFF
            img = np.ndarray((h, w, 4), dtype=np.uint8, buffer=shm.buf[HEADER:HEADER + w * h * 4])
            if roi:
                x, y, rw, rh = roi
                img = img[int(y * h):int((y + rh) * h), int(x * w):int((x + rw) * w)]
            return seq, img[:, :, :3].copy()


class RemotePlaySource:
    """Frame source for the engine / preview (same interface as capture.WindowGrabber)."""

    def __init__(self, rp, roi=None):
        self.rp = rp
        self.roi = roi
        self.closed = False
        rp.acquire()

    def next(self, last_seq, timeout=1.0):
        end = time.perf_counter() + timeout
        while True:
            if self.rp.seq != last_seq:
                seq, img = self.rp.frame(self.roi)
                if img is not None:
                    return seq, (time.perf_counter(), img)
            if time.perf_counter() >= end:
                return last_seq, None
            time.sleep(0.003)

    def stop(self):
        if not self.closed:
            self.closed = True
            self.rp.release()
