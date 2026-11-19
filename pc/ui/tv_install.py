"""How to install the TV app, per TV brand: Android / Google TV, Samsung (Tizen), LG (webOS).
Used on the TV page and in the first-run guide. cfg["tv_brand"] remembers the choice; "TV'de aç" follows
cfg["tv_app_brand"] (the TV app that last connected) once there is one."""
import shutil

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

from gt import config, tvctl

from . import theme
from .widgets import Card, icon_button

BRANDS = [
    ("android", "Android TV / Google TV (TCL, Sony, Philips, Xiaomi, Hisense…)"),
    ("samsung", "Samsung (Tizen)"),
    ("lg", "LG (webOS)"),
]
PACKAGES = {"android": config.TV_APK, "samsung": config.ROOT / "OyunCeviri-Samsung.wgt",
            "lg": config.ROOT / "OyunCeviri-LG.ipk"}


def _text(html):
    label = QLabel(html)
    label.setWordWrap(True)
    label.setTextFormat(Qt.RichText)
    label.setOpenExternalLinks(True)
    label.setTextInteractionFlags(Qt.TextBrowserInteraction)
    return label


def _steps(items):
    return _text("".join(
        f"<p style='margin:6px 0'><span style='color:{theme.ACCENT_HI}; font-weight:600'>{i}.</span>&nbsp; {t}</p>"
        for i, t in enumerate(items, 1)))


def _link(url, text=None):
    return f"<a style='color:#7FB2FF' href='{url}'>{text or url}</a>"


def _code(text):
    return (f"<pre style='background:{theme.BG}; color:{theme.TEXT}; padding:8px 10px; margin:4px 0; "
            f"font-family:Consolas'>{text}</pre>")


class TvInstallGuide(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        row = QHBoxLayout()
        row.addWidget(QLabel("TV'nin markası / sistemi"))
        self.brand = QComboBox()
        for key, label in BRANDS:
            self.brand.addItem(label, key)
        row.addWidget(self.brand, 1)
        lay.addLayout(row)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._android())
        self.pages.addWidget(self._samsung())
        self.pages.addWidget(self._lg())
        lay.addWidget(self.pages)
        self.brand.currentIndexChanged.connect(self._brand_changed)
        self.brand.setCurrentIndex(max(0, self.brand.findData(win.cfg.get("tv_brand", "android"))))
        self.pages.setCurrentIndex(self.brand.currentIndex())

    def show_brand(self, brand):
        """Follow a brand set elsewhere (the connected TV app told it) without saving again."""
        self.brand.blockSignals(True)
        self.brand.setCurrentIndex(max(0, self.brand.findData(brand)))
        self.brand.blockSignals(False)
        self.pages.setCurrentIndex(self.brand.currentIndex())

    def _brand_changed(self):
        self.pages.setCurrentIndex(self.brand.currentIndex())
        self.win.cfg["tv_brand"] = self.brand.currentData()
        self.win.persist_config("tv_brand")

    # ---- Android / Google TV ----

    def _android(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)
        auto = Card("Yol 1 · Otomatik (önerilen)",
                    "Bilgisayar TV'yi ağda bulur, uygulamayı kurar, açar ve TV'yi PS5'in girişine geçirir. TV'de bir "
                    "kez geliştirici ayarı açmak gerekir.")
        auto.add(_steps([
            "TV'de <b>Ayarlar → Sistem → Hakkında</b>'ya gir, <b>Android TV OS derlemesi</b> satırına 7 kez bas "
            "(\"Geliştiricisiniz\" yazısı çıkar).",
            "<b>Ayarlar → Sistem → Geliştirici seçenekleri</b>'nde <b>USB hata ayıklama</b>'yı aç.",
            "Aşağıdaki <b>TV'de aç</b>'a bas. TV'de \"USB hata ayıklamaya izin verilsin mi?\" çıkarsa \"Her zaman izin "
            "ver\"i işaretle ve <b>İzin ver</b>'e bas.",
        ]))
        row = QHBoxLayout()
        go = icon_button(theme.Icon.TV, "TV'de aç", "primary")
        go.clicked.connect(lambda: self.win.activate_tv("android"))
        row.addWidget(go)
        row.addStretch(1)
        auto.add_layout(row)
        box.addWidget(auto)
        usb = Card("Yol 2 · USB bellekle", "TV'de geliştirici ayarı açılamıyorsa uygulamayı USB bellekle kur.")
        usb.add(_steps([
            "USB belleği bilgisayara tak, aşağıdaki düğmeyle uygulama dosyasını (OyunCeviri-TV.apk) belleğe kopyala.",
            "TV'de Play Store'dan bir dosya yöneticisi kur (örneğin <b>File Commander</b> ya da <b>X-plore</b>).",
            "USB belleği TV'ye tak, dosya yöneticisinde belleği aç ve <b>OyunCeviri-TV.apk</b>'yı seç.",
            "\"Bilinmeyen uygulamalar\" uyarısı çıkarsa dosya yöneticisine izin ver, sonra <b>Yükle</b>.",
            "<b>Oyun Çeviri</b>'yi aç; ekran üstü iznini kendisi sorar, <b>İzin ver</b>'e bas. Uygulama bu bilgisayarı "
            "kendisi bulur.",
        ]))
        usb.add_layout(self._save_row("android", "APK'yı USB belleğe kopyala"))
        box.addWidget(usb)
        return page

    # ---- Samsung (Tizen) ----

    def _samsung(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)
        how = Card("Samsung TV'de nasıl çalışır",
                   "Samsung, başka bir uygulamanın HDMI görüntüsünün üstüne yazı çizmesine izin vermez. Bu yüzden "
                   "Oyun Çeviri uygulaması PS5'in HDMI görüntüsünü kendi içinde tam ekran açar ve altyazıyı onun "
                   "üstüne yazar. 2019 ve sonrası Samsung TV'ler (Tizen 5.0+).")
        box.addWidget(how)
        inst = Card("Kurulum (bir kez)")
        inst.add(_steps([
            "TV'de <b>Uygulamalar</b>'ı (Apps) aç.",
            "Kumandada <b>1 2 3 4 5</b>'e bas ve birkaç saniye bekle (ya da ekran klavyesinde 12345 yaz). "
            "<b>Developer Mode</b> penceresi açılır. Açılmazsa aynısını <b>Ayarlar</b> ekranındayken dene.",
            f"<b>Developer mode</b>'u <b>On</b> yap, <b>Host PC IP</b> olarak bu bilgisayarın adresini yaz: "
            f"<b>{tvctl.local_ip() or '?'}</b> ve <b>OK</b>'e bas.",
            "Kumandadaki <b>güç tuşunu 3 saniye basılı tut</b>: TV tamamen kapanıp yeniden açılır. (Normal kapatıp "
            "açmak yetmez, Developer Mode ancak böyle devreye girer.)",
            "TV açılınca aşağıdaki <b>Kur ve aç</b>'a bas. Tarayıcıda Samsung giriş sayfası açılırsa ücretsiz Samsung "
            "hesabınla giriş yap; giriş bitince uygulama kendiliğinden kurulup açılır.",
        ]))
        inst.add(_text(f"<span style='color:{theme.MUTED}'>Samsung girişi yalnızca ilk kurulumda istenir: Samsung "
                       f"uygulamayı bu TV için imzalar. Kurulum olmazsa programın klasöründeki "
                       f"<b>logs\\tv-install.log</b> dosyasını bana gönder.</span>"))
        inst.add_layout(self._action_row("samsung"))
        box.addWidget(inst)
        box.addStretch(1)
        return page

    def _lg(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)
        how = Card("LG TV'de nasıl çalışır",
                   "LG de başka bir uygulamanın HDMI görüntüsünün üstüne yazı çizmesine izin vermez. Oyun Çeviri "
                   "uygulaması PS5'in HDMI görüntüsünü kendi içinde tam ekran açar ve altyazıyı onun üstüne yazar.")
        box.addWidget(how)
        inst = Card("Kurulum (bir kez)")
        inst.add(_steps([
            f"{_link('https://webostv.developer.lge.com', 'webostv.developer.lge.com')} adresinde ücretsiz bir LG "
            f"geliştirici hesabı aç.",
            "TV'de <b>LG Content Store</b>'dan <b>Developer Mode</b> uygulamasını kur, aç ve bu hesapla giriş yap.",
            "<b>Dev Mode Status</b>'u aç. TV yeniden başlar.",
            "Developer Mode uygulamasını tekrar aç, <b>Key Server</b>'ı aç ve uygulama ekranda kalsın. Ekranda yazan "
            "<b>Passphrase</b>'i aşağıya yaz ve <b>Kur ve aç</b>'a bas.",
        ]))
        inst.add(_text(f"<span style='color:{theme.MUTED}'>Developer Mode'un süresi, Oyun Çeviri her bağlandığında "
                       f"kendiliğinden uzatılır. Kurulum olmazsa programın klasöründeki <b>logs\\tv-install.log</b> "
                       f"dosyasını bana gönder.</span>"))
        inst.add_layout(self._action_row("lg"))
        box.addWidget(inst)
        box.addStretch(1)
        return page

    # ---- Samsung / LG: find the TV, install and start the app ----

    def _action_row(self, brand):
        from PySide6.QtWidgets import QLineEdit
        lay = QVBoxLayout()
        row = QHBoxLayout()
        ip = QLineEdit()
        ip.setPlaceholderText("TV'nin IP adresi (boş bırakırsan ağda kendisi aranır)")
        row.addWidget(ip, 1)
        passphrase = None
        if brand == "lg":
            passphrase = QLineEdit()
            passphrase.setPlaceholderText("Passphrase (TV ekranında)")
            passphrase.setMaximumWidth(220)
            row.addWidget(passphrase)
        go = icon_button(theme.Icon.TV, "Kur ve aç", "primary")
        row.addWidget(go)
        lay.addLayout(row)
        status = QLabel()
        status.setWordWrap(True)
        status.setTextFormat(Qt.RichText)
        status.setObjectName("muted")
        lay.addWidget(status)
        go.clicked.connect(lambda: self.win.install_web_tv(brand, ip.text().strip(),
                                                           passphrase.text().strip() if passphrase else ""))
        self.win.bridge.tv_progress.connect(lambda state, text: self._web_progress(brand, status, go, state, text))
        return lay

    def _web_progress(self, brand, status, button, state, text):
        if self.brand.currentData() != brand:
            return
        color = {"ok": theme.GREEN, "error": theme.RED}.get(state, theme.MUTED)
        status.setText(f"<span style='color:{color}'>{text}</span>")
        button.setEnabled(state != "busy")

    # ---- saving a package ----

    def _save_row(self, brand, label):
        row = QVBoxLayout()
        line = QHBoxLayout()
        button = icon_button(theme.Icon.USB if brand == "android" else theme.Icon.OPEN, label)
        status = QLabel()
        status.setWordWrap(True)
        button.clicked.connect(lambda: self._save(brand, status))
        line.addWidget(button)
        line.addStretch(1)
        row.addLayout(line)
        row.addWidget(status)
        return row

    def _save(self, brand, status):
        src = PACKAGES[brand]
        if not src.exists():
            status.setText(f"<span style='color:{theme.RED}'>Paket dosyası bulunamadı: {src.name}</span>")
            return
        folder = QFileDialog.getExistingDirectory(self, "Nereye kaydedilsin? (USB bellek ya da bir klasör)")
        if not folder:
            return
        try:
            shutil.copy2(src, folder)
        except OSError as e:
            status.setText(f"<span style='color:{theme.RED}'>Kaydedilemedi: {e}</span>")
            return
        status.setText(f"<span style='color:{theme.GREEN}'>Kaydedildi: {folder}\\{src.name} ✓</span>")
