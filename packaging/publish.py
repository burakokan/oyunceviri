"""Builds a version and puts it on GitHub Releases, where installed apps update themselves from.

    .venv\\Scripts\\python.exe packaging\\publish.py                 build + update package, upload
    .venv\\Scripts\\python.exe packaging\\publish.py --setup         ...and the full setup (exe + bin parts)
    options: --no-build (use the existing dist), --notes "what changed", --dry-run (nothing is uploaded)

The version comes from pc/gt/version.py (raise it first). The update package holds only the files that changed
since the previous release (its manifest is in packaging/releases/), so a code change is ~10 MB and a game pack
change only that pack. The GitHub token is the one Git already keeps for github.com (Git Credential Manager);
it is never printed or written anywhere.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packaging"
DIST = PKG / "dist" / "OyunCeviri"
OUT = PKG / "output"
RELEASES = PKG / "releases"
PY = ROOT / ".venv" / "Scripts" / "python.exe"
ISCC = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Inno" / "ISCC.exe"
PART_LIMIT = 1_900_000_000      # GitHub takes release files up to 2 GiB

sys.path.insert(0, str(ROOT / "pc"))
from gt.updater import protected  # noqa: E402
from gt.version import REPO, VERSION, parse  # noqa: E402

API = f"https://api.github.com/repos/{REPO}"
UPLOADS = f"https://uploads.github.com/repos/{REPO}"


def say(text):
    print(time.strftime("%H:%M:%S"), text, flush=True)


def token():
    r = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                       capture_output=True, text=True, env=dict(os.environ, GCM_INTERACTIVE="never",
                                                                 GIT_TERMINAL_PROMPT="0"))
    for line in r.stdout.splitlines():
        if line.startswith("password="):
            return line[len("password="):]
    sys.exit("GitHub girişi bulunamadı: bir kez 'git push' ile GitHub'a giriş yap.")


def session():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token()}", "Accept": "application/vnd.github+json",
                      "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "OyunCeviri-Publish"})
    return s


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def manifest(folder):
    out = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            out[path.relative_to(folder).as_posix()] = [path.stat().st_size, sha256(path)]
    return out


def previous_manifest():
    """The newest saved manifest older than this version: (version, {rel: [size, sha]})."""
    found = []
    for f in RELEASES.glob("*.json"):
        if parse(f.stem) < parse(VERSION):
            found.append((parse(f.stem), f))
    if not found:
        return None, None
    f = max(found)[1]
    return f.stem, json.loads(f.read_text(encoding="utf-8"))["files"]


def build():
    say("TV web uygulaması paketleniyor…")
    subprocess.run([str(PY), str(PKG / "build_tv_web.py")], cwd=PKG, check=True)
    say("PyInstaller çalışıyor (birkaç dakika)…")
    subprocess.run([str(PY), "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", "dist", "--workpath",
                    "build", "OyunCeviri.spec"], cwd=PKG, check=True,
                   stdout=open(PKG / "pyinstaller.log", "w"), stderr=subprocess.STDOUT)


def build_setup():
    say("Kurulum dosyası derleniyor (uzun sürer)…")
    for old in OUT.glob("OyunCeviri-Kurulum*"):
        old.unlink()
    subprocess.run([str(PY), str(PKG / "make_wizard.py")], cwd=PKG, check=True)
    subprocess.run([str(ISCC), f"/DAppVersion={VERSION}", "OyunCeviri.iss"], cwd=PKG, check=True,
                   stdout=open(PKG / "iscc.log", "w"), stderr=subprocess.STDOUT)
    return sorted(OUT.glob("OyunCeviri-Kurulum*"))


def update_parts(changed):
    """Zip the changed files into parts below GitHub's file limit."""
    parts, current, size = [], [], 0
    for rel in changed:
        n = (DIST / rel).stat().st_size
        if current and size + n > PART_LIMIT:
            parts.append(current)
            current, size = [], 0
        current.append(rel)
        size += n
    if current:
        parts.append(current)
    out = []
    for i, files in enumerate(parts, 1):
        path = OUT / f"update-{VERSION}-{i}.zip"
        say(f"Güncelleme paketi {path.name}: {len(files)} dosya")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for rel in files:
                z.write(DIST / rel, rel)
        out.append(path)
    return out


class Reader:
    """A file read in large blocks that prints the upload progress."""

    def __init__(self, path):
        self.f = open(path, "rb")
        self.size = path.stat().st_size
        self.done = 0
        self.last = -1
        self.name = path.name

    def __len__(self):
        return self.size

    def read(self, n=-1):
        block = self.f.read(max(n, 1 << 20) if n and n > 0 else -1)
        self.done += len(block)
        pct = self.done * 100 // max(1, self.size)
        if pct // 5 != self.last // 5 or (pct == 100 and self.last != 100):
            self.last = pct
            say(f"  {self.name}: %{pct}")
        return block


def remote_assets(s, release):
    """The release's files now (retried: the connection may come and go)."""
    for attempt in range(30):
        try:
            r = s.get(f"{API}/releases/{release['id']}", timeout=30)
            r.raise_for_status()
            return r.json().get("assets", [])
        except requests.RequestException:
            time.sleep(10)
    sys.exit("GitHub'a ulaşılamıyor.")


def upload(s, release, path, label=None):
    """Upload one file; a file already there with the same size is kept (so a broken run can just be repeated)."""
    size = path.stat().st_size
    for asset in remote_assets(s, release):
        if asset["name"] == path.name:
            if asset.get("state") == "uploaded" and asset["size"] == size and path.name != "manifest.json":
                say(f"  zaten yüklü: {path.name}")
                return asset
            s.delete(asset["url"], timeout=30)
    for attempt in range(6):
        reader = Reader(path)
        try:
            r = s.post(f"{UPLOADS}/releases/{release['id']}/assets", params={"name": path.name, "label": label or ""},
                       data=reader, headers={"Content-Type": "application/octet-stream",
                                             "Content-Length": str(reader.size)}, timeout=(30, 900))
            if r.status_code < 300:
                return r.json()
            say(f"  yükleme hatası {r.status_code}: {r.text[:200]}")
        except requests.RequestException as e:
            say(f"  yükleme kesildi, tekrar denenecek: {type(e).__name__}")
        finally:
            reader.f.close()
        time.sleep(15 * (attempt + 1))
        # a half-uploaded file blocks the name: remove it before trying again
        for asset in remote_assets(s, release):
            if asset["name"] == path.name:
                try:
                    s.delete(asset["url"], timeout=30)
                except requests.RequestException:
                    pass
    sys.exit(f"{path.name} yüklenemedi.")


def release_for(s, notes, dry):
    tag = f"v{VERSION}"
    r = s.get(f"{API}/releases/tags/{tag}")
    if r.status_code == 200:
        return r.json()
    if dry:
        return {"id": 0, "assets": []}
    body = (notes or "") + ("\n\nKurulu uygulama bu sürüme kendisi güncellenir (Genel → Güncelleme)."
                            "\nYeni bilgisayara kurmak için: OyunCeviri-Kurulum.exe ve yanındaki .bin dosyalarını "
                            "aynı klasöre indirip exe'yi çalıştır.")
    r = s.post(f"{API}/releases", json={"tag_name": tag, "target_commitish": "main", "name": f"Oyun Çeviri {VERSION}",
                                        "body": body.strip(), "draft": False, "prerelease": False})
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", action="store_true", help="also build and upload the full setup")
    ap.add_argument("--no-build", action="store_true", help="use the existing dist folder")
    ap.add_argument("--notes", default="", help="what changed (shown in the app)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--upload-only", action="store_true",
                    help="build nothing: upload what an interrupted run left in packaging/output")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    RELEASES.mkdir(exist_ok=True)
    if args.upload_only:
        mfile = OUT / "manifest.json"
        if json.loads(mfile.read_text(encoding="utf-8"))["version"] != VERSION:
            sys.exit("packaging/output başka bir sürümün dosyalarını tutuyor.")
        assets = ([OUT / "update.json"] if (OUT / "update.json").exists() else []) + sorted(OUT.glob("update-*.zip"))
        assets += sorted(OUT.glob("OyunCeviri-Kurulum*")) + [mfile]
        s = session()
        release = release_for(s, args.notes, False)
        for a in assets:
            say(f"Yükleniyor: {a.name} ({a.stat().st_size / 1e6:.1f} MB)")
            upload(s, release, a)
        (RELEASES / f"{VERSION}.json").write_text(mfile.read_text(encoding="utf-8"), encoding="utf-8")
        say(f"Bitti: {release.get('html_url', '')}")
        return
    if not args.no_build:
        build()
    say(f"Sürüm {VERSION}: dosyaların özeti çıkarılıyor…")
    files = manifest(DIST)
    bad = [rel for rel in files if protected(rel)]      # the same list the updater never writes
    if bad:
        sys.exit(f"Kişisel dosya pakette, durduruldu: {bad[:5]}")

    base, before = previous_manifest()
    assets, info = [], None
    for old in OUT.glob("update-*"):
        old.unlink()
    if before is not None:
        changed = [rel for rel, (size, digest) in files.items() if before.get(rel, [None, None])[1] != digest]
        deleted = sorted(set(before) - set(files))
        say(f"{base} → {VERSION}: {len(changed)} dosya değişti, {len(deleted)} dosya silindi")
        parts = update_parts(changed)
        info = {"version": VERSION, "base": base, "notes": args.notes,
                "parts": [{"name": p.name, "size": p.stat().st_size, "sha256": sha256(p)} for p in parts],
                "files": {rel: files[rel][1] for rel in changed}, "deleted": deleted}
        (OUT / "update.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        assets += [OUT / "update.json"] + parts
        say(f"Güncelleme boyutu: {sum(p.stat().st_size for p in parts) / 1e6:.1f} MB")
    else:
        say("Önceki sürüm yok: bu ilk sürüm (yalnızca kurulum dosyası).")
    if args.setup:
        assets += build_setup()
    if not assets:
        sys.exit("Yüklenecek bir şey yok (--setup ver ya da önce bir sürüm yayınla).")
    mfile = OUT / "manifest.json"
    mfile.write_text(json.dumps({"version": VERSION, "files": files}, ensure_ascii=False), encoding="utf-8")
    assets.append(mfile)

    if args.dry_run:
        for a in assets:
            say(f"(deneme) yüklenecekti: {a.name} {a.stat().st_size / 1e6:.1f} MB")
        return
    s = session()
    release = release_for(s, args.notes, args.dry_run)
    for a in assets:
        say(f"Yükleniyor: {a.name} ({a.stat().st_size / 1e6:.1f} MB)")
        upload(s, release, a)
    (RELEASES / f"{VERSION}.json").write_text(mfile.read_text(encoding="utf-8"), encoding="utf-8")
    say(f"Bitti: {release.get('html_url', '')}")


if __name__ == "__main__":
    main()
