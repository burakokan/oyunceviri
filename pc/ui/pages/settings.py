"""General settings page: text reading (OCR), background mode, shortcut, updates, moving settings, about."""
import os
import subprocess
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QFileDialog, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from gt import config, settings_io
from gt.updater import FROZEN
from gt.version import REPO, VERSION

from .. import theme
from ..widgets import Card, Divider, SettingRow, Toggle, icon_button

TOKEN_HELP = ("Gerekmez, boş bırak: güncellemeler herkese açık depodan gelir. Yalnızca depo bir gün gizli yapılırsa "
              "okuma izinli bir anahtar (github.com → Settings → Developer settings → Fine-grained tokens, "
              "<b>Contents → Read-only</b>) buraya yapıştırılır.")


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
        update.add(SettingRow("Yeni sürümü kendiliğinden ara",
                              "Açılışta ve açıkken saatte bir yeni sürüme bakar, varsa haber verir. Hiçbir şey "
                              "kendiliğinden indirilmez ya da kurulmaz: kurulum yalnızca sen \"İndir ve kur\"a "
                              "basınca olur, oyun sırasında program yeniden başlamaz. Ayarların, PS5 kaydın, "
                              "konuşmacı renklerin ve kayıtların güncellemede değişmez.", auto))
        update.add(Divider())
        self.token = QLineEdit(self.cfg["update"].get("token", ""))
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("github_pat_…")
        self.token.setMinimumWidth(260)
        self.token.editingFinished.connect(self._set_token)
        token_row = SettingRow("GitHub erişim anahtarı (gerekmez)", TOKEN_HELP, self.token)
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

        move = Card("Ayarları başka bilgisayara taşı",
                    "Ayarlarını bir dosyaya yaz, öbür bilgisayarda o dosyadan yükle. Taşınanlar: altyazı ve görev / "
                    "telefon alanları, filtreler, çeviri motoru, TV görünümü, konuşmacı renkleri. Taşınmayanlar "
                    "(her bilgisayarda yeniden yapılır): PS5 bağlantısı ve PSN hesabı, TV'nin adresi ve markası.")
        export = icon_button(theme.Icon.ADD, "Dosyaya yaz…")
        export.clicked.connect(self._export_settings)
        move.add(SettingRow("Dışa aktar", "API anahtarlarını (DeepL, Groq, Gemini) da koymak isteyip istemediğin "
                            "sorulur.", export))
        move.add(Divider())
        bring = icon_button(theme.Icon.OPEN, "Dosyadan yükle…")
        bring.clicked.connect(self._import_settings)
        move.add(SettingRow("İçe aktar", "Bu bilgisayarın ayarları dosyadakilerle değişir, sonra uygulama yeniden "
                            "açılır. Dosyada anahtar yoksa bu bilgisayardaki anahtarlar kalır.", bring))
        lay.addWidget(move)

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

    # ---- settings to / from a file ----

    def _page(self, name):
        return next((p for p in self.win.pages if type(p).__name__ == name), None)

    def _export_settings(self):
        include = False
        if settings_io.has_keys(self.cfg):
            box = QMessageBox(QMessageBox.Question, "Ayarları dışa aktar",
                              "API anahtarların (DeepL, Groq, Gemini) da dosyaya konsun mu?\n\nAnahtarlı dosyayı "
                              "yalnızca kendi bilgisayarlarına taşı, kimseyle paylaşma.", parent=self)
            yes = box.addButton("Evet, anahtarlarla", QMessageBox.YesRole)
            no = box.addButton("Hayır, anahtarsız", QMessageBox.NoRole)
            box.addButton("Vazgeç", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() not in (yes, no):
                return
            include = box.clickedButton() is yes
        start = os.path.join(os.path.expanduser("~"), "Desktop",
                             "OyunCeviri-ayarlar" + ("-anahtarli" if include else "") + ".json")
        path, _ = QFileDialog.getSaveFileName(self, "Ayarları kaydet", start, "Ayar dosyası (*.json)")
        if not path:
            return
        look = self._page("TvLookPage")
        data = settings_io.export(self.cfg, include,
                                  tv_style=dict(look.style) if look is not None and look.tv_reported else None,
                                  speakers=dict(self.win.engine.colors.colors))
        try:
            settings_io.write(path, data)
        except OSError as e:
            self.win.show_message(f"Dosya yazılamadı: {e}", error=True)
            return
        self.win.show_message(f"Ayarlar kaydedildi: {path}" + (" (API anahtarlarıyla)" if include else ""))

    def _import_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, "Ayar dosyasını seç", os.path.join(os.path.expanduser("~"),
                                              "Desktop"), "Ayar dosyası (*.json)")
        if not path:
            return
        try:
            data = settings_io.read(path)
        except settings_io.SettingsFileError as e:
            QMessageBox.warning(self, "Ayarları içe aktar", str(e))
            return
        text = (f"{settings_io.summary(data)}\n\nBu bilgisayarın ayarları dosyadakilerle değişecek. PS5 bağlantısı, "
                f"PSN hesabı ve TV'nin adresi olduğu gibi kalır.\n\nUygulama kapanıp yeniden açılacak"
                + (", altyazı çevirisi birkaç saniye duracak" if getattr(self.win, "_engine_running", False) else "")
                + ". Devam edilsin mi?")
        if QMessageBox.question(self, "Ayarları içe aktar", text, QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        changed = settings_io.apply(self.cfg, data)
        if data.get("tv_style"):
            self.cfg["tv_style_pending"] = data["tv_style"]     # sent to the TV when it connects
        config.save(self.cfg)
        colors = data.get("speaker_colors")
        if isinstance(colors, dict):
            self.win.engine.colors.colors.update({str(k): str(v) for k, v in colors.items()})
            self.win.engine.colors._save()
        self.win.show_message(f"{changed} ayar yüklendi, uygulama yeniden açılıyor…")
        self.win.restart_app()

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
            self.win.check_updates()

    def _update_clicked(self):
        state, _, plan = self.win.update_state
        if state == "available" and FROZEN:
            self.win.download_update(plan)
        elif state == "ready":
            self.win.install_update()
        elif state == "setup" and plan or state == "available":
            # the full setup is needed, or the app runs from source (it cannot install): the release page
            QDesktopServices.openUrl(QUrl((plan or {}).get("url") or f"https://github.com/{REPO}/releases"))
        else:
            self.win.check_updates()

    def on_update_state(self, state, text, plan):
        self.update_status.setText(text)
        self.update_status.setStyleSheet(f"color: {theme.RED};" if state == "error" else "")
        labels = {"checking": (theme.Icon.SYNC, "Bakılıyor…"), "downloading": (theme.Icon.SYNC, "İndiriliyor…"),
                  "ready": (theme.Icon.REFRESH, "Yeniden başlat ve kur"), "setup": (theme.Icon.OPEN, "Sayfayı aç")}
        if state == "available" and FROZEN:
            mb = max(1, round((plan or {}).get("size", 0) / 1e6))
            glyph, text = theme.Icon.SYNC, f"İndir ve kur ({mb} MB)"
        elif state == "available":
            glyph, text = theme.Icon.OPEN, "Sürüm sayfası"
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
