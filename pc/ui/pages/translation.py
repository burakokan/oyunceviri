"""Translation page: model, device, beam size, test box and output corrections."""
import threading
import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from gt import filters

from .. import theme
from ..widgets import Card, Divider, PairListEditor, SettingRow, Toggle, icon_button

# Lines that are not in a game pack: measured on 22 hard lines (idioms, slang, swearing) on this PC.
ENGINES = [
    ("smart", "Akıllı", "Önerilen",
     "Önce DeepL (anlamı korur). DeepL \"siz\" derse, küfrü yumuşatırsa, İngilizce kelime bırakırsa ya da "
     "yetişmezse Qwen (daha doğal). ~0,27 sn. İnternet yoksa yedek model."),
    ("deepl", "DeepL", "Çevrimiçi",
     "~0,29 sn · bazen \"siz\" der. Ayda 1 milyon karakter ücretsiz."),
    ("groq", "Qwen 3.8 (Groq)", "Çevrimiçi",
     "~0,26 sn · hep \"sen\" der, küfürleri yumuşatmaz. Günde 1000 satır ücretsiz."),
    ("gemma", "Gemma 4 E2B", "Bu bilgisayarda",
     "~0,18 sn · internet gerekmez, ekran kartında çalışır (~3 GB)."),
    ("local", "OPUS-MT", "En hızlı",
     "~0,04 sn · internet gerekmez. Deyimleri kelime kelime çevirir."),
]

# The backup model: used when no online answer comes in time or there is no internet.
BACKUPS = [
    ("nmt", "models/opus-mt-tc-big-en-tr", "OPUS-MT", "Önerilen",
     "~0,04 sn, her zaman hazır. Daha doğal Türkçe, kelime atlamaz."),
    ("nmt", "models/quickmt-en-tr", "quickmt", "En hızlı",
     "~0,015 sn. Daha düz çeviri, bazen kelime atlar."),
    ("gemma", None, "Gemma 4 E2B", "Ekran kartında",
     "~0,2 sn. Deyimlerde bazen daha iyi, hep \"sen\" der. Çalışmazsa OPUS-MT."),
]

# The test box: every translator on its own, the smart choice, or all side by side.
TESTS = [("all", "Hepsi (yan yana)"), ("smart", "Akıllı"), ("DeepL", "DeepL"), ("Qwen", "Qwen 3.8 (Groq)"),
         ("Gemma", "Gemma 4 E2B"), ("OPUS-MT", "OPUS-MT"), ("quickmt", "quickmt")]
NMT_PATHS = {"OPUS-MT": "models/opus-mt-tc-big-en-tr", "quickmt": "models/quickmt-en-tr"}

MODELS = [
    ("models/opus-mt-tc-big-en-tr", "OPUS-MT", "Önerilen",
     "Daha doğal Türkçe, oyundaki gibi \"sen\" diye hitap eder, kelime atlamaz. Satır başına ~38 ms."),
    ("models/quickmt-en-tr", "quickmt", "En hızlı",
     "Satır başına ~15 ms. Daha düz çeviri, bazen kelime atlar."),
]


class _Result(QObject):
    done = Signal(str)
    compared = Signal(str)
    tested = Signal(dict)


class OptionCard(QFrame):
    clicked = Signal()

    def __init__(self, title, badge, text):
        super().__init__()
        self.setObjectName("optionCard")
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        head = QHBoxLayout()
        t = QLabel(title)
        t.setObjectName("optionTitle")
        b = QLabel(badge)
        b.setStyleSheet(f"color: {theme.ACCENT_HI}; font-weight: 600;")
        head.addWidget(t)
        head.addStretch(1)
        head.addWidget(b)
        lay.addLayout(head)
        d = QLabel(text)
        d.setObjectName("muted")
        d.setWordWrap(True)
        lay.addWidget(d)

    def set_selected(self, on):
        self.setProperty("selected", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, e):
        self.clicked.emit()


class TranslationPage(QWidget):
    title = "Çeviri"
    hint = "Paketi olmayan satırları hangi çevirinin yapacağı, çeviri testi ve düzeltmeler."

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cfg = win.cfg
        self._result = _Result()
        self._result.done.connect(self._show_result)
        self._result.tested.connect(self._show_test)
        self._result.compared.connect(lambda html: self.output.setText(html))
        self._nmt = {}                      # path -> LocalTranslator, for the test box only

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        engine = Card("Çeviri motoru",
                      "Oyun paketinde olan replikler her zaman anında paketten gelir. Burada pakette olmayan "
                      "satırları kimin çevireceği seçilir. Süreler bu bilgisayarda ölçüldü.")
        grid = QGridLayout()
        grid.setSpacing(12)
        self.engine_options = []
        from gt.conductor import Gemma
        for i, (key, title, badge, text) in enumerate(ENGINES):
            card = OptionCard(title, badge, text)
            if key == "gemma" and not Gemma.available():
                card.setEnabled(False)
                card.setToolTip("Gemma 4 bu bilgisayarda kurulu değil.")
            card.clicked.connect(lambda k=key: self._set_engine(k))
            grid.addWidget(card, i // 3, i % 3)
            self.engine_options.append((key, card))
        engine.add_layout(grid)
        engine.add(Divider())
        keys = QGridLayout()
        keys.setHorizontalSpacing(10)
        self.deepl_key = QLineEdit(self.cfg["online"].get("deepl_key", ""))
        self.groq_key = QLineEdit(self.cfg["online"].get("groq_key", ""))
        for row, (label, field, hint) in enumerate([
                ("DeepL anahtarı", self.deepl_key, "deepl.com/pro-api → DeepL API Free"),
                ("Groq anahtarı", self.groq_key, "console.groq.com → API Keys")]):
            field.setEchoMode(QLineEdit.Password)
            field.setPlaceholderText(hint)
            keys.addWidget(QLabel(label), row, 0)
            keys.addWidget(field, row, 1)
        test = icon_button(theme.Icon.CHECK, "Kaydet ve dene", "primary")
        test.clicked.connect(self._save_keys)
        keys.addWidget(test, 0, 2, 2, 1)
        engine.add_layout(keys)
        self.engine_status = QLabel("Anahtarlar sadece bu bilgisayarda saklanır.")
        self.engine_status.setObjectName("muted")
        self.engine_status.setWordWrap(True)
        self.engine_status.setTextFormat(Qt.RichText)
        engine.add(self.engine_status)
        lay.addWidget(engine)
        self._refresh_engines()

        screen = Card("Ekran çevirisi (menü, görev, harita)",
                      "Ana Sayfa'daki Ekran çevirisi düğmesiyle açılır. Burada hangi çeviricinin kullanılacağı seçilir.")
        how = QComboBox()
        how.addItem("Gemini Flash-Lite — en doğru, birkaç saniye (önerilen)", "gemini")
        how.addItem("Yerel model — anında ama daha düz", "local")
        how.setCurrentIndex(max(0, how.findData(self.cfg["screen"].get("translator", "gemini"))))
        how.currentIndexChanged.connect(lambda: self._set_screen_translator(how.currentData()))
        screen.add(SettingRow("Çevirici",
                              "Gemini, Oyun Paketleri sayfasındaki ücretsiz anahtarla çalışır. Ücretsiz günlük hakkı "
                              "biterse ya da internet yoksa yerel model devreye girer. Aynı yazı bir kez çevrilir, "
                              "sonra hatırlanır.", how))
        small = Toggle(self.cfg["screen"].get("small_text", False))
        small.toggled.connect(self._set_small_text)
        screen.add(Divider())
        screen.add(SettingRow("Küçük yazıları da bul",
                              "Ekranı daha yüksek çözünürlükte tarar: küçük HUD ve menü yazıları da bulunur. Her tarama "
                              "~0,3 yerine ~1 sn sürer (işlemciyi biraz daha yorar).", small))
        lay.addWidget(screen)

        model = Card("Yedek model",
                     "İnternet yoksa, çevrimiçi çeviriciler 0,45 saniyede yetişmezse ya da ücretsiz hakları biterse "
                     "bu model çevirir. \"OPUS-MT\" motoru seçiliyken de bu model kullanılır (OPUS-MT ya da quickmt).")
        from gt.conductor import Gemma
        grid = QGridLayout()
        grid.setSpacing(12)
        self.options = []
        for i, (kind, path, title, badge, text) in enumerate(BACKUPS):
            card = OptionCard(title, badge, text)
            if kind == "gemma" and not Gemma.available():
                card.setEnabled(False)
                card.setToolTip("Gemma 4 bu bilgisayarda kurulu değil.")
            card.clicked.connect(lambda k=kind, p=path: self._set_backup(k, p))
            grid.addWidget(card, 0, i)
            self.options.append((kind, path, card))
        model.add_layout(grid)
        model.add(Divider())
        self.device = QComboBox()
        self.device.addItem("Ekran kartı (önerilen)", "cuda")
        self.device.addItem("İşlemci", "cpu")
        self.device.setCurrentIndex(0 if self.cfg["translator"]["device"] == "cuda" else 1)
        self.device.currentIndexChanged.connect(self._set_device)
        model.add(SettingRow("OPUS-MT / quickmt nerede çalışsın", "Ekran kartı ~3 kat daha hızlı.", self.device))
        model.add(Divider())
        uncensored = Toggle(self.cfg["uncensored"])
        uncensored.toggled.connect(self._set_uncensored)
        model.add(SettingRow("Küfürleri yumuşatmadan çevir",
                             "Model bazı küfürleri yumuşatıyor (\"Shit!\" → \"Kahretsin!\"). Açıkken gerçek "
                             "karşılığı yazılır: \"Siktir!\", \"Orospu çocuğu!\" gibi.", uncensored))
        model.add(Divider())
        join = QLabel("Bölünmüş cümleler: Oyun bir cümleyi iki ekrana bölerse iki parça tek cümle olarak birlikte "
                      "çevrilir ve bir kez gösterilir (ayarı Filtreler sayfasında).")
        join.setObjectName("muted")
        join.setWordWrap(True)
        model.add(join)
        self.model_status = QLabel()
        self.model_status.setObjectName("muted")
        model.add(self.model_status)
        lay.addWidget(model)
        self._refresh_options()

        test = Card("Çeviri testi",
                    "İngilizce bir cümle yaz, istediğin çeviriciyi seç: nasıl çevrildiğini ve ne kadar sürdüğünü gör. "
                    "\"Hepsi\" bütün çevirileri yan yana gösterir, \"Akıllı\" hangisini neden seçtiğini de gösterir. "
                    "Oyun paketlerine bakılmaz.")
        row = QHBoxLayout()
        self.input = QLineEdit("If you spill the beans to the king, you'll be barking up the wrong tree.")
        self.input.returnPressed.connect(self._translate)
        self.test_engine = QComboBox()
        for key, label in TESTS:
            self.test_engine.addItem(label, key)
        go = icon_button(theme.Icon.GLOBE, "Çevir", "primary")
        go.clicked.connect(self._translate)
        row.addWidget(self.input, 1)
        row.addWidget(self.test_engine)
        row.addWidget(go)
        test.add_layout(row)
        self.output = QLabel("—")
        self.output.setWordWrap(True)
        self.output.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.output.setStyleSheet("font-size: 13pt;")
        test.add(self.output)
        lay.addWidget(test)

        fixes = Card("Çeviri düzeltmeleri",
                     "Modelin hep aynı şekilde yanlış çevirdiği ifadeleri düzelt. Çeviriden sonra uygulanır.")
        editor = PairListEditor(self.cfg["corrections"])
        editor.changed.connect(self._set_corrections)
        fixes.add(editor)
        clear_cache = icon_button(theme.Icon.REFRESH, "Çeviri önbelleğini temizle")
        clear_cache.clicked.connect(self._clear_cache)
        fixes.add(clear_cache).setMaximumWidth(260)
        lay.addWidget(fixes)
        lay.addStretch(1)

    def _refresh_options(self):
        fallback = self.cfg["mt"].get("fallback", "nmt")
        for kind, path, card in self.options:
            card.set_selected(kind == fallback and (kind == "gemma" or path == self.cfg["translator"]["model"]))

    def _changed(self):
        self.win.save_config()
        self.model_status.setText("Model yükleniyor…")
        threading.Thread(target=self._preload, daemon=True).start()

    def _preload(self):
        try:
            tr = self.win.engine.translator(self.cfg)
            self._result.done.emit(f"__status__Hazır · {tr.device}")
        except Exception as e:  # noqa: BLE001
            self._result.done.emit(f"__status__Model yüklenemedi: {e}")

    def _set_engine(self, key):
        self.cfg["mt"]["engine"] = key
        self.win.save_config()
        self._refresh_engines()
        if self.win.engine.running:
            self.win.engine.conductor.warm(self.cfg)

    def _refresh_engines(self):
        current = self.cfg["mt"]["engine"]
        for key, card in self.engine_options:
            card.set_selected(key == current)

    def _save_keys(self):
        self.cfg["online"]["deepl_key"] = self.deepl_key.text().strip()
        self.cfg["online"]["groq_key"] = self.groq_key.text().strip()
        self.win.persist_config(("online", "deepl_key"), ("online", "groq_key"))
        self.engine_status.setText("Deneniyor…")
        threading.Thread(target=lambda: self._result.tested.emit(self.win.engine.conductor.test(self.cfg)),
                         daemon=True).start()

    def _show_test(self, results):
        lines = []
        for name, (ok, text) in results.items():
            color = theme.GREEN if ok else theme.RED
            lines.append(f"<span style='color:{color}'>{'✓' if ok else '✗'} {name}</span>: {text}")
        self.engine_status.setText("<br>".join(lines))

    def _set_backup(self, kind, path):
        self.cfg["mt"]["fallback"] = kind
        if path:
            self.cfg["translator"]["model"] = path
        self._refresh_options()
        self._changed()
        if kind == "gemma" and self.win.engine.running:
            self.win.engine.conductor.warm(self.cfg)

    def _set_model(self, path):
        self.cfg["translator"]["model"] = path
        self._refresh_options()
        self._changed()

    def _set_device(self):
        self.cfg["translator"]["device"] = self.device.currentData()
        self.cfg["translator"]["compute_type"] = "float16" if self.device.currentData() == "cuda" else "int8"
        self._changed()

    def _set_small_text(self, on):
        self.cfg["screen"]["small_text"] = on
        self.win.save_config()

    def _set_screen_translator(self, value):
        self.cfg["screen"]["translator"] = value
        self.win.save_config()

    def _set_uncensored(self, on):
        self.cfg["uncensored"] = on
        self.win.save_config()

    def _set_corrections(self, pairs):
        self.cfg["corrections"] = pairs
        self.win.save_config()

    def _clear_cache(self):
        tr = self.win.engine._translator
        if tr is not None:
            tr.cache.clear()
        self.model_status.setText("Önbellek temizlendi.")

    def _translate(self):
        text = self.input.text().strip()
        if not text:
            return
        self.output.setText("Çevriliyor…")
        which = self.test_engine.currentData()
        threading.Thread(target=lambda: self._result.compared.emit(self._run_test(text, which)), daemon=True).start()

    def _nmt_model(self, name):
        from gt.translate import LocalTranslator
        path = NMT_PATHS[name]
        if path not in self._nmt:
            t = self.cfg["translator"]
            self._nmt[path] = LocalTranslator(path, t["device"], t["compute_type"], t.get("beam_size", 2))
        return self._nmt[path]

    def _one(self, name, english):
        """-> (turkish, ms, error) of one translator, finished like in the game."""
        engine = self.win.engine
        try:
            if name in NMT_PATHS:
                model = self._nmt_model(name)
                model.cache.pop(english, None)
                t = time.perf_counter()
                tr = model.translate(english)
                ms = (time.perf_counter() - t) * 1000
            else:
                tr, ms = engine.conductor.run_one(name, english, self.cfg, engine._context(english, self.cfg))
            return engine.polish(english, tr, self.cfg), ms, None
        except Exception as e:  # noqa: BLE001 - shown in the result
            return None, None, str(e)[:100]

    def _run_test(self, text, which):
        from concurrent.futures import ThreadPoolExecutor
        from gt.conductor import judge, turkish_too
        speaker, english = filters.split_speaker(text)
        name = f"<span style='color:{theme.ACCENT_HI}'>{speaker}:</span> " if speaker else ""
        muted = f"color:{theme.MUTED}; font-size:10pt"

        def row(label, tr, ms, error=None, chosen=False, why=None):
            mark = f"<b style='color:{theme.GREEN}'>✓ seçildi</b> · " if chosen else ""
            if error or tr is None:
                body = f"<span style='color:{theme.RED}'>{error or 'yetişmedi'}</span>"
            else:
                body = f"{name}{tr}"
            info = f"{mark}{ms:.0f} ms" if ms is not None else mark.rstrip(" · ")
            if why:
                info += " · " + ", ".join(why)
            return (f"<tr><td style='padding:4px 12px 4px 0'><b>{label}</b></td><td style='padding:4px 12px 4px 0'>"
                    f"{body}</td><td style='{muted}'>{info}</td></tr>")

        if which == "all":
            names = ["DeepL", "Qwen", "Gemma", "OPUS-MT", "quickmt"]
            with ThreadPoolExecutor(len(names) + 1) as pool:
                smart = pool.submit(self._smart, english)
                results = dict(zip(names, pool.map(lambda n: self._one(n, english), names)))
                s_tr, s_ms, s_used, _ = smart.result()
            rows = [row(f"Akıllı → {s_used}", s_tr, s_ms, chosen=True)]
            accepted = turkish_too([(english, r[0]) for r in results.values() if r[0]])
            rows += [row(n, *results[n], why=judge(english, results[n][0], accepted)[1] if results[n][0] else None)
                     for n in names]
            return "<table>" + "".join(rows) + "</table>"
        if which == "smart":
            tr, ms, used, candidates = self._smart(english)
            rows = [row(f"Akıllı → {used}", tr, ms, chosen=True)]
            for c in candidates:
                label = c["name"] + (" (yedek)" if c.get("backup") else "")
                rows.append(row(label, c["tr"], c["ms"], chosen=c["name"] == used, why=c["why"] or ["sorun yok"]))
            return ("<table>" + "".join(rows) + "</table>"
                    f"<p style='{muted}'>Seçim kuralı: önce DeepL (anlamı korur). DeepL'de görünür bir hata varsa "
                    f"(\"siz\" demek, küfrü yumuşatmak, İngilizce kelime bırakmak, yarım kalmak) daha az hatalı olan "
                    f"seçilir. Hiçbiri 0,5 sn'de yetişmezse yedek model.</p>")
        tr, ms, error = self._one(which, english)
        return "<table>" + row(which, tr, ms, error, why=judge(english, tr)[1] if tr else None) + "</table>"

    def _smart(self, english):
        import copy
        cfg = copy.deepcopy(self.cfg)
        cfg["mt"]["engine"] = "smart"
        cfg["packs"]["game"] = "off"
        engine = self.win.engine
        t = time.perf_counter()
        tr, used = engine.conductor.translate(english, cfg, engine._context(english, cfg))
        ms = (time.perf_counter() - t) * 1000
        return engine.polish(english, tr, cfg), ms, used, engine.conductor.last["candidates"]

    def _show_result(self, text):
        if text.startswith("__status__"):
            self.model_status.setText(text[len("__status__"):])
        else:
            self.output.setText(text)
