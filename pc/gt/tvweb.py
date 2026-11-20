"""Samsung (Tizen) and LG (webOS) TVs: find the TV, install / update the Oyun Çeviri TV app, start it.

Samsung (the way GameTranslator and Tizen Studio do it): the TV's Developer Mode is on with this PC's address as
"Host PC IP". vendor/samsung/SamsungHelper.exe (TizenSdb.Core) connects with sdb, gets a certificate for this
TV from Samsung after a one-time Samsung account sign-in in the browser, signs the app, installs and starts it.

LG: the Developer Mode app is on (Dev Mode Status + Key Server). The SSH key is fetched from the TV's Key Server
once and unlocked with the Passphrase shown on the TV; then the app is installed over SSH (port 9922, the way
ares-install does it) and started. Every connection also renews Developer Mode (its 1000 hours start again), like
the EXTEND button of the TV app.
Keys and certificates are kept in tv-keys/ (never in the installer).
"""
import io
import json
import re
import shutil
import socket
import subprocess
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


from .config import ROOT

KEYS = ROOT / "tv-keys"
LOG = ROOT / "logs" / "tv-install.log"
_NO_WINDOW = 0x08000000


def log(text):
    """One line in logs/tv-install.log: what the Samsung / LG install did (to find out why it failed)."""
    import time
    try:
        LOG.parent.mkdir(exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(text).rstrip() + "\n")
    except OSError:
        pass


def _open(ip, port, timeout=0.6):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def scan(port, progress=lambda t: None):
    """Addresses on the local /24 network with this port open."""
    from .tvctl import scan_port
    return scan_port(port, progress)


def with_pc_address(package, tv_ip):
    """A copy of the Samsung package with this PC's addresses in pc.js (the app tries them first, so it connects at
    once instead of searching the whole network). The copy is signed and installed in place of the plain package."""
    import tempfile
    from .tvctl import lan_ips, pc_ip_for
    try:
        first = pc_ip_for(tv_ip) if tv_ip else None
        ips = [ip for ip in [first] + lan_ips() if ip]
        ips = list(dict.fromkeys(ips))
        if not ips:
            return package
        copy = Path(tempfile.mkdtemp(prefix="oyunceviri-")) / package.name
        shutil.copyfile(package, copy)
        with zipfile.ZipFile(copy, "a") as z:
            if "pc.js" not in z.namelist():
                z.writestr("pc.js", f"window.OC_PC = {json.dumps(ips)};\n")
        log(f"Samsung: bu PC'nin adresleri pakete yazıldı: {', '.join(ips)}")
        return copy
    except (OSError, zipfile.BadZipFile) as e:
        log(f"Samsung: adres pakete yazılamadı ({e}), paket olduğu gibi kuruluyor")
        return package


# ---------------------------------------------------------------- Samsung

class Samsung:
    PORT = 26101
    HELPER = ROOT / "vendor" / "samsung" / "SamsungHelper.exe"
    PACKAGE = ROOT / "OyunCeviri-Samsung.wgt"
    APP_ID = "OyCvrTV001.OyunCeviri"
    PACKAGE_ID = "OyCvrTV001"
    STEPS = {"connecting": "TV'ye bağlanılıyor…", "certificate": "Samsung'dan bu TV için sertifika alınıyor…",
             "signing": "Uygulama imzalanıyor…", "installing": "TV'ye kuruluyor…",
             "reinstalling": "Eski kopya kaldırılıp yeniden kuruluyor…", "starting": "TV'de açılıyor…"}
    ERRORS = {
        "Unreachable": "TV bu bilgisayarı kabul etmedi. TV'deki Developer Mode penceresinde \"Host PC IP\" bu "
                       "bilgisayarın adresi olmalı ({me}); düzeltip kumandadaki güç tuşunu 3 saniye basılı tutarak "
                       "TV'yi yeniden başlat.",
        "TooOld": "Bu Samsung TV çok eski (2019 ve sonrası modeller destekleniyor).",
        "LoginFailed": "Samsung girişi tamamlanmadı. Tekrar dene ve açılan sayfada girişi bitir.",
        "CertificateFailed": "Samsung imza sertifikasını vermedi. Birkaç dakika sonra tekrar dene.",
        "InstallFailed": "TV kurulumu kabul etmedi.",
    }

    @classmethod
    def available(cls):
        return cls.HELPER.exists() and cls.PACKAGE.exists()

    @classmethod
    def devmode(cls, ip):
        return _open(ip, cls.PORT, timeout=2)

    @classmethod
    def find(cls, hint, progress):
        if hint and cls.devmode(hint):
            return hint
        found = scan(cls.PORT, progress)
        return found[0] if found else None

    @classmethod
    def _run(cls, args, progress, timeout=900):
        """Runs the helper; its JSON lines become progress messages. -> (ok, message)."""
        try:
            log(f"Samsung: {args[0]} {args[1] if len(args) > 1 else ''}")
            proc = subprocess.Popen([str(cls.HELPER), *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
        except OSError as e:
            log(f"Samsung: helper did not start: {e}")
            return False, f"Samsung yardımcı programı açılamadı: {e}"
        result = (False, "Samsung yardımcı programı cevap vermedi.")
        for raw in proc.stdout:
            log("  " + raw[:600])
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if "step" in msg:
                if msg["step"] == "signin":
                    progress("Tarayıcıda Samsung giriş sayfası açıldı: ücretsiz Samsung hesabınla giriş yap "
                             "(yalnızca ilk kurulumda). Samsung uygulamayı bu TV için imzalar.")
                else:
                    progress(cls.STEPS.get(msg["step"], msg["step"]))
            elif msg.get("ok"):
                result = (True, "")
            elif "error" in msg:
                from .tvctl import pc_ip_for
                me = pc_ip_for(args[1]) if len(args) > 1 else None
                text = cls.ERRORS.get(msg.get("kind"), "Samsung kurulumu başarısız.").format(me=me or "?")
                result = (False, f"{text} ({msg['error'][:160]})")
        proc.wait(timeout=timeout)
        log(f"Samsung: exit {proc.returncode}, {'OK' if result[0] else result[1]}")
        return result

    @classmethod
    def install(cls, ip, progress):
        package = with_pc_address(cls.PACKAGE, ip)
        try:
            ok, message = cls._run(["install", ip, str(package), str(KEYS / "samsung"), cls.APP_ID, cls.PACKAGE_ID],
                                   progress)
        finally:
            if package != cls.PACKAGE:
                shutil.rmtree(package.parent, ignore_errors=True)     # the temporary copy with the address
        return ok, ("Samsung TV'ye kuruldu ve açıldı." if ok else message)

    @classmethod
    def launch(cls, ip, progress=lambda t: None):
        return cls._run(["launch", ip, cls.APP_ID], progress, timeout=60)


# ---------------------------------------------------------------- LG

class LG:
    PORT = 9922
    APP_ID = "com.oyunceviri.tv"
    PACKAGE = ROOT / "OyunCeviri-LG.ipk"
    TEMP = "/media/developer/temp"
    APPINFO = f"/media/developer/apps/usr/palm/applications/{APP_ID}/appinfo.json"

    @classmethod
    def available(cls):
        return cls.PACKAGE.exists()

    @classmethod
    def devmode(cls, ip):
        return _open(ip, cls.PORT, timeout=2)

    @classmethod
    def find(cls, hint, progress):
        if hint and cls.devmode(hint):
            return hint
        found = scan(cls.PORT, progress)
        return found[0] if found else None

    @staticmethod
    def key_file(ip):
        return KEYS / "lg" / f"{ip.replace('.', '_')}.pem"

    @classmethod
    def has_key(cls, ip):
        return cls.key_file(ip).exists()

    @classmethod
    def fetch_key(cls, ip, passphrase):
        """Key Server (TV port 9991) -> the SSH key, unlocked with the Passphrase shown on the TV."""
        import paramiko
        try:
            pem = urllib.request.urlopen(f"http://{ip}:9991/webos_rsa", timeout=6).read().decode()
        except OSError:
            return False, "TV'nin Key Server'ına ulaşılamadı. Developer Mode uygulamasında Key Server açık olmalı ve " \
                          "uygulama ekranda kalmalı."
        key = None
        for word in dict.fromkeys([passphrase.strip(), passphrase.strip().upper()]):
            try:
                key = paramiko.RSAKey.from_private_key(io.StringIO(pem), password=word or None)
                break
            except paramiko.SSHException:
                continue
        if key is None:
            return False, "Passphrase yanlış. TV'deki Developer Mode uygulamasında yazanı aynen yaz."
        path = cls.key_file(ip)
        path.parent.mkdir(parents=True, exist_ok=True)
        key.write_private_key_file(str(path))
        return True, ""

    @classmethod
    def _ssh(cls, ip):
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, port=cls.PORT, username="prisoner", key_filename=str(cls.key_file(ip)), timeout=8,
                       allow_agent=False, look_for_keys=False, disabled_algorithms={"pubkeys": ["rsa-sha2-256",
                                                                                               "rsa-sha2-512"]})
        return client

    @staticmethod
    def _run(client, command, data=None, timeout=300):
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        if data is not None:
            stdin.write(data)
            stdin.channel.shutdown_write()
        out = stdout.read().decode(errors="replace") + stderr.read().decode(errors="replace")
        return stdout.channel.recv_exit_status(), out

    @classmethod
    def package_version(cls):
        """The version written in the .ipk (its control file)."""
        import gzip
        import tarfile
        data = cls.PACKAGE.read_bytes()
        pos = 8
        while pos < len(data):
            name, size = data[pos:pos + 16].decode().strip(), int(data[pos + 48:pos + 58].decode().strip())
            if name.startswith("control.tar"):
                with tarfile.open(fileobj=io.BytesIO(gzip.decompress(data[pos + 60:pos + 60 + size]))) as tar:
                    for member in tar.getmembers():
                        if member.name.endswith("control"):
                            m = re.search(r"^Version:\s*(\S+)", tar.extractfile(member).read().decode(), re.M)
                            return m.group(1) if m else "0"
            pos += 60 + size + (size & 1)
        return "0"

    @classmethod
    def installed_version(cls, client):
        _, out = cls._run(client, f"cat {cls.APPINFO} 2>/dev/null")
        m = re.search(r'"version"\s*:\s*"([^"]+)"', out)
        return m.group(1) if m else None

    @classmethod
    def install(cls, ip, progress):
        version = cls.package_version()
        try:
            progress("TV'ye bağlanılıyor…")
            client = cls._ssh(ip)
        except Exception as e:  # noqa: BLE001 - shown to the user
            return False, f"TV'ye bağlanılamadı ({e}). Developer Mode açık mı, Passphrase doğru mu?"
        try:
            remote = f"{cls.TEMP}/{cls.APP_ID}_{version}_all.ipk"
            progress("Uygulama TV'ye yükleniyor…")
            data = cls.PACKAGE.read_bytes()
            code, out = cls._run(client, f"mkdir -p {cls.TEMP} && rm -f {cls.TEMP}/{cls.APP_ID}_*.ipk && cat > '{remote}'",
                                 data)
            if code != 0:
                return False, f"Yükleme başarısız: {out[:200]}"
            progress("TV'ye kuruluyor…")
            params = json.dumps({"id": "com.ares.defaultName", "ipkUrl": remote, "subscribe": True})
            log = f"{cls.TEMP}/oyunceviri-install.log"
            command = "; ".join([
                f"rm -f {log}",
                f"sleep 210 </dev/null 2>/dev/null | /usr/bin/luna-send-pub -i "
                f"'luna://com.webos.appInstallService/dev/install' '{params}' >{log} 2>&1 & L=$!",
                "i=0",
                f"while [ $i -lt 180 ]; do grep -q -i -e '\"state\" *: *\"installed' -e 'failed' -e "
                f"'\"returnValue\" *: *false' -e '\"state\" *: *\"success' {log} 2>/dev/null && break; "
                f"kill -0 $L 2>/dev/null || break; sleep 1; i=$((i+1)); done",
                f"cat {log}", "kill $L 2>/dev/null", f"rm -f {log}"])
            _, out = cls._run(client, command, timeout=240)
            if re.search(r'"returnValue"\s*:\s*false|failed', out, re.I) and not re.search(r'installed', out, re.I):
                return False, f"TV kurulumu kabul etmedi: {out[-200:]}"
            if cls.installed_version(client) != version:
                return False, "Kurulum bitmedi gibi görünüyor; birazdan tekrar dene."
            cls._run(client, f"rm -f '{remote}'")
            cls.renew(client)
            progress("TV'de açılıyor…")
            cls._launch(client, ip)
            return True, "LG TV'ye kuruldu ve açıldı."
        finally:
            client.close()

    @classmethod
    def _launch(cls, client, ip=None):
        """Starts the app; it is told this PC's address ("pc"), so it connects at once instead of searching."""
        from .tvctl import pc_ip_for
        launch = {"id": cls.APP_ID}
        if ip:
            launch["params"] = {"pc": pc_ip_for(ip)}
        cls._run(client, f"/usr/bin/luna-send-pub -n 1 'luna://com.webos.applicationManager/launch' "
                         f"'{json.dumps(launch)}'", timeout=20)

    @classmethod
    def launch(cls, ip, progress=lambda t: None):
        try:
            client = cls._ssh(ip)
        except Exception as e:  # noqa: BLE001
            return False, f"TV'ye bağlanılamadı ({e})."
        try:
            hours = cls.renew(client)
            cls._launch(client, ip)
            extra = f" Developer Mode {hours} saat daha açık." if hours else ""
            return True, "LG TV'de uygulama açıldı." + extra
        finally:
            client.close()

    @classmethod
    def renew(cls, client):
        """Developer Mode's time starts again (the EXTEND button of the TV app). -> hours left, or None."""
        _, token = cls._run(client, "cat /var/luna/preferences/devmode_enabled 2>/dev/null", timeout=15)
        token = token.strip()
        if not token or " " in token:
            return None
        base = "https://developer.lge.com/secure/{}.dev?sessionToken=" + urllib.parse.quote(token)
        try:
            if "success" not in urllib.request.urlopen(base.format("ResetDevModeSession"), timeout=10).read().decode().lower():
                return None
            m = re.search(r"(\d{1,4}):(\d{2}):(\d{2})",
                          urllib.request.urlopen(base.format("CheckDevModeSession"), timeout=10).read().decode())
            return int(m.group(1)) if m else None
        except OSError:
            return None

