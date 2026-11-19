"""TV look page: edit the TV subtitle style from the PC; every change shows up on the TV immediately."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from .. import theme
from ..widgets import Card, Divider, SettingRow, Toggle, icon_button

FONTS = [("sans", "Standart"), ("condensed", "Dar"), ("medium", "Orta kalın"), ("light", "İnce"),
         ("serif", "Tırnaklı"), ("mono", "Eş aralıklı")]

# How new lines come: "single" = one line, a new translation takes the old one's place; "stack" = the old one moves
# up a row (dimmed) and stays until it could be read. Stored in the style as maxLines / prevHoldMs / stackPrevious.
LAYOUTS = [("stack", "Önceki çeviri yukarı kaysın (kalabalık sahnede alt alta)"),
           ("single", "Tek satır: yeni çeviri eskisinin yerine geçsin")]
LAYOUT_STYLE = {"single": {"maxLines": 1, "prevHoldMs": 0, "stackPrevious": False},
                "stack": {"maxLines": 4, "prevHoldMs": 2500, "stackPrevious": False}}

# (section, [(key, title, kind, options...)])
SCHEMA = [
    ("Yazı", [
        ("textSize", "Yazı boyutu", "int", 16, 72, 2, ""),
        ("font", "Yazı tipi", "choice", FONTS),
        ("bold", "Kalın", "bool"),
        ("textColor", "Yazı rengi", "color"),
        ("uppercase", "BÜYÜK HARF", "bool"),
        ("lineSpacing", "Satır aralığı", "int", 80, 200, 5, "%"),
        ("letterSpacing", "Harf aralığı", "int", -5, 30, 1, ""),
        ("maxWidth", "En fazla genişlik", "int", 30, 100, 5, "%"),
        ("autoShrink", "Uzun satırları küçült", "bool"),
        ("prevSmaller", "Önceki satır küçük olsun", "bool"),
    ]),
    ("Konuşmacı adı", [
        ("speakerShow", "Konuşmacı adını göster", "bool"),
        ("speakerColors", "Her konuşmacı kendi renginde (aynı isim hep aynı renk)", "bool"),
        ("speakerColor", "İsim rengi (yukarıdaki kapalıyken)", "color"),
        ("speakerOwnLine", "İsim ayrı satırda", "bool"),
    ]),
    ("Kenarlık ve gölge", [
        ("outline", "Kenarlık kalınlığı", "int", 0, 8, 1, ""),
        ("outlineColor", "Kenarlık rengi", "color"),
        ("shadow", "Gölge", "int", 0, 20, 1, ""),
    ]),
    ("Arka plan", [
        ("bgOpacity", "Opaklık (0 = kutu yok)", "int", 0, 100, 5, "%"),
        ("bgColor", "Kutu rengi", "color"),
        ("bgRadius", "Köşe yuvarlaklığı", "int", 0, 40, 2, ""),
        ("bgPadding", "İç boşluk", "int", 0, 40, 2, ""),
    ]),
    ("Konum", [
        ("position", "Dikey konum", "choice", [("bottom", "Altta"), ("middle", "Ortada"), ("top", "Üstte")]),
        ("offset", "Kenardan uzaklık", "int", 0, 45, 1, "%"),
        ("align", "Yatay hizalama", "choice", [("left", "Sola"), ("center", "Ortaya"), ("right", "Sağa")]),
        ("xOffset", "Yatay kaydırma (sola − / sağa +)", "int", -45, 45, 1, "%"),
    ]),
    ("İngilizce orijinal", [
        ("showEnglish", "İngilizcesini de göster", "bool"),
        ("englishSize", "Boyutu (Türkçeye göre)", "int", 30, 100, 5, "%"),
        ("englishColor", "Rengi", "color"),
        ("englishAbove", "Türkçenin üstünde göster", "bool"),
    ]),
    ("Zamanlama", [
        ("lingerMs", "Ekranda kalma (altyazı kaybolduktan sonra)", "int", 0, 5000, 100, " ms"),
        ("fadeMs", "Geçiş efekti", "int", 0, 600, 20, " ms"),
        ("maxLines", "Kalabalık sahnede en fazla satır (her biri okunana kadar kalır)", "int", 1, 6, 1, ""),
        ("prevHoldMs", "Yukarı kayan satır en az bu kadar kalsın (0 = kapalı)", "int", 0, 8000, 250, " ms"),
        ("stackPrevious", "Önceki satır hep kalsın", "bool"),
        ("readBaseMs", "En az okuma süresi", "int", 0, 5000, 250, " ms"),
        ("readPerCharMs", "Karakter başına okuma süresi", "int", 0, 150, 5, " ms"),
        ("readMaxMs", "En fazla okuma süresi", "int", 1000, 10000, 500, " ms"),
        ("provisional", "Yarım cümleyi italik göster", "bool"),
    ]),
]

PRESETS = [
    ("Klasik", {}),
    ("Sinema", {"bgOpacity": 0, "outline": 4, "shadow": 8}),
    ("Sarı altyazı", {"bgOpacity": 0, "textColor": "#FFF59D", "speakerColor": "#FFFFFF", "outline": 4}),
    ("Büyük ve okunaklı", {"textSize": 40, "bgOpacity": 75, "maxWidth": 90}),
    ("Sade", {"font": "light", "bold": False, "outline": 0, "shadow": 0, "bgOpacity": 40}),
    ("Üstte", {"position": "top", "offset": 5}),
    ("Sol alt köşe", {"position": "bottom", "align": "left", "offset": 4, "maxWidth": 55}),
    ("Sağ alt köşe", {"position": "bottom", "align": "right", "offset": 4, "maxWidth": 55}),
]

DEFAULT_STYLE = {
    "textSize": 30, "font": "sans", "bold": True, "textColor": "#FFFFFF", "uppercase": False, "lineSpacing": 115,
    "letterSpacing": 0, "speakerShow": True, "speakerColors": True, "speakerColor": "#FFD54F",
    "speakerOwnLine": False, "outline": 3,
    "outlineColor": "#000000", "shadow": 6, "bgColor": "#000000", "bgOpacity": 55, "bgRadius": 12,
    "bgPadding": 14, "position": "bottom", "offset": 6, "align": "center", "xOffset": 0, "maxWidth": 80,
    "showEnglish": False,
    "englishSize": 60, "englishColor": "#B0BEC5", "englishAbove": False, "lingerMs": 400, "fadeMs": 120,
    "stackPrevious": False, "prevHoldMs": 2500, "readBaseMs": 1500, "readPerCharMs": 50, "readMaxMs": 5000,
    "provisional": True, "autoShrink": False, "prevSmaller": False, "maxLines": 4,
}


class ColorButton(QPushButton):
    def __init__(self, on_pick):
        super().__init__()
        self.setFixedSize(120, 34)
        self.setCursor(Qt.PointingHandCursor)
        self._value = "#FFFFFF"
        self._on_pick = on_pick
        self.clicked.connect(self._pick)

    def set_value(self, value):
        self._value = value
        c = QColor(value)
        text = "black" if c.lightness() > 140 else "white"
        self.setText(value.upper())
        self.setStyleSheet(f"background: {value}; color: {text}; border: 1px solid {theme.BORDER}; "
                           f"border-radius: 8px; font-weight: 600;")

    def _pick(self):
        c = QColorDialog.getColor(QColor(self._value), self, "Renk seç")
        if c.isValid():
            self.set_value(c.name().upper())
            self._on_pick(c.name().upper())


class TvLookPage(QWidget):
    title = "TV Görünümü"
    hint = "Altyazının TV'deki görünümünü buradan ayarla; her değişiklik TV'de anında görünür."

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.style = dict(DEFAULT_STYLE)
        self.tv_reported = False                # the TV told its look (only then is it worth taking to another PC)
        self._saved_style = dict(self.style)    # the style kept on the TV (Kaydet / Vazgeç)
        self.controls = {}
        self.screen_controls = {}
        self._loading = False
        self._send_timer = QTimer(self, singleShot=True, interval=80)
        self._send_timer.timeout.connect(self._send)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        top = Card()
        row = QHBoxLayout()
        self.state = QLabel()
        self.state.setStyleSheet("font-weight: 600;")
        test = icon_button(theme.Icon.PLAY, "TV'de test yazısı göster", "primary")
        test.clicked.connect(self._test)
        reset = icon_button(theme.Icon.REFRESH, "Varsayılana dön")
        reset.clicked.connect(lambda: self._apply_preset({}))
        row.addWidget(self.state, 1)
        row.addWidget(reset)
        row.addWidget(test)
        top.add_layout(row)
        presets = QHBoxLayout()
        presets.addWidget(QLabel("Hazır görünümler:"))
        for name, change in PRESETS:
            b = QPushButton(name)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=change: self._apply_preset(c))
            presets.addWidget(b)
        presets.addStretch(1)
        top.add_layout(presets)
        lay.addWidget(top)

        layout_card = Card("Satır düzeni")
        layout_card.add(self._control(("_layout", "Yeni çeviri gelince", "layout")))
        layout_card.add(Divider())
        append = Toggle(self.win.cfg.get("append_rest", True))
        append.toggled.connect(self._set_append)
        layout_card.add(SettingRow("Cümlenin devamını alt satıra ekle",
                                   "Bir cümle sonraki ekranda (ya da aynı satırda uzayarak) devam edince ekrandaki "
                                   "Türkçe hiç değişmez; devamı hemen altına ayrı satır olarak eklenir. Kapalıyken "
                                   "bütün cümle baştan çevrilip satırın üstüne yazılır.", append))
        lay.addWidget(layout_card)

        grid = QGridLayout()
        grid.setSpacing(16)
        for i, (section, fields) in enumerate(SCHEMA):
            card = Card(section)
            for j, field in enumerate(fields):
                if j:
                    card.add(Divider())
                card.add(self._control(field))
            grid.addWidget(card, i // 2, i % 2, Qt.AlignTop)
        lay.addLayout(grid)
        lay.addWidget(self._screen_card())
        lay.addStretch(1)

        self._fill()
        win.bridge.tv_style.connect(self.on_tv_style)
        win.bridge.clients.connect(self.on_clients)
        self.on_clients([])

    # ---- screen translation look (menus, quests) ----

    def _screen_card(self):
        from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSlider, QWidget
        st = self.win.cfg["screen"]
        card = Card("Ekran çevirisi görünümü (menü, görev, harita)",
                    "Ekran çevirisinin Türkçe kutuları. Değişiklikler TV'de hemen görünür; oyun yoksa \"TV'de örnek "
                    "göster\" ile dene.")

        def combo(items, key):
            c = QComboBox()
            for value, label in items:
                c.addItem(label, value)
            c.setCurrentIndex(max(0, c.findData(st.get(key))))
            c.currentIndexChanged.connect(lambda: self._screen_set(key, c.currentData()))
            self.screen_controls[key] = ("combo", c, None, "")
            return c

        def slider(key, lo, hi, unit):
            box = QWidget()
            h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            s.setValue(int(st.get(key, 100)))
            s.setMinimumWidth(220)
            value = QLabel(f"{s.value()}{unit}")
            value.setMinimumWidth(44)
            s.valueChanged.connect(lambda v: (value.setText(f"{v}{unit}"), self._screen_set(key, v)))
            self.screen_controls[key] = ("slider", s, value, unit)
            h.addWidget(s)
            h.addWidget(value)
            return box

        card.add(SettingRow("Arka plan", "Oyunun rengi: kutu, İngilizce yazının arkasındaki rengi alır, menüyle "
                            "kaynaşır. Yok: kutu çizilmez, Türkçe gölgeli yazılır (İngilizce altından görünebilir).",
                            combo([("auto", "Oyunun rengi (önerilen)"), ("dark", "Koyu"),
                                   ("none", "Yok — gölgeli yazı")], "bg")))
        card.add(Divider())
        card.add(SettingRow("Kutunun opaklığı", "100: İngilizceyi tamamen kapatır; azaldıkça arkası görünür.",
                            slider("opacity", 20, 100, "%")))
        card.add(Divider())
        card.add(SettingRow("Yazı boyutu", "İngilizce yazının boyutuna göre. Türkçe uzun gelirse sığması için "
                            "kendiliğinden küçülür; yandaki ya da alttaki çevirinin üstüne taşmaz.",
                            slider("text_scale", 60, 160, "%")))
        card.add(Divider())
        card.add(SettingRow("Yazı rengi", None, combo([("auto", "İngilizce yazının rengi"), ("white", "Beyaz"),
                                                      ("yellow", "Sarı")], "text_color")))
        row = QHBoxLayout()
        show = icon_button(theme.Icon.PLAY, "TV'de örnek göster")
        show.clicked.connect(self.win.screen.preview)
        row.addWidget(show)
        row.addStretch(1)
        card.add_layout(row)
        return card

    def _screen_set(self, key, value):
        self.win.cfg["screen"][key] = value
        self.win.save_config()
        self.win.screen.restyle()

    # ---- controls ----

    def _control(self, field):
        key, title, kind = field[0], field[1], field[2]
        if kind == "int":
            lo, hi, step, unit = field[3:7]
            box = QWidget()
            h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(lo, hi)
            slider.setSingleStep(step)
            slider.setPageStep(step * 2)
            slider.setMinimumWidth(130)
            value = QLabel()
            value.setMinimumWidth(58)

            def changed(v, key=key, unit=unit, value=value, step=step):
                v = round(v / step) * step
                value.setText(f"%{v}" if unit == "%" else f"{v}{unit}")
                self._set(key, v)

            slider.valueChanged.connect(changed)
            h.addWidget(slider)
            h.addWidget(value)
            self.controls[key] = (kind, slider, value, unit)
            return SettingRow(title, None, box)
        if kind == "layout":
            combo = QComboBox()
            for v, label in LAYOUTS:
                combo.addItem(label, v)
            combo.currentIndexChanged.connect(lambda _=0, combo=combo: self._set_layout(combo.currentData()))
            self.controls[key] = (kind, combo)
            return SettingRow(title, "Tek satırda ekranda hep yalnız en son çeviri durur; önceki satır yukarı kaymaz. "
                              "Uzun bir cümle yine iki satıra bölünebilir.", combo)
        if kind == "bool":
            t = Toggle()
            t.toggled.connect(lambda v, key=key: self._set(key, v))
            self.controls[key] = (kind, t)
            return SettingRow(title, None, t)
        if kind == "choice":
            combo = QComboBox()
            for v, label in field[3]:
                combo.addItem(label, v)
            combo.currentIndexChanged.connect(lambda _=0, key=key, combo=combo: self._set(key, combo.currentData()))
            self.controls[key] = (kind, combo)
            return SettingRow(title, None, combo)
        button = ColorButton(lambda v, key=key: self._set(key, v))
        self.controls[key] = (kind, button)
        return SettingRow(title, None, button)

    def _fill(self):
        self._loading = True
        for key, ctl in self.controls.items():
            kind = ctl[0]
            if kind == "layout":
                ctl[1].setCurrentIndex(ctl[1].findData(
                    "single" if int(self.style.get("maxLines", DEFAULT_STYLE["maxLines"])) <= 1 else "stack"))
                continue
            v = self.style.get(key, DEFAULT_STYLE[key])
            if kind == "int":
                ctl[1].setValue(int(v))
                ctl[2].setText(f"%{v}" if ctl[3] == "%" else f"{v}{ctl[3]}")
            elif kind == "bool":
                ctl[1].setChecked(bool(v))
            elif kind == "choice":
                i = ctl[1].findData(v)
                ctl[1].setCurrentIndex(max(0, i))
            else:
                ctl[1].set_value(v)
        self._loading = False

    # ---- sync ----

    def _set(self, key, value):
        if self._loading:
            return
        self.style[key] = value
        self._send_timer.start()
        self.win.save_config()      # shown on the TV now; kept with Kaydet, undone with Vazgeç

    def _set_append(self, on):
        self.win.cfg["append_rest"] = on
        self.win.save_config()

    def _set_layout(self, layout):
        if self._loading:
            return
        self.style.update(LAYOUT_STYLE[layout])
        self._fill()                # the "Zamanlama" controls show the new values
        self._send_timer.start()
        self.win.save_config()

    def _send(self):
        self.win.server.send({"type": "style", "style": self.style})

    def _apply_preset(self, change):
        self.style = dict(DEFAULT_STYLE, **change)
        self._fill()
        self._send()
        self._test()
        self.win.save_config()

    def committed(self):
        self._saved_style = dict(self.style)

    def reverted(self):
        """Back to the saved look: the TV gets the saved style again, the controls show it."""
        self.style = dict(self._saved_style)
        self._fill()
        self._send()
        st = self.win.cfg["screen"]
        for key, (kind, widget, label, unit) in self.screen_controls.items():
            widget.blockSignals(True)
            if kind == "combo":
                widget.setCurrentIndex(max(0, widget.findData(st.get(key))))
            else:
                widget.setValue(int(st.get(key, 100)))
                label.setText(f"{widget.value()}{unit}")
            widget.blockSignals(False)

    def _test(self):
        self.win.server.send({"type": "line", "id": -1, "speaker": "Karl",
                              "en": "Rifle, no scope, keeps things interesting.",
                              "tr": "Tüfek, dürbün yok, işleri ilginç tutuyor."})

    def on_tv_style(self, style):
        self.tv_reported = True
        self.style = dict(DEFAULT_STYLE, **style)
        self._saved_style = dict(self.style)    # what the TV keeps
        self._fill()

    def on_clients(self, clients):
        if clients:
            self.state.setText(f"<span style='color:{theme.GREEN}'>● TV bağlı — değişiklikler anında uygulanır</span>")
        else:
            self.state.setText(f"<span style='color:{theme.MUTED}'>● TV bağlı değil — TV'de Oyun Çeviri'yi aç</span>")
