"""Home page: setup checklist, the current subtitle, latency numbers, what OCR sees and the history."""
import statistics

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import readiness, theme
from ..game_select import GameName, GameSelect
from ..widgets import Card, ImageView, StatTile, Toggle, draw_lines_preview, icon_button, icon_label

# Remote Play is ~60 ms behind the HDMI picture (chiaki-ng measurement); the TV needs ~1 frame to draw.
REMOTE_PLAY_MS = 60
TV_DRAW_MS = 16
MAX_ROWS = 300


STEPS = [  # (title, check, what the button does, button text)
    ("PS5 bağlantısı", readiness.ps5, lambda win: win.go("Ps5Page"), "Ayarla"),
    ("Altyazı alanı", readiness.region, lambda win: win.go("RegionPage"), "Seç"),
    ("TV uygulaması", readiness.tv, lambda win: win.activate_tv(), "TV'de aç"),
]
STATE = {"ok": (theme.Icon.CHECK, theme.GREEN), "warn": (theme.Icon.WARNING, theme.YELLOW),
         "missing": (theme.Icon.WARNING, theme.RED)}


class Checklist(Card):
    """What is ready and what is missing, in the order it has to be done."""

    def __init__(self, win):
        super().__init__("Hazırlık")
        self.win = win
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(2, 1)
        self.rows = []
        for i, (title, check, action, label) in enumerate(STEPS):
            icon = icon_label(theme.Icon.CHECK, 16)
            name = QLabel(f"{i + 1} · {title}")
            name.setObjectName("stepTitle")
            detail = QLabel()
            detail.setObjectName("muted")
            detail.setWordWrap(True)
            button = QPushButton(label)
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumWidth(110)
            button.clicked.connect(lambda _=False, a=action: a(win))
            for col, w in enumerate((icon, name, detail, button)):
                grid.addWidget(w, i, col)
            self.rows.append((check, icon, detail, button))
        n = len(STEPS)
        grid.addWidget(icon_label(theme.Icon.GAME, 16, theme.ACCENT_HI), n, 0)
        game = QLabel(f"{n + 1} · Oynadığın oyun")
        game.setObjectName("stepTitle")
        grid.addWidget(game, n, 1)
        game_row = QHBoxLayout()
        game_row.addWidget(GameSelect(win), 1)
        game_row.addWidget(GameName(win))
        grid.addLayout(game_row, n, 2, 1, 2)
        # Shown while "auto" is chosen: which game the subtitles were recognized as
        self.detected_icon = icon_label(theme.Icon.CHECK, 16)
        self.detected_title = QLabel("Algılanan oyun")
        self.detected_title.setObjectName("stepTitle")
        self.detected = QLabel()
        self.detected.setWordWrap(True)
        self.pin_button = QPushButton("Bu oyunu seç")
        self.pin_button.setCursor(Qt.PointingHandCursor)
        self.pin_button.setToolTip("Seçim \"Otomatik\"ten bu oyuna geçer; sonraki açılışlarda da bu oyunun paketi "
                                   "ilk replikten itibaren kullanılır.")
        self.pin_button.clicked.connect(self._pin)
        for col, w in enumerate((self.detected_icon, self.detected_title, self.detected, self.pin_button)):
            grid.addWidget(w, n + 1, col)
        self.add_layout(grid)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.add(self.summary)
        self._timer = QTimer(self, interval=1500)
        self._timer.timeout.connect(self.refresh)

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
        self._timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._timer.stop()

    def refresh(self):
        missing = []
        for (title, *_), (check, icon, detail, button) in zip(STEPS, self.rows):
            state, text = check(self.win)
            glyph, color = STATE[state]
            icon.setText(glyph)
            icon.setStyleSheet(f"color: {color};")
            detail.setText(text)
            button.setEnabled(not (check is readiness.tv and self.win.tv_activation[0] == "busy"))
            primary = state != "ok"
            if button.objectName() != ("primary" if primary else ""):
                button.setObjectName("primary" if primary else "")
                button.style().unpolish(button)
                button.style().polish(button)
            if state == "missing":
                missing.append(title)
        self._refresh_detected()
        if missing:
            self.summary.setText(f"<span style='color:{theme.YELLOW}'>Önce şunu tamamla: {', '.join(missing)}. "
                                 f"Yandaki düğme ilgili sayfayı açar.</span>")
        elif self.win.engine.running:
            self.summary.setText(f"<span style='color:{theme.GREEN}'>Çalışıyor. Oyundaki altyazılar TV'de "
                                 f"Türkçe görünür.</span>")
        else:
            self.summary.setText(f"<span style='color:{theme.GREEN}'>Hazır. Oyunu aç ve sağ üstteki "
                                 f"<b>Başlat</b>'a bas.</span>")


    def _refresh_detected(self):
        lib = self.win.engine.packs
        auto = self.win.cfg["packs"]["game"] == "auto"
        wrong = None if auto else lib.packs.get(lib.mismatch)
        for w in (self.detected_icon, self.detected_title, self.detected, self.pin_button):
            w.setVisible(auto or wrong is not None)
        if wrong:
            # A game is chosen, but the subtitles are clearly from another one.
            self.detected_icon.setText(theme.Icon.WARNING)
            self.detected_icon.setStyleSheet(f"color: {theme.YELLOW};")
            self.detected_title.setText("Başka oyun?")
            self.detected.setText(f"<span style='color:{theme.YELLOW}'>Seçili oyunun paketinde bulunmayan replikler "
                                  f"<b>{wrong.title}</b> paketinde var. O oyunu oynuyorsan onu seç.</span>")
            self.pin_button.setEnabled(True)
            return
        self.detected_title.setText("Algılanan oyun")
        if not auto:
            return
        pack = lib.packs.get(lib.detected)
        if pack:
            self.detected_icon.setText(theme.Icon.CHECK)
            self.detected_icon.setStyleSheet(f"color: {theme.GREEN};")
            self.detected.setText(f"<b style='color:{theme.GREEN}'>{pack.title}</b>"
                                  f"<span style='color:{theme.MUTED}'> · hazır çevirisi kullanılıyor</span>")
        else:
            self.detected_icon.setText(theme.Icon.INFO)
            self.detected_icon.setStyleSheet(f"color: {theme.MUTED};")
            self.detected.setText(f"<span style='color:{theme.MUTED}'>Henüz algılanmadı — oyunda birkaç replikten "
                                  f"sonra burada görünür</span>")
        self.pin_button.setEnabled(pack is not None)

    def _pin(self):
        lib = self.win.engine.packs
        target = lib.mismatch if self.win.cfg["packs"]["game"] != "auto" else lib.detected
        if target in lib.packs:
            self.win.cfg["packs"]["game"] = target
            lib.reset_detection()
            self.win.persist_config(("packs", "game"))
            self.refresh()


class ScreenCard(Card):
    """Screen translation: on / off, "translate now", and what it is doing."""

    def __init__(self, win):
        super().__init__("Ekran çevirisi · menü, görev, harita",
                         "Açıkken menüler, görev listesi, hedefler, harita ve bölge adları gibi ekrandaki İngilizce "
                         "yazılar Türkçeye çevrilip TV'de aynı yere, İngilizcenin üstüne yazılır. Yazı kaybolunca "
                         "Türkçesi de hemen kalkar; değişince 1-2 saniyede yenilenir. Kapalıyken \"Şimdi çevir\" o "
                         "anki ekranı bir kez çevirir.")
        self.win = win
        row = QHBoxLayout()
        self.toggle = Toggle(win.cfg["screen"]["enabled"])
        self.toggle.toggled.connect(win.set_screen_translation)
        self.state = QLabel()
        self.state.setObjectName("stepTitle")
        now = icon_button(theme.Icon.SYNC, "Şimdi çevir")
        now.clicked.connect(win.screen.translate_now)
        row.addWidget(self.toggle)
        row.addWidget(self.state)
        row.addSpacing(16)
        row.addWidget(now)
        row.addStretch(1)
        self.add_layout(row)
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self.add(self.status)
        win.bridge.screen_status.connect(self.status.setText)
        win.screen_changed.connect(self._changed)
        self._changed(win.cfg["screen"]["enabled"])

    def _changed(self, on):
        if self.toggle.isChecked() != on:
            self.toggle.setChecked(on)
        self.state.setText("Aktif" if on else "Pasif")
        self.state.setStyleSheet(f"color: {theme.GREEN if on else theme.MUTED};")
        how = ("Gemini ile (doğru, birkaç saniye)" if self.win.cfg["screen"].get("translator", "gemini") == "gemini"
               and self.win.cfg["gemini"].get("key") else "yerel modelle")
        if on:
            self.status.setText(f"Ekrandaki yazılar {how} çevrilecek. Başlat'a basılı olmalı.")


class LivePage(QWidget):
    title = "Ana Sayfa"
    hint = "Hazırlık durumu ve oyundaki altyazıların anlık çevirisi."

    def __init__(self, win):
        super().__init__()
        self.win = win
        self._pc_times = []
        self._tv_ms = None
        self._rows = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        lay.addWidget(Checklist(win))
        lay.addWidget(ScreenCard(win))

        now = Card("Şu anki altyazı")
        self.speaker = QLabel()
        self.speaker.setObjectName("nowSpeaker")
        self.turkish = QLabel("Henüz altyazı yok — Başlat'a bas ve oyunda bir konuşma bekle.")
        self.turkish.setObjectName("nowTurkish")
        self.turkish.setWordWrap(True)
        self.english = QLabel()
        self.english.setObjectName("nowEnglish")
        self.english.setWordWrap(True)
        now.add(self.speaker)
        now.add(self.turkish)
        now.add(self.english)
        self.speaker.hide()
        lay.addWidget(now)

        tiles = QGridLayout()
        tiles.setSpacing(16)
        self.t_pc = StatTile("PC'de işleme (altyazı → çeviri)")
        self.t_avg = StatTile("Ortalama (son 20 satır)")
        self.t_tv = StatTile("PC → TV iletimi")
        self.t_total = StatTile("Tahmini toplam gecikme")
        self.t_total.setToolTip(f"PC + TV iletimi + Remote Play (~{REMOTE_PLAY_MS} ms) + TV çizimi (~{TV_DRAW_MS} ms)")
        for i, t in enumerate((self.t_pc, self.t_avg, self.t_tv, self.t_total)):
            tiles.addWidget(t, 0, i)
        lay.addLayout(tiles)

        row = QHBoxLayout()
        row.setSpacing(16)
        seen = Card("Okunan alan", "Üstte altyazı alanı, altta programın gördüğü harfler (siyah) ve bulunan satırlar (yeşil).")
        self.preview = seen.add(ImageView("Başlatınca burada görünür", min_height=150))
        row.addWidget(seen, 1)
        lay.addLayout(row)

        history = Card("Geçmiş")
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Saat", "Konuşmacı", "İngilizce", "Türkçe", "Kaynak", "PC", "TV"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(260)
        h = self.table.horizontalHeader()
        for col, mode in enumerate([QHeaderView.ResizeToContents, QHeaderView.ResizeToContents,
                                    QHeaderView.Stretch, QHeaderView.Stretch, QHeaderView.ResizeToContents,
                                    QHeaderView.ResizeToContents, QHeaderView.ResizeToContents]):
            h.setSectionResizeMode(col, mode)
        history.add(self.table)
        self.detail = QLabel("Bir satıra tıkla: her çeviricinin çevirisi, süresi ve hangisinin neden seçildiği "
                             "burada görünür.")
        self.detail.setObjectName("muted")
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.RichText)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        history.add(self.detail)
        self.table.itemSelectionChanged.connect(self._show_detail)
        lay.addWidget(history, 1)

        self._load_history()
        win.bridge.line.connect(self.on_line)
        win.bridge.clear.connect(self.on_clear)
        win.bridge.preview.connect(self.on_preview)
        win.bridge.ack.connect(self.on_ack)

    def on_line(self, line):
        self.turkish.setStyleSheet("")
        self.speaker.setVisible(bool(line["speaker"]))
        self.speaker.setText(line["speaker"] or "")
        self.turkish.setText(line["tr"])
        self.english.setText(line["en"])

        self._pc_times = (self._pc_times + [line["pc_ms"]])[-20:]
        self.t_pc.set(f"{line['pc_ms']:.0f} ms", self._color(line["pc_ms"], 120, 250))
        self.t_pc.label.setText(f"PC'de işleme · OCR {line['ocr_ms']:.0f} · çeviri {line['tr_ms']:.0f} ms")
        avg = statistics.median(self._pc_times)
        self.t_avg.set(f"{avg:.0f} ms", self._color(avg, 120, 250))
        self._update_total(line["pc_ms"])

        self._add_row(line, "…")
        self._rows[line["id"]] = self.table.item(0, 6)

    def _add_row(self, line, tv):
        self.table.insertRow(0)
        raw = line.get("source") or "Model"
        source = "Paket" if raw.startswith("Paket") else raw
        values = [line["time"], line.get("speaker") or "", line["en"], line["tr"], source,
                  f"{line.get('pc_ms', 0):.0f} ms", tv]
        for col, v in enumerate(values):
            item = QTableWidgetItem(v)
            if col in (0, 4, 5, 6):
                item.setTextAlignment(Qt.AlignCenter)
            if col == 0:
                item.setData(Qt.UserRole, line)
            if col == 4:
                item.setToolTip(line.get("source", "") + ("\nAyrıntı için satıra tıkla." if line.get("candidates") else ""))
                if source == "Paket":
                    item.setForeground(QColor(theme.GREEN))
                elif source in ("DeepL", "Qwen"):
                    item.setForeground(QColor(theme.ACCENT_HI))
            self.table.setItem(0, col, item)
        while self.table.rowCount() > MAX_ROWS:
            self.table.removeRow(self.table.rowCount() - 1)
        self.table.resizeRowToContents(0)

    def _show_detail(self):
        rows = {i.row() for i in self.table.selectedItems()}
        if not rows:
            return
        line = self.table.item(min(rows), 0).data(Qt.UserRole) or {}
        muted = f"color:{theme.MUTED}"
        src = line.get("source") or "Model"
        head = (f"<b>{line.get('en', '')}</b><br>Gösterilen: <b>{line.get('tr', '')}</b> "
                f"<span style='{muted}'>· {src}</span>")
        candidates = line.get("candidates")
        if not candidates:
            why = ("hazır çeviri, oyun paketinden geldi" if src.startswith("Paket")
                   else "bu satır için çevirici ayrıntısı kaydedilmemiş")
            self.detail.setText(f"{head}<br><span style='{muted}'>{why}</span>")
            return
        rows_html = []
        for c in candidates:
            chosen = c["name"] == src
            label = c["name"] + (" (yedek)" if c.get("backup") else "")
            mark = f"<b style='color:{theme.GREEN}'>✓ seçildi</b>" if chosen else ""
            tr = c["tr"] if c["tr"] is not None else f"<span style='color:{theme.RED}'>—</span>"
            info = [f"{c['ms']} ms"] if c.get("ms") is not None else []
            info += c.get("why") or ["sorun yok"]
            rows_html.append(f"<tr><td style='padding:3px 12px 3px 0'><b>{label}</b></td>"
                             f"<td style='padding:3px 12px 3px 0'>{tr}</td><td style='{muted}'>{mark} "
                             f"{' · '.join(info)}</td></tr>")
        self.detail.setText(f"{head}<table style='margin-top:6px'>{''.join(rows_html)}</table>"
                            f"<span style='{muted}'>Seçim: önce DeepL; DeepL'de görünür bir hata varsa daha az hatalı olan; hiçbiri 0,5 sn'de yetişmezse yedek model.</span>")

    def _load_history(self):
        """The lines of the last sessions (logs/session-*.jsonl), so the history survives a restart."""
        import json
        from gt.logbook import LOG_DIR
        lines = []
        for path in sorted(LOG_DIR.glob("session-*.jsonl"))[-5:]:
            try:
                for raw in path.read_text(encoding="utf-8").splitlines():
                    if '"line"' in raw:
                        lines.append(json.loads(raw)["line"])
            except (OSError, ValueError, KeyError):
                continue
        for line in lines[-100:]:
            self._add_row(line, "")

    def on_ack(self, line_id, rtt_ms):
        self._tv_ms = rtt_ms / 2
        self.t_tv.set(f"{self._tv_ms:.0f} ms", self._color(self._tv_ms, 30, 80))
        item = self._rows.pop(line_id, None)
        if item is not None:
            try:
                item.setText(f"{self._tv_ms:.0f} ms")
            except RuntimeError:
                pass  # row already removed
        if self._pc_times:
            self._update_total(self._pc_times[-1])

    def _update_total(self, pc_ms):
        tv = self._tv_ms if self._tv_ms is not None else 10
        total = pc_ms + tv + REMOTE_PLAY_MS + TV_DRAW_MS
        self.t_total.set(f"≈ {total / 1000:.2f} sn", self._color(total, 250, 500))

    def on_clear(self):
        self.turkish.setStyleSheet(f"color: {theme.MUTED};")
        self.english.setText("")
        self.speaker.hide()
        self.turkish.setText("(ekranda altyazı yok)")

    def on_preview(self, crop, mask, boxes):
        self.preview.set_image(draw_lines_preview(crop, mask, boxes))

    @staticmethod
    def _color(value, good, ok):
        return theme.GREEN if value <= good else theme.YELLOW if value <= ok else theme.RED
