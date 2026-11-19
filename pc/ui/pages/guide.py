"""First-run guide: step by step, from the second PSN account to the first game. Opens by itself on the
first start (cfg "onboarded"); each step has its own buttons and shows ✓ when it is done."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .. import readiness, theme
from ..game_select import GameSelect
from ..widgets import Card, Divider, icon_button
from ..tv_install import TvInstallGuide
from .ps5 import Ps5Page


def _text(html):
    label = QLabel(html)
    label.setWordWrap(True)
    label.setTextFormat(Qt.RichText)
    label.setOpenExternalLinks(True)
    return label


def _steps(items):
    """Numbered list as rich text."""
    return _text("".join(
        f"<p style='margin:6px 0'><span style='color:{theme.ACCENT_HI}; font-weight:600'>{i}.</span>&nbsp; {t}</p>"
        for i, t in enumerate(items, 1)))


def _status():
    label = QLabel()
    label.setWordWrap(True)
    label.setTextFormat(Qt.RichText)
    return label


class GuidePage(QWidget):
    title = "Başlarken"
    hint = "İlk kurulum rehberi. Adımları sırayla yap; hepsi bu uygulamanın içinden yapılır."

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cfg = win.cfg
        self._checks = []       # (step index, check function)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        side = Card()
        side.setFixedWidth(250)
        self.group = QButtonGroup(self)
        self.step_buttons = []
        side_box = QVBoxLayout()
        side_box.setSpacing(2)
        side.add_layout(side_box)

        main = Card()
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        main.add(self.stack, 1)
        main.add(Divider())
        nav = QHBoxLayout()
        self.back = QPushButton("← Geri")
        self.back.setCursor(Qt.PointingHandCursor)
        self.back.clicked.connect(lambda: self.show_step(self.stack.currentIndex() - 1))
        self.next = QPushButton("İleri →")
        self.next.setObjectName("primary")
        self.next.setCursor(Qt.PointingHandCursor)
        self.next.clicked.connect(self._next)
        nav.addWidget(self.back)
        nav.addStretch(1)
        nav.addWidget(self.next)
        main.add_layout(nav)

        for title, build, check in self._pages():
            i = self.stack.count()
            page = QWidget()
            box = QVBoxLayout(page)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(12)
            head = QLabel(title)
            head.setObjectName("guideTitle")
            box.addWidget(head)
            build(box)
            box.addStretch(1)
            # Each step scrolls on its own, so Back / Next always stay on screen.
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidget(page)
            scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
            self.stack.addWidget(scroll)
            b = QPushButton(f"{i + 1}. {title}")
            b.setObjectName("guideStep")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self.show_step(i))
            self.group.addButton(b)
            side_box.addWidget(b)
            self.step_buttons.append((b, title))
            if check:
                self._checks.append((i, check))
        side_box.addStretch(1)

        lay.addWidget(side)
        lay.addWidget(main, 1)
        self.show_step(0)
        self._timer = QTimer(self, interval=1500)
        self._timer.timeout.connect(self.refresh)

    # ---- steps ----

    def _pages(self):
        return [
            ("Hoş geldin", self._welcome, None),
            ("İkinci PSN hesabı", self._account, None),
            ("PS5'te Uzaktan Oynatma", self._remote_play, None),
            ("PS5'i bağla", self._ps5, readiness.ps5),
            ("TV uygulaması", self._tv, readiness.tv),
            ("Altyazı alanı", self._region, readiness.region),
            ("Oynarken kol", self._controller, None),
            ("Hazırsın", self._ready, None),
        ]

    def _welcome(self, box):
        box.addWidget(_text(
            "Oyun Çeviri, PS5 oyunlarındaki İngilizce altyazıları okur, Türkçeye çevirir ve TV'de oyunun "
            "üstünde gösterir. Oyunu TV'de her zamanki gibi oynarsın; bu bilgisayar PS5'in görüntüsünü "
            "Remote Play ile arka planda alır ve altyazıyı oradan okur."))
        box.addWidget(_text("<b>Gerekenler</b>"))
        box.addWidget(_steps([
            "PS5, TV ve bu bilgisayar aynı modeme bağlı olmalı (bilgisayar ve PS5 için kablo önerilir).",
            "Android TV / Google TV (TCL, Sony, Philips, Xiaomi, Hisense…), Samsung ya da LG TV.",
            "Ücretsiz ikinci bir PSN hesabı (bir sonraki adımda anlatılıyor).",
            "Oynarken bu bilgisayar açık kalmalı. Ekran kapalı olabilir; uygulama saatin yanındaki simgede "
            "çalışır.",
        ]))
        box.addWidget(_text(f"<span style='color:{theme.MUTED}'>Kurulum bir kez yapılır, yaklaşık 10 dakika "
                            f"sürer. Sonra her seferinde yalnızca <b>Başlat</b>'a basarsın.</span>"))

    def _account(self, box):
        box.addWidget(_text(
            "Remote Play'e oyunu oynadığın kendi hesabınla bağlanırsan PS5 o hesabın kolunu kapatır. Bu "
            "yüzden bilgisayar <b>ikinci bir hesapla</b> bağlanır; sen kendi hesabınla oynamaya devam edersin."))
        box.addWidget(_steps([
            "PS5'te ana ekranda sağ üstteki profil resmine bas → <b>Kullanıcı Değiştir</b> → <b>Kullanıcı "
            "Ekle</b> → <b>Başlayın</b>.",
            "<b>Hesap Oluştur</b>'u seç ve ücretsiz yeni bir PSN hesabı aç (başka bir e-posta adresiyle). "
            "Hesabı telefondan ya da bilgisayardan "
            "<a style='color:#7FB2FF' href='https://www.playstation.com'>playstation.com</a> üzerinden açıp "
            "PS5'te bununla giriş da yapabilirsin.",
            "Bu ikinci hesapla PS5'te bir kez oturum aç. Bundan sonra oyunu yine kendi hesabınla oynarsın.",
            "Yeni hesabın şifresini bir yere not et; 4. adımda bu hesapla giriş yapacaksın.",
        ]))

    def _remote_play(self, box):
        box.addWidget(_text("PS5'te iki ayar açık olmalı. Bunlar bütün hesaplar için geçerlidir."))
        box.addWidget(_steps([
            "<b>Ayarlar → Sistem → Uzaktan Oynatma → Uzaktan Oynatmayı Etkinleştir</b>: açık.",
            "<b>Ayarlar → Sistem → Güç Tasarrufu → Dinlenme Modunda Kullanılabilen Özellikler</b>: "
            "<b>İnternete Bağlı Kal</b> ve <b>PS5'in Ağ Üzerinden Açılmasını Etkinleştir</b> açık. Böylece "
            "PS5 dinlenme modundayken bu uygulama onu uyandırabilir.",
        ]))
        box.addWidget(_text(f"<span style='color:{theme.MUTED}'>Menü adları PS5'in diline göre biraz farklı "
                            f"olabilir (İngilizcesi: Remote Play, Power Saving, Stay Connected to the Internet, "
                            f"Enable Turning On PS5 from Network).</span>"))

    def _ps5(self, box):
        box.addWidget(_text("Bilgisayarı PS5'e bir kez tanıt. Giriş adımında <b>ikinci hesabı</b> kullan; kodu "
                            "alırken PS5'te de ikinci hesapla oturum açık olsun."))
        self.ps5_status = _status()
        box.addWidget(self.ps5_status)
        box.addWidget(Ps5Page(self.win, compact=True))

    def _tv(self, box):
        self.tv_status = _status()
        box.addWidget(self.tv_status)
        box.addWidget(TvInstallGuide(self.win))

    def _region(self, box):
        box.addWidget(_text(
            "Programa altyazının ekranın neresinde çıktığını göster; yalnızca orayı okur. PS5'i aç, oyunda bir "
            "konuşma altyazısı ekrandayken aşağıdaki düğmeye bas ve görüntünün üstünde fareyle altyazının "
            "olduğu yeri çerçeve içine al. İki satırlık altyazılara yer bırak."))
        self.region_status = _status()
        box.addWidget(self.region_status)
        row = QHBoxLayout()
        go = icon_button(theme.Icon.CROP, "Altyazı alanını seç", "primary")
        go.clicked.connect(self._open_region)
        row.addWidget(go)
        row.addStretch(1)
        box.addLayout(row)
        box.addWidget(_text(f"<span style='color:{theme.MUTED}'>Seçtikten sonra soldaki menüden "
                            f"<b>Başlarken</b>'e dönüp devam et. Çoğu oyunda altyazı aynı yerde çıkar; her oyun "
                            f"için yeniden seçmek gerekmez.</span>"))

    def _controller(self, box):
        box.addWidget(_text(
            "Program PS5'e bağlandığında (<b>Başlat</b>'a basınca) kolun bağlantısı bir anlığına düşebilir; bu "
            "normal. Kolu geri almak için:"))
        box.addWidget(_steps([
            "Koldaki <b>PS tuşuna bir kez bas</b>. Ekrana kullanıcı seçimi gelir.",
            "<b>Kendi (ana) hesabını</b> seç. Remote Play'in kullandığı ikinci hesabı seçme.",
            "Kol yine tepki vermezse <b>PS tuşunu birkaç saniye basılı tut</b>; kol yeniden devreye girer.",
        ]))
        box.addWidget(_text(f"<span style='color:{theme.MUTED}'>Oyunu her zamanki gibi kendi hesabınla "
                            f"oynarsın. İkinci hesap yalnızca görüntüyü almak için arka planda bağlı kalır; "
                            f"kupaların ve kayıtların kendi hesabında kalır.</span>"))

    def _ready(self, box):
        box.addWidget(_text("Her oyun öncesi yapman gereken tek şey:"))
        box.addWidget(_steps([
            "PS5'te oyunu aç.",
            "Burada oynayacağın oyunu seç (paketi varsa replikler hazır Türkçesiyle, beklemeden çıkar). "
            "Emin değilsen \"Otomatik algıla\"da bırak.",
            "Sağ üstteki <b>Başlat</b>'a bas. TV uygulaması kapalıysa kendiliğinden açılır ve TV PS5 ekranına "
            "geçer.",
        ]))
        row = QHBoxLayout()
        row.addWidget(QLabel("Oyun"))
        row.addWidget(GameSelect(self.win), 1)
        box.addLayout(row)
        box.addWidget(_text(f"<span style='color:{theme.MUTED}'>Yazı boyutu, renk ve konum: <b>TV Görünümü</b>. "
                            f"Hazır çeviriler ve yeni paketler: <b>Oyun Paketleri</b>. Bu rehber her zaman "
                            f"soldaki menüde <b>Başlarken</b>'de.</span>"))

    # ---- actions ----

    def _open_region(self):
        self.win.go("RegionPage")
        self.win.show_message("Altyazının çıktığı yeri seçince soldaki menüden Başlarken'e dönüp devam et.")

    def _next(self):
        i = self.stack.currentIndex()
        if i == self.stack.count() - 1:
            self.cfg["onboarded"] = True
            self.win.persist_config("onboarded")
            self.win.go("LivePage")
            return
        self.show_step(i + 1)

    def show_step(self, i):
        i = max(0, min(i, self.stack.count() - 1))
        self.stack.setCurrentIndex(i)
        self.step_buttons[i][0].setChecked(True)
        self.back.setEnabled(i > 0)
        self.next.setText("Rehberi bitir ✓" if i == self.stack.count() - 1 else "İleri →")
        self.refresh()

    # ---- live status ----

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
        self._timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._timer.stop()

    def refresh(self):
        done = {i: check(self.win)[0] == "ok" for i, check in self._checks}
        for i, (button, title) in enumerate(self.step_buttons):
            mark = "✓ " if done.get(i) else ""
            button.setText(f"{mark}{i + 1}. {title}")
        for label, check in ((getattr(self, "ps5_status", None), readiness.ps5),
                             (getattr(self, "tv_status", None), readiness.tv),
                             (getattr(self, "region_status", None), readiness.region)):
            if label is None:
                continue
            state, text = check(self.win)
            color = {"ok": theme.GREEN, "warn": theme.YELLOW, "missing": theme.MUTED}[state]
            label.setText(f"<span style='color:{color}'>{'✓' if state == 'ok' else '●'} {text}</span>")
