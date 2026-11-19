"""Reusable widgets: cards, toggles, setting rows, image views, region selector, list editors."""
import cv2
import numpy as np
from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, Signal, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

from . import theme


def icon_label(glyph, size=14, color=None):
    label = QLabel(glyph)
    font = QFont(theme.ICON_FONT)
    font.setPixelSize(size)
    label.setFont(font)
    if color:
        label.setStyleSheet(f"color: {color};")
    return label


def icon_button(glyph, text, object_name=None):
    """Push button with a Segoe Fluent icon in front of the text."""
    button = QPushButton(f"{glyph}  {text}" if text else glyph)
    if object_name:
        button.setObjectName(object_name)
    button.setCursor(Qt.PointingHandCursor)
    # The icon font only covers the glyph; Qt falls back to the text font for the rest.
    font = QFont(button.font())
    font.setFamilies([theme.ICON_FONT, theme.FONT])
    button.setFont(font)
    return button


def bgr_to_qimage(arr):
    arr = np.ascontiguousarray(arr)
    if arr.ndim == 2:
        h, w = arr.shape
        return QImage(arr.data, w, h, arr.strides[0], QImage.Format_Grayscale8).copy()
    h, w = arr.shape[:2]
    return QImage(arr.data, w, h, arr.strides[0], QImage.Format_BGR888).copy()


class WheelGuard(QObject):
    """The mouse wheel only ever scrolls the page: it never changes a drop-down, number box or slider the pointer
    happens to be over, not even one clicked before (that silently changed settings and the selected game).
    Settings are changed by clicking / dragging / typing. An open drop-down list still scrolls with the wheel."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and isinstance(obj, (QComboBox, QAbstractSpinBox, QSlider)):
            w = obj.parentWidget()
            while w is not None and not isinstance(w, QAbstractScrollArea):
                w = w.parentWidget()
            if w is not None:
                QApplication.sendEvent(w.viewport(), event)
            return True
        return False


class Card(QFrame):
    def __init__(self, title=None, hint=None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 18, 20, 18)
        self.body.setSpacing(12)
        if title:
            t = QLabel(title)
            t.setObjectName("cardTitle")
            self.body.addWidget(t)
        if hint:
            h = QLabel(hint)
            h.setObjectName("cardHint")
            h.setWordWrap(True)
            self.body.addWidget(h)
        self.hint_label = h if hint else None

    def add(self, widget, stretch=0):
        self.body.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout):
        self.body.addLayout(layout)
        return layout


class Pill(QLabel):
    """Small rounded status chip: colored dot + text."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setObjectName("pill")
        self.setTextFormat(Qt.RichText)
        self.set_state(theme.MUTED, text)

    def set_state(self, color, text):
        self.setText(f'<span style="color:{color}; font-size:11pt;">●</span>&nbsp; {text}')


class Toggle(QAbstractButton):
    """iOS-style switch."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(46, 26)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _get_knob(self):
        return self._pos

    def _set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = QColor(theme.ACCENT) if self.isChecked() else QColor(theme.BORDER)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + self._pos * (r.width() - d - 6)
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


class SettingRow(QWidget):
    """Title + description on the left, a control on the right."""

    def __init__(self, title, description, control, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(16)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("rowTitle")
        t.setWordWrap(True)
        texts.addWidget(t)
        if description:
            d = QLabel(description)
            d.setObjectName("muted")
            d.setWordWrap(True)
            texts.addWidget(d)
        row.addLayout(texts, 1)
        row.addWidget(control, 0, Qt.AlignVCenter | Qt.AlignRight)


class Divider(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(1)
        self.setStyleSheet(f"background: {theme.BORDER};")


class StatTile(QFrame):
    def __init__(self, label, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(2)
        self.value = QLabel("—")
        self.value.setObjectName("statValue")
        self.label = QLabel(label)
        self.label.setObjectName("statLabel")
        lay.addWidget(self.value)
        lay.addWidget(self.label)

    def set(self, text, color=None):
        self.value.setText(text)
        self.value.setStyleSheet(f"color: {color};" if color else "")


class ImageView(QLabel):
    """Shows a numpy image scaled to fit, keeping the aspect ratio."""

    def __init__(self, placeholder="", min_height=80, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(min_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(f"background: {theme.BG}; border: 1px solid {theme.BORDER}; border-radius: 8px;"
                           f"color: {theme.MUTED};")
        self._image = None
        self.setText(placeholder)

    def set_image(self, arr_or_qimage):
        self._image = arr_or_qimage if isinstance(arr_or_qimage, QImage) else bgr_to_qimage(arr_or_qimage)
        self._rescale()

    def clear_image(self, text=""):
        self._image = None
        self.setPixmap(QPixmap())
        self.setText(text)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()

    def _rescale(self):
        if self._image is None:
            return
        size = self.size() - QSize(4, 4)
        self.setPixmap(QPixmap.fromImage(self._image).scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class RegionSelector(QWidget):
    """Live picture of the game window; drag with the mouse to select the subtitle area."""

    roi_selected = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)
        self._image = None
        self._roi = None
        self._drag_start = None
        self._drag_now = None
        self.placeholder = "chiaki-ng penceresi bulunamadı"
        self.label = "Altyazı alanı"
        self._others = []           # the other chosen areas [(label, roi)], drawn dashed

    def set_frame(self, arr):
        self._image = bgr_to_qimage(arr)
        self.update()

    def clear_frame(self, text):
        self._image = None
        self.placeholder = text
        self.update()

    def set_roi(self, roi, label=None):
        self._roi = roi
        if label:
            self.label = label
        self.update()

    def set_others(self, others):
        self._others = [(label, roi) for label, roi in others if roi]
        self.update()

    def _target(self):
        if self._image is None:
            return QRectF()
        iw, ih = self._image.width(), self._image.height()
        scale = min(self.width() / iw, self.height() / ih)
        w, h = iw * scale, ih * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _to_frac(self, pt):
        t = self._target()
        return (min(max((pt.x() - t.x()) / t.width(), 0.0), 1.0),
                min(max((pt.y() - t.y()) / t.height(), 0.0), 1.0))

    def mousePressEvent(self, e):
        if self._image is not None and e.button() == Qt.LeftButton:
            self._drag_start = self._to_frac(e.position())
            self._drag_now = self._drag_start

    def mouseMoveEvent(self, e):
        if self._drag_start:
            self._drag_now = self._to_frac(e.position())
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag_start and e.button() == Qt.LeftButton:
            (x0, y0), (x1, y1) = self._drag_start, self._to_frac(e.position())
            self._drag_start = self._drag_now = None
            x, y, w, h = min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)
            if w > 0.02 and h > 0.02:
                self._roi = [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]
                self.roi_selected.emit(self._roi)
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(theme.BG))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        if self._image is None:
            p.setPen(QColor(theme.MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, self.placeholder)
            return
        t = self._target()
        p.drawImage(t, self._image)
        for label, other in self._others:
            r = QRectF(t.x() + other[0] * t.width(), t.y() + other[1] * t.height(),
                       other[2] * t.width(), other[3] * t.height())
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(theme.MUTED), 1, Qt.DashLine))
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QColor(theme.MUTED))
            p.drawText(QPointF(r.left() + 6, r.top() - 6), label)
        rect = None
        if self._drag_start and self._drag_now:
            (x0, y0), (x1, y1) = self._drag_start, self._drag_now
            rect = (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        elif self._roi:
            rect = self._roi
        if rect:
            r = QRectF(t.x() + rect[0] * t.width(), t.y() + rect[1] * t.height(),
                       rect[2] * t.width(), rect[3] * t.height())
            shade = QColor(0, 0, 0, 140)
            p.setPen(Qt.NoPen)
            p.setBrush(shade)
            p.drawRect(QRectF(t.left(), t.top(), t.width(), r.top() - t.top()))
            p.drawRect(QRectF(t.left(), r.bottom(), t.width(), t.bottom() - r.bottom()))
            p.drawRect(QRectF(t.left(), r.top(), r.left() - t.left(), r.height()))
            p.drawRect(QRectF(r.right(), r.top(), t.right() - r.right(), r.height()))
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QColor("white"))
            p.drawText(QPointF(r.left() + 6, r.top() - 6), self.label)


class ListEditor(QWidget):
    """Editable list of strings."""

    changed = Signal(list)

    def __init__(self, items, placeholder, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.list = QListWidget()
        self.list.setMaximumHeight(130)
        self.list.addItems(items)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText(placeholder)
        self.input.returnPressed.connect(self._add)
        add = icon_button(theme.Icon.ADD, "Ekle")
        add.clicked.connect(self._add)
        remove = icon_button(theme.Icon.DELETE, "Sil")
        remove.clicked.connect(self._remove)
        row.addWidget(self.input, 1)
        row.addWidget(add)
        row.addWidget(remove)
        lay.addLayout(row)

    def items(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def _add(self):
        text = self.input.text()
        if text.strip() and text not in self.items():
            self.list.addItem(text)
            self.input.clear()
            self.changed.emit(self.items())

    def _remove(self):
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self.changed.emit(self.items())


class PairListEditor(QWidget):
    """Editable list of (wrong -> right) pairs."""

    changed = Signal(list)

    def __init__(self, pairs, parent=None):
        super().__init__(parent)
        self._pairs = [list(p) for p in pairs]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.list = QListWidget()
        self.list.setMaximumHeight(150)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        self.wrong = QLineEdit()
        self.wrong.setPlaceholderText("Yanlış çeviri (örn. İyi atıştı)")
        self.right = QLineEdit()
        self.right.setPlaceholderText("Doğrusu (örn. İyi atış)")
        self.right.returnPressed.connect(self._add)
        add = icon_button(theme.Icon.ADD, "Ekle")
        add.clicked.connect(self._add)
        remove = icon_button(theme.Icon.DELETE, "Sil")
        remove.clicked.connect(self._remove)
        row.addWidget(self.wrong, 1)
        row.addWidget(QLabel("→"))
        row.addWidget(self.right, 1)
        row.addWidget(add)
        row.addWidget(remove)
        lay.addLayout(row)
        self._refresh()

    def _refresh(self):
        self.list.clear()
        for wrong, right in self._pairs:
            self.list.addItem(f"{wrong}   →   {right}")

    def _add(self):
        if self.wrong.text().strip():
            self._pairs.append([self.wrong.text(), self.right.text()])
            self.wrong.clear()
            self.right.clear()
            self._refresh()
            self.changed.emit(self._pairs)

    def _remove(self):
        rows = sorted((self.list.row(i) for i in self.list.selectedItems()), reverse=True)
        for r in rows:
            self._pairs.pop(r)
        self._refresh()
        self.changed.emit(self._pairs)


def draw_lines_preview(crop, mask, lines):
    """Original strip on top, what OCR sees (black on white, green line boxes) below."""
    seen = cv2.cvtColor(255 - mask, cv2.COLOR_GRAY2BGR)
    for y0, y1, x0, x1 in lines:
        cv2.rectangle(seen, (x0, y0), (x1 - 1, y1 - 1), (80, 200, 120), 2)
    gap = np.full((6, crop.shape[1], 3), 14, np.uint8)
    return np.vstack([crop, gap, seen])
