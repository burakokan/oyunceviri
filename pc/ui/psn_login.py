"""Sony sign-in for linking the PS5. Two ways, in one window:
1. inside the app: when Sony sends the page to the Remote Play redirect address, the app takes the code itself;
2. in the PC's own browser (when Sony shows "an error occurred" inside the app, or the web view is missing):
   Sony ends on a blank / error-looking page; the user copies its address (the way chiaki-ng does it). The app
   sees the copied link on the clipboard by itself; it can also be pasted into the box."""
from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

from gt import ps5link

from . import theme
from .widgets import icon_button


class _Catcher(QObject):
    """Sees every request of the page (on Qt's network thread) and stops the one to the redirect page."""
    caught = Signal(str)

    def __init__(self):
        super().__init__()
        from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor

        catcher = self

        class Interceptor(QWebEngineUrlRequestInterceptor):
            def interceptRequest(self, info):
                url = info.requestUrl().toString()
                if url.startswith(ps5link.REDIRECT):
                    info.block(True)
                    catcher.caught.emit(url)

        self.interceptor = Interceptor()


def _look_like_chrome(profile):
    """Sony's sign-in can refuse a browser that calls itself "QtWebEngine": send what desktop Chrome sends."""
    profile.setHttpUserAgent(" ".join(p for p in profile.httpUserAgent().split() if not p.startswith("QtWebEngine/")))
    try:
        hints = profile.clientHints()
        version = hints.fullVersion()
        hints.setFullVersionList({"Chromium": version, "Google Chrome": version, "Not=A?Brand": "24.0.0.0"})
    except (AttributeError, RuntimeError):
        pass


class PsnLogin(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PSN girişi · ikinci hesap")
        self.resize(600, min(900, QGuiApplication.primaryScreen().availableGeometry().height() - 60))
        self.code = None
        self.profile = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        hint = QLabel("PS5'te Remote Play için kullanacağın <b>ikinci</b> PSN hesabıyla giriş yap. Giriş bitince bu "
                      "pencere kendiliğinden kapanır.")
        hint.setWordWrap(True)
        hint.setContentsMargins(14, 10, 14, 10)
        lay.addWidget(hint)
        try:
            self._web_view(lay)
        except Exception as e:  # noqa: BLE001 - no web view on this PC: the browser way still works
            self.view = None
            missing = QLabel(f"Giriş sayfası bu pencerede açılamadı ({e}). Aşağıdaki <b>Tarayıcıda aç</b> ile devam et.")
            missing.setWordWrap(True)
            missing.setContentsMargins(14, 10, 14, 10)
            lay.addWidget(missing, 1)
        lay.addWidget(self._browser_way())
        QGuiApplication.clipboard().dataChanged.connect(self._clipboard)

    # ---- 1. inside the app ----

    def _web_view(self, lay):
        from PySide6.QtWebEngineCore import QWebEngineProfile
        from PySide6.QtWebEngineWidgets import QWebEngineView

        # Qt 6's default profile keeps nothing on disk (no saved cookies or password).
        self.profile = QWebEngineProfile.defaultProfile()
        _look_like_chrome(self.profile)
        self.catcher = _Catcher()
        self.catcher.caught.connect(self._caught)
        self.profile.setUrlRequestInterceptor(self.catcher.interceptor)
        self.view = QWebEngineView(self)
        self.view.urlChanged.connect(lambda url: self._caught(url.toString()))
        lay.addWidget(self.view, 1)
        self.view.load(QUrl(ps5link.LOGIN_URL))

    # ---- 2. the PC's browser ----

    def _browser_way(self):
        box = QFrame()
        box.setObjectName("card")
        box.setStyleSheet(f"#card {{ background: {theme.CARD}; border-top: 1px solid {theme.BORDER}; }}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        row = QHBoxLayout()
        title = QLabel("<b>Burada \"Bir hata oluştu\" mu çıktı?</b> Tarayıcıyla giriş yap:")
        title.setWordWrap(True)
        row.addWidget(title, 1)
        open_button = icon_button(theme.Icon.OPEN, "Tarayıcıda aç", "primary")
        open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(ps5link.LOGIN_URL)))
        row.addWidget(open_button)
        lay.addLayout(row)
        steps = QLabel(
            f"<span style='color:{theme.MUTED}'>1. Açılan sayfada ikinci PSN hesabınla giriş yap.<br>"
            "2. Giriş bitince boş ya da hata gibi görünen bir sayfa açılır (adresi <i>remoteplay.dl.playstation.net"
            "</i> ile başlar). Bu normal.<br>"
            "3. Adres çubuğuna tıkla ve linki kopyala (Ctrl+C). Program kopyaladığın linki kendisi alır; almazsa "
            "aşağıya yapıştır.</span>")
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.RichText)
        lay.addWidget(steps)
        paste_row = QHBoxLayout()
        self.paste = QLineEdit()
        self.paste.setPlaceholderText("https://remoteplay.dl.playstation.net/remoteplay/redirect?code=…")
        self.paste.returnPressed.connect(self._pasted)
        paste_row.addWidget(self.paste, 1)
        go = icon_button(theme.Icon.CHECK, "Devam")
        go.clicked.connect(self._pasted)
        paste_row.addWidget(go)
        lay.addLayout(paste_row)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setTextFormat(Qt.RichText)
        lay.addWidget(self.note)
        return box

    def _clipboard(self):
        text = QGuiApplication.clipboard().text()
        if "remoteplay/redirect" in text:
            self.paste.setText(text.strip())
            self._pasted()

    def _pasted(self):
        text = self.paste.text()
        if self._caught(text):
            return
        error = ps5link.error_from_redirect(text)
        if error:
            message = f"Sony girişi reddetti: {error}. Tarayıcıda aç'a basıp tekrar giriş yap."
        elif text.strip():
            message = ("Bu link doğru değil. Girişten sonra açılan sayfanın adresini (remoteplay.dl.playstation.net/"
                       "… ile başlar) baştan sona kopyala.")
        else:
            message = "Önce linki yapıştır."
        self.note.setText(f"<span style='color:{theme.RED}'>{message}</span>")

    # ---- result ----

    def _caught(self, url):
        code = ps5link.code_from_redirect(url)
        if code and not self.code:
            self.code = code
            self.accept()
        return bool(code)

    def done(self, result):
        try:
            QGuiApplication.clipboard().dataChanged.disconnect(self._clipboard)
        except (RuntimeError, TypeError):
            pass
        if self.profile is not None:
            self.profile.setUrlRequestInterceptor(None)
        if self.view is not None:
            self.view.stop()
        super().done(result)
