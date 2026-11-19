"""Is everything ready to play? One check per setup step, shared by the home page checklist and the PS5 page.
Each check returns (state, text): state is "ok", "warn" (works, but needs attention) or "missing"."""
from gt.remoteplay import DLL, active_roi, load_registration, uses_builtin
from gt.winutil import find_window


def ps5(win):
    cfg = win.cfg
    reg = load_registration()
    if cfg.get("capture", "auto") == "window" or not DLL.exists():
        hwnd, _ = find_window(cfg["window_process"])
        if hwnd:
            return "ok", "chiaki-ng penceresi açık"
        return "warn", "chiaki-ng penceresi kapalı — açıp PS5'e bağlan"
    if not reg:
        return "missing", "PS5 henüz kaydedilmedi"
    if uses_builtin(cfg) and win.rp.state == "connected":
        return "ok", f"Bağlı: {reg['nickname']}"
    if win.rp.state == "error":
        return "warn", f"{reg['nickname']} · bağlantı hatası: {win.rp.text}"
    return "ok", f"Kayıtlı: {reg['nickname']} (Başlat'a basınca bağlanır)"


def region(win):
    if active_roi(win.cfg):
        return "ok", "Seçildi"
    return "missing", "Altyazının çıktığı yer henüz seçilmedi"


def tv(win):
    clients = getattr(win, "tv_clients", [])
    if clients:
        return "ok", f"Bağlı ({clients[0]['ip']})"
    state, text = getattr(win, "tv_activation", (None, ""))
    if state in ("busy", "error"):
        return "warn", text
    if win.tv_kind() in ("samsung", "lg"):
        return "warn", "Bağlı değil — kurulum adımlarından sonra \"Kur ve aç\"a bas"
    return "warn", "Bağlı değil — \"TV'de aç\"a bas (TV'yi bulup uygulamayı kendisi açar)"
