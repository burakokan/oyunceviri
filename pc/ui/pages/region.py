"""Area page: pick the subtitle area (and tune the white-text threshold) and the extra areas - hint box, phone,
mission objective - on the live PS5 picture; every extra area has its own reading filter and its own look on the TV."""
import os
import re
import subprocess
import threading
import time

import cv2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from gt import config
from gt.capture import WindowGrabber
from gt.engine import Engine, calibrate
from gt.ocr import make_ocr, text_mask
from gt.regions import FILTERS, area_cfg
from gt.remoteplay import RemotePlaySource, needs_link, uses_builtin
from gt.winutil import find_window

from .. import theme
from ..widgets import Card, Divider, ImageView, RegionSelector, SettingRow, Toggle, draw_lines_preview, icon_button
from .tv_look import ColorButton

PREVIEW_WIDTH = 1280
# The areas that can be chosen here: subtitles (read line by line) and the extra areas (translated as one box).
AREAS = [("subtitle", "Altyazı"), ("objective", "Görev hedefi"), ("hint", "Görev / ipucu kutusu"),
         ("phone", "Telefon mesajları")]
LABELS = {"subtitle": "Altyazı alanı", "objective": "Görev hedefi", "hint": "Görev kutusu", "phone": "Telefon"}
PICK_HINTS = {
    "subtitle": "Oyunda bir altyazı ekrandayken görüntünün üstünde fareyle sürükle. İki satırlık altyazılara yer "
                "bırak, mermi sayısı gibi HUD yazılarını mümkünse dışarıda bırak. Seçim anında kaydedilir.",
    "objective": "Oyunda altyazının altında kısa görev yazısı (\"Go to the bank.\", \"Press □ to threaten the "
                 "teller\") çıkınca o satırı fareyle sürükle; uzayabileceği için biraz geniş seç. Altyazı okuyucu "
                 "bu alanı atlar: görev yazısı ayrı okunur, çevrilir ve TV'de kendi ayarlarıyla gösterilir.",
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
    hint = ("Altyazının, görev yazısının, görev kutusunun ve telefon mesajlarının çıktığı yerleri seç; program "
            "yalnızca bu alanları okur.")

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cfg = win.cfg
        self._grab = None
        self._seq = 0
        self._ocr = None
        self._last_ocr = 0.0
        self._last_find = 0.0
        self._crops = []          # the subtitle area's last pictures (for "Otomatik ayarla")
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
        buttons = QHBoxLayout()
        auto = icon_button(theme.Icon.SYNC, "Otomatik ayarla")
        auto.setToolTip("Ekranda bir altyazı varken bas: parlaklık ve renk eşiklerinin hepsini dener, en iyi okuyanı seçer")
        auto.clicked.connect(self.auto_thresholds)
        self.auto_button = auto
        defaults = icon_button(theme.Icon.REFRESH, "Varsayılan ayarlar")
        defaults.clicked.connect(self.reset_thresholds)
        look = icon_button(theme.Icon.TV, "TV'de görünümü (boyut, renk, konum, tek satır)…")
        look.clicked.connect(lambda: self.win.go("TvLookPage"))
        buttons.addWidget(auto)
        buttons.addWidget(defaults)
        buttons.addWidget(look)
        buttons.addStretch(1)
        tune.add_layout(buttons)
        lay.addWidget(tune, 2)

        self.area_card = self._build_area_card()
        self.area_card.hide()
        lay.addWidget(self.area_card, 2)
        self.look_card = self._build_look_card()
        self.look_card.hide()
        lay.addWidget(self.look_card)
        win.bridge.region_status.connect(self.on_region_status)

        self.timer = QTimer(self)
        self.timer.setInterval(66)
        self.timer.timeout.connect(self.tick)

    def _build_area_card(self):
        card = Card("2 · Bu alanın okunması",
                    "Alanda yazı çıkınca okunur, çevrilir ve TV'de tek kutuda gösterilir; yazı kaybolunca kutu da "
                    "kalkar. Tuş simgeleri (L3, R2, □ …) çeviride aynı yerde, aynı resimle durur.")
        self.area_toggle = Toggle(False)
        self.area_toggle.toggled.connect(self._set_enabled)
        card.add(SettingRow("Bu alanı çevir", "Kapalıyken bu alan hiç okunmaz.", self.area_toggle))
        card.add(Divider())
        self.filter = QComboBox()
        for value, label in FILTERS.items():
            self.filter.addItem(label, value)
        self.filter.currentIndexChanged.connect(lambda _: self._set_area("filter", self.filter.currentData()))
        card.add(SettingRow("Hangi yazılar okunsun",
                            "Alana giren tabela, afiş ya da sahne yazısı çevrilmesin diye. Koyu kutudaki beyaz yazı: "
                            "görev kutusu gibi siyah zeminde beyaz yazı. Kenarlıklı beyaz yazı: altyazı ve görev "
                            "hedefi gibi koyu kenarlı yazı. Alttaki görüntüde okunan yazılar yeşil, atlananlar "
                            "kırmızı çerçeveli.", self.filter))
        self.text_min, text_row = self._area_slider("Yazı parlaklığı",
                                                    "Harfler en az bu kadar parlak olmalı. Soluk tabelalar da "
                                                    "okunuyorsa yükselt, asıl yazı atlanıyorsa düşür.",
                                                    100, 255, "text_min")
        card.add(text_row)
        self.bg_max, self.bg_row = self._area_slider("Zemin koyuluğu",
                                                     "Kutunun zemini en fazla bu kadar açık olabilir. Kutu "
                                                     "atlanıyorsa yükselt, açık renkli tabelalar okunuyorsa düşür.",
                                                     20, 160, "bg_max")
        card.add(self.bg_row)
        card.add(Divider())
        self.skip_menus = Toggle(True)
        self.skip_menus.toggled.connect(lambda v: self._set_area("skip_menus", v))
        card.add(SettingRow("Menü yazılarını atla",
                            "Oyunun duraklatma menüsü, mağaza listeleri ve tuş çubukları (\"Game Store Help Photo "
                            "Studio\", \"SELECT EXIT\") kutuyla aynı görünse de çevrilmez: bütün kelimeleri büyük "
                            "harfle başlayan, noktalaması olmayan yazılar atlanır. Görev ipuçları cümle olduğu için "
                            "okunmaya devam eder.", self.skip_menus))
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        self.ignore = QLineEdit()
        self.ignore.setPlaceholderText("örnek: Photo Studio, Saved Outfits")
        self.ignore.setMinimumWidth(260)
        self.ignore.editingFinished.connect(self._set_ignore)
        add = icon_button(theme.Icon.ADD, "Ekrandakini ekle")
        add.setToolTip("Alanda şu an okunan yazıyı istisnalara ekler")
        add.clicked.connect(self._ignore_current)
        row.addWidget(self.ignore, 1)
        row.addWidget(add)
        card.add(SettingRow("İstisnalar", "Bu yazılardan birini içeren okuma hiç çevrilmez (virgülle ayır). "
                            "Atlanmasını istediğin şey ekrandayken \"Ekrandakini ekle\"ye bas.", box))
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
        return card

    def _build_look_card(self):
        card = Card("3 · TV'de görünüm",
                    "Her alanın kendi ayarı var; değişiklik TV'de hemen görünür. Oyun yoksa \"TV'de örnek göster\" "
                    "ile dene.")
        self.place = QComboBox()
        for value, label in (("cover", "İngilizcenin üstüne"), ("below", "İngilizcenin altına"),
                             ("above", "İngilizcenin üstünde (yukarıda)"), ("bottom", "Ekranın altında, ortada"),
                             ("top", "Ekranın üstünde, ortada")):
            self.place.addItem(label, value)
        self.place.currentIndexChanged.connect(lambda _: self._set_area("place", self.place.currentData(), True))
        card.add(SettingRow("Nerede", "Üstüne: Türkçe kutu İngilizcenin yerine geçer. Altına / yukarıda: İngilizce "
                            "görünür kalır. Ekranın altı / üstü: alanın yeri ne olursa olsun sabit yerde.", self.place))
        self.offset, self.offset_row = self._area_slider("Kenardan uzaklık", None, 0, 45, "offset", unit="%",
                                                         restyle=True)
        card.add(self.offset_row)
        self.align = QComboBox()
        self.align.addItem("Sola", "left")
        self.align.addItem("Ortaya", "center")
        self.align.currentIndexChanged.connect(lambda _: self._set_area("align", self.align.currentData(), True))
        self.align_row = SettingRow("Hizalama", "Ortaya: Türkçe, İngilizce yazının ortasına göre iki yana uzar "
                                    "(altyazının altındaki görev yazısı gibi).", self.align)
        card.add(self.align_row)
        card.add(Divider())
        self.size, size_row = self._area_slider("Yazı boyutu", "İngilizce yazının boyutuna göre. Sığmazsa "
                                                "kendiliğinden küçülür.", 50, 200, "size", unit="%", restyle=True)
        card.add(size_row)
        self.keep_lines = Toggle(True)
        self.keep_lines.toggled.connect(lambda v: self._set_area("keep_lines", v, True))
        card.add(SettingRow("Satır sayısı İngilizceyle aynı",
                            "Türkçe, İngilizce kaç satırsa o kadar satırda gösterilir (\"Paradise Taxi / "
                            "Dialing...\" iki satır kalır); sığmazsa yazı biraz küçülür. Kapalıyken kutu aşağı "
                            "doğru uzar.", self.keep_lines))
        self.fg = ColorButton(lambda v: self._set_area("fg", v, True))
        card.add(SettingRow("Yazı rengi", None, self.fg))
        self.bg = ColorButton(lambda v: self._set_area("bg", v, True))
        card.add(SettingRow("Kutu rengi", None, self.bg))
        self.opacity, opacity_row = self._area_slider("Kutunun opaklığı", "0: kutu yok, yazı gölgeli. 100: "
                                                      "İngilizceyi tamamen kapatır.", 0, 100, "opacity", unit="%",
                                                      restyle=True)
        card.add(opacity_row)
        row = QHBoxLayout()
        sample = icon_button(theme.Icon.TV, "TV'de örnek göster")
        sample.clicked.connect(lambda: self.win.regions.preview(self.area))
        row.addWidget(sample)
        row.addStretch(1)
        card.add_layout(row)
        return card

    def _area_slider(self, title, desc, lo, hi, key, unit="", restyle=False):
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(lo, hi)
        slider.setMinimumWidth(220)
        value = QLabel()
        value.setMinimumWidth(44)

        def changed(v):
            value.setText(f"{v}{unit}")
            self._set_area(key, v, restyle)

        slider.valueChanged.connect(changed)
        slider.value_label = value
        slider.unit = unit
        h.addWidget(slider)
        h.addWidget(value)
        return slider, SettingRow(title, desc, box)

    # ---- areas ----

    def _area_cfg(self, kind):
        """The area's settings in cfg (missing keys filled in from the defaults)."""
        a = self.cfg.setdefault("regions", {}).setdefault(kind, {})
        for key, value in area_cfg(self.cfg, kind).items():
            a.setdefault(key, value)
        return a

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
        self.look_card.setVisible(kind != "subtitle")
        self.win.regions.watching = {kind} if kind != "subtitle" and self.isVisible() else set()
        if kind != "subtitle":
            a = self._area_cfg(kind)
            self._syncing = True            # showing the saved values, not changing them
            self.area_toggle.setChecked(bool(a.get("enabled")))
            self.filter.setCurrentIndex(max(0, self.filter.findData(a["filter"])))
            self.place.setCurrentIndex(max(0, self.place.findData(a["place"])))
            self.align.setCurrentIndex(max(0, self.align.findData(a["align"])))
            for slider, key in ((self.text_min, "text_min"), (self.bg_max, "bg_max"), (self.offset, "offset"),
                                (self.size, "size"), (self.opacity, "opacity")):
                slider.setValue(int(a[key]))
                slider.value_label.setText(f"{int(a[key])}{slider.unit}")
            self.fg.set_value(a["fg"])
            self.skip_menus.setChecked(bool(a.get("skip_menus")))
            self.keep_lines.setChecked(bool(a.get("keep_lines", True)))
            self.ignore.setText(", ".join(a.get("ignore") or []))
            self.bg.set_value(a["bg"])
            self._syncing = False
            self._show_rows_for_settings(a)
            self.builtin_note.setVisible(not self._builtin)
            self.area_status.setText("Durum: " + ("açık" if a.get("enabled") and a.get("roi") else "kapalı"))
            self._show_last()

    def _set_enabled(self, on):
        if self._syncing:
            return
        self._area_cfg(self.area)["enabled"] = on
        self.win.persist_config(("regions", self.area, "enabled"))
        self.area_status.setText("Durum: " + ("açık" if on and self.current_roi() else "kapalı"))

    def _set_area(self, key, value, restyle=False):
        """An area setting changed: kept at once (like the area itself), the TV gets the new look right away."""
        if self._syncing or self.area == "subtitle":
            return
        a = self._area_cfg(self.area)
        a[key] = value
        self.win.persist_config(("regions", self.area, key))
        self._show_rows_for_settings(a)
        if restyle:
            self.win.regions.restyle()

    def _set_ignore(self):
        if self._syncing or self.area == "subtitle":
            return
        phrases = [p.strip() for p in self.ignore.text().split(",") if p.strip()]
        if phrases != (self._area_cfg(self.area).get("ignore") or []):
            self._set_area("ignore", phrases)

    def _ignore_current(self):
        """The text the area reads now becomes an exception (the menu that is on screen)."""
        info = self.win.regions.debug.get(self.area) or {}
        texts = [r["text"].strip() for r in info.get("rows", []) if r.get("text", "").strip()]
        if not texts:
            self.win.show_message("Alanda şu an okunan bir yazı yok.", error=True)
            return
        current = [p.strip() for p in self.ignore.text().split(",") if p.strip()]
        for t in texts:
            t = t.replace(",", " ")
            if t not in current:
                current.append(t)
        self.ignore.setText(", ".join(current))
        self._set_ignore()
        self.win.show_message(f"İstisnalara eklendi: {', '.join(texts)[:120]}")

    def _show_rows_for_settings(self, a):
        """Only the controls that matter for the chosen filter / place are shown."""
        self.bg_row.setVisible(a["filter"] == "dark_box")
        fixed = a["place"] in ("top", "bottom")
        self.offset_row.setVisible(fixed)
        self.align_row.setVisible(not fixed)

    def on_region_status(self, kind, text):
        if kind == self.area:
            self.area_status.setText(f"Durum: {text}")
            self._show_last()

    def _draw_area_rows(self, crop):
        """The area's picture with the text pieces of its last reading: green = read, red = left out by the
        filter (the reason next to it)."""
        info = self.win.regions.debug.get(self.area)
        if not info or tuple(info["size"]) != (crop.shape[1], crop.shape[0]) or time.monotonic() - info["time"] > 5:
            return crop
        out = crop.copy()
        for r in info["rows"]:
            x0, y0, x1, y1 = (int(v) for v in r["rect"])
            color = (80, 200, 80) if r["ok"] else (60, 60, 230)
            cv2.rectangle(out, (x0, y0), (x1, y1), color, 2)
            if not r["ok"] and r.get("why"):
                label = r["why"].translate(str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU"))
                cv2.putText(out, label, (x0 + 2, max(12, y0 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
                            cv2.LINE_AA)
        return out

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

    def auto_thresholds(self):
        """Tries every brightness / colour pair on the last moments of the subtitle area and keeps the best."""
        crops = self._crops[::3][-4:]
        if not crops or self.area != "subtitle":
            self.win.show_message("Önce altyazı alanını seç; ekranda bir altyazı varken bas.", error=True)
            return
        self.auto_button.setEnabled(False)
        self.auto_button.setText("  Ayarlanıyor…")
        cfg, roi = dict(self.cfg), self.current_roi()

        def work():
            try:
                if self._ocr is None:
                    self._ocr = make_ocr(cfg["ocr_engine"], accurate=False)
                result = calibrate(cfg, crops, roi, self._ocr)
            except Exception as e:  # noqa: BLE001 - shown to the user
                result = e
            QTimer.singleShot(0, self, lambda: self._auto_done(result))

        threading.Thread(target=work, daemon=True).start()

    def _auto_done(self, result):
        self.auto_button.setEnabled(True)
        self.auto_button.setText(f"{theme.Icon.SYNC}  Otomatik ayarla")
        if isinstance(result, Exception):
            self.win.show_message(f"Otomatik ayar yapılamadı: {result}", error=True)
            return
        v_min, s_max, text, score = result
        if score < 8 or not text:
            self.win.show_message("Ekranda okunacak bir altyazı bulunamadı. Oyunda bir altyazı çıkınca tekrar bas.",
                                  error=True)
            return
        self.v_slider.setValue(v_min)
        self.s_slider.setValue(s_max)
        self.win.show_message(f"Ayarlandı: parlaklık {v_min}, renk {s_max}. Okunan: {text.splitlines()[0][:80]} "
                              f"(beğendiysen üstteki çubuktan Kaydet).")

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
        self.win.regions.watching = set()
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
            self.area_preview.set_image(self._draw_area_rows(crop))
            return
        self._crops = (self._crops + [crop.copy()])[-12:]       # the last moments, for "Otomatik ayarla"
        mask = text_mask(crop, self.cfg["text_v_min"], self.cfg["text_s_max"])
        boxes = Engine.lines(self.cfg, crop, mask, roi)
        self.preview.set_image(draw_lines_preview(crop, mask, boxes))
        if time.monotonic() - self._last_ocr > 0.5:
            self._last_ocr = time.monotonic()
            if self._ocr is None:
                self._ocr = make_ocr(self.cfg["ocr_engine"], accurate=False)
            text = self._ocr.read(crop, mask, boxes=boxes)
            self.read_label.setText(f"Okunan: {text or '—'}")
