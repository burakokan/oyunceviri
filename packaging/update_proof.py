"""Proof that an in-place update never touches the user's own files (settings, PS5 keys, speaker colours, caches,
logs, TV keys, packs being built), even when a release wrongly contains them or lists them as deleted.

    .venv\\Scripts\\python.exe packaging\\update_proof.py [test folder]      (default: D:\\OyunCeviriTest)

It makes a small "installed app" in the test folder (another name and place than the real one), serves a fake
GitHub release from this PC whose update package carries the user's files with other content, an "../escape.txt"
and deletes for them, and runs the real updater (pc/gt/updater.py: check, download, the PowerShell apply script)
on it. Then every user file is compared byte by byte with how it was before. The real app is not touched.
"""
import hashlib
import http.server
import io
import json
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pc"))
from gt.updater import PROTECTED, PROTECTED_DIRS  # noqa: E402

USER_FILES = {      # the user's own files, as an installed app has them
    "config.json": '{"online": {"deepl_key": "KULLANICI-ANAHTARI"}, "roi_builtin": [0.2, 0.8, 0.6, 0.15]}',
    "ps5.json": '{"host": "192.168.1.77", "regist_key": "KULLANICI-PS5"}',
    "speakers.json": '{"jason": "#4FC3F7", "lucia": "#FFD54F"}',
    "region_cache.json": '{"Go to the bank.": "Bankaya git."}',
    "screen_cache.json": '{"OPTIONS": "SEÇENEKLER"}',
    "logs/session-20261119-041230.jsonl": '{"t": "04:12:41.874", "read": ""}',
    "logs/remoteplay.log": "2026-11-19 20:31:00 [connected] PS5'e bağlandı",
    "tv-keys/author.p12": "SAMSUNG-SERTIFIKA",
    "packs/build/status.json": '{"gta-6": "building"}',
    "packs/build/gta-6/translations.jsonl": '{"en": "Hey.", "tr": "Selam."}',
}
APP_V1 = {"OyunCeviri.txt": "uygulama 1.0.0", "packs/gta-6.json.gz": "paket v4", "eski-dosya.txt": "1.0.0'da var"}
APP_V2 = {"OyunCeviri.txt": "uygulama 1.1.0", "packs/gta-6.json.gz": "paket v5", "yeni-dosya.txt": "1.1.0'da geldi"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def write(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def release(base_url):
    """A release 1.1.0 (base 1.0.0) whose package wrongly holds every user file with other content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for rel, text in APP_V2.items():
            z.writestr(rel, text)
        for rel in USER_FILES:
            z.writestr(rel, "GÜNCELLEME BUNU YAZMAMALI")
        z.writestr("../escape.txt", "uygulama klasörünün dışına yazmamalı")
    part = buf.getvalue()
    info = {"version": "1.1.0", "base": "1.0.0", "notes": "kanıt testi",
            "parts": [{"name": "update-1.1.0-1.zip", "size": len(part), "sha256": hashlib.sha256(part).hexdigest()}],
            "files": {rel: hashlib.sha256(t.encode()).hexdigest() for rel, t in APP_V2.items()},
            "deleted": ["eski-dosya.txt"] + list(USER_FILES)}
    assets = {"update.json": json.dumps(info).encode(), "update-1.1.0-1.zip": part}
    rel = [{"tag_name": "v1.1.0", "draft": False, "prerelease": False, "html_url": base_url,
            "assets": [{"name": n, "url": f"{base_url}/assets/{n}"} for n in assets]}]
    return rel, assets


def serve(assets_for):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            releases, assets = assets_for()
            if self.path.startswith("/releases"):
                body = json.dumps(releases).encode()
            elif self.path.startswith("/assets/"):
                body = assets[self.path.split("/")[-1]]
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    test = Path(sys.argv[1] if len(sys.argv) > 1 else r"D:\OyunCeviriTest")
    app = test / "Oyun Ceviri Test"
    if app.resolve() == ROOT.resolve() or "gametranslate" in str(app).lower():
        sys.exit("Test klasörü gerçek uygulama olamaz.")
    shutil.rmtree(test, ignore_errors=True)
    write(app, APP_V1)
    write(app, USER_FILES)
    (test / "escape.txt").unlink(missing_ok=True)
    before = {rel: digest(app / rel) for rel in USER_FILES}

    url = {}
    srv = serve(lambda: release(url["base"]))
    url["base"] = f"http://127.0.0.1:{srv.server_port}"
    print(f"Sahte kurulum: {app}")
    print(f"Sahte GitHub sürümü: {url['base']} (paket kullanıcı dosyalarını farklı içerikle taşıyor ve siliyor)")

    # The update runs in a child process, like the app: the apply script waits for it to exit.
    child = subprocess.run([sys.executable, "-c", f"""
import sys; sys.path.insert(0, {str(ROOT / 'pc')!r})
from gt.updater import Updater
u = Updater({{"update": {{"token": ""}}}}, root={str(app)!r}, version="1.0.0", api={url['base']!r})
plan = u.check()
print("  denetim:", plan["state"], plan.get("version"))
u.download(plan)
print("  indirildi, kurulmayı bekliyor:", u.ready())
u.apply(relaunch=False)
print("  kurulum betiği başladı; uygulama kapanıyor")
"""], capture_output=True, text=True, encoding="utf-8")
    print(child.stdout.rstrip())
    if child.returncode:
        print(child.stderr)
        sys.exit("Güncelleme çalıştırılamadı.")
    result = app / "update" / "result.txt"
    for _ in range(120):
        if result.exists():
            break
        time.sleep(0.5)
    srv.shutdown()
    print("  kurulum sonucu:", result.read_text(encoding="utf-8-sig").strip() if result.exists() else "YOK")

    ok = result.exists() and result.read_text(encoding="utf-8-sig").strip() == "ok 1.1.0"
    print("\nKullanıcı dosyaları (öncesi = sonrası olmalı):")
    for rel in USER_FILES:
        same = digest(app / rel) == before[rel]
        ok &= same
        print(f"  {'AYNI    ' if same else 'DEĞİŞTİ!'} {rel}")
    print("\nUygulama dosyaları (güncellenmeli):")
    for rel, text in APP_V2.items():
        good = (app / rel).exists() and (app / rel).read_text(encoding="utf-8") == text
        ok &= good
        print(f"  {'güncel  ' if good else 'ESKİ!   '} {rel}")
    gone = not (app / "eski-dosya.txt").exists()
    escaped = (test / "escape.txt").exists()
    ok &= gone and not escaped
    print(f"  {'silindi ' if gone else 'DURUYOR!'} eski-dosya.txt (yeni sürümde yok)")
    print(f"  {'yazılmadı' if not escaped else 'YAZILDI!'} ../escape.txt (uygulama klasörünün dışı)")
    listed = (app / "update" / "files.txt").read_text(encoding="utf-8").split("\n")
    leaked = [r for r in listed if r in PROTECTED or r.startswith(PROTECTED_DIRS)]
    ok &= not leaked
    print(f"  kaldırıcının silme listesinde kullanıcı dosyası: {leaked or 'yok'}")
    print("\nSONUÇ:", "GEÇTİ - güncelleme kullanıcı dosyalarına dokunmadı." if ok else "KALDI")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
