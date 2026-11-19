"""Main window: sidebar navigation, header with status and Start button, pages, tray icon."""
import copy
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea,
    QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from gt import config, tvctl
from gt.engine import Engine
from gt.regions import RegionTranslator
from gt.screen import ScreenTranslator
from gt.remoteplay import RemotePlay, active_roi, needs_link, uses_builtin
from gt.server import SubtitleServer
from gt.updater import FROZEN, UpdateError, Updater
from gt.version import TV_APP, TV_WEB, VERSION, parse
from gt.winutil import find_window

from . import theme
from .game_select import GameSelect
from .pages.filters_page import FiltersPage
from .pages.guide import GuidePage
from .pages.live import LivePage
from .pages.packs_page import PacksPage
from .pages.ps5 import Ps5Page
from .pages.region import RegionPage
from .pages.settings import SettingsPage
from .pages.translation import TranslationPage
from .pages.tv import TvPage
from .pages.tv_look import TvLookPage
from .widgets import Pill, icon_button, icon_label


class Bridge(QObject):
    """Carries engine / server events from worker threads to the UI thread."""
    status = Signal(str, str)
    line = Signal(dict)
    clear = Signal()
    preview = Signal(object, object, object)
    clients = Signal(list)
    ack = Signal(int, float)
    tv_style = Signal(dict)
    rp_status = Signal(str, str)
    tv_progress = Signal(str, str)      # "busy" / "ok" / "error", text
    tv_found = Signal(str)              # the TV's address, to remember it
    screen_status = Signal(str)         # screen translation (menus, quests)
    region_status = Signal(str, str)    # hint box / phone area: kind, text
    update_state = Signal(str, str, object)     # updates: state, text, plan
    message = Signal(str, bool)         # a message for the banner from a worker thread: text, error


# Sidebar: section title, then (icon, page) in that section
NAV = [
    ("OYNA", [(theme.Icon.HOME, LivePage)]),
    ("KURULUM (BİR KEZ)", [(theme.Icon.HELP, GuidePage), (theme.Icon.LINK, Ps5Page), (theme.Icon.CROP, RegionPage),
                           (theme.Icon.TV, TvPage)]),
    ("OYUNLAR", [(theme.Icon.LIBRARY, PacksPage)]),
    ("AYARLAR", [(theme.Icon.PALETTE, TvLookPage), (theme.Icon.FILTER, FiltersPage),
                 (theme.Icon.GLOBE, TranslationPage), (theme.Icon.SETTINGS, SettingsPage)]),
]
PAGES = [item for _, items in NAV for item in items]


class MainWindow(QMainWindow):
    screen_changed = Signal(bool)
    def __init__(self, icon):
        super().__init__()
        self.setWindowTitle("Oyun Çeviri")
        self.setWindowIcon(icon)
        self.resize(1280, 860)
        self.setMinimumSize(1000, 680)
        self.cfg = config.load()
        # The game choice is not kept between starts: every start begins with automatic detection.
        self.cfg["packs"]["game"] = "auto"
        self.cfg["packs"]["custom_title"] = ""
        # Settings pages change self.cfg at once (so the change can be tried), but it is written to config.json
        # only with "Kaydet"; "Vazgeç" goes back to the last saved state. self._saved = what is on disk.
        self._saved = copy.deepcopy(self.cfg)
        self._dirty = False
        self._quitting = False
        self._tray_hint_shown = False
        self.tv_clients = []
        self.tv_activation = (None, "")     # last state and text of "open the TV app"
        self.updater = Updater(self.cfg)
        self.update_state = ("idle", "", None)
        self._applying = False
        self._tv_updates = set()            # (ip, version) of TV apps already updated / reported this session
        self._tv_update_waiting = []        # Android TV apps to update once the subtitles are stopped

        self.bridge = Bridge()
        self.server = SubtitleServer(self.cfg["ws_port"], on_clients=self.bridge.clients.emit,
                                     on_ack=self.bridge.ack.emit, on_style=self.bridge.tv_style.emit)
        self.rp = RemotePlay(on_status=self.bridge.rp_status.emit)
        self.engine = Engine(self.server, on_status=self.bridge.status.emit, on_line=self.bridge.line.emit,
                             on_clear=self.bridge.clear.emit, on_preview=self.bridge.preview.emit, rp=self.rp)

        self.screen = ScreenTranslator(self.server, self.rp, self.cfg,
                                       local_translate=lambda text: self.engine.machine_translate(text, self.cfg),
                                       game_title=self._game_title, on_status=self.bridge.screen_status.emit)
        self.screen.set_enabled(self.cfg["screen"]["enabled"])
        # The hint box and the phone's messages, each translated into one box (when their area is chosen and on).
        self.regions = RegionTranslator(self.server, self.rp, self.cfg, self.engine,
                                        on_status=self.bridge.region_status.emit)


        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._build_sidebar())
        content = QWidget()
        content.setObjectName("content")
        v = QVBoxLayout(content)
        v.setContentsMargins(28, 22, 28, 22)
        v.setSpacing(14)
        v.addWidget(self._build_header())
        self.banner = QFrame()
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 10, 14, 10)
        self.banner_icon = icon_label(theme.Icon.WARNING, 16)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        bl.addWidget(self.banner_icon)
        bl.addWidget(self.banner_text, 1)
        v.addWidget(self.banner)
        v.addWidget(self._build_save_bar())
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        h.addWidget(content, 1)
        self.setCentralWidget(root)

        self.pages = []
        for (glyph, cls), button in zip(PAGES, self.nav_buttons):
            page = cls(self)
            self.pages.append(page)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            scroll.setFrameShape(QFrame.NoFrame)
            self.stack.addWidget(scroll)
        self.select_page(0)
        if not self.cfg.get("onboarded"):
            self.go("GuidePage")        # first start: the step-by-step guide

        self.bridge.status.connect(self.on_status)
        self.bridge.clients.connect(self.on_clients)
        self.bridge.rp_status.connect(self.on_rp_status)
        self.bridge.tv_progress.connect(self._tv_progress)
        self.bridge.tv_found.connect(self._tv_found)
        self.bridge.update_state.connect(self._on_update_state)
        self.bridge.message.connect(self.show_message)
        self._build_tray(icon)

        self._window_timer = QTimer(self, interval=2000)
        self._window_timer.timeout.connect(self.check_window)
        self._window_timer.start()
        self.check_window()
        # A TV app that was already running can connect while the window is still being built, before the
        # clients signal is connected: take the server's current list instead of assuming "no TV".
        self.on_clients(self.server.snapshot() or [])
        self.refresh_banner()
        if self.server.error:
            self.show_message(self.server.error, error=True)
        if self.cfg.get("tv_ip"):
            self.server.beacon_to.add(self.cfg["tv_ip"].split(":")[0])
        self._start_updates()

    # ---- layout ----

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(232)
        v = QVBoxLayout(side)
        v.setContentsMargins(16, 22, 16, 18)
        v.setSpacing(4)
        logo = QHBoxLayout()
        logo.setSpacing(10)
        mark = icon_label(theme.Icon.TV, 26, theme.ACCENT)
        names = QVBoxLayout()
        names.setSpacing(0)
        title = QLabel("Oyun Çeviri")
        title.setObjectName("appTitle")
        sub = QLabel("PS5 · İngilizce → Türkçe")
        sub.setObjectName("appSubtitle")
        names.addWidget(title)
        names.addWidget(sub)
        logo.addWidget(mark)
        logo.addLayout(names, 1)
        v.addLayout(logo)
        v.addSpacing(14)

        self.nav_group = QButtonGroup(self)
        self.nav_buttons = []
        for section, items in NAV:
            v.addSpacing(10)
            head = QLabel(section)
            head.setObjectName("navSection")
            v.addWidget(head)
            v.addSpacing(2)
            for glyph, cls in items:
                i = len(self.nav_buttons)
                b = icon_button(glyph, f"  {cls.title}")
                b.setObjectName("navButton")
                b.setCheckable(True)
                b.clicked.connect(lambda _=False, i=i: self.select_page(i))
                self.nav_group.addButton(b)
                self.nav_buttons.append(b)
                v.addWidget(b)
        v.addStretch(1)
        self.side_tv = Pill("TV")
        self.side_ps = Pill("PS5 görüntüsü")
        v.addWidget(self.side_ps)
        v.addSpacing(6)
        v.addWidget(self.side_tv)
        return side

    def _build_header(self):
        header = QFrame()
        header.setObjectName("header")
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 0)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.page_title = QLabel()
        self.page_title.setObjectName("pageTitle")
        self.page_hint = QLabel()
        self.page_hint.setObjectName("pageHint")
        self.page_hint.setWordWrap(True)
        texts.addWidget(self.page_title)
        texts.addWidget(self.page_hint)
        h.addLayout(texts, 1)
        game = QLabel("Oyun")
        game.setObjectName("muted")
        h.addWidget(game)
        h.addSpacing(6)
        self.game_select = GameSelect(self, width=270)
        h.addWidget(self.game_select)
        h.addSpacing(14)
        self.status_pill = Pill("Durduruldu")
        h.addWidget(self.status_pill, 0, Qt.AlignVCenter)
        h.addSpacing(10)
        self.start_button = icon_button(theme.Icon.PLAY, "Başlat", "startButton")
        self.start_button.clicked.connect(self.toggle_engine)
        h.addWidget(self.start_button)
        return header

    def _build_tray(self, icon):
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("Oyun Çeviri")
        menu = QMenu()
        show = QAction("Pencereyi göster", self)
        show.triggered.connect(self.bring_to_front)
        self.tray_toggle = QAction("Başlat", self)
        self.tray_toggle.triggered.connect(self.toggle_engine)
        quit_action = QAction("Çıkış", self)
        quit_action.triggered.connect(self.quit)
        self.tray_screen = QAction("Ekran çevirisi (menü, görev)", self, checkable=True)
        self.tray_screen.setChecked(self.cfg["screen"]["enabled"])
        self.tray_screen.toggled.connect(self.set_screen_translation)
        screen_now = QAction("Ekranı şimdi çevir", self)
        screen_now.triggered.connect(self.screen.translate_now)
        menu.addAction(show)
        menu.addAction(self.tray_toggle)
        menu.addSeparator()
        menu.addAction(self.tray_screen)
        menu.addAction(screen_now)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.bring_to_front() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def select_page(self, i):
        self.stack.setCurrentIndex(i)
        self.nav_buttons[i].setChecked(True)
        page = self.pages[i]
        self.page_title.setText(page.title)
        self.page_hint.setText(page.hint)

    def go(self, name):
        """Open a page by its class name, e.g. win.go("RegionPage")."""
        for i, page in enumerate(self.pages):
            if type(page).__name__ == name:
                self.select_page(i)
                return

    # ---- state ----

    def _build_save_bar(self):
        bar = QFrame()
        bar.setObjectName("saveBar")
        bar.setStyleSheet(f"#saveBar {{ background: {theme.CARD_HI}; border: 1px solid {theme.ACCENT}; "
                          f"border-radius: 10px; }}")
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 8, 14, 8)
        h.addWidget(icon_label(theme.Icon.INFO, 16, theme.ACCENT_HI))
        text = QLabel("Kaydedilmemiş ayar değişikliği var. Şu an deneniyor; kalıcı olması için <b>Kaydet</b>'e bas "
                      "(Ctrl+S), istemiyorsan <b>Vazgeç</b>.")
        text.setWordWrap(True)
        h.addWidget(text, 1)
        undo = icon_button(theme.Icon.REFRESH, "Vazgeç")
        undo.clicked.connect(self.revert_settings)
        save = icon_button(theme.Icon.CHECK, "Kaydet", "primary")
        save.clicked.connect(self.commit_settings)
        h.addWidget(undo)
        h.addWidget(save)
        bar.hide()
        self.save_bar = bar
        QShortcut(QKeySequence.Save, self, self.commit_settings)
        return bar

    def save_config(self):
        """A setting changed on a settings page: used right away, written to disk with "Kaydet"."""
        if not self._dirty:
            self._dirty = True
            self.save_bar.show()

    def persist_config(self, *paths):
        """Internal state that is kept at once (found TV address, chosen subtitle area, PS5 link, game choice…):
        only these values go to disk, unsaved settings stay unsaved. paths: "key" or ("section", "key")."""
        for path in paths:
            keys = (path,) if isinstance(path, str) else tuple(path)
            src, dst = self.cfg, self._saved
            for k in keys[:-1]:
                src = src.get(k, {})
                dst = dst.setdefault(k, {})
            if keys[-1] in src:
                dst[keys[-1]] = copy.deepcopy(src[keys[-1]])
            else:
                dst.pop(keys[-1], None)
        config.save(self._saved)

    def commit_settings(self):
        config.save(self.cfg)
        self._saved = copy.deepcopy(self.cfg)
        self._dirty = False
        self.save_bar.hide()
        for page in self.pages:
            if hasattr(page, "committed"):
                page.committed()
        self.tray.showMessage("Oyun Çeviri", "Ayarlar kaydedildi ✓", QSystemTrayIcon.Information, 1500)

    def revert_settings(self):
        """Back to the last saved settings: the values, and the pages that show them."""
        saved = copy.deepcopy(self._saved)
        self.cfg.clear()
        self.cfg.update(saved)          # in place: the engine and the screen translator keep the same dict
        for i, page in enumerate(self.pages):
            if type(page).__name__ in ("FiltersPage", "SettingsPage", "TranslationPage"):
                scroll = self.stack.widget(i)
                fresh = type(page)(self)
                old = scroll.takeWidget()
                scroll.setWidget(fresh)
                self.pages[i] = fresh
                old.deleteLater()
            elif hasattr(page, "reverted"):
                page.reverted()
        self.screen.restyle()
        self._dirty = False
        self.save_bar.hide()

    def toggle_engine(self):
        if self.engine.running:
            self.engine.stop()
            self.status_pill.set_state(theme.YELLOW, "Durduruluyor…")
        else:
            if not active_roi(self.cfg):
                self.go("RegionPage")
                self.show_message("Önce altyazının çıktığı alanı seç.", error=True)
                return
            self.engine.start(self.cfg)
            self.go("LivePage")
            if not self.tv_clients:
                self.activate_tv()      # the TV app is not running: start it from here

    def on_status(self, state, text):
        colors = {"stopped": theme.MUTED, "loading": theme.YELLOW, "waiting": theme.YELLOW,
                  "running": theme.GREEN, "error": theme.RED}
        labels = {"stopped": "Durduruldu", "loading": "Yükleniyor", "waiting": "Bekleniyor",
                  "running": "Çalışıyor", "error": "Hata"}
        self.status_pill.set_state(colors[state], labels[state])
        running = state in ("loading", "waiting", "running")
        self.start_button.setText(f"{theme.Icon.STOP}  Durdur" if running else f"{theme.Icon.PLAY}  Başlat")
        self.start_button.setProperty("running", "true" if running else "false")
        self.start_button.style().unpolish(self.start_button)
        self.start_button.style().polish(self.start_button)
        self.tray_toggle.setText("Durdur" if running else "Başlat")
        self._engine_running = running
        if state == "stopped" and self._tv_update_waiting:
            waiting, self._tv_update_waiting = self._tv_update_waiting, []
            for ip, old in waiting:
                self._update_tv_app(ip, old)
        self.tray.setToolTip(f"Oyun Çeviri · {labels[state]}")
        if state in ("error", "waiting"):
            self.show_message(text, error=state == "error")
        else:
            self.refresh_banner()

    # ---- screen translation ----

    def set_screen_translation(self, on):
        self.cfg["screen"]["enabled"] = on
        self.persist_config(("screen", "enabled"))
        self.screen.set_enabled(on)
        if self.tray_screen.isChecked() != on:
            self.tray_screen.setChecked(on)
        self.screen_changed.emit(on)

    def _game_title(self):
        return self.engine.game_title(self.cfg)

    # ---- TV app ----

    def install_web_tv(self, brand, ip="", passphrase=""):
        """Samsung / LG: find the TV in Developer Mode, install (or update) the TV app and start it."""
        if self.tv_activation[0] == "busy":
            return
        self.bridge.tv_progress.emit("busy", "TV aranıyor…")

        def work():
            from gt import tvctl, tvweb
            from gt.tvweb import LG, Samsung
            tv = Samsung if brand == "samsung" else LG
            name = "Samsung" if brand == "samsung" else "LG"

            def say(state, text):
                tvweb.log(f"[{state}] {text}")
                self.bridge.tv_progress.emit(state, text)

            progress = lambda t: say("busy", t)  # noqa: E731
            tvweb.log(f"--- {name} kurulum · bu PC: {', '.join(tvctl.lan_ips()) or '?'} · yazılan IP: {ip or '-'}")
            found = tv.find(ip or self.cfg.get("tv_ip", ""), progress)
            if not found:
                restart = ("Developer Mode'u açtıktan sonra kumandadaki güç tuşunu 3 saniye basılı tutarak TV'yi yeniden "
                           "başlattın mı? " if tv is Samsung else "")
                say("error", f"Ağda Developer Mode'u açık bir {name} TV bulunamadı. {restart}TV ile bu bilgisayar aynı "
                             f"ağda olmalı. Bulamıyorsa TV'nin IP adresini yaz (TV'de Ayarlar → Genel → Ağ → Ağ Durumu).")
                return
            self.bridge.tv_found.emit(found)
            if tv is Samsung:
                progress(f"TV bulundu ({found}). TV'deki Host PC IP {tvctl.pc_ip_for(found)} olmalı.")
            if tv is LG and (passphrase or not LG.has_key(found)):
                if not passphrase:
                    say("error", "TV'deki Developer Mode uygulamasında yazan Passphrase'i yaz.")
                    return
                ok, message = LG.fetch_key(found, passphrase)
                if not ok:
                    say("error", message)
                    return
            ok, message = tv.install(found, progress)
            say("ok" if ok else "error", message)

        threading.Thread(target=work, daemon=True).start()

    def activate_tv(self, brand=None):
        """Find the TV on the network, install the TV app if needed and start it (background thread).
        Samsung / LG: start the installed app (it switches to the PS5's HDMI input by itself).
        brand: "android" from the Android steps' button; otherwise the TV app that last connected."""
        if self.tv_activation[0] == "busy":
            return
        brand = brand if isinstance(brand, str) else self.tv_kind()
        if brand in ("samsung", "lg"):
            self.bridge.tv_progress.emit("busy", "TV uygulaması açılıyor…")

            def web():
                from gt.tvweb import LG, Samsung
                tv = Samsung if brand == "samsung" else LG
                ip = tv.find(self.cfg.get("tv_ip", ""), lambda t: self.bridge.tv_progress.emit("busy", t))
                if not ip:
                    self.bridge.tv_progress.emit("error", "TV bulunamadı: TV açık ve Developer Mode açık olmalı.")
                    return
                self.bridge.tv_found.emit(ip)
                if tv is LG and not LG.has_key(ip):
                    self.bridge.tv_progress.emit("error", "Önce TV Uygulaması sayfasından LG kurulumunu yap.")
                    return
                ok, message = tv.launch(ip)
                self.bridge.tv_progress.emit("ok" if ok else "error",
                                             (message or "TV uygulaması açıldı.") if ok else
                                             f"TV uygulaması açılamadı: {message}")

            threading.Thread(target=web, daemon=True).start()
            return
        self._tv_progress("busy", "TV aranıyor…")

        def work():
            ok, message, ip = tvctl.activate(self.cfg.get("tv_ip", ""), config.TV_APK,
                                             lambda t: self.bridge.tv_progress.emit("busy", t),
                                             connected=lambda: bool(self.server.tv_ips),
                                             found=self.server.beacon_to.add,
                                             hdmi_port=self.cfg.get("tv_hdmi") or None)
            if ip:
                self.bridge.tv_found.emit(ip)
            self.bridge.tv_progress.emit("ok" if ok else "error", message)

        threading.Thread(target=work, daemon=True).start()

    def _tv_progress(self, state, text):
        self.tv_activation = (state, text)

    def _tv_found(self, ip):
        if self.cfg.get("tv_ip") != ip:
            self.cfg["tv_ip"] = ip
            self.persist_config("tv_ip")

    def tv_kind(self):
        """The TV "TV'de aç" works with: the kind of the TV app that last connected; the brand picked on the TV page
        only until a TV app has connected once (picking a brand just to read its steps changes nothing)."""
        return self.cfg.get("tv_app_brand") or self.cfg.get("tv_brand", "android")

    @staticmethod
    def _brand_of(clients):
        """The TV kind a connected TV app reports: Android app "0.9", web app "0.8-web-tizen" / "-webos"."""
        for c in clients:
            version = str(c.get("version") or "?")
            if version.endswith("-tizen"):
                return "samsung"
            if version.endswith("-webos"):
                return "lg"
            if version != "?" and "-web" not in version:
                return "android"
        return None

    def on_clients(self, clients):
        self.tv_clients = clients
        self._check_tv_apps(clients)
        if clients:
            self.side_tv.set_state(theme.GREEN, f"TV bağlı · {clients[0]['ip']}")
        else:
            self.side_tv.set_state(theme.MUTED, "TV bağlı değil")
        # The connected TV app knows what TV it runs on: a brand picked by hand (e.g. while reading the Samsung
        # steps) must not make "TV'de aç" look for the wrong kind of TV.
        brand = self._brand_of(clients)
        if brand and (brand != self.cfg.get("tv_app_brand") or brand != self.cfg.get("tv_brand")):
            self.cfg["tv_app_brand"] = self.cfg["tv_brand"] = brand
            self.persist_config("tv_app_brand", "tv_brand")
            from .tv_install import TvInstallGuide
            for guide in self.findChildren(TvInstallGuide):
                guide.show_brand(brand)
            self.refresh_banner()

    def check_window(self):
        live = self.server.snapshot() or []
        if [(c["ip"], c.get("version")) for c in live] != [(c["ip"], c.get("version")) for c in self.tv_clients]:
            self.on_clients(live)       # a missed connect / disconnect message
        if uses_builtin(self.cfg):
            self.on_rp_status(self.rp.state, self.rp.text, banner=False)
            return
        if needs_link(self.cfg):
            self.side_ps.set_state(theme.MUTED, "PS5 bağlı değil")
            return
        hwnd, _ = find_window(self.cfg["window_process"])
        if hwnd:
            self.side_ps.set_state(theme.GREEN, "chiaki-ng açık")
        else:
            self.side_ps.set_state(theme.MUTED, "chiaki-ng kapalı")

    def on_rp_status(self, state, text, banner=True):
        colors = {"connected": theme.GREEN, "connecting": theme.YELLOW, "quit": theme.YELLOW,
                  "error": theme.RED, "off": theme.MUTED, "asleep": theme.MUTED}
        labels = {"connected": "PS5 bağlı", "connecting": "PS5'e bağlanıyor", "quit": "PS5 yeniden bağlanıyor",
                  "error": "PS5 bağlantı hatası", "off": "PS5 (dahili Remote Play)", "asleep": "PS5 kapalı"}
        self.side_ps.set_state(colors.get(state, theme.MUTED), labels.get(state, "PS5"))
        self.side_ps.setToolTip(text)
        if self.engine.log and (state, text) != getattr(self, "_rp_logged", None):
            self._rp_logged = (state, text)
            self.engine.log.note(remote_play=state, text=text[:160])     # why the picture stopped, in the log
        if banner and state in ("quit", "error", "asleep"):
            self.show_message(f"Remote Play: {text}", error=state == "error")
        elif banner and state == "connected":
            self.refresh_banner()

    def show_message(self, text, error=False):
        self.banner.setObjectName("bannerError" if error else "banner")
        self.banner_icon.setText(theme.Icon.WARNING if error else theme.Icon.INFO)
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
        for w in (self.banner_icon, self.banner_text):
            w.style().unpolish(w)
            w.style().polish(w)
        self.banner_text.setText(text)
        self.banner.show()

    def refresh_banner(self):
        if not active_roi(self.cfg):
            self.show_message("Altyazı Alanı sayfasından altyazının çıktığı yeri seç (PS5 görüntüsü orada "
                              "kendiliğinden açılır). Ana Sayfa'daki hazırlık listesi sırayı gösterir.")
        else:
            self.banner.hide()

    # ---- updates (GitHub Releases) ----

    def _start_updates(self):
        """At start: report an update installed while the app was closed, then look for a new one."""
        result = self.updater.finish()
        if result and result[0] == "ok":
            self.show_message(f"Oyun Çeviri {VERSION} sürümüne güncellendi ✓")
            self.tray.showMessage("Oyun Çeviri", f"{VERSION} sürümüne güncellendi.", QSystemTrayIcon.Information,
                                  4000)
        elif result:
            self.show_message("Güncelleme kurulamadı (dosyalar kullanımdaydı). Genel → Güncelleme'den tekrar dene; "
                              "ayrıntı logs\\update.log içinde.", error=True)
        ready = self.updater.ready()
        if ready:
            self._on_update_state("ready", f"{ready} sürümü indirildi. Uygulamayı kapatınca kurulur.", None)
        elif FROZEN and self.cfg["update"]["auto"]:
            QTimer.singleShot(20000, lambda: self.check_updates(download=True))

    def check_updates(self, download=False):
        """Look for a new version (background thread); download it too when download=True."""
        if self.update_state[0] in ("checking", "downloading"):
            return
        self.bridge.update_state.emit("checking", "Yeni sürüm aranıyor…", None)

        def work():
            try:
                plan = self.updater.check()
            except UpdateError as e:
                self.bridge.update_state.emit("error", str(e), None)
                return
            except Exception as e:      # an unexpected answer must not break the app
                self.bridge.update_state.emit("error", f"Güncelleme denetlenemedi: {e}", None)
                return
            if plan["state"] == "latest":
                self.bridge.update_state.emit("latest", f"En yeni sürüm kurulu ({VERSION}).", plan)
            elif plan["state"] == "setup":
                self.bridge.update_state.emit("setup", f"{plan['version']} sürümü yeni kurulum istiyor: sürüm "
                                                       f"sayfasından kurulum dosyasını indir.", plan)
            else:
                notes = " · ".join(plan["notes"][-3:])
                self.bridge.update_state.emit("available", f"Yeni sürüm var: {plan['version']}."
                                                           + (f" {notes}" if notes else ""), plan)
                if download and FROZEN:
                    self._download(plan)

        threading.Thread(target=work, daemon=True).start()

    def download_update(self, plan):
        if self.update_state[0] in ("checking", "downloading"):
            return
        threading.Thread(target=self._download, args=(plan,), daemon=True).start()

    def _download(self, plan):
        last = [-1]

        def progress(done, total):
            pct = int(done * 100 / total) if total else 100
            if pct != last[0]:
                last[0] = pct
                self.bridge.update_state.emit("downloading", f"{plan['version']} indiriliyor… %{pct}", plan)

        progress(0, plan["size"])
        try:
            self.updater.download(plan, progress)
        except UpdateError as e:
            self.bridge.update_state.emit("error", str(e), None)
            return
        except Exception as e:
            self.bridge.update_state.emit("error", f"Güncelleme indirilemedi: {e}", None)
            return
        self.bridge.update_state.emit("ready", f"{plan['version']} sürümü indirildi. Uygulamayı kapatınca kurulur; "
                                               f"hemen kurmak için \"Yeniden başlat ve kur\".", plan)

    def _on_update_state(self, state, text, plan):
        previous = self.update_state[0]
        self.update_state = (state, text, plan)
        for page in self.pages:
            if hasattr(page, "on_update_state"):
                page.on_update_state(state, text, plan)
        if state == "ready" and previous == "downloading":
            self.tray.showMessage("Oyun Çeviri", f"Güncelleme hazır ({plan['version']}). Uygulamayı kapatınca "
                                  f"kurulur.", QSystemTrayIcon.Information, 5000)

    def install_update(self):
        version = self.updater.ready()
        if not version:
            return
        text = (f"{version} sürümü kurulacak: Oyun Çeviri kapanıp birkaç saniye içinde yeniden açılacak."
                + (" Altyazı çevirisi kısa bir süre duracak." if getattr(self, "_engine_running", False) else ""))
        if QMessageBox.question(self, "Oyun Çeviri", text, QMessageBox.Ok | QMessageBox.Cancel,
                                QMessageBox.Ok) != QMessageBox.Ok:
            return
        try:
            self.updater.apply(relaunch=True)
        except OSError as e:
            self.show_message(f"Güncelleme başlatılamadı: {e}", error=True)
            return
        self._applying = True
        self.quit()

    # ---- TV app versions ----

    def _check_tv_apps(self, clients):
        """A connected TV app older than the one this app carries: the Android app is updated over the network
        (only while the subtitles are stopped, so a game is never interrupted); Samsung / LG get a note."""
        for c in clients:
            version, ip = str(c.get("version") or ""), c.get("ip", "")
            if not version or version == "?" or not ip or (ip, version) in self._tv_updates:
                continue
            web = "-web" in version
            if parse(version) >= parse(TV_WEB if web else TV_APP):
                continue
            self._tv_updates.add((ip, version))
            if web:
                self.show_message(f"TV uygulaması eski ({version.split('-')[0]}, yenisi {TV_WEB}). TV Uygulaması "
                                  f"sayfasından TV'ye yeniden kur.")
            elif getattr(self, "_engine_running", False):
                self._tv_update_waiting.append((ip, version))
            else:
                self._update_tv_app(ip, version)

    def _update_tv_app(self, ip, old):
        if not config.TV_APK.exists():
            return
        self.show_message(f"TV uygulaması güncelleniyor ({old} → {TV_APP})…")

        def work():
            ok, message = tvctl.install(ip, config.TV_APK, lambda t: None)
            self.bridge.message.emit(f"TV uygulaması {TV_APP} sürümüne güncellendi ✓" if ok else
                                     f"TV uygulaması güncellenemedi: {message}", not ok)

        threading.Thread(target=work, daemon=True).start()

    # ---- window / tray ----

    def bring_to_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):
        if self._quitting or not self.cfg["minimize_to_tray"]:
            self.quit()
            e.accept()
            return
        e.ignore()
        self.hide()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self.tray.showMessage("Oyun Çeviri", "Arka planda çalışmaya devam ediyor. Kapatmak için simgeye sağ "
                                  "tıklayıp Çıkış'ı seç.", QSystemTrayIcon.Information, 4000)

    def quit(self):
        self._quitting = True
        self.engine.stop()
        self.engine.conductor.gemma.stop()      # the llama.cpp process of Gemma 4, if it was started
        if self._dirty:
            keep = QMessageBox.question(self, "Oyun Çeviri", "Kaydedilmemiş ayar değişiklikleri var. Kaydedilsin mi?",
                                        QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
            if not keep:
                for page in self.pages:
                    if type(page).__name__ == "TvLookPage":
                        page.reverted()     # the TV gets its saved look back
            config.save(self.cfg if keep else self._saved)
        else:
            config.save(self.cfg)
        if FROZEN and not self._applying and self.updater.ready():
            try:
                self.updater.apply(relaunch=False)      # a downloaded update is installed once the app has closed
            except OSError:
                pass
        self.tray.hide()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()
