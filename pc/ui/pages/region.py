"""Area page: pick the subtitle area (and tune the white-text threshold), the hint box area and the phone area
on the live PS5 picture."""
import os
import re
import subprocess
import time

import cv2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout,
                               QWidget)

from gt import config
from gt.capture import WindowGrabber
from gt.engine import Engine
from gt.ocr import make_ocr, text_mask
from gt.remoteplay import RemotePlaySource, needs_link, uses_builtin
from gt.winutil import find_window

from .. import theme
from ..widgets import Card, ImageView, RegionSelector, SettingRow, Toggle, draw_lines_preview, icon_button

PREVIEW_WIDTH = 1280
# The areas that can be chosen here: subtitles (read line by line) and the extra areas (translated as one box).
AREAS = [("subtitle", "Altyazı"), ("hint", "Görev / ipucu kutusu"), ("phone", "Telefon mesajları")]
LABELS = {"subtitle": "Altyazı alanı", "hint": "Görev kutusu", "phone": "Telefon"}
PICK_HINTS = {
    "subtitle": "Oyunda bir altyazı ekrandayken görüntünün üstünde fareyle sürükle. İki satırlık altyazılara yer "
                "bırak, mermi sayısı gibi HUD yazılarını mümkünse dışarıda bırak. Seçim anında kaydedilir.",
    "hint": "Oyunda bir görev / ipucu kutusu (\"Press L3 to swim faster…\") ekrandayken kutunun çıktığı yeri "
            "fareyle sürükle; kutu uzayabileceği için biraz geniş seç. Kutudaki bütün satırlar tek cümle gibi "
            "çevrilir ve TV'de tek kutuda, tuş simgeleriyle birlikte gösterilir.",
    "phone": "Oyundaki telefona mesaj geldiğinde telefon ekranının (mesajların) olduğu yeri fareyle sürükle. Her "
             "mesaj ayrı çevrilir ve TV'de tek kutuda alt alta gösterilir.",
}
_TOKEN_EN = re.compile(r"⟦\d+\|([^⟧]*)⟧")
_TOKEN_TR = re.compile(r"⟦\d+⟧")


class RegionPage(QWidget):
    title = "Altyazı Alanı"
    hint = "Altyazının, görev kutusunun ve telefon mesajlarının çıktığı yerleri seç; program yalnızca bu alanları okur."

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cfg = win.cfg
        self._grab = None
        self._seq = 0
        self._ocr = None
        self._last_ocr = 0.0
        self._last_find = 0.0
        self._syncing = False
        self._builtin = self._unlinked = False
        self.area = "subtitle"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        self.pick = pick = Card("1 · Alanı seç", PICK_HINTS["subtitle"])
        seg = QHBoxLayout()
        seg.setSpacing(8)
        seg.addWidget(QLabel("Hangi alan:"))
        self.area_group = QButtonGroup(self)
        self.area_buttons = {}
        for kind, text in AREAS:
            b = QPushButton(text)
            b.setObjectName("segButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=kind: self.select_area(k))
            self.area_group.addButton(b)
            self.area_buttons[kind] = b
            seg.addWidget(b)
        seg.addStretch(1)
        self.area_buttons["subtitle"].setChecked(True)
        pick.add_layout(seg)
        top = QHBoxLayout()
        self.window_label = QLabel()
        self.window_label.setObjectName("muted")
        self.open_chiaki_button = open_chiaki = icon_button(theme.Icon.OPEN, "chiaki-ng'yi aç")
        open_chiaki.clicked.connect(self.open_chiaki)
        reset = icon_button(theme.Icon.DELETE, "Seçimi temizle")
        reset.clicked.connect(self.clear_roi)
        top.addWidget(self.window_label, 1)
        top.addWidget(open_chiaki)
        top.addWidget(reset)
        pick.add_layout(top)
        self.selector = pick.add(RegionSelector(), 1)
        self.selector.set_roi(self.cfg.get("roi"))
        self.selector.roi_selected.connect(self.on_roi)
        lay.addWidget(pick, 3)

        self.tune = tune = Card("2 · Okumayı ayarla",
                                "Alttaki görüntüde harfler siyah, geri kalan her yer beyaz olmalı ve her satır yeşil "
                                "kutuya alınmalı. Değilse kaydırıcılarla ayarla.")
        self.preview = tune.add(ImageView("Önce bir alan seç", min_height=170))
        self.read_label = QLabel("Okunan: —")
        self.read_label.setWordWrap(True)
        self.read_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        tune.add(self.read_label)
        self.v_slider, v_row = self._slider(
            "Parlaklık eşiği", "Altyazı harfleri bu değerden parlak olmalı. Arka plan da okunuyorsa yükselt, "
            "harfler kopuk görünüyorsa düşür.", 100, 255, "text_v_min")
        self.s_slider, s_row = self._slider(
            "Renk toleransı", "Beyaz yazı için düşük tut. Renkli (sarı vb.) altyazılı oyunlarda yükselt.",
            0, 255, "text_s_max")
        tune.add(v_row)
        tune.add(s_row)
        defaults = icon_button(theme.Icon.REFRESH, "Varsayılan ayarlar")
        defaults.clicked.connect(self.reset_thresholds)
        tune.add(defaults).setMaximumWidth(220)
        lay.addWidget(tune, 2)

        self.area_card = self._build_area_card()
        self.area_card.hide()
        lay.addWidget(self.area_card, 2)
        win.bridge.region_status.connect(self.on_region_status)

        self.timer = QTimer(self)
        self.timer.setInterval(66)
        self.timer.timeout.connect(self.tick)

    def _build_area_card(self):
        card = Card("2 · Bu alanın çevirisi",
                    "Alanda yazı çıkınca okunur, çevrilir ve TV'de tek kutuda gösterilir; yazı kaybolunca kutu da "
                    "kalkar. Tuş simgeleri (L3, R2, ✕ …) çeviride aynı yerde, aynı resimle durur.")
        self.area_toggle = Toggle(False)
        self.area_toggle.toggled.connect(self._set_enabled)
        card.add(SettingRow("Bu alanı çevir", "Kapalıyken bu alan hiç okunmaz.", self.area_toggle))
        self.place = QComboBox()
        self.place.addItem("İngilizcenin üstüne", "cover")
        self.place.addItem("İngilizcenin altına", "below")
        self.place.currentIndexChanged.connect(self._set_place)
        card.add(SettingRow("TV'de nerede",
                            "Üstüne: Türkçe kutu İngilizcenin yerine geçer (gerekirse aşağı doğru uzar). Altına: "
                            "İngilizce kutu görünür kalır, Türkçesi hemen altında çıkar.", self.place))
        self.builtin_note = QLabel("Bu alanlar yalnızca dahili Remote Play ile çalışır (PS5 Bağlantısı sayfası).")
        self.builtin_note.setObjectName("muted")
        self.builtin_note.setWordWrap(True)
        card.add(self.builtin_note)
        self.area_preview = card.add(ImageView("Önce alanı seç", min_height=150))
        self.area_status = QLabel("Durum: —")
        self.area_status.setObjectName("muted")
        card.add(self.area_status)
        self.area_read = QLabel("Okunan: —")
        self.area_read.setWordWrap(True)
        self.area_read.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.add(self.area_read)
        sample = icon_button(theme.Icon.TV, "TV'de örnek göster")
        sample.clicked.connect(lambda: self.win.regions.preview(self.area))
        card.add(sample).setMaximumWidth(240)
        return card

    # ---- areas ----

    def _area_cfg(self, kind):
        return self.cfg.setdefault("regions", {}).setdefault(kind, {"enabled": False, "roi": None, "place": "cover"})

    def current_roi(self, kind=None):
        kind = kind or self.area
        if kind == "subtitle":
            return self.cfg.get(self.roi_key)
        return self._area_cfg(kind).get("roi")

    def select_area(self, kind):
        self.area = kind
        self.area_buttons[kind].setChecked(True)
        if self.pick.hint_label is not None:
            self.pick.hint_label.setText(PICK_HINTS[kind])
        self.selector.set_roi(self.current_roi(), LABELS[kind])
        self.selector.set_others([(LABELS[k], self.current_roi(k)) for k, _ in AREAS if k != kind])
        self.tune.setVisible(kind == "subtitle")
        self.area_card.setVisible(kind != "subtitle")
        if kind != "subtitle":
            a = self._area_cfg(kind)
            self._syncing = True            # showing the saved values, not changing them
            self.area_toggle.setChecked(bool(a.get("enabled")))
            self.place.setCurrentIndex(max(0, self.place.findData(a.get("place", "cover"))))
            self._syncing = False
            self.builtin_note.setVisible(not self._builtin)
            self.area_status.setText("Durum: " + ("açık" if a.get("enabled") and a.get("roi") else "kapalı"))
            self._show_last()

    def _set_enabled(self, on):
        if self._syncing:
            return
        self._area_cfg(self.area)["enabled"] = on
        self.win.persist_config(("regions", self.area, "enabled"))
        self.area_status.setText("Durum: " + ("açık" if on and self.current_roi() else "kapalı"))

    def _set_place(self, _):
        if self._syncing:
            return
        self._area_cfg(self.area)["place"] = self.place.currentData()
        self.win.persist_config(("regions", self.area, "place"))
        self.win.regions.restyle()

    def on_region_status(self, kind, text):
        if kind == self.area:
            self.area_status.setText(f"Durum: {text}")
            self._show_last()

    def _show_last(self):
        last = self.win.regions.last.get(self.area)
        if not last:
            self.area_read.setText("Okunan: —")
            return
        en = _TOKEN_EN.sub(lambda m: f"[{m.group(1)}]", last["en"]).replace("\n", " / ")
        tr = _TOKEN_TR.sub("[tuş]", last["tr"]).replace("\n", " / ")
        self.area_read.setText(f"Okunan: {en}\nÇeviri ({last['via']}): {tr}")

    # ---- controls ----

    def reverted(self):
        """Settings went back to the saved ones: show the saved thresholds."""
        for slider, value, key in getattr(self, "_sliders", []):
            slider.blockSignals(True)
            slider.setValue(self.cfg[key])
            slider.blockSignals(False)
            value.setText(str(self.cfg[key]))
        self.select_area(self.area)

    def _slider(self, title, desc, lo, hi, key):
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(self.cfg[key])
        slider.setMinimumWidth(260)
        value = QLabel(str(self.cfg[key]))
        value.setMinimumWidth(32)

        def changed(v):
            value.setText(str(v))
            self.cfg[key] = v
            self.win.save_config()

        slider.valueChanged.connect(changed)
        self._sliders = getattr(self, "_sliders", []) + [(slider, value, key)]
        h.addWidget(slider)
        h.addWidget(value)
        return slider, SettingRow(title, desc, box)

    def reset_thresholds(self):
        self.v_slider.setValue(config.DEFAULTS["text_v_min"])
        self.s_slider.setValue(config.DEFAULTS["text_s_max"])

    @property
    def roi_key(self):
        """The built-in Remote Play picture has no window frame around it, so it has its own area."""
        return "roi_builtin" if self._builtin else "roi"

    def on_roi(self, roi):
        if self.area == "subtitle":
            self.cfg[self.roi_key] = roi
            self.win.persist_config(self.roi_key)
        else:
            a = self._area_cfg(self.area)
            a["roi"] = roi
            a["enabled"] = True             # chosen: meant to be used
            self.win.persist_config(("regions", self.area, "roi"), ("regions", self.area, "enabled"))
            self.select_area(self.area)
        self.win.refresh_banner()

    def clear_roi(self):
        if self.area == "subtitle":
            self.cfg[self.roi_key] = None
            self.preview.clear_image("Önce bir alan seç")
            self.win.persist_config(self.roi_key)
        else:
            self._area_cfg(self.area)["roi"] = None
            self.area_preview.clear_image("Önce alanı seç")
            self.win.persist_config(("regions", self.area, "roi"))
        self.selector.set_roi(None)
        self.win.refresh_banner()

    def open_chiaki(self):
        path = self.cfg["chiaki_path"]
        if os.path.exists(path):
            subprocess.Popen([path], cwd=os.path.dirname(path))
        else:
            self.win.show_message("chiaki-ng bulunamadı. PS5 Bağlantısı sayfasında (Gelişmiş) yerini seç.", error=True)

    # ---- live picture ----

    def showEvent(self, e):
        super().showEvent(e)
        self._builtin = uses_builtin(self.cfg)
        self._unlinked = not self._builtin and needs_link(self.cfg)
        self.open_chiaki_button.setVisible(not self._builtin and not self._unlinked)
        self.select_area(self.area)
        self.timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()
        self._close_grab()

    def _close_grab(self):
        if self._grab:
            self._grab.stop()
            self._grab = None

    def tick(self):
        if self._builtin:
            if self._grab is None:
                self._grab = RemotePlaySource(self.win.rp)
                self._seq = 0
            rp = self.win.rp
            self.window_label.setText(f"Dahili Remote Play: {rp.text or 'başlatılıyor…'}  (chiaki-ng kapalı olmalı)")
            if not rp.seq:
                self.selector.clear_frame("PS5 görüntüsü bekleniyor…")
        elif self._unlinked:
            self.window_label.setText("PS5 henüz bağlanmadı. Önce PS5 Bağlantısı sayfasından PS5'i bağla.")
            self.selector.clear_frame("PS5 bağlanınca görüntü burada çıkar")
            return
        elif self._grab is None or self._grab.closed:
            self._close_grab()
            now = time.monotonic()
            if now - self._last_find < 1.0:
                return
            self._last_find = now
            hwnd, title = find_window(self.cfg["window_process"])
            if not hwnd:
                self.window_label.setText("chiaki-ng penceresi bulunamadı. Aç, PS5'e bağlan ve pencereyi küçültme.")
                self.selector.clear_frame("chiaki-ng penceresi bekleniyor…")
                return
            self.window_label.setText(f"Pencere: {title}")
            self._grab = WindowGrabber(hwnd)
            self._seq = 0
        self._seq, item = self._grab.next(self._seq, timeout=0)
        if item is None:
            return
        frame = item[1]
        h, w = frame.shape[:2]
        scale = min(1.0, PREVIEW_WIDTH / w)
        self.selector.set_frame(cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                                if scale < 1 else frame)
        roi = self.current_roi()
        if not roi:
            return
        x, y, rw, rh = roi
        crop = frame[int(y * h):int((y + rh) * h), int(x * w):int((x + rw) * w)]
        if crop.size == 0:
            return
        if self.area != "subtitle":
            self.area_preview.set_image(crop)
            return
        mask = text_mask(crop, self.cfg["text_v_min"], self.cfg["text_s_max"])
        boxes = Engine.lines(self.cfg, crop, mask, roi)
        self.preview.set_image(draw_lines_preview(crop, mask, boxes))
        if time.monotonic() - self._last_ocr > 0.5:
            self._last_ocr = time.monotonic()
            if self._ocr is None:
                self._ocr = make_ocr(self.cfg["ocr_engine"], accurate=False)
            text = self._ocr.read(crop, mask, boxes=boxes)
            self.read_label.setText(f"Okunan: {text or '—'}")
