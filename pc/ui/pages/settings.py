"""General settings page: text reading (OCR), background mode, shortcut, updates, about."""
import os
import subprocess
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from gt import config
from gt.updater import FROZEN
from gt.version import REPO, VERSION

from .. import theme
from ..widgets import Card, Divider, SettingRow, Toggle, icon_button

TOKEN_HELP = ("Depo gizli olduğu için gerekiyor, her bilgisayarda bir kez girilir. Almak için: github.com → sağ üstte "
              "profil → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new "
              "token. Repository access: <b>Only select repositories → oyunceviri</b>, Permissions: <b>Contents → "
              "Read-only</b>. Çıkan anahtarı buraya yapıştır.")


class SettingsPage(QWidget):
    title = "Genel"
    hint = "Yazı okuma, arka planda çalışma ve kısayol."

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cfg = win.cfg

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        general = Card("Yazı okuma ve uygulama")
        ocr = QComboBox()
        ocr.addItem("PP-OCRv6 tiny (önerilen)", "rapid")
        ocr.addItem("Windows OCR (İngilizce dil paketi gerekir)", "windows")
        ocr.setCurrentIndex(0 if self.cfg["ocr_engine"] == "rapid" else 1)
        ocr.currentIndexChanged.connect(lambda: self._set("ocr_engine", ocr.currentData()))
        general.add(SettingRow("Yazı okuma motoru",
                               "Ekrandaki İngilizce yazıyı okuyan motor. Önerilen, satır başına ~10 ms'de okur. "
                               "Değişiklik bir sonraki Başlat'ta uygulanır.", ocr))
        general.add(Divider())
        accurate = Toggle(self.cfg["ocr_accurate"])
        accurate.toggled.connect(lambda v: self._set("ocr_accurate", v))
        general.add(SettingRow("Satırı son kez büyük modelle oku",
                               "Satır ekranda oturunca daha büyük OCR modeliyle bir kez daha okunur. I/l karışması "
                               "ve harf atlama azalır, satır başına ~40 ms ekler. (Yeniden başlatınca uygulanır.)",
                               accurate))
        general.add(Divider())
        log = Toggle(self.cfg["debug_log"])
        log.toggled.connect(lambda v: self._set("debug_log", v))
        general.add(SettingRow("Teşhis kaydı",
                               "Okunan yazıları, çevirileri ve her satırın altyazı alanı görüntüsünü logs klasörüne "
                               "kaydeder. Sorun ararken açık tut.", log))
        general.add(Divider())
        tray = Toggle(self.cfg["minimize_to_tray"])
        tray.toggled.connect(lambda v: self._set("minimize_to_tray", v))
        general.add(SettingRow("Kapatınca arka planda çalış",
                               "Pencereyi kapatınca uygulama saatin yanındaki simgede çalışmaya devam eder.", tray))
        general.add(Divider())
        shortcut = icon_button(theme.Icon.ADD, "Masaüstüne kısayol koy")
        shortcut.clicked.connect(self._desktop_shortcut)
        general.add(SettingRow("Masaüstü kısayolu", "Oyun Çeviri'yi masaüstünden açmak için.", shortcut))
        lay.addWidget(general)

        update = Card("Güncelleme")
        self.update_button = icon_button(theme.Icon.SYNC, "Denetle")
        self.update_button.clicked.connect(self._update_clicked)
        self.update_row = SettingRow(f"Oyun Çeviri {VERSION}", "", self.update_button)
        self.update_status = QLabel("Yeni sürüm olup olmadığına bakılmadı.")
        self.update_status.setObjectName("muted")
        self.update_status.setWordWrap(True)
        self.update_row.layout().itemAt(0).layout().addWidget(self.update_status)
        update.add(self.update_row)
        update.add(Divider())
        auto = Toggle(self.cfg["update"]["auto"])
        auto.toggled.connect(self._set_auto_update)
        update.add(SettingRow("Kendiliğinden güncelle",
                              "Açılışta yeni sürüme bakar ve arka planda indirir. Uygulamayı kapatınca kurulur; "
                              "oyun sırasında hiçbir şey yeniden başlamaz. Oyun paketleri ve TV uygulaması da "
                              "bununla güncellenir.", auto))
        update.add(Divider())
        self.token = QLineEdit(self.cfg["update"].get("token", ""))
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("github_pat_…")
        self.token.setMinimumWidth(260)
        self.token.editingFinished.connect(self._set_token)
        token_row = SettingRow("GitHub erişim anahtarı", TOKEN_HELP, self.token)
        for label in token_row.findChildren(QLabel):
            label.setOpenExternalLinks(True)
        update.add(token_row)
        if not FROZEN:
            note = QLabel("Uygulama kaynak koddan çalışıyor: yeni sürüme bakılabilir ama kurulum yalnızca kurulu "
                          "uygulamada yapılır.")
            note.setObjectName("muted")
            note.setWordWrap(True)
            update.add(note)
        lay.addWidget(update)

        about = Card("Hakkında")
        info = QLabel(
            f"Oyun Çeviri {VERSION}<br>"
            f"<span style='color:{theme.MUTED}'>PS5 altyazılarını okuyup Türkçeye çevirir ve TV'de gösterir. "
            f"Her şey bu bilgisayarda çalışır.<br>Ayar dosyası: {config.CONFIG_PATH}<br>"
            f"Güncellemeler: github.com/{REPO}</span>")
        info.setWordWrap(True)
        about.add(info)
        lay.addWidget(about)
        lay.addStretch(1)

    # ---- updates (the main window does the work; this page shows it) ----

    def _set_auto_update(self, on):
        self.cfg["update"]["auto"] = on
        self.win.persist_config(("update", "auto"))

    def _set_token(self):
        token = self.token.text().strip()
        if token == self.cfg["update"].get("token", ""):
            return
        self.cfg["update"]["token"] = token
        self.win.persist_config(("update", "token"))
        if token:
            self.win.check_updates(download=FROZEN and self.cfg["update"]["auto"])

    def _update_clicked(self):
        state, _, plan = self.win.update_state
        if state == "available" and FROZEN:
            self.win.download_update(plan)
        elif state == "ready":
            self.win.install_update()
        elif state == "setup" and plan:
            QDesktopServices.openUrl(QUrl(plan.get("url") or f"https://github.com/{REPO}/releases"))
        else:
            self.win.check_updates()

    def on_update_state(self, state, text, plan):
        self.update_status.setText(text)
        self.update_status.setStyleSheet(f"color: {theme.RED};" if state == "error" else "")
        labels = {"checking": (theme.Icon.SYNC, "Bakılıyor…"), "downloading": (theme.Icon.SYNC, "İndiriliyor…"),
                  "ready": (theme.Icon.REFRESH, "Yeniden başlat ve kur"), "setup": (theme.Icon.OPEN, "Sayfayı aç")}
        if state == "available" and FROZEN:
            mb = max(1, round((plan or {}).get("size", 0) / 1e6))
            glyph, text = theme.Icon.SYNC, f"İndir ({mb} MB)"
        else:
            glyph, text = labels.get(state, (theme.Icon.SYNC, "Denetle"))
        self.update_button.setText(f"{glyph}  {text}")
        self.update_button.setObjectName("primary" if state in ("available", "ready") else "")
        self.update_button.style().unpolish(self.update_button)
        self.update_button.style().polish(self.update_button)
        self.update_button.setEnabled(state not in ("checking", "downloading"))

    def _set(self, key, value):
        self.cfg[key] = value
        self.win.save_config()

    def _desktop_shortcut(self):
        ok = create_shortcut(os.path.join(os.path.expanduser("~"), "Desktop", "Oyun Çeviri.lnk"))
        self.win.show_message("Masaüstüne kısayol kondu." if ok else "Kısayol oluşturulamadı.", error=not ok)


def create_shortcut(path):
    """Windows .lnk that starts the app without a console window."""
    if getattr(sys, "frozen", False):          # installed app: the exe itself
        pythonw, app = sys.executable, None
    else:
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        app = config.ROOT / "pc" / "app.py"
    icon = config.ASSETS / "icon.ico"
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
        "$s.TargetPath = $env:TARGET; $s.Arguments = $env:ARGS; $s.WorkingDirectory = $env:WD;"
        "$s.IconLocation = $env:ICON; $s.Description = 'Oyun Ceviri'; $s.Save()"
    )
    env = dict(os.environ, LNK=path, TARGET=pythonw, ARGS=f'"{app}"' if app else "",
               WD=str(app.parent if app else config.ROOT), ICON=str(icon))
    r = subprocess.run(["powershell", "-NoProfile", "-Command", script], env=env, capture_output=True,
                       creationflags=0x08000000)
    return r.returncode == 0
