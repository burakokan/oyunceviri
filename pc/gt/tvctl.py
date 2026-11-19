"""Find the TV on the network, install / update the TV app and start it, all with adb over the network.

adb comes with the app (vendor/adb); the Android SDK copy is only a fallback.
"""
import os
import re
import socket
import subprocess
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import ROOT

ADB_PORT = 5555
_BUNDLED = ROOT / "vendor" / "adb" / "adb.exe"
_SDK = Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
ADB = _BUNDLED if _BUNDLED.exists() else _SDK
PACKAGE = "com.gametranslate.tv"
_NO_WINDOW = 0x08000000


def _adb(*args, timeout=120):
    try:
        p = subprocess.run([str(ADB), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=_NO_WINDOW)
        return p.returncode == 0, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


# Adapters that are not the home network: VMs, WSL, VPNs and other virtual networks
_VIRTUAL = ("vethernet", "virtualbox", "vmware", "hyper-v", "wsl", "docker", "loopback", "bluetooth", "tailscale",
            "zerotier", "hamachi", "radmin", "wireguard", "wiresock", "openvpn", "nordlynx", "tap-", "tun")


def _route_ip():
    """The address Windows uses for the internet (no packet is sent); can be a VPN's."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("8.8.8.8", 9))
            return s.getsockname()[0]
        except OSError:
            return None


def lan_ips():
    """This PC's IPv4 addresses on local networks, the likely home network first (192.168.x, then the one used for
    the internet). VPN / virtual adapters are left out when they can be told apart by name."""
    import ipaddress
    try:
        import psutil
        stats = psutil.net_if_stats()
        found = []
        for name, addrs in psutil.net_if_addrs().items():
            st = stats.get(name)
            if not st or not st.isup or any(v in name.lower() for v in _VIRTUAL):
                continue
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith(("127.", "169.254."))                         and ipaddress.ip_address(a.address).is_private:
                    found.append(a.address)
    except Exception:  # noqa: BLE001 - psutil missing: only the internet route
        found = []
    route = _route_ip()
    if route and route not in found and ipaddress.ip_address(route).is_private:
        found.append(route)
    return sorted(dict.fromkeys(found), key=lambda ip: (not ip.startswith("192.168."), ip != route))


def local_ip():
    """This PC's address on the home network (the one the TV should use)."""
    ips = lan_ips()
    return ips[0] if ips else _route_ip()


def subnets():
    """The /24 networks to search for the TV: '192.168.1' …"""
    return list(dict.fromkeys(ip.rsplit(".", 1)[0] for ip in lan_ips()))[:4]


def pc_ip_for(tv_ip):
    """This PC's address on the TV's network (what the TV must be given as "Host PC IP")."""
    prefix = tv_ip.rsplit(".", 1)[0] if tv_ip else ""
    return next((ip for ip in lan_ips() if ip.startswith(prefix + ".")), local_ip())


def _open(ip, port=ADB_PORT, timeout=0.5):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def scan(progress=lambda t: None):
    """Addresses on the local /24 network with adb's network port open (Android / Google TVs)."""
    return scan_port(ADB_PORT, progress)


def scan_port(port, progress=lambda t: None):
    """Addresses on this PC's local /24 networks with this TCP port open."""
    mine = set(lan_ips())
    for net in subnets():           # the likely home network first; the others only when nothing is found
        progress(f"Ağda TV aranıyor ({net}.x)…")
        ips = [f"{net}.{i}" for i in range(1, 255) if f"{net}.{i}" not in mine]
        with ThreadPoolExecutor(max_workers=128) as pool:
            found = [ip for ip, ok in zip(ips, pool.map(lambda ip: _open(ip, port, 0.6), ips)) if ok]
        if found:
            return found
    return []


def _state(target):
    _adb("connect", target, timeout=15)
    ok, out = _adb("-s", target, "get-state", timeout=10)
    if ok and "device" in out:
        return "device"
    _, devices = _adb("devices")
    if f"{target}\tunauthorized" in devices:
        return "unauthorized"
    return None


def _target(ip):
    return ip if ":" in ip else f"{ip}:{ADB_PORT}"


def find_tv(hint, progress):
    """-> (ip, state): the saved address first, then the whole network. state: device / unauthorized / None."""
    tried = set()
    for ip in [hint] if hint else []:
        tried.add(ip)
        progress(f"TV'ye bağlanılıyor ({ip})…")
        if _open(ip.split(":")[0], timeout=1.0):
            state = _state(_target(ip))
            if state:
                return ip, state
    for ip in scan(progress):
        if ip in tried:
            continue
        progress(f"TV'ye bağlanılıyor ({ip})…")
        state = _state(_target(ip))
        if state:
            return ip, state
    return None, None


def _start_service(target, connected, progress):
    """Start the subtitle service without leaving the HDMI input; open the app only if that is not enough."""
    _adb("-s", target, "shell", "appops", "set", PACKAGE, "SYSTEM_ALERT_WINDOW", "allow")
    _adb("-s", target, "shell", "dumpsys", "deviceidle", "whitelist", f"+{PACKAGE}")
    progress("TV uygulaması başlatılıyor…")
    _adb("-s", target, "shell", "am", "broadcast", "-f", "0x20", "-n", f"{PACKAGE}/.BootReceiver")
    if _wait(connected, 6):
        return True
    # Background start refused (or turned off in the TV app): open the app once.
    progress("TV uygulaması açılıyor…")
    _adb("-s", target, "shell", "am", "start", "-n", f"{PACKAGE}/.MainActivity")
    return _wait(connected, 10)


# ---------------------------------------------------------------- HDMI input (the PS5's picture)

_HW = re.compile(r"TvInputHardwareInfo \{id=(\d+), type=9[^}]*?hdmi_port=(\d+)")
_LINKED = re.compile(r"TvInputHardwareInfo \{id=(\d+),[^}]*\}, mInfo: TvInputInfo\{id=([^,]+),")
_STATE = re.compile(r"TvInputInfo\{id=([^,]+),[^}]*\}; state: (\d)")


def hdmi_inputs(target):
    """-> [{"id", "port", "hw", "state"}] of the TV's HDMI inputs (state 0 = something is plugged in)."""
    _, out = _adb("-s", target, "shell", "dumpsys", "tv_input", timeout=20)
    ports = {int(m.group(1)): int(m.group(2)) for m in _HW.finditer(out)}       # hardware id -> HDMI port
    states = {m.group(1): int(m.group(2)) for m in _STATE.finditer(out)}       # input id -> state
    linked = {int(m.group(1)): m.group(2) for m in _LINKED.finditer(out)}      # hardware id -> input id
    found = []
    for hw, port in ports.items():
        iid = linked.get(hw) or next((i for i in states if i.endswith(f"/HW{hw}")), None)
        if iid:
            found.append({"id": iid, "port": port, "hw": hw, "state": states.get(iid, 2)})
    return sorted(found, key=lambda x: x["port"])


def _setting(target, name):
    _, out = _adb("-s", target, "shell", "settings", "get", "global", name, timeout=10)
    return out.strip()


def ps5_input(target, port=None):
    """The HDMI input the PS5 is on: the chosen port, else the last HDMI input used (TCL), else one in use."""
    inputs = hdmi_inputs(target)
    if not inputs:
        return None
    if port:
        return next((i for i in inputs if i["port"] == port), None)
    last = _setting(target, "tcl_sys_tv_input_last_device_id")
    if last.isdigit():
        hit = next((i for i in inputs if i["hw"] == int(last)), None)
        if hit:
            return hit
    return next((i for i in inputs if i["state"] == 0), inputs[0])


def show_ps5(target, port=None):
    """Switch the TV to the PS5's HDMI input (no-op if it is already on screen). -> the input or None."""
    inp = ps5_input(target, port)
    if not inp:
        return None
    _, focus = _adb("-s", target, "shell", "dumpsys", "window", "displays", timeout=10)
    current = _setting(target, "tcl_sys_tv_input_current_device_id")
    on_tv_app = re.search(r"mCurrentFocus=.*(TVActivity|tv\.TvActivity|LiveTv)", focus or "")
    if on_tv_app and current == str(inp["hw"]):
        return inp
    uri = "content://android.media.tv/passthrough/" + urllib.parse.quote(inp["id"], safe="")
    _adb("-s", target, "shell", "am", "start", "-a", "android.intent.action.VIEW",
         "-t", "vnd.android.cursor.item/channel", "-d", uri, timeout=15)
    return inp


def _wait(connected, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if connected():
            return True
        time.sleep(0.5)
    return connected()


def activate(hint, apk, progress, connected=lambda: False, found=lambda ip: None, hdmi_port=None):
    """One button: find the TV, install the app if it is missing, start it, then switch the TV to the PS5.
    -> (ok, message, ip). progress(text) is called for each step; connected() tells whether the TV app is
    connected to this PC (the WebSocket server sees it); found(ip) as soon as the TV's address is known."""
    if not ADB.exists():
        return False, "adb bulunamadı.", hint
    ip, state = find_tv(hint, progress)
    if ip:
        found(ip.split(":")[0])
    if not ip:
        return False, ("Ağda TV bulunamadı. TV açık mı ve bilgisayarla aynı modeme bağlı mı? TV'de Geliştirici "
                       "seçenekleri > USB hata ayıklama açık olmalı (adımlar aşağıda)."), hint
    if state == "unauthorized":
        return False, ("TV bulundu ama izin bekliyor: TV ekranındaki \"USB hata ayıklamaya izin verilsin mi?\" "
                       "penceresinde \"Her zaman izin ver\"i işaretleyip İzin ver'e bas, sonra tekrar dene."), ip
    target = _target(ip)
    installed = "package:" in _adb("-s", target, "shell", "pm", "path", PACKAGE)[1]
    if not installed:
        ok, message = install(ip, apk, progress)
        if not ok:
            return False, message, ip
    ok = connected() or _start_service(target, connected, progress)
    progress("TV PS5 ekranına geçiriliyor…")
    inp = show_ps5(target, hdmi_port)
    where = f" PS5 ekranı (HDMI {inp['port']}) açıldı." if inp else ""
    if ok:
        return True, "TV uygulaması bağlı." + where, ip
    return False, ("TV uygulaması açıldı ama bilgisayara bağlanamadı. TV ile bilgisayar aynı modeme bağlı mı? "
                   "Bilgisayarda VPN açıksa kapatıp tekrar dene." + where), ip


def install(ip, apk, progress):
    """Connect, install/update the APK, grant the overlay permission and start the app.

    progress(text) is called for each step; returns (ok, message).
    """
    if not ADB.exists():
        return False, "adb bulunamadı."
    if not Path(apk).exists():
        return False, f"APK bulunamadı: {apk}"
    target = _target(ip)

    progress(f"TV'ye bağlanılıyor ({target})…")
    state = _state(target)
    if state == "unauthorized":
        return False, "TV'de çıkan 'USB hata ayıklamaya izin ver' penceresini onayla ve tekrar dene."
    if state != "device":
        return False, "TV'ye bağlanılamadı. TV'de Geliştirici seçenekleri > USB hata ayıklama açık olmalı."

    first_install = "package:" not in _adb("-s", target, "shell", "pm", "path", PACKAGE)[1]
    progress("Uygulama yükleniyor…")
    ok, out = _adb("-s", target, "install", "-r", str(apk), timeout=180)
    if not ok or "Success" not in out:
        return False, f"Yükleme başarısız: {out}"

    progress("Ekran üstü izni veriliyor…")
    _adb("-s", target, "shell", "appops", "set", PACKAGE, "SYSTEM_ALERT_WINDOW", "allow")
    _adb("-s", target, "shell", "dumpsys", "deviceidle", "whitelist", f"+{PACKAGE}")

    progress("Uygulama başlatılıyor…")
    if first_install:
        _adb("-s", target, "shell", "am", "start", "-n", f"{PACKAGE}/.MainActivity")
    else:
        # Update: restart only the subtitle service, so a game on the HDMI input stays on screen.
        _adb("-s", target, "shell", "am", "broadcast", "-f", "0x20", "-n", f"{PACKAGE}/.BootReceiver")
    return True, "TV uygulaması güncellendi ve başlatıldı."
