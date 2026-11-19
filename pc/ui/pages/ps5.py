"""PS5 page: is a PS5 registered for Remote Play, and registering one inside the app (no chiaki-ng):
find the PS5, sign in with the second PSN account, type the 8-digit code."""
import os
import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from gt import ps5link
from gt.remoteplay import load_registration, uses_builtin

from .. import readiness, theme
from ..widgets import Card, Divider, SettingRow, icon_button

COLORS = {"ok": theme.GREEN, "warn": theme.YELLOW, "missing": theme.RED}


class _Work(QObject):
    found = Signal(list, str)           # consoles, error
    account = Signal(bytes, str)        # account id, error
    registered = Signal(object, str)    # registration, error


def _step(n, title):
    label = QLabel(f"<span style='color:{theme.ACCENT_HI}; font-weight:600'>{n}.</span>&nbsp; <b>{title}</b>")
    label.setWordWrap(True)
    label.setContentsMargins(0, 10 if n > 1 else 0, 0, 0)
    return label


def _note():
    label = QLabel()
    label.setWordWrap(True)
    label.setObjectName("muted")
    return label


class Ps5Page(QWidget):
    title = "PS5 Bağlantısı"
    hint = "Program PS5 görüntüsünü Remote Play ile alır ve altyazıyı oradan okur. Oyunu TV'de her zamanki gibi oynarsın."

    def __init__(self, win, compact=False):
        """compact: only the registration steps (used inside the first-run guide)."""
        super().__init__()
        self.win = win
        self.cfg = win.cfg
        self._account = b""
        self._work = _Work()
        self._work.found.connect(self._found)
        self._work.account.connect(self._got_account)
        self._work.registered.connect(self._registered)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        status = Card("Durum")
        self.state = QLabel()
        self.state.setStyleSheet("font-size: 12pt; font-weight: 600;")
        status.add(self.state)
        self.detail = _note()
        status.add(self.detail)
        lay.addWidget(status)
        status.setVisible(not compact)

        reg = Card("PS5'i kaydet (yalnızca ilk sefer, ~3 dakika)",
                   "Her şey bu uygulamanın içinde yapılır; başka program gerekmez. <b>İkinci bir PSN hesabı</b> "
                   "gerekir: kendi hesabınla bağlanırsan oynadığın kolun bağlantısı kopar. Ücretsiz bir PSN hesabı "
                   "aç ve PS5'te bu hesapla bir kez oturum aç.")

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)

        grid.addWidget(_step(1, "PS5'i bul"), 0, 0)
        self.find_button = icon_button(theme.Icon.REFRESH, "Ağda PS5'i ara")
        self.find_button.clicked.connect(self._find)
        grid.addWidget(self.find_button, 0, 1)
        row = QHBoxLayout()
        self.ps5_combo = QComboBox()
        self.ps5_combo.setMinimumWidth(260)
        self.ps5_combo.setEditable(True)
        self.ps5_combo.lineEdit().setPlaceholderText("PS5'in adresi (bulunca kendisi dolar)")
        row.addWidget(self.ps5_combo, 1)
        grid.addLayout(row, 1, 0, 1, 2)
        self.find_note = _note()
        grid.addWidget(self.find_note, 2, 0, 1, 2)

        grid.addWidget(_step(2, "İkinci PSN hesabıyla giriş yap"), 3, 0)
        self.login_button = icon_button(theme.Icon.OPEN, "PSN'e giriş yap")
        self.login_button.clicked.connect(self._login)
        grid.addWidget(self.login_button, 3, 1)
        self.login_note = _note()
        self.login_note.setText("Sony'nin giriş sayfası uygulamanın içinde açılır. Giriş bitince hesap bilgisi "
                                "kendiliğinden alınır; adres kopyalayıp yapıştırmak gerekmez.")
        grid.addWidget(self.login_note, 4, 0, 1, 2)

        grid.addWidget(_step(3, "PS5'teki kodu yaz"), 5, 0)
        explain = _note()
        explain.setText("PS5'te ikinci hesapla oturum açıkken <b>Ayarlar → Sistem → Uzaktan Oynatma → Cihazı "
                        "Bağla</b> (Link Device). Ekranda çıkan 8 haneli kodu buraya yaz.")
        grid.addWidget(explain, 6, 0, 1, 2)
        row = QHBoxLayout()
        self.pin = QLineEdit()
        self.pin.setPlaceholderText("8 haneli kod")
        self.pin.setMaxLength(9)
        self.pin.setMaximumWidth(200)
        self.pin.returnPressed.connect(self._register)
        self.register_button = icon_button(theme.Icon.CHECK, "Kaydet", "primary")
        self.register_button.clicked.connect(self._register)
        row.addWidget(self.pin)
        row.addWidget(self.register_button)
        row.addStretch(1)
        grid.addLayout(row, 7, 0, 1, 2)
        self.register_note = _note()
        grid.addWidget(self.register_note, 8, 0, 1, 2)
        reg.add_layout(grid)
        lay.addWidget(reg)

        adv = Card("Gelişmiş")
        mode = QComboBox()
        mode.addItem("Dahili — pencere gerekmez (önerilen)", "builtin")
        mode.addItem("chiaki-ng penceresinden oku", "window")
        mode.setCurrentIndex(1 if self.cfg.get("capture") == "window" else 0)
        mode.currentIndexChanged.connect(lambda: self._set_capture(mode.currentData()))
        adv.add(SettingRow("Bağlantı türü",
                           "Dahili bağlantı arka planda kendiliğinden bağlanır, PS5 uykudaysa uyandırır, koparsa "
                           "yeniden bağlanır (1080p / 30 fps). chiaki-ng penceresi yalnızca eski yöntem için.", mode))
        adv.add(Divider())
        path_row = QHBoxLayout()
        self.chiaki = QLineEdit(self.cfg["chiaki_path"])
        self.chiaki.editingFinished.connect(self._set_chiaki)
        browse = icon_button(theme.Icon.OPEN, "Gözat")
        browse.clicked.connect(self._browse)
        path_row.addWidget(QLabel("chiaki-ng yeri"))
        path_row.addWidget(self.chiaki, 1)
        path_row.addWidget(browse)
        adv.add_layout(path_row)
        adv.add(Divider())
        forget = icon_button(theme.Icon.DELETE, "Bu uygulamadaki PS5 kaydını sil")
        forget.clicked.connect(self._forget)
        adv.add(SettingRow("Kaydı sil", "Başka bir PS5'e geçerken ya da kayıt bozulduysa. Sonra yeniden kaydet.",
                           forget))
        lay.addWidget(adv)
        adv.setVisible(not compact)
        lay.addStretch(1)

        self._timer = QTimer(self, interval=2000)
        self._timer.timeout.connect(self.refresh)

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
        self._timer.start()
        if not load_registration() and self.ps5_combo.count() == 0 and self.find_button.isEnabled():
            self._find()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._timer.stop()

    def refresh(self):
        state, text = readiness.ps5(self.win)
        self.state.setText(f"<span style='color:{COLORS[state]}'>●</span> {text}")
        reg = load_registration()
        if reg:
            how = "dahili bağlantı" if uses_builtin(self.cfg) else "chiaki-ng penceresi"
            source = "bu uygulamada kaydedildi" if ps5link.load() else "eski chiaki-ng kaydı"
            self.detail.setText(f"PS5: {reg['nickname']} · adres {reg['host']} · {how} · {source}. "
                                f"Yeniden kaydetmek gerekmez.")
        else:
            self.detail.setText("PS5 henüz kaydedilmedi. Aşağıdaki 3 adımı sırayla yap.")

    # ---- 1. find ----

    def _find(self):
        self.find_button.setEnabled(False)
        self.find_note.setText("PS5 aranıyor…")

        def work():
            try:
                self._work.found.emit(ps5link.discover(3000), "")
            except Exception as e:  # noqa: BLE001 - shown in the page
                self._work.found.emit([], str(e))

        threading.Thread(target=work, daemon=True).start()

    def _found(self, consoles, error):
        self.find_button.setEnabled(True)
        self.ps5_combo.clear()
        for c in consoles:
            self.ps5_combo.addItem(f"{c['name']}  ·  {c['host']}", c["host"])
        if consoles:
            self.find_note.setText(f"<span style='color:{theme.GREEN}'>Bulundu: "
                                   + ", ".join(f"{c['name']} ({'açık' if c['awake'] else 'uykuda'})" for c in consoles)
                                   + "</span>")
        else:
            self.find_note.setText(error or "PS5 bulunamadı. PS5 açık mı ve bilgisayarla aynı modeme bağlı mı? "
                                            "Bulamazsa PS5'in adresini kutuya kendin yaz (PS5: Ayarlar → Ağ → "
                                            "Bağlantı Durumu).")

    def _host(self):
        data = self.ps5_combo.currentData()
        if data and self.ps5_combo.currentText().endswith(data):
            return data
        return self.ps5_combo.currentText().strip().split("·")[-1].strip()

    # ---- 2. PSN account ----

    def _login(self):
        try:
            from ..psn_login import PsnLogin
            dialog = PsnLogin(self)
        except Exception as e:  # noqa: BLE001 - web view missing or broken
            self.login_note.setText(f"<span style='color:{theme.RED}'>Giriş penceresi açılamadı: {e}</span>")
            return
        if not dialog.exec() or not dialog.code:
            self.login_note.setText("Giriş tamamlanmadı. Tekrar dene.")
            return
        code = dialog.code
        self.login_button.setEnabled(False)
        self.login_note.setText("Hesap bilgisi alınıyor…")

        def work():
            try:
                self._work.account.emit(ps5link.account_from_code(code), "")
            except Exception as e:  # noqa: BLE001
                self._work.account.emit(b"", str(e))

        threading.Thread(target=work, daemon=True).start()

    def _got_account(self, account, error):
        self.login_button.setEnabled(True)
        if account:
            self._account = account
            self.login_note.setText(f"<span style='color:{theme.GREEN}'>Hesap alındı ✓</span> Şimdi 3. adım.")
            self.pin.setFocus()
        else:
            self.login_note.setText(f"<span style='color:{theme.RED}'>{error}</span>")

    # ---- 3. register ----

    def _register(self):
        host = self._host()
        if not host:
            self.register_note.setText(f"<span style='color:{theme.RED}'>Önce 1. adımda PS5'i bul.</span>")
            return
        if not self._account:
            self.register_note.setText(f"<span style='color:{theme.RED}'>Önce 2. adımda PSN'e giriş yap.</span>")
            return
        if self.win.engine.running and uses_builtin(self.cfg):
            self.register_note.setText(f"<span style='color:{theme.RED}'>Önce sağ üstten Durdur'a bas.</span>")
            return
        pin = self.pin.text()
        self.register_button.setEnabled(False)
        self.register_note.setText("PS5'e kaydediliyor… (en çok 30 saniye)")

        def work():
            try:
                self._work.registered.emit(ps5link.register(host, self._account, pin), "")
            except Exception as e:  # noqa: BLE001
                self._work.registered.emit(None, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _registered(self, reg, error):
        self.register_button.setEnabled(True)
        if not reg:
            self.register_note.setText(f"<span style='color:{theme.RED}'>{error}</span>")
            return
        ps5link.save(reg)
        self.pin.clear()
        self.register_note.setText(f"<span style='color:{theme.GREEN}'>Kaydedildi: {reg['nickname']} ✓ Artık "
                                   f"Başlat'a basman yeterli.</span>")
        if self.cfg.get("capture") == "window":
            self.cfg["capture"] = "auto"
            self.win.persist_config("capture")
        self.win.refresh_banner()
        self.win.check_window()
        self.refresh()

    # ---- advanced ----

    def _forget(self):
        ps5link.forget()
        self.refresh()
        self.win.check_window()

    def _set_capture(self, mode):
        self.cfg["capture"] = mode
        self.win.persist_config("capture")
        self.win.refresh_banner()
        self.win.check_window()
        self.refresh()
        if self.win.engine.running:
            self.win.show_message("Bağlantı türü bir sonraki Başlat'ta değişir (Durdur → Başlat).")

    def _set_chiaki(self):
        self.cfg["chiaki_path"] = self.chiaki.text().strip()
        self.win.persist_config("chiaki_path")

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "chiaki.exe'yi seç", os.path.dirname(self.cfg["chiaki_path"]),
                                              "Programlar (*.exe)")
        if path:
            self.chiaki.setText(os.path.normpath(path))
            self._set_chiaki()
