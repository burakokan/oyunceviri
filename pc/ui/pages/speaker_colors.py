"""Filtreler -> Konuşmacı renkleri: everyone who spoke, with the colour their name gets on the TV. A colour picked here
is kept for good (the app no longer measures it): the stream washes the game's name colours out, so a name that is
pastel on the TV can come out a little off, and this puts it right once."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QColorDialog, QGridLayout, QHBoxLayout, QLineEdit, QMenu, QPushButton, QScrollArea,
                               QWidget)

from .. import theme
from ..widgets import Card, icon_button

# The TV shades to choose from (the game's colour families, saturated, and a few more), never white.
CHOICES = [("Göl yeşili", "#3FD5C4"), ("Açık mavi", "#4FC3F7"), ("Buz mavisi", "#80DEEA"), ("Koyu turkuaz", "#26A69A"),
           ("Mavi", "#64B5F6"), ("Çivit", "#7986CB"), ("Pembe", "#F48FB1"), ("Koyu pembe", "#F06292"),
           ("Lila", "#CE93D8"), ("Lavanta", "#B39DDB"), ("Mercan", "#FF8A80"), ("Sarı", "#FFD54F"),
           ("Krem", "#FFF59D"), ("Turuncu", "#FFB74D"), ("Somon", "#FF8A65"), ("Yeşil", "#9CCC65"),
           ("Açık yeşil", "#A5D6A7")]
COLUMNS = 3


def swatch(color, size=14):
    pix = QPixmap(size, size)
    pix.fill(QColor(color))
    return QIcon(pix)


class SpeakerColorsCard(Card):
    def __init__(self, win):
        super().__init__("Konuşmacı renkleri",
                         "Şimdiye kadar konuşan herkes, adının TV'deki rengiyle. Yanlış olana tıkla ve TV'de "
                         "gördüğün rengi seç: o kişi bundan sonra hep o renkte yazılır (kilit simgesi). "
                         "\"Oyundaki gibi\" kilidi kaldırır, renk yine oyundan ölçülür. Local, Tourist gibi "
                         "adlarda her satır kendi rengini alır; birini seçersen hepsi o renkte olur.")
        self.win = win
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Ad ara…")
        self.search.textChanged.connect(self.refresh)
        refresh = icon_button(theme.Icon.REFRESH, "Yenile")
        refresh.clicked.connect(self.refresh)
        top.addWidget(self.search, 1)
        top.addWidget(refresh)
        self.add_layout(top)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setMaximumHeight(320)
        self.area.setFrameShape(QScrollArea.NoFrame)
        self.add(self.area)
        self.refresh()

    def _colors(self):
        engine = getattr(self.win, "engine", None)
        return getattr(engine, "colors", None)

    def refresh(self):
        colors = self._colors()
        people = colors.people() if colors is not None else []
        want = self.search.text().strip().casefold()
        if want:
            people = [p for p in people if want in p["name"].casefold()]
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for i, p in enumerate(people):
            grid.addWidget(self._button(p), i // COLUMNS, i % COLUMNS)
        if not people:
            empty = QPushButton("Henüz konuşan yok: oyunda biri konuşunca burada görünür." if not want
                                else "Bu adla kimse yok.")
            empty.setEnabled(False)
            grid.addWidget(empty, 0, 0, 1, COLUMNS)
        grid.setRowStretch(grid.rowCount(), 1)
        self.area.setWidget(holder)

    def _button(self, p):
        color = p["color"] or theme.MUTED
        text = p["name"] + ("" if p["color"] else "  (satır satır)" if p.get("generic") else "  (renk yok)")
        button = QPushButton(f"{theme.Icon.LOCK}  {text}" if p["locked"] else text)
        font = QFont(button.font())
        font.setFamilies([theme.ICON_FONT, theme.FONT])
        font.setBold(True)
        button.setFont(font)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(f"{p['name']}: {p['color'] or 'her satır kendi rengi'}"
                          + (" (senin seçtiğin, kilitli)" if p["locked"] else " (oyundan)")
                          + f" · {p['lines']} ölçüm")
        button.setStyleSheet(f"QPushButton {{ color: {color}; background: {theme.BG}; text-align: left; "
                             f"padding: 7px 10px; border: 1px solid {theme.BORDER}; border-radius: 8px; }}"
                             f"QPushButton:hover {{ border: 1px solid {theme.ACCENT}; }}")
        button.clicked.connect(lambda _=False, p=p, b=button: self._menu(p, b))
        return button

    def _menu(self, p, button):
        menu = QMenu(self)
        for label, color in CHOICES:
            act = menu.addAction(swatch(color), label + ("  ✓" if p["locked"] and p["color"] == color else ""))
            act.triggered.connect(lambda _=False, c=color: self._lock(p, c))
        other = menu.addAction("Başka renk…")
        other.triggered.connect(lambda: self._pick(p))
        menu.addSeparator()
        auto = menu.addAction("Oyundaki gibi (kilidi kaldır)")
        auto.setEnabled(p["locked"])
        auto.triggered.connect(lambda: self._unlock(p))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _pick(self, p):
        chosen = QColorDialog.getColor(QColor(p["color"] or "#3FD5C4"), self, f"{p['name']} için renk")
        if chosen.isValid():
            self._lock(p, chosen.name().upper())

    def _lock(self, p, color):
        colors = self._colors()
        if colors is not None:
            colors.lock(p["key"], color)
        self.refresh()

    def _unlock(self, p):
        colors = self._colors()
        if colors is not None:
            colors.unlock(p["key"])
        self.refresh()
