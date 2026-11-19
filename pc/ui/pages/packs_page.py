"""Game packs page: which game is played, the installed packs, and building new packs with Gemini."""
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QSystemTrayIcon,
    QVBoxLayout, QWidget,
)

from gt.packbuild import gemini
from gt.packbuild.builder import PackBuilder

from .. import theme
from ..game_select import GameName, GameSelect, origin
from ..widgets import Card, Divider, SettingRow, icon_button

STATE = {
    "idle": (theme.MUTED, "Oluşturulmadı"),
    "queued": (theme.YELLOW, "Sırada"),
    "reading": (theme.YELLOW, "Metin indiriliyor"),
    "translating": (theme.ACCENT_HI, "Çevriliyor"),
    "done": (theme.GREEN, "Hazır"),
    "quota": (theme.YELLOW, "Kota doldu"),
    "error": (theme.RED, "Hata"),
    "stopped": (theme.MUTED, "Yarıda"),
}


class _Result(QObject):
    done = Signal(str, bool, str)
    quota = Signal(float)


class PacksPage(QWidget):
    title = "Oyun Paketleri"
    hint = "Oyunların hazır Türkçe çevirileri. Paketi olan oyunda replikler beklemeden, en doğru haliyle çıkar."

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cfg = win.cfg
        self._test = _Result()
        self._test.done.connect(self._show_test)
        self._test.quota.connect(self._quota_reached)
        self._quota_told = 0.0
        self.builder = PackBuilder(self.cfg, win.engine.packs, on_quota=self._test.quota.emit,
                                   fallback=lambda en: win.engine.machine_translate(en, self.cfg))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        playing = Card("Oynadığın oyun",
                       "Oyunu seçersen paketi ilk replikten itibaren kullanılır. \"Otomatik algıla\"da birkaç "
                       "replikten sonra hangi oyun olduğu kendiliğinden anlaşılır. Aynı seçim üst çubukta da var.")
        playing.add(GameSelect(win))
        playing.add(GameName(win))
        self.playing_state = QLabel()
        self.playing_state.setObjectName("muted")
        playing.add(self.playing_state)
        lay.addWidget(playing)

        installed = Card("Yüklü paketler")
        self.installed = QLabel("Paketler yükleniyor…")
        self.installed.setTextFormat(Qt.RichText)
        self.installed.setWordWrap(True)
        installed.add(self.installed)
        self._installed_list = None
        lay.addWidget(installed)

        key = Card("Gemini anahtarı",
                   "Çeviriyi Google'ın Gemini yapay zekâsı yapar; ücretsiz anahtar yeterli. Anahtarı "
                   "<a href='https://aistudio.google.com/apikey' style='color:#7FB2FF'>aistudio.google.com/apikey</a> "
                   "adresinden Google hesabınla al (\"Create API key\"), buraya yapıştır. Anahtar sadece bu "
                   "bilgisayarda saklanır. Oyun oynarken kullanılmaz; sadece paket hazırlarken.")
        for label in key.findChildren(QLabel):
            if label.objectName() == "cardHint":
                label.setOpenExternalLinks(True)
                label.setTextFormat(Qt.RichText)
        row = QHBoxLayout()
        self.key = QLineEdit(self.cfg["gemini"]["key"])
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Anahtarı buraya yapıştır")
        show = QPushButton(theme.Icon.INFO)
        show.setToolTip("Göster / gizle")
        show.setCheckable(True)
        show.toggled.connect(lambda on: self.key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        save = icon_button(theme.Icon.CHECK, "Kaydet ve dene", "primary")
        save.clicked.connect(self._save_key)
        row.addWidget(self.key, 1)
        row.addWidget(show)
        row.addWidget(save)
        key.add_layout(row)
        self.model = QComboBox()
        for mid, label in gemini.MODELS:
            self.model.addItem(label, mid)
        self.model.setCurrentIndex(max(0, self.model.findData(self.cfg["gemini"]["model"])))
        self.model.currentIndexChanged.connect(self._set_model)
        key.add(Divider())
        key.add(SettingRow("Model", "Flash-Lite günde çok daha fazla istek yapabiliyor; paketler daha çabuk biter.",
                           self.model))
        self.key_status = QLabel("Anahtar girilmedi." if not self.cfg["gemini"]["key"] else "Anahtar kayıtlı.")
        self.key_status.setObjectName("muted")
        self.key_status.setWordWrap(True)
        key.add(self.key_status)

        games = Card("Yeni paket oluştur",
                     "Paketi olmayan popüler oyunlar. Her oyunun İngilizce diyaloğu internetten (oyun dosyası dökümleri, wiki senaryoları) indirilir, "
                     "60'ar satırlık parçalar halinde önceki satırlar ve sahne bilgisiyle çevrilir. İlerleme "
                     "kaydedilir: uygulamayı kapatsan ya da günlük ücretsiz kota dolsa da sonra kaldığı yerden "
                     "devam eder. Biten kısımlar oyunda hemen kullanılır.")
        buttons = QHBoxLayout()
        self.all_button = icon_button(theme.Icon.PLAY, "Tümünü sırayla oluştur", "primary")
        self.all_button.clicked.connect(self._start_all)
        self.stop_button = icon_button(theme.Icon.STOP, "Durdur")
        self.stop_button.clicked.connect(self._stop)
        buttons.addWidget(self.all_button)
        buttons.addWidget(self.stop_button)
        self.games_note = QLabel()
        self.games_note.setStyleSheet(f"color: {theme.RED};")
        buttons.addWidget(self.games_note)
        buttons.addStretch(1)
        games.add_layout(buttons)
        games.add(Divider())

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        self.rows = {}
        for r, (jid, job) in enumerate(self.builder.jobs.items()):
            names = QVBoxLayout()
            names.setSpacing(0)
            t = QLabel(job.src["title"])
            t.setObjectName("rowTitle")
            a = QLabel(job.src["about"])
            a.setObjectName("muted")
            names.addWidget(t)
            names.addWidget(a)
            box = QWidget()
            box.setLayout(names)
            state = QLabel()
            state.setMinimumWidth(170)
            bar = QProgressBar()
            bar.setTextVisible(False)
            bar.setFixedWidth(170)
            bar.setFixedHeight(8)
            go = icon_button(theme.Icon.PLAY, "Oluştur")
            go.clicked.connect(lambda _=False, j=jid: self._start([j]))
            grid.addWidget(box, r, 0)
            grid.addWidget(state, r, 1)
            grid.addWidget(bar, r, 2)
            grid.addWidget(go, r, 3)
            self.rows[jid] = (state, bar, go)
        games.add_layout(grid)
        lay.addWidget(games)
        lay.addWidget(key)
        lay.addStretch(1)

        self._timer = QTimer(self, interval=1000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()
        if self.cfg["gemini"]["building"] and self.cfg["gemini"]["key"]:
            QTimer.singleShot(5000, self._start_all)   # continue what was left unfinished last time

    # ---- key ----

    def _save_key(self):
        self.cfg["gemini"]["key"] = self.key.text().strip()
        self.win.persist_config(("gemini", "key"))
        if not self.cfg["gemini"]["key"]:
            self.key_status.setText("Anahtar girilmedi.")
            return
        self.key_status.setText("Deneniyor…")
        key, model = self.cfg["gemini"]["key"], self.cfg["gemini"]["model"]

        def work():
            try:
                used = model
                try:
                    tr = gemini.Gemini(key, model).test()
                except gemini.NotFree:
                    # The chosen model has no free quota (or another name): use a free Flash model instead.
                    for other in gemini.free_models(key):
                        if other == model:
                            continue
                        try:
                            tr, used = gemini.Gemini(key, other).test(), other
                            break
                        except gemini.NotFree:
                            continue
                    else:
                        raise
                self._test.done.emit(f"Çalışıyor ({used}, ücretsiz). Deneme: \"Let's get the hell out of here!\" "
                                     f"→ \"{tr}\"", True, used)
            except Exception as e:  # noqa: BLE001 - shown to the user
                self._test.done.emit(f"Olmadı: {e}", False, "")

        threading.Thread(target=work, daemon=True).start()

    def _show_test(self, text, ok, model):
        self.key_status.setText(text)
        self.key_status.setStyleSheet(f"color: {theme.GREEN if ok else theme.RED};")
        if ok and model != self.cfg["gemini"]["model"]:
            if self.model.findData(model) < 0:
                self.model.addItem(f"{model} (ücretsiz)", model)
            self.model.setCurrentIndex(self.model.findData(model))

    def _quota_reached(self, reset):
        """Tell the user once a day; the builder waits for the reset and continues by itself."""
        if time.time() - self._quota_told < 12 * 3600:
            return
        self._quota_told = time.time()
        self.win.tray.showMessage(
            "Oyun Çeviri · Gemini limiti doldu",
            "Bugünkü ücretsiz çeviri limiti bitti (bütün ücretsiz modellerde). Ücretli kullanıma geçilmedi; "
            f"limit saat {time.strftime('%H:%M', time.localtime(reset))} civarı yenilenince kaldığı yerden "
            "kendisi devam edecek.",
            QSystemTrayIcon.Warning, 15000)

    def _set_model(self):
        self.cfg["gemini"]["model"] = self.model.currentData()
        self.win.persist_config(("gemini", "model"))

    # ---- jobs ----

    def _start(self, ids):
        if not self.cfg["gemini"]["key"]:
            self.key_status.setText("Önce Gemini anahtarını yapıştırıp \"Kaydet ve dene\"ye bas.")
            self.key_status.setStyleSheet(f"color: {theme.RED};")
            self.games_note.setText("Önce sayfanın altındaki Gemini anahtarını gir.")
            return
        self.games_note.setText("")
        self.builder.start(ids)
        self.cfg["gemini"]["building"] = True
        self.win.persist_config(("gemini", "building"))
        self._refresh()

    def _start_all(self):
        self._start(list(self.builder.jobs))

    def _stop(self):
        self.builder.stop()
        self.cfg["gemini"]["building"] = False
        self.win.persist_config(("gemini", "building"))

    def _refresh_installed(self):
        lib = self.win.engine.packs
        if not lib.ready:
            return
        game = self.cfg["packs"]["game"]
        detected = lib.packs.get(lib.detected)
        if game == "auto":
            state = (f"<span style='color:{theme.GREEN}'>Algılanan oyun: {detected.title}</span>" if detected
                     else "Henüz oyun algılanmadı (Başlat'tan sonra birkaç replik bekler).")
        elif game == "off":
            state = "Paketler kapalı: her satırı çeviri modeli çevirir."
        else:
            title = lib.packs[game].title if game in lib.packs else game
            state = f"<span style='color:{theme.GREEN}'>Seçili oyun: {title}</span> (algılama beklenmez)"
        self.playing_state.setText(state)
        titles = lib.titles()
        if titles == self._installed_list:
            return
        self._installed_list = titles
        rows = "".join(
            f"<tr><td>{title}</td><td align='right'>&nbsp;&nbsp;{count:,}&nbsp;&nbsp;</td>"
            f"<td style='color:{theme.MUTED}'>{origin(source)}</td></tr>".replace(",", ".")
            for _, title, count, source in titles)
        self.installed.setText(f"{len(titles)} oyunun paketi var:"
                               f"<table cellspacing='0' cellpadding='3'>"
                               f"<tr><td><b>Oyun</b></td><td align='right'><b>Replik</b></td>"
                               f"<td><b>Nereden</b></td></tr>{rows}</table>")

    def _refresh(self):
        self._refresh_installed()
        for jid, job in self.builder.jobs.items():
            state, bar, go = self.rows[jid]
            color, label = STATE.get(job.state, (theme.MUTED, job.state))
            detail = job.message if job.state in ("reading", "translating", "error", "quota") else ""
            if job.state == "done":
                detail = f"{job.done:,} replik".replace(",", ".") if job.done else ""
            elif job.state == "stopped" and job.total:
                detail = f"{job.done:,} / {job.total:,}".replace(",", ".")
            state.setText(f"<span style='color:{color}'>●</span> {label}"
                          + (f"<br><span style='color:{theme.MUTED}; font-size:9pt'>{detail}</span>" if detail else ""))
            state.setToolTip(job.message)
            bar.setMaximum(max(1, job.total))
            bar.setValue(job.total if job.state == "done" and not job.total else job.done)
            busy = job.state in ("queued", "reading", "translating")
            go.setEnabled(not busy and job.state != "done")
            go.setText(f"{theme.Icon.PLAY}  {'Devam et' if job.state in ('stopped', 'quota', 'error') else 'Oluştur'}")
        self.stop_button.setEnabled(self.builder.running)
        self.all_button.setEnabled(not self.builder.running)
