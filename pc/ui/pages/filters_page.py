"""Filters page: HUD/number filter, speaker names, cut phrases, ignored lines, stability."""
from PySide6.QtWidgets import QLabel, QLineEdit, QSpinBox, QVBoxLayout, QWidget

from gt import filters

from ..widgets import Card, Divider, ListEditor, SettingRow, Toggle


class FiltersPage(QWidget):
    title = "Filtreler"
    hint = "Altyazı olmayan yazıları ayıkla, konuşmacı adlarını ve okuma hızını ayarla."

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cfg = win.cfg
        f = self.cfg["filters"]

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        main = Card("Genel")
        hud = Toggle(f["hud_numbers"])
        hud.toggled.connect(lambda v: self._set("hud_numbers", v))
        main.add(SettingRow("Sayı ve HUD filtresi",
                            "Mermi sayısı (30/120), mesafe (150m), süre (12:45) gibi yalnızca sayıdan oluşan yazıları "
                            "ve satır kenarındaki sayaçları atar. Cümle içindeki sayılara dokunmaz.", hud))
        main.add(Divider())
        centered = Toggle(f.get("centered", True))
        centered.toggled.connect(lambda v: self._set("centered", v))
        main.add(SettingRow("Yalnızca ortadaki yazıyı oku",
                            "Altyazılar ekranın ortasında çıkar; kenarlardaki bölge adı (QUITO), sayaç, tuş ipucu "
                            "gibi HUD yazıları yok sayılır. Altyazısı sola yaslı oyunlarda kapat.", centered))
        main.add(Divider())
        titles = Toggle(f.get("skip_titles", True))
        titles.toggled.connect(lambda v: self._set("skip_titles", v))
        main.add(SettingRow("Bölge ve görev başlıklarını atla",
                            "\"FORT QUITO\" gibi büyük harfli, noktalamasız kısa yazılar çevrilmez. "
                            "\"ARGH!!\" gibi bağırışlar etkilenmez.", titles))
        main.add(Divider())
        sticky = Toggle(f.get("sticky_rows", True))
        sticky.toggled.connect(lambda v: self._set("sticky_rows", v))
        main.add(SettingRow("Ekranda takılı kalan yazıyı atla",
                            "Altyazı alanında 6 saniyeden uzun duran bir satır (görev yazısı, bildirim, dükkân adı), "
                            "altında yeni konuşma başlayınca yok sayılır; yeni cümleye karışmaz.", sticky))
        main.add(Divider())
        repeat = Toggle(f.get("repeat_block", True))
        repeat.toggled.connect(lambda v: self._set("repeat_block", v))
        main.add(SettingRow("Tekrar eden tabela / reklam yazısını sustur",
                            "Konuşmacısı ve noktalaması olmayan aynı yazı 5 dakikada 3 kez çıkarsa 10 dakika "
                            "gösterilmez (yoldan geçerken okunan tabela, reklam, HUD yazısı).", repeat))
        main.add(Divider())
        speaker = Toggle(f["speaker_names"])
        speaker.toggled.connect(lambda v: self._set("speaker_names", v))
        main.add(SettingRow("Konuşmacı adını göster",
                            "\"Karl: …\" gibi satırlarda isim çevrilmeden başta gösterilir. Kapatırsan yalnızca "
                            "konuşma çevrilir.", speaker))
        game_color = Toggle(f.get("speaker_color_game", True))
        game_color.toggled.connect(lambda v: self._set("speaker_color_game", v))
        main.add(SettingRow("Ad rengi oyundaki gibi",
                            "Konuşmacının adı TV'de oyundaki rengin ailesinden (turkuaz, pembe, sarı, krem…) canlı bir "
                            "tonla yazılır. PS5'in yayını ad renklerini neredeyse beyaza soldurduğu için renk ailesi "
                            "ekrandan anlaşılır, ton canlı seçilir. Her kişinin rengi kaydedilir ve hep aynı kalır; "
                            "bir konuşmada iki kişi aynı rengi almaz; rengi anlaşılamayan kişiye de beyaz değil bir "
                            "renk verilir. Kapatırsan uygulamanın kendi renkleri kullanılır. TV Görünümü'nde "
                            "\"Konuşmacı adları renkli\" açık olmalı.", game_color))
        main.add(Divider())
        names_only = Toggle(f.get("names_only", False))
        names_only.toggled.connect(lambda v: self._set("names_only", v))
        main.add(SettingRow("Yalnız adı olan satırları göster",
                            "Oyun her konuşmanın başına \"Ad:\" yazıyorsa (GTA 6'da altyazı ayarlarından konuşmacı "
                            "adı açıkken) adı olmayan yazı tabela ya da HUD sayılır ve gösterilmez. Görev yazıları ve "
                            "tuş ipuçları yine gösterilir. Oyun adları her satıra yazmıyorsa kendiliğinden devre dışı "
                            "kalır.", names_only))
        main.add(Divider())
        letters = QSpinBox()
        letters.setRange(1, 12)
        letters.setValue(f["min_letters"])
        letters.valueChanged.connect(lambda v: self._set("min_letters", v))
        main.add(SettingRow("En az harf sayısı",
                            "Bundan az harf içeren okumalar (\"FA\", tek harfler) gösterilmez.", letters))
        main.add(Divider())
        stable = QSpinBox()
        stable.setRange(1, 6)
        stable.setValue(self.cfg["stable_reads"])
        stable.setSuffix(" kare")
        stable.valueChanged.connect(self._set_stable)
        main.add(SettingRow("Kararlılık",
                            "Bir satır kaç kare üst üste aynı okununca gösterilsin. 2 önerilir. Yükseltirsen yanlış "
                            "okumalar azalır ama her kare ~17 ms gecikme ekler. (Yeniden başlatınca uygulanır.)",
                            stable))
        main.add(Divider())
        partial = QSpinBox()
        partial.setRange(0, 1500)
        partial.setSingleStep(50)
        partial.setSuffix(" ms")
        partial.setValue(self.cfg["partial_wait_ms"])
        partial.valueChanged.connect(self._set_partial)
        main.add(SettingRow("Yarım satır bekleme",
                            "Nokta ile bitmeyen satır bu kadar süre değişmezse okunmuş sayılır (kelime kelime açılan "
                            "altyazılar için). (Yeniden başlatınca uygulanır.)", partial))
        main.add(Divider())
        hold = Toggle(self.cfg["hold_unfinished"])
        hold.toggled.connect(lambda v: self._set_top("hold_unfinished", v))
        main.add(SettingRow("Bölünmüş cümleyi aynı satırda tamamla",
                            "Oyun bir cümleyi iki ekrana bölerse ilk parça beklemeden gösterilir; devamı gelince TV'de "
                            "aynı satır bütün cümleyle değişir (yeni satır açılmaz). Yarım kalan, daha net okunan ya da "
                            "uzayan satır da aynı satırda düzelir. Kapatırsan her ekran ayrı satır olur.", hold))
        lay.addWidget(main)

        cut = Card("Kesilecek ifadeler",
                   "Satırda bu ifade görülürse oradan sonrası atılır. Altyazının yanına karışan tuş ipuçları için: "
                   "\"Swap\" → \"…unturned! Swap Gewehr 1943 for…\" satırından ipucu kısmı silinir. Büyük/küçük "
                   "harfe duyarlıdır.")
        cut_list = ListEditor(f["cut_phrases"], "Yeni ifade, örn. Pick up")
        cut_list.changed.connect(lambda items: self._set("cut_phrases", items))
        cut.add(cut_list)
        lay.addWidget(cut)

        ignore = Card("Yok sayılacak satırlar", "Bu ifadeyi içeren satırlar hiç gösterilmez (büyük/küçük harf fark etmez).")
        ignore_list = ListEditor(f["ignore_lines"], "Yeni ifade, örn. Checkpoint reached")
        ignore_list.changed.connect(lambda items: self._set("ignore_lines", items))
        ignore.add(ignore_list)
        lay.addWidget(ignore)

        test = Card("Filtre testi", "Bir OCR satırı yaz, filtrelerden sonra ne kaldığını gör.")
        self.test_input = QLineEdit("German Infantry: Leave no stone unturned! Swap Gewehr 1943 for M.Pist.40")
        self.test_input.textChanged.connect(self._run_test)
        self.test_output = QLabel()
        self.test_output.setWordWrap(True)
        test.add(self.test_input)
        test.add(self.test_output)
        lay.addWidget(test)
        lay.addStretch(1)
        self._run_test()

    def _set(self, key, value):
        self.cfg["filters"][key] = value
        self.win.save_config()
        self._run_test()

    def _set_stable(self, v):
        self.cfg["stable_reads"] = v
        self.win.save_config()

    def _set_top(self, key, v):
        self.cfg[key] = v
        self.win.save_config()

    def _set_partial(self, v):
        self.cfg["partial_wait_ms"] = v
        self.win.save_config()

    def _run_test(self):
        cleaned = filters.clean(self.test_input.text(), self.cfg["filters"])
        if not cleaned:
            self.test_output.setText("→ <i>gösterilmez</i>")
            return
        speaker, body = filters.split_speaker(cleaned)
        if speaker and self.cfg["filters"]["speaker_names"]:
            self.test_output.setText(f"→ Konuşmacı: <b>{speaker}</b> &nbsp;·&nbsp; Çevrilecek: <b>{body}</b>")
        else:
            self.test_output.setText(f"→ Çevrilecek: <b>{body}</b>")
