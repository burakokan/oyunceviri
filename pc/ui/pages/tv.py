"""TV page: connection status, test messages and installing / updating the TV app."""
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QVBoxLayout, QWidget

from gt import config, tvctl

from .. import theme
from ..tv_install import TvInstallGuide
from ..widgets import Card, SettingRow, icon_button

SAMPLES = [
    ("Karl", "Hedef kalede. İçeri gir, dışarı çık ve fark edilme."),
    ("", "Gardiyanlar gergin görünüyor. Bir şeyler oluyor."),
    ("Alman Piyadesi", "Taş üstünde taş bırakmayın!"),
]


class _Progress(QObject):
    step = Signal(str)
    done = Signal(bool, str)


class TvPage(QWidget):
    title = "TV Uygulaması"
    hint = "Türkçe altyazıyı oyunun üstünde gösteren TV uygulaması: Android / Google TV, Samsung ve LG için kurulum, bağlantı ve test."

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cfg = win.cfg
        self._sample = 0
        self._progress = _Progress()
        self._progress.step.connect(lambda t: self.install_status.setText(t))
        self._progress.done.connect(self._install_done)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        conn = Card("Bağlantı", "TV'de Oyun Çeviri uygulaması açıkken bu bilgisayarı kendiliğinden bulur ve "
                                "bağlanır. TV ile bilgisayar aynı modeme bağlı olmalı.")
        self.state = QLabel()
        self.state.setStyleSheet("font-size: 12pt; font-weight: 600;")
        conn.add(self.state)
        self.list = QListWidget()
        self.list.setMaximumHeight(110)
        conn.add(self.list)
        row = QHBoxLayout()
        self.open_button = icon_button(theme.Icon.TV, "TV'yi bul ve uygulamayı aç", "primary")
        self.open_button.setToolTip("Ağda TV'yi kendisi bulur, uygulama yoksa kurar, varsa başlatır. Oyun "
                                    "ekranından (HDMI) çıkmaz. Başlat'a basınca TV bağlı değilse bu kendiliğinden "
                                    "yapılır.")
        self.open_button.clicked.connect(self.win.activate_tv)
        row.addWidget(self.open_button)
        test = icon_button(theme.Icon.PLAY, "Test yazısı gönder")
        test.clicked.connect(self.send_test)
        clear = icon_button(theme.Icon.DELETE, "Ekranı temizle")
        clear.clicked.connect(lambda: self.win.server.send({"type": "clear"}))
        row.addWidget(test)
        row.addWidget(clear)
        row.addStretch(1)
        conn.add_layout(row)
        hdmi = QComboBox()
        hdmi.addItem("Otomatik (TV'de en son açılan HDMI)", 0)
        for n in range(1, 5):
            hdmi.addItem(f"HDMI {n}", n)
        hdmi.setCurrentIndex(max(0, hdmi.findData(self.cfg.get("tv_hdmi", 0))))
        hdmi.currentIndexChanged.connect(lambda: self._set_hdmi(hdmi.currentData()))
        conn.add(SettingRow("PS5'in bağlı olduğu giriş",
                            "Bağlantı kurulunca TV kendiliğinden bu girişe (PS5'in görüntüsüne) geçer.", hdmi))
        self.open_status = QLabel()
        self.open_status.setWordWrap(True)
        self.open_status.setObjectName("muted")
        conn.add(self.open_status)
        lay.addWidget(conn)

        setup = Card("TV uygulamasını kur", "TV'nin markasını seç; kurulum adımları ona göre gösterilir.")
        setup.add(TvInstallGuide(win))
        lay.addWidget(setup)

        inst = Card("Android TV: elle kurulum / güncelleme",
                    "\"TV'de aç\" TV'yi ağda bulamazsa TV'nin IP adresini (TV: Ayarlar → Ağ ve İnternet) yazıp "
                    "buradan kur ya da güncelle.")
        row = QHBoxLayout()
        self.ip = QLineEdit(self.cfg.get("tv_ip", ""))
        self.ip.setPlaceholderText("TV'nin IP adresi, örn. 192.168.1.128")
        self.install_button = icon_button(theme.Icon.SYNC, "Kur / güncelle", "primary")
        self.install_button.clicked.connect(self.install)
        row.addWidget(self.ip, 1)
        row.addWidget(self.install_button)
        inst.add_layout(row)
        self.install_status = QLabel()
        self.install_status.setWordWrap(True)
        self.install_status.setObjectName("muted")
        inst.add(self.install_status)
        apk = QLabel(f"Yüklenecek dosya: {config.TV_APK.name}" if config.TV_APK.exists()
                     else "TV uygulaması dosyası (OyunCeviri-TV.apk) bulunamadı.")
        apk.setObjectName("muted")
        inst.add(apk)
        lay.addWidget(inst)

        look = Card("Altyazı görünümü",
                    "Yazı boyutu, renkler, arka plan, konum ve diğer tüm görünüm ayarları TV Görünümü sayfasında. "
                    "Aynı ayarlar TV uygulamasından kumandayla da yapılabilir.")
        go = icon_button(theme.Icon.PALETTE, "TV Görünümü'ne git")
        go.clicked.connect(lambda: self.win.go("TvLookPage"))
        look.add(go).setMaximumWidth(240)
        lay.addWidget(look)
        lay.addStretch(1)

        win.bridge.clients.connect(self.on_clients)
        win.bridge.tv_progress.connect(self._open_progress)
        self.on_clients([])

    def on_clients(self, clients):
        self.list.clear()
        if clients:
            self.state.setText(f"● {len(clients)} TV bağlı")
            self.state.setStyleSheet(f"font-size: 12pt; font-weight: 600; color: {theme.GREEN};")
            for c in clients:
                self.list.addItem(f"{c['ip']}   ·   uygulama sürümü {c['version']}")
            if not self.ip.text():
                self.ip.setText(clients[0]["ip"])
        else:
            self.state.setText("● Bağlı TV yok")
            self.state.setStyleSheet(f"font-size: 12pt; font-weight: 600; color: {theme.MUTED};")
            self.list.addItem("TV'de Oyun Çeviri uygulamasını aç.")

    def _set_hdmi(self, port):
        self.cfg["tv_hdmi"] = port
        self.win.persist_config("tv_hdmi")

    def _open_progress(self, state, text):
        color = {"ok": theme.GREEN, "error": theme.RED}.get(state, theme.MUTED)
        self.open_status.setText(f"<span style='color:{color}'>{text}</span>")
        self.open_button.setEnabled(state != "busy")
        ip = self.win.cfg.get("tv_ip")
        if ip and not self.ip.text():
            self.ip.setText(ip)

    def send_test(self):
        speaker, text = SAMPLES[self._sample % len(SAMPLES)]
        self._sample += 1
        self.win.server.send({"type": "line", "id": -self._sample, "speaker": speaker, "en": "", "tr": text})

    def install(self):
        ip = self.ip.text().strip()
        if not ip:
            self.install_status.setText("Önce TV'nin IP adresini yaz.")
            return
        self.cfg["tv_ip"] = ip
        self.win.persist_config("tv_ip")
        self.install_button.setEnabled(False)
        threading.Thread(
            target=lambda: self._progress.done.emit(*tvctl.install(ip, config.TV_APK, self._progress.step.emit)),
            daemon=True).start()

    def _install_done(self, ok, message):
        self.install_button.setEnabled(True)
        color = theme.GREEN if ok else theme.RED
        self.install_status.setText(f"<span style='color:{color}'>{message}</span>")
