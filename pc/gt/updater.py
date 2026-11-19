"""In-place updates of the installed app from GitHub Releases (no new setup needed).

Every release (tag "v1.2.3", made by packaging/publish.py) carries:
  update.json          {"version": "1.2.3", "base": "1.2.2", "notes": "...",
                        "parts": [{"name", "size", "sha256"}], "files": {"rel/path": sha256}, "deleted": [...]}
  update-1.2.3-1.zip…  the files that changed since the release "base" (each part < 2 GB)
  OyunCeviri-Kurulum…  only in some releases: the full setup for a new PC
The app walks the releases newer than itself in order (each one's base must be the one before), downloads and
checks every part, unpacks them into update/staging and, when the user agrees or closes the app, quits and lets a
small PowerShell script copy the files over the installed ones (and start the app again). Settings, PS5 keys, logs
and caches are never part of an update.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import requests

from .config import ROOT
from .version import REPO, VERSION, parse

FROZEN = getattr(sys, "frozen", False)
TIMEOUT = 20
# Never written by an update, whatever a release contains: the user's own data in the app folder.
PROTECTED = {"config.json", "ps5.json", "speakers.json", "region_cache.json", "screen_cache.json"}
PROTECTED_DIRS = ("logs/", "tv-keys/", "update/", "packs/build/")

APPLY_PS1 = r"""$ErrorActionPreference = 'SilentlyContinue'
$app = '{app}'
$dir = Join-Path $app 'update'
New-Item -ItemType Directory -Force -Path (Join-Path $app 'logs') | Out-Null
$log = Join-Path $app 'logs\update.log'
function Write-Log($m) {{ Add-Content -LiteralPath $log -Encoding UTF8 -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $m) }}
Write-Log 'Guncelleme {version}: uygulamanin kapanmasi bekleniyor'
$p = Get-Process -Id {pid}
if ($p) {{ $p.WaitForExit(60000) | Out-Null }}
$until = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $until) {{
    $busy = @(Get-Process | Where-Object {{ $_.Path -and $_.Path.StartsWith($app + '\', [StringComparison]::OrdinalIgnoreCase) }})
    if ($busy.Count -eq 0) {{ break }}
    Start-Sleep -Milliseconds 500
}}
robocopy (Join-Path $dir 'staging') $app /E /IS /IT /R:20 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
$rc = $LASTEXITCODE
if ($rc -lt 8) {{
    foreach ($rel in (Get-Content -LiteralPath (Join-Path $dir 'delete.txt') -Encoding UTF8)) {{
        if ($rel) {{ Remove-Item -LiteralPath (Join-Path $app $rel) -Force }}
    }}
    Remove-Item -LiteralPath (Join-Path $dir 'staging') -Recurse -Force
    Remove-Item -LiteralPath (Join-Path $dir 'ready.json') -Force
    Set-Content -LiteralPath (Join-Path $dir 'result.txt') -Value 'ok {version}' -Encoding UTF8
    # "Installed apps" in Windows shows the new version too
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{{8C6F2B8E-5D1A-4C1E-9E33-0A7B3E2C9F11}}_is1'
    if (Test-Path $key) {{ Set-ItemProperty -Path $key -Name DisplayVersion -Value '{version}' }}
    Write-Log 'Tamam'
}} else {{
    Set-Content -LiteralPath (Join-Path $dir 'result.txt') -Value "fail $rc" -Encoding UTF8
    Write-Log "Dosyalar kopyalanamadi (robocopy $rc)"
}}
if (${relaunch}) {{ Start-Process -FilePath (Join-Path $app 'OyunCeviri.exe') -WorkingDirectory $app }}
"""


class UpdateError(Exception):
    """A failed check or download, with a message for the user (Turkish)."""


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def protected(rel):
    rel = rel.replace("\\", "/")
    return rel in PROTECTED or rel.startswith(PROTECTED_DIRS)


class Updater:
    """root: the installed app folder; api: the GitHub API of the repository (both replaceable for tests)."""

    def __init__(self, cfg, root=ROOT, version=VERSION, api=f"https://api.github.com/repos/{REPO}"):
        self.cfg = cfg
        self.root = Path(root).resolve()
        self.version = version
        self.api = api
        self.dir = self.root / "update"
        self.staging = self.dir / "staging"
        self.ready_file = self.dir / "ready.json"       # a staged update: {"version", "delete", "files"}
        self.result_file = self.dir / "result.txt"      # from the apply script: "ok 1.2.3" / "fail <code>"
        self.files_list = self.dir / "files.txt"        # every file an update wrote (the uninstaller removes them)

    # ---- GitHub ----

    def _headers(self, raw=False):
        h = {"User-Agent": "OyunCeviri-Updater", "X-GitHub-Api-Version": "2022-11-28",
             "Accept": "application/octet-stream" if raw else "application/vnd.github+json"}
        token = (self.cfg.get("update", {}).get("token") or "").strip()
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    def _get(self, url, raw=False, stream=False, params=None):
        # requests drops the Authorization header when GitHub redirects a download to its file storage.
        try:
            r = requests.get(url, headers=self._headers(raw), params=params, stream=stream, timeout=TIMEOUT)
        except requests.RequestException:
            raise UpdateError("GitHub'a ulaşılamadı. İnternet bağlantısını kontrol et.")
        if r.status_code in (401, 403, 404):
            if r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0":
                raise UpdateError("GitHub sorgu sınırı doldu, bir saat sonra tekrar dene.")
            if not self._headers().get("Authorization"):
                raise UpdateError("Güncellemeler gizli depoda: aşağıya GitHub erişim anahtarını gir.")
            raise UpdateError("Erişim anahtarı kabul edilmedi (süresi dolmuş ya da bu depoya izni yok).")
        if r.status_code >= 400:
            raise UpdateError(f"GitHub hata verdi ({r.status_code}). Biraz sonra tekrar dene.")
        return r

    def check(self):
        """-> {"state": "latest"} | {"state": "available", "version", "size", "notes", "steps", "url"}
        | {"state": "setup", "version", "url"} (the jump needs the full setup: a release without an update)."""
        releases = self._get(f"{self.api}/releases", params={"per_page": 50}).json()
        newer = sorted((r for r in releases if not r.get("draft") and not r.get("prerelease")
                        and parse(r["tag_name"]) > parse(self.version)), key=lambda r: parse(r["tag_name"]))
        if not newer:
            return {"state": "latest", "version": self.version}
        latest = newer[-1]
        plan = {"state": "available", "version": latest["tag_name"].lstrip("vV"), "url": latest.get("html_url", ""),
                "size": 0, "notes": [], "steps": []}
        base = self.version
        for rel in newer:
            assets = {a["name"]: a for a in rel.get("assets", [])}
            if "update.json" not in assets:
                return {"state": "setup", "version": plan["version"], "url": plan["url"]}
            info = self._get(assets["update.json"]["url"], raw=True).json()
            if parse(info.get("base") or "0") != parse(base) or any(p["name"] not in assets for p in info["parts"]):
                return {"state": "setup", "version": plan["version"], "url": plan["url"]}
            parts = [dict(p, url=assets[p["name"]]["url"]) for p in info["parts"]]
            plan["steps"].append({"version": info["version"], "info": info, "parts": parts})
            plan["size"] += sum(p["size"] for p in parts)
            if info.get("notes"):
                plan["notes"].append(f"{info['version']}: {info['notes']}")
            base = info["version"]
        return plan

    # ---- download ----

    def download(self, plan, progress=lambda done, total: None):
        """Download, check and unpack every step of the plan into update/staging; then the update is ready."""
        shutil.rmtree(self.staging, ignore_errors=True)
        self.ready_file.unlink(missing_ok=True)
        temp = self.dir / "download"
        shutil.rmtree(temp, ignore_errors=True)
        temp.mkdir(parents=True)
        self.staging.mkdir(parents=True)
        expected, deleted, done = {}, set(), 0
        for step in plan["steps"]:
            info = step["info"]
            for part in step["parts"]:
                path, h = temp / part["name"], hashlib.sha256()
                r = self._get(part["url"], raw=True, stream=True)
                try:
                    with open(path, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                            h.update(chunk)
                            done += len(chunk)
                            progress(done, plan["size"])
                except (requests.RequestException, OSError):
                    raise UpdateError("İndirme yarıda kesildi, tekrar dene.")
                finally:
                    r.close()
                if h.hexdigest() != part["sha256"]:
                    raise UpdateError("İndirilen dosya bozuk geldi, tekrar dene.")
                with zipfile.ZipFile(path) as z:
                    for name in z.namelist():
                        target = (self.staging / name).resolve()
                        if self.staging.resolve() not in target.parents or protected(name):
                            continue        # never outside the app folder, never the user's own files
                        if name.endswith("/"):
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(name) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst, 1 << 20)
                path.unlink()
            for rel in info.get("deleted", []):
                if not protected(rel):
                    deleted.add(rel)
                    expected.pop(rel, None)
                    (self.staging / rel).unlink(missing_ok=True)
            for rel, digest in info["files"].items():
                if not protected(rel):
                    expected[rel] = digest
                    deleted.discard(rel)
        shutil.rmtree(temp, ignore_errors=True)
        for rel, digest in expected.items():
            f = self.staging / rel
            if not f.exists() or sha256(f) != digest:
                raise UpdateError(f"Güncellemedeki bir dosya eksik ya da bozuk ({rel}).")
        self.ready_file.write_text(json.dumps({"version": plan["version"], "delete": sorted(deleted),
                                               "files": sorted(expected)}, ensure_ascii=False), encoding="utf-8")

    # ---- install ----

    def ready(self):
        """The version of a downloaded update waiting to be installed, or None."""
        try:
            v = json.loads(self.ready_file.read_text(encoding="utf-8"))["version"]
        except (OSError, ValueError, KeyError):
            return None
        return v if parse(v) > parse(self.version) else None

    def apply(self, relaunch=True):
        """Start the script that copies the staged files once this app has quit. The caller quits right after."""
        ready = json.loads(self.ready_file.read_text(encoding="utf-8"))
        (self.dir / "delete.txt").write_text("\n".join(ready["delete"]), encoding="utf-8")
        known = set(self.files_list.read_text(encoding="utf-8").split("\n")) if self.files_list.exists() else set()
        self.files_list.write_text("\n".join(sorted((known | set(ready["files"])) - {""})), encoding="utf-8")
        self.result_file.unlink(missing_ok=True)
        script = self.dir / "apply.ps1"
        script.write_text(APPLY_PS1.format(app=str(self.root).replace("'", "''"), version=ready["version"],
                                           pid=os.getpid(), relaunch="true" if relaunch else "false"),
                          encoding="utf-8-sig")
        subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                          "-File", str(script)], cwd=str(self.dir), close_fds=True,
                         creationflags=0x08000000 | 0x00000200)     # no window, own process group

    def finish(self):
        """At start: the result of an update installed while the app was closed -> ("ok", version) /
        ("fail", text) / None. Leftovers of an applied or outdated update are removed."""
        result = None
        if self.result_file.exists():
            text = self.result_file.read_text(encoding="utf-8-sig").strip()
            self.result_file.unlink(missing_ok=True)
            kind, _, rest = text.partition(" ")
            result = ("ok", rest) if kind == "ok" else ("fail", rest)
        if self.ready_file.exists() and not self.ready():
            self.ready_file.unlink(missing_ok=True)
            shutil.rmtree(self.staging, ignore_errors=True)
        shutil.rmtree(self.dir / "download", ignore_errors=True)
        return result
