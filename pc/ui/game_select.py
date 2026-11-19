"""Which game is being played: "auto" (detected from the first few known lines), one game (its pack is used
right away, no detection), or "off". Every copy of the box shows the same choice (cfg["packs"]["game"])."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QWidget


def origin(source):
    """Where a pack came from, for the list on the Translation page."""
    if "Gemini" in source:
        return "Bizim çeviri (Gemini)"
    if "GameTranslator" in source or "kullanıcı yaması" in source:
        return "GameTranslator'dan"
    return "CouchSubs'tan"


class GameName(QWidget):
    """The game's name when it has no pack ("GTA 6"): told to the translators, so names, places and slang of
    that game come out right. Used only after "Kaydet" (or Enter); not kept after the app is closed, like the
    game choice."""

    def __init__(self, win):
        super().__init__()
        from . import theme
        from .widgets import icon_button
        self.win = win
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.edit = QLineEdit(win.cfg["packs"].get("custom_title", ""))
        self.edit.setPlaceholderText("Listede yoksa oyunun adı (örn. GTA 6)")
        self.edit.setToolTip("Çeviricilere \"bu oyun X\" diye söylenir: karakter, yer adları ve argo daha doğru "
                             "çevrilir. Kaydet'e (ya da Enter'a) basınca geçerli olur.")
        self.edit.setMaximumWidth(240)
        self.edit.textChanged.connect(self._edited)
        self.edit.returnPressed.connect(self._save)
        self.save = icon_button(theme.Icon.CHECK, "Kaydet")
        self.save.setToolTip("Oyun adını kaydet")
        self.save.clicked.connect(self._save)
        lay.addWidget(self.edit)
        lay.addWidget(self.save)
        self._edited()
        self._timer = QTimer(self, interval=1500)
        self._timer.timeout.connect(self._sync)
        self._timer.start()

    def _saved_text(self):
        return self.win.cfg["packs"].get("custom_title", "")

    def _edited(self, *_):
        self.save.setEnabled(self.edit.text().strip() != self._saved_text())

    def _save(self):
        self.win.cfg["packs"]["custom_title"] = self.edit.text().strip()
        self.win.persist_config(("packs", "custom_title"))
        self._edited()

    def _sync(self):
        """Another copy of the box (home page / packs page) saved a name: show it here too."""
        text = self._saved_text()
        if not self.edit.hasFocus() and not self.save.isEnabled() and self.edit.text().strip() != text:
            self.edit.blockSignals(True)
            self.edit.setText(text)
            self.edit.blockSignals(False)
        self._edited()


class GameSelect(QComboBox):
    def __init__(self, win, width=300):
        super().__init__()
        self.win = win
        self._items = None
        self.setMinimumWidth(width)
        self.setMaxVisibleItems(30)
        self.setToolTip("Oynadığın oyunu seçersen o oyunun hazır çevirisi ilk replikten itibaren kullanılır; "
                        "algılama beklenmez. \"Otomatik\"te birkaç replikten sonra oyun kendiliğinden bulunur.")
        self.currentIndexChanged.connect(self._chosen)
        self._timer = QTimer(self, interval=1500)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def refresh(self):
        if self.view().isVisible():         # never change the list while it is open
            return
        lib = self.win.engine.packs
        game = self.win.cfg["packs"]["game"]
        titles = lib.titles() if lib.ready else []
        items = tuple((pid, count) for pid, _, count, _ in titles)
        self.blockSignals(True)
        if items != self._items:
            self._items = items
            self.clear()
            self.addItem("Otomatik algıla", "auto")
            for pid, title, count, _ in titles:
                self.addItem(f"{title}  ({count:,} replik)".replace(",", "."), pid)
            self.addItem("Paket kullanma (hepsini model çevirsin)", "off")
        detected = lib.packs.get(lib.detected)
        self.setItemText(0, f"Otomatik · {detected.title}" if detected else "Otomatik algıla")
        self.setCurrentIndex(max(0, self.findData(game)))
        self.blockSignals(False)

    def _chosen(self):
        game = self.currentData()
        if game is None or game == self.win.cfg["packs"]["game"]:
            return
        self.win.cfg["packs"]["game"] = game
        self.win.engine.packs.reset_detection()
        self.win.persist_config(("packs", "game"))
        self.refresh()
